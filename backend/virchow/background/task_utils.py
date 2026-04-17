"""Background task utilities.

Contains query-history report helpers (used by all deployment modes) and
in-process background task execution helpers for NO_VECTOR_DB mode:

- Atomic claim-and-mark helpers that prevent duplicate processing
- Drain loops that process all pending user file work

Each claim function runs a short-lived transaction: SELECT ... FOR UPDATE
SKIP LOCKED, UPDATE the row to remove it from future queries, COMMIT.
After the commit the row lock is released, but the row is no longer
eligible for re-claiming.  No long-lived sessions or advisory locks.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from virchow.utils.logger import setup_logger

logger = setup_logger()

# ------------------------------------------------------------------
# Query-history report helpers (pre-existing, used by all modes)
# ------------------------------------------------------------------

QUERY_REPORT_NAME_PREFIX = "query-history"


def construct_query_history_report_name(
    task_id: str,
) -> str:
    return f"{QUERY_REPORT_NAME_PREFIX}-{task_id}.csv"


def extract_task_id_from_query_history_report_name(name: str) -> str:
    return name.removeprefix(f"{QUERY_REPORT_NAME_PREFIX}-").removesuffix(".csv")


# ------------------------------------------------------------------
# Atomic claim-and-mark helpers
# ------------------------------------------------------------------
# Each function runs inside a single short-lived session/transaction:
#   1. SELECT ... FOR UPDATE SKIP LOCKED  (locks one eligible row)
#   2. UPDATE the row so it is no longer eligible
#   3. COMMIT  (releases the row lock)
# After the commit, no other drain loop can claim the same row.


def _claim_next_pending_rag_upload(db_session: Session) -> str | None:
    """Claim the next PENDING RAG upload record.

    Short-lived lock to prevent duplicate processing.
    """
    from virchow.db.custom_rag_models import AdminUpload, UserUpload, FileStage
    from sqlalchemy import text
    
    # Debug: check current schema/search_path
    current_schema = db_session.execute(text("SELECT current_schema()")).scalar()
    search_path = db_session.execute(text("SHOW search_path")).scalar()
    logger.notice(f"Claiming RAG upload. Schema: {current_schema}, Search Path: {search_path}")

    # Check Admin first
    record_id = db_session.execute(
        select(AdminUpload.file_id)
        .where(AdminUpload.stage == FileStage.QUEUED)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    
    if record_id:
        return str(record_id)
        
    # Check User next
    record_id = db_session.execute(
        select(UserUpload.file_id)
        .where(UserUpload.stage == FileStage.QUEUED)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    
    return str(record_id) if record_id else None


def drain_rag_upload_loop() -> None:
    """Process all pending RAG upload records."""
    from virchow.db.engine.sql_engine import get_session_with_current_tenant
    from virchow.server.documents.rag_processing import process_rag_upload

    while True:
        with get_session_with_current_tenant() as session:
            record_id = _claim_next_pending_rag_upload(session)
        if record_id is None:
            break
        try:
            process_rag_upload(session, record_id)
        except Exception:
             logger.exception(f"Failed to process RAG upload {record_id}")
