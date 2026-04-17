import asyncio
from datetime import datetime
from datetime import timezone
import os
import re

import asyncpg
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from litellm import completion
from virchow.auth.users import current_user
from virchow.auth.users import current_curator_or_admin_user
from virchow.configs.constants import DEFAULT_CC_PAIR_ID
from virchow.configs.constants import DocumentSource
from virchow.configs.constants import PUBLIC_API_TAGS
from virchow.connectors.models import Document
from virchow.connectors.models import IndexAttemptMetadata
from virchow.error_handling.error_codes import VirchowErrorCode
from virchow.error_handling.exceptions import VirchowError
from virchow.db.connector_credential_pair import get_connector_credential_pair_from_id
from virchow.db.document import delete_documents_complete__no_commit
from virchow.db.document import get_document
from virchow.db.document import get_documents_by_cc_pair
from virchow.db.document import get_ingestion_documents
from virchow.db.engine.sql_engine import get_session
from virchow.db.models import User
from virchow.db.search_settings import get_active_search_settings
from virchow.db.search_settings import get_current_search_settings
from virchow.db.search_settings import get_secondary_search_settings
from virchow.document_index.factory import get_all_document_indices
from virchow.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from virchow.indexing.embedder import DefaultIndexingEmbedder
from virchow.indexing.indexing_pipeline import run_indexing_pipeline
from virchow.server.virchow_api.models import DocMinimalInfo
from virchow.server.virchow_api.models import IngestionDocument
from virchow.server.virchow_api.models import IngestionResult
from virchow.server.virchow_api.models import MdChunkMatch
from virchow.server.virchow_api.models import MdChunksAskRequest
from virchow.server.virchow_api.models import MdChunksAskResponse
from virchow.server.utils_vector_db import require_vector_db
from virchow.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# not using /api to avoid confusion with nginx api path routing
router = APIRouter(prefix="/virchow-api", tags=PUBLIC_API_TAGS)


def _validated_identifier(name: str, field_name: str) -> str:
    if not _SAFE_IDENTIFIER_PATTERN.match(name):
        raise VirchowError(
            VirchowErrorCode.INVALID_INPUT,
            f"Invalid {field_name} identifier: {name}",
        )
    return name


async def _fetch_md_chunk_matches(question: str, top_k: int) -> list[MdChunkMatch]:
    db_host = os.getenv("MD_CHUNKS_DB_HOST", "host.docker.internal")
    db_port = int(os.getenv("MD_CHUNKS_DB_PORT", "5432"))
    db_name = os.getenv("MD_CHUNKS_DB_NAME", "ragchat")
    db_user = os.getenv("MD_CHUNKS_DB_USER", "postgres")
    db_password = os.getenv("MD_CHUNKS_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    db_schema = _validated_identifier(
        os.getenv("MD_CHUNKS_DB_SCHEMA", "rag"), "schema"
    )
    db_table = _validated_identifier(
        os.getenv("MD_CHUNKS_TABLE", "md_chunks"), "table"
    )

    if not db_password:
        raise VirchowError(
            VirchowErrorCode.MISSING_REQUIRED_FIELD,
            "MD_CHUNKS_DB_PASSWORD (or POSTGRES_PASSWORD) must be set",
        )

    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name,
    )
    try:
        fts_query = f"""
            SELECT
                doc_id,
                chunk_index,
                content,
                ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', $1)) AS score
            FROM {db_schema}.{db_table}
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)
            ORDER BY score DESC
            LIMIT $2
        """
        rows = await conn.fetch(fts_query, question, top_k)

        if not rows:
            like_query = f"""
                SELECT
                    doc_id,
                    chunk_index,
                    content,
                    0.0::float8 AS score
                FROM {db_schema}.{db_table}
                WHERE content ILIKE ('%' || $1 || '%')
                LIMIT $2
            """
            rows = await conn.fetch(like_query, question, top_k)

        return [
            MdChunkMatch(
                doc_id=row.get("doc_id"),
                chunk_index=row.get("chunk_index"),
                content=row.get("content", ""),
                score=float(row.get("score", 0.0)),
            )
            for row in rows
        ]
    finally:
        await conn.close()


def _answer_from_matches(question: str, matches: list[MdChunkMatch]) -> str:
    api_key = os.getenv("GEN_AI_API_KEY", "")
    model_name = os.getenv("GEN_AI_MODEL_VERSION", "gpt-5-nano")
    if not api_key:
        raise VirchowError(
            VirchowErrorCode.MISSING_REQUIRED_FIELD,
            "GEN_AI_API_KEY must be set",
        )

    context = "\n\n".join(
        [
            f"[doc_id={m.doc_id}, chunk_index={m.chunk_index}, score={m.score:.4f}]\n{m.content}"
            for m in matches
        ]
    )

    response = completion(
        model=f"openai/{model_name}",
        api_key=api_key,
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer only from the provided context. "
                    "If context is insufficient, say you could not find the answer."
                ),
            },
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nContext:\n{context}",
            },
        ],
    )
    answer_content = response.choices[0].message.content
    if isinstance(answer_content, str):
        return answer_content
    return str(answer_content)


