"""
Minimal Virchow RAG Backend.
Auth, Redis, MinIO, and Celery have been removed.
Only PostgreSQL + the RAG upload pipeline are active.
"""

import logging
import os
import sys
import warnings
import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
# Load environment from root
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_root, ".env"))

import uvicorn
try:
    import pika
except Exception:
    pika = None
from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

# ── RAG Pipeline Path Injection ─────────────────────────────────────────────
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(_root, "rag_pipeline"))

try:
    from src.database.redis_db import RedisStateManager
    from src.database.rabbitmq_broker import rabbit_connect, setup_topology
    from src.storage.seaweedfs_client import SeaweedFSClient
    from src.storage.storage_service import StorageService
    from src.services.rag_pipeline import RAGPipeline
    from src.config import cfg
except Exception:
    RedisStateManager = None
    rabbit_connect = None
    setup_topology = None
    SeaweedFSClient = None
    StorageService = None
    RAGPipeline = None
    cfg = None

from virchow import __version__
from virchow.configs.app_configs import APP_API_PREFIX
from virchow.configs.app_configs import APP_HOST
from virchow.configs.app_configs import APP_PORT
from virchow.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from virchow.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from virchow.configs.app_configs import POSTGRES_DB
from virchow.configs.app_configs import POSTGRES_HOST
from virchow.configs.app_configs import POSTGRES_PASSWORD
from virchow.configs.app_configs import POSTGRES_PORT
from virchow.configs.app_configs import POSTGRES_USER
from virchow.configs.constants import POSTGRES_WEB_APP_NAME

# Mock components that were in deleted db
class SqlEngine:
    engine = None
    @staticmethod
    def set_app_name(_): pass
    @staticmethod
    def init_engine(**kwargs): pass
    @staticmethod
    def get_engine(): return SqlEngine.engine
    @staticmethod
    def reset_engine(): SqlEngine.engine = None

try:
    from src.database.postgres_db import get_pg_pool, create_schema, get_pg_connection
except Exception:
    import psycopg2
    from psycopg2 import pool as psycopg2_pool

    def get_pg_pool(minconn: int, maxconn: int):
        return psycopg2_pool.SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            host=POSTGRES_HOST,
            port=int(POSTGRES_PORT),
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_DB,
        )

    def create_schema(conn):
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{POSTGRES_DEFAULT_SCHEMA}"')
        conn.commit()

    def get_pg_connection():
        return psycopg2.connect(
            host=POSTGRES_HOST,
            port=int(POSTGRES_PORT),
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_DB,
        )

# from virchow.setup import setup_virchow
from virchow.utils.logger import setup_logger
from virchow.utils.logger import setup_uvicorn_logger
from virchow.utils.middleware import add_endpoint_context_middleware
from virchow.utils.middleware import add_virchow_request_id_middleware

from shared_configs.configs import CORS_ALLOWED_ORIGIN
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# ── RAG pipeline ────────────────────────────────────────────────────────────
from virchow.server.stubs import create_empty_router
try:
    from virchow.server.documents.rag_upload import router as rag_upload_router
except Exception:
    rag_upload_router = create_empty_router()

from virchow.auth.users import current_admin_user
from virchow.auth.users import current_chat_accessible_user
from virchow.auth.users import current_curator_or_admin_user
from virchow.auth.users import current_user
# Mock User model
class User:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


warnings.filterwarnings("ignore", category=ResourceWarning)

logger = setup_logger()
file_handlers = [
    h for h in logger.logger.handlers if isinstance(h, logging.FileHandler)
]
setup_uvicorn_logger(shared_file_handlers=file_handlers)


# ── Helpers ──────────────────────────────────────────────────────────────────


def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logger.exception(f"{request}: {exc_str}")
    return JSONResponse(
        content={"status_code": 422, "message": exc_str, "data": None},
        status_code=422,
    )


def value_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ValueError):
        raise exc
    try:
        raise exc
    except Exception:
        logger.exception("ValueError")
    return JSONResponse(status_code=400, content={"message": str(exc)})


