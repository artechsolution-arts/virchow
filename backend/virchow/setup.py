import time

from sqlalchemy.orm import Session

from virchow.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from virchow.configs.app_configs import DISABLE_VECTOR_DB
from virchow.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_VIRCHOW
from virchow.configs.app_configs import INTEGRATION_TESTS_MODE
from virchow.configs.app_configs import MANAGED_VESPA
from virchow.configs.app_configs import VESPA_NUM_ATTEMPTS_ON_STARTUP
from virchow.configs.constants import KV_REINDEX_KEY
from virchow.configs.embedding_configs import SUPPORTED_EMBEDDING_MODELS
from virchow.configs.embedding_configs import SupportedEmbeddingModel
from virchow.configs.model_configs import GEN_AI_API_KEY
from virchow.configs.model_configs import GEN_AI_MODEL_VERSION
from virchow.context.search.models import SavedSearchSettings
from virchow.db.connector import check_connectors_exist
from virchow.db.connector import create_initial_default_connector
from virchow.db.connector_credential_pair import associate_default_cc_pair
from virchow.db.connector_credential_pair import get_connector_credential_pairs
from virchow.db.connector_credential_pair import resync_cc_pair
from virchow.db.credentials import create_initial_public_credential
from virchow.db.document import check_docs_exist
from virchow.db.enums import EmbeddingPrecision
from virchow.db.index_attempt import cancel_indexing_attempts_past_model
from virchow.db.index_attempt import expire_index_attempts
from virchow.db.llm import fetch_default_llm_model
from virchow.db.llm import fetch_existing_llm_provider
from virchow.db.llm import update_default_provider
from virchow.db.llm import upsert_llm_provider
from virchow.db.search_settings import get_active_search_settings
from virchow.db.search_settings import get_current_search_settings
from virchow.db.search_settings import update_current_search_settings
from virchow.db.swap_index import check_and_perform_index_swap
from virchow.document_index.factory import get_all_document_indices
from virchow.document_index.interfaces import DocumentIndex
from virchow.document_index.opensearch.client import OpenSearchClient
from virchow.document_index.opensearch.client import wait_for_opensearch_with_timeout
from virchow.document_index.opensearch.opensearch_document_index import set_cluster_state
from virchow.document_index.vespa.index import VespaIndex
from virchow.indexing.models import IndexingSetting
from virchow.key_value_store.factory import get_kv_store
from virchow.key_value_store.interface import KvKeyNotFoundError
from virchow.llm.constants import LlmProviderNames
# from virchow.llm.well_known_providers.llm_provider_options import get_openai_model_names
from virchow.natural_language_processing.search_nlp_models import EmbeddingModel
from virchow.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from virchow.server.manage.llm.models import LLMProviderUpsertRequest
from virchow.server.manage.llm.models import ModelConfigurationUpsertRequest
from virchow.server.settings.store import load_settings
from virchow.server.settings.store import store_settings
from virchow.utils.gpu_utils import gpu_status_request
from virchow.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT


logger = setup_logger()


def setup_virchow(
    db_session: Session,
    tenant_id: str,
) -> None:
    """
    Minimal Virchow setup for RAG pipeline.
    Ensures the 'General' department exists.
    """
    from virchow.db.custom_rag_models import Department
    from sqlalchemy import select

    logger.notice(f"Setting up minimal RAG for tenant: {tenant_id}")
    
    dept = db_session.execute(
        select(Department).where(Department.name == "General")
    ).scalars().first()
    
    if not dept:
        logger.notice("Creating initial 'General' department...")
        dept = Department(name="General", description="Default RAG department")
        db_session.add(dept)
        db_session.commit()


def mark_reindex_flag(db_session: Session) -> None:
    kv_store = get_kv_store()
    try:
        value = kv_store.load(KV_REINDEX_KEY)
        logger.debug(f"Re-indexing flag has value {value}")
        return
    except KvKeyNotFoundError:
        # Only need to update the flag if it hasn't been set
        pass

    # If their first deployment is after the changes, it will
    # enable this when the other changes go in, need to avoid
    # this being set to False, then the user indexes things on the old version
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    if docs_exist or connectors_exist:
        kv_store.store(KV_REINDEX_KEY, True)
    else:
        kv_store.store(KV_REINDEX_KEY, False)