@router.get("/connector-docs/{cc_pair_id}")
def get_docs_by_connector_credential_pair(
    cc_pair_id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
    db_docs = get_documents_by_cc_pair(cc_pair_id=cc_pair_id, db_session=db_session)
    return [
        DocMinimalInfo(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            link=doc.link,
        )
        for doc in db_docs
    ]


@router.post("/md-chunks/ask")
def ask_md_chunks(
    request: MdChunksAskRequest,
    _: User = Depends(current_user),
) -> MdChunksAskResponse:
    question = request.question.strip()
    if not question:
        raise VirchowError(VirchowErrorCode.INVALID_INPUT, "question must not be empty")

    top_k = max(1, min(request.top_k, 20))

    try:
        matches = asyncio.run(_fetch_md_chunk_matches(question, top_k))
    except VirchowError:
        raise
    except Exception as e:
        raise VirchowError(
            VirchowErrorCode.BAD_GATEWAY,
            f"Failed to query md_chunks: {e}",
        ) from e

    if not matches:
        return MdChunksAskResponse(
            answer="I could not find relevant content in rag.md_chunks for this question.",
            matches=[],
        )

    try:
        answer = _answer_from_matches(question, matches)
    except VirchowError:
        raise
    except Exception as e:
        raise VirchowError(
            VirchowErrorCode.LLM_PROVIDER_ERROR,
            f"Failed to generate answer: {e}",
        ) from e

    return MdChunksAskResponse(answer=answer, matches=matches)


@router.get("/ingestion")
def get_ingestion_docs(
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DocMinimalInfo]:
    db_docs = get_ingestion_documents(db_session)
    return [
        DocMinimalInfo(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            link=doc.link,
        )
        for doc in db_docs
    ]


@router.post("/ingestion", dependencies=[Depends(require_vector_db)])
def upsert_ingestion_doc(
    doc_info: IngestionDocument,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> IngestionResult:
    tenant_id = get_current_tenant_id()

    doc_info.document.from_ingestion_api = True

    if doc_info.document.doc_updated_at is None:
        doc_info.document.doc_updated_at = datetime.now(tz=timezone.utc)

    document = Document.from_base(doc_info.document)

    # TODO once the frontend is updated with this enum, remove this logic
    if document.source == DocumentSource.INGESTION_API:
        document.source = DocumentSource.FILE

    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=doc_info.cc_pair_id or DEFAULT_CC_PAIR_ID,
    )
    if cc_pair is None:
        raise HTTPException(
            status_code=400, detail="Connector-Credential Pair specified does not exist"
        )

    # Need to index for both the primary and secondary index if possible
    active_search_settings = get_active_search_settings(db_session)
    # This flow is for indexing so we get all indices.
    document_indices = get_all_document_indices(
        active_search_settings.primary,
        None,
        None,
    )

    search_settings = get_current_search_settings(db_session)

    index_embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
        search_settings=search_settings
    )

    # Build adapter for primary indexing
    adapter = DocumentIndexingBatchAdapter(
        db_session=db_session,
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        tenant_id=tenant_id,
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        ),
        user=user,
    )

    indexing_pipeline_result = run_indexing_pipeline(
        embedder=index_embedding_model,
        document_indices=document_indices,
        ignore_time_skip=True,
        db_session=db_session,
        tenant_id=tenant_id,
        document_batch=[document],
        request_id=None,
        adapter=adapter,
    )

    from virchow.db.audit_log import log_action
    log_action(
        db_session=db_session,
        action="UPSERT_DOCUMENT",
        details={"document_id": document.id, "cc_pair_id": cc_pair.id},
        user_id=user.id if user else None
    )

    # If there's a secondary index being built, index the doc but don't use it for return here
    if active_search_settings.secondary:
        sec_search_settings = get_secondary_search_settings(db_session)

        if sec_search_settings is None:
            # Should not ever happen
            raise RuntimeError(
                "Secondary index exists but no search settings configured"
            )

        new_index_embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=sec_search_settings
        )

        # This flow is for indexing so we get all indices.
        sec_document_indices = get_all_document_indices(
            active_search_settings.secondary, None, None
        )

        run_indexing_pipeline(
            embedder=new_index_embedding_model,
            document_indices=sec_document_indices,
            ignore_time_skip=True,
            db_session=db_session,
            tenant_id=tenant_id,
            document_batch=[document],
            request_id=None,
            adapter=adapter,
        )

    return IngestionResult(
        document_id=document.id,
        already_existed=indexing_pipeline_result.new_docs > 0,
    )


@router.delete("/ingestion/{document_id}", dependencies=[Depends(require_vector_db)])
def delete_ingestion_doc(
    document_id: str,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    raise HTTPException(status_code=403, detail="Deletion is not allowed")