def include_router_with_global_prefix_prepended(
    application: FastAPI, router: APIRouter, **kwargs: Any
) -> None:
    processed_global_prefix = f"/{APP_API_PREFIX.strip('/')}" if APP_API_PREFIX else ""
    passed_in_prefix = kwargs.get("prefix")
    if passed_in_prefix:
        final_prefix = (
            f"{processed_global_prefix}/{str(passed_in_prefix).strip('/')}"
        )
    else:
        final_prefix = processed_global_prefix
    application.include_router(router, **{**kwargs, "prefix": final_prefix})


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    sys.setrecursionlimit(5000)

    # Use the pool from rag_pipeline
    pool = get_pg_pool(
        minconn=POSTGRES_API_SERVER_POOL_SIZE,
        maxconn=POSTGRES_API_SERVER_POOL_SIZE + POSTGRES_API_SERVER_POOL_OVERFLOW
    )
    SqlEngine.engine = pool # Store pool where engine was expected
    
    # Initialize Schema
    try:
        conn = pool.getconn()
        create_schema(conn)
        pool.putconn(conn)
    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}")
    
    # CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    # with get_session_with_current_tenant() as db_session:
    #     setup_virchow(db_session, POSTGRES_DEFAULT_SCHEMA)

    # Background poller (replaces Celery since DISABLE_VECTOR_DB=true)
    # WARNING: These background tasks likely import from virchow.db too.
    # We may need to disable them if they crash.
    # try:
    #     from virchow.background.periodic_poller import recover_stuck_user_files
    #     from virchow.background.periodic_poller import start_periodic_poller
    #     recover_stuck_user_files(POSTGRES_DEFAULT_SCHEMA)
    #     start_periodic_poller(POSTGRES_DEFAULT_SCHEMA)
    # except Exception as e:
    #     logger.error(f"Failed to start background pollers: {e}")


    # ── RAG Pipeline Infrastructure ──────────────────────────────────────────
    logger.info("Initializing Modular RAG Infrastructure...")
    
    if all(
        [
            RedisStateManager,
            rabbit_connect,
            setup_topology,
            SeaweedFSClient,
            StorageService,
            RAGPipeline,
            cfg,
        ]
    ):
        try:
            # 1. Redis
            rsm = RedisStateManager()
            app.state.rsm = rsm

            # 2. RabbitMQ
            mq_conn = rabbit_connect()
            setup_topology(mq_conn)
            app.state.mq_conn = mq_conn

            # 3. SeaweedFS
            sw_client = SeaweedFSClient(
                filer_url=cfg.SEAWEEDFS_FILER_URL,
                master_url=cfg.SEAWEEDFS_MASTER_URL,
            )
            storage = StorageService(sw_client)
            app.state.storage = storage

            # 4. Pipeline Service
            app.state.rag_service = RAGPipeline(
                conn=SqlEngine.get_engine(), rsm=rsm, storage=storage
            )
        except Exception as e:
            logger.warning(f"RAG infra unavailable; continuing without it: {e}")
    else:
        logger.warning("RAG pipeline dependencies unavailable; starting API without them.")

    yield

    # Cleanup
    if hasattr(app.state, "mq_conn") and app.state.mq_conn.is_open:
        app.state.mq_conn.close()
    
    from virchow.background.periodic_poller import stop_periodic_poller

    stop_periodic_poller()
    SqlEngine.reset_engine()


# ── Application factory ───────────────────────────────────────────────────────