def setup_document_indices(
    document_indices: list[DocumentIndex],
    index_setting: IndexingSetting,
    secondary_index_setting: IndexingSetting | None,
    num_attempts: int = VESPA_NUM_ATTEMPTS_ON_STARTUP,
) -> bool:
    """Sets up all input document indices.

    If any document index setup fails, the function will return False. Otherwise
    returns True.
    """
    for document_index in document_indices:
        # Document index startup is a bit slow, so give it a few seconds.
        WAIT_SECONDS = 5
        document_index_setup_success = False
        for x in range(num_attempts):
            try:
                logger.notice(
                    f"Setting up document index {document_index.__class__.__name__} (attempt {x + 1}/{num_attempts})..."
                )
                document_index.ensure_indices_exist(
                    primary_embedding_dim=index_setting.final_embedding_dim,
                    primary_embedding_precision=index_setting.embedding_precision,
                    secondary_index_embedding_dim=(
                        secondary_index_setting.final_embedding_dim
                        if secondary_index_setting
                        else None
                    ),
                    secondary_index_embedding_precision=(
                        secondary_index_setting.embedding_precision
                        if secondary_index_setting
                        else None
                    ),
                )

                logger.notice(
                    f"Document index {document_index.__class__.__name__} setup complete."
                )
                document_index_setup_success = True
                break
            except Exception:
                logger.exception(
                    f"Document index {document_index.__class__.__name__} setup did not succeed. "
                    "The relevant service may not be ready yet. "
                    f"Retrying in {WAIT_SECONDS} seconds."
                )
                time.sleep(WAIT_SECONDS)

        if not document_index_setup_success:
            logger.error(
                f"Document index {document_index.__class__.__name__} setup did not succeed. "
                f"Attempt limit reached. ({num_attempts})"
            )
            return False

    return True


def setup_postgres(db_session: Session) -> None:
    logger.notice("Verifying default connector/credential exist.")
    create_initial_public_credential(db_session)
    create_initial_default_connector(db_session)
    associate_default_cc_pair(db_session)

    # OpenAI/Cloud defaults are disabled for on-premises deployment.
    # LLM configuration should be handled through the UI or environment variables.
    pass


def update_default_multipass_indexing(db_session: Session) -> None:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    logger.debug(f"Docs exist: {docs_exist}, Connectors exist: {connectors_exist}")

    if not docs_exist and not connectors_exist:
        logger.info(
            "No existing docs or connectors found. Checking GPU availability for multipass indexing."
        )
        gpu_available = gpu_status_request(indexing=True)
        logger.info(f"GPU available: {gpu_available}")

        current_settings = get_current_search_settings(db_session)

        logger.notice(f"Updating multipass indexing setting to: {gpu_available}")
        updated_settings = SavedSearchSettings.from_db_model(current_settings)
        # Enable multipass indexing if GPU is available or if using a cloud provider
        updated_settings.multipass_indexing = (
            gpu_available or current_settings.cloud_provider is not None
        )
        update_current_search_settings(db_session, updated_settings)

        # Update settings with GPU availability
        settings = load_settings()
        settings.gpu_enabled = gpu_available
        store_settings(settings)
        logger.notice(f"Updated settings with GPU availability: {gpu_available}")

    else:
        logger.debug(
            "Existing docs or connectors found. Skipping multipass indexing update."
        )


def setup_multitenant_virchow() -> None:
    if DISABLE_VECTOR_DB:
        logger.notice("DISABLE_VECTOR_DB is set — skipping multitenant Vespa setup.")
        return

    if ENABLE_OPENSEARCH_INDEXING_FOR_VIRCHOW:
        opensearch_client = OpenSearchClient()
        if not wait_for_opensearch_with_timeout(client=opensearch_client):
            raise RuntimeError("Failed to connect to OpenSearch.")
        set_cluster_state(opensearch_client)

    # For Managed Vespa, the schema is sent over via the Vespa Console manually.
    # NOTE: Pretty sure this code is never hit in any production environment.
    if not MANAGED_VESPA:
        setup_vespa_multitenant(SUPPORTED_EMBEDDING_MODELS)


def setup_vespa_multitenant(supported_indices: list[SupportedEmbeddingModel]) -> bool:
    # TODO(andrei): We don't yet support OpenSearch for multi-tenant instances
    # so this function remains unchanged.
    # This is for local testing
    WAIT_SECONDS = 5
    VESPA_ATTEMPTS = 5
    for x in range(VESPA_ATTEMPTS):
        try:
            logger.notice(f"Setting up Vespa (attempt {x + 1}/{VESPA_ATTEMPTS})...")
            VespaIndex.register_multitenant_indices(
                indices=[index.index_name for index in supported_indices]
                + [
                    f"{index.index_name}{ALT_INDEX_SUFFIX}"
                    for index in supported_indices
                ],
                embedding_dims=[index.dim for index in supported_indices]
                + [index.dim for index in supported_indices],
                # on the cloud, just use float for all indices, the option to change this
                # is not exposed to the user
                embedding_precisions=[
                    EmbeddingPrecision.FLOAT for _ in range(len(supported_indices) * 2)
                ],
            )

            logger.notice("Vespa setup complete.")
            return True
        except Exception:
            logger.notice(
                f"Vespa setup did not succeed. The Vespa service may not be ready yet. Retrying in {WAIT_SECONDS} seconds."
            )
            time.sleep(WAIT_SECONDS)

    logger.error(
        f"Vespa setup did not succeed. Attempt limit reached. ({VESPA_ATTEMPTS})"
    )
    return False