def get_application() -> FastAPI:
    application = FastAPI(
        title="Virchow RAG Backend (no-auth)",
        version=__version__,
        description="Virchow RAG pipeline — auth/Redis/MinIO/Celery removed",
        lifespan=lifespan,
    )

    # ── Exception handlers ───────────────────────────────────────────────────
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(ValueError, value_error_handler)

    # ── CORS ─────────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGIN,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    add_virchow_request_id_middleware(application, "API", logger)
    add_endpoint_context_middleware(application)

    # ── Health / state (provides /health, /version) ───────────────────────────
    # state_router gets included *after* _auth_router to prevent /auth/type conflict

    # ── Settings stub ─────────────────────────────────────────────────────────
    _settings_stub = APIRouter(prefix="/settings")

    @_settings_stub.get("")
    def stub_settings() -> dict:
        return {
            "auto_scroll": True,
            "application_status": "ACTIVE",
            "gpu_enabled": False,
            "maximum_chat_retention_days": None,
            "notifications": [],
            "needs_reindexing": False,
            "anonymous_user_enabled": False,
            "invite_only_enabled": False,
            "deep_research_enabled": True,
            "temperature_override_enabled": True,
            "query_history_type": "NORMAL",
        }

    include_router_with_global_prefix_prepended(application, _settings_stub)

    # ── Mock Basic Auth (Login only) ──────────────────────────────────────────
    from fastapi.security import OAuth2PasswordRequestForm
    from fastapi import Depends, HTTPException, Response

    _auth_router = APIRouter()

    @_auth_router.get("/auth/type")
    def get_auth_type() -> dict:
        return {
            "auth_type": "basic",
            "requires_verification": False,
            "anonymous_user_enabled": False,
            "password_min_length": 1,
            "has_users": True,
            "oauth_enabled": False,
        }

    @_auth_router.post("/auth/login")
    def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
        # Accept any login and set a mock session cookie
        response.set_cookie(key="fastapiusersauth", value=form_data.username, httponly=True)
        return {"status": "success"}

    @_auth_router.get("/me")
    def get_me(request: Request) -> dict:
        """Return admin user only if mock_session cookie exists."""
        if not request.cookies.get("fastapiusersauth"):
            raise HTTPException(status_code=403, detail="Not authenticated")
        return {
            "id": "00000000-0000-0000-0000-000000000000",
            "email": request.cookies.get("fastapiusersauth") or "admin@virchow.local",
            "is_active": True,
            "is_superuser": True,
            "is_verified": True,
            "name": "Admin",
            "role": "admin",
            "preferences": {
                "chosen_assistants": None,
                "visible_assistants": [],
                "hidden_assistants": [],
                "pinned_assistants": [],
                "default_model": None,
                "recent_assistants": [],
                "auto_scroll": True,
                "shortcut_enabled": False,
                "temperature_override_enabled": False,
                "theme_preference": "light",
                "chat_background": None,
                "default_app_mode": "CHAT"
            }
        }

    include_router_with_global_prefix_prepended(application, _auth_router)
    # include_router_with_global_prefix_prepended(application, state_router)

    # ── Enterprise-settings stub ──────────────────────────────────────────────
    _ee_stub = APIRouter(prefix="/enterprise-settings")

    @_ee_stub.get("")
    def stub_enterprise_settings() -> dict:
        return {
            "application_name": None,
            "use_custom_logo": False,
            "use_custom_logotype": False,
            "logo_display_style": None,
            "custom_nav_items": [],
            "two_lines_for_chat_header": None,
            "custom_lower_disclaimer_content": None,
            "custom_header_content": None,
            "custom_popup_header": None,
            "custom_popup_content": None,
            "enable_consent_screen": None,
            "consent_screen_prompt": None,
            "show_first_visit_notice": None,
            "custom_greeting_message": None,
        }

    @_ee_stub.get("/custom-analytics-script")
    def stub_analytics_script() -> None:
        return None

    include_router_with_global_prefix_prepended(application, _ee_stub)

    # ── Dependencies Mock for RAG Backend ─────────────────────────────────────
    
    def mock_get_admin_user() -> User:
        user = User(
            id="00000000-0000-0000-0000-000000000000",
            email="admin@virchow.local",
            role="admin",
            is_active=True,
            is_superuser=True,
        )
        return user

    application.dependency_overrides[current_admin_user] = mock_get_admin_user
    application.dependency_overrides[current_curator_or_admin_user] = mock_get_admin_user
    application.dependency_overrides[current_user] = mock_get_admin_user
    application.dependency_overrides[current_chat_accessible_user] = mock_get_admin_user

    # ── Additional Routers ────────────────────────────────────────────────────
    
    _kg_stub = APIRouter(prefix="/admin/kg")
    @_kg_stub.get("/exposed")
    def stub_kg_exposed() -> list:
        return []
    include_router_with_global_prefix_prepended(application, _kg_stub)

    # ── Stubs ────────────────────────────────────────────────────────────────
    include_router_with_global_prefix_prepended(application, create_empty_router())

    # ── RAG upload pipeline ───────────────────────────────────────────────────
    include_router_with_global_prefix_prepended(application, rag_upload_router)

    return application


app = get_application()


if __name__ == "__main__":
    logger.notice(
        f"Starting Virchow RAG Backend {__version__} on http://{APP_HOST}:{APP_PORT}/"
    )
    uvicorn.run(app, host=APP_HOST, port=APP_PORT)
