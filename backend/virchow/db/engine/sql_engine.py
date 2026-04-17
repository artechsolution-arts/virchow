from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id
from virchow.configs.app_configs import POSTGRES_DB
from virchow.configs.app_configs import POSTGRES_HOST
from virchow.configs.app_configs import POSTGRES_PASSWORD
from virchow.configs.app_configs import POSTGRES_PORT
from virchow.configs.app_configs import POSTGRES_USER


def build_connection_string() -> str:
    return (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


class SqlEngine:
    engine: Engine | None = None
    app_name: str | None = None
    _session_factory: sessionmaker[Session] | None = None

    @staticmethod
    def set_app_name(app_name: str) -> None:
        SqlEngine.app_name = app_name

    @staticmethod
    def init_engine(pool_size: int = 20, max_overflow: int = 5) -> None:
        if SqlEngine.engine is not None:
            return
        connect_args = {}
        if SqlEngine.app_name:
            connect_args["application_name"] = SqlEngine.app_name
        SqlEngine.engine = create_engine(
            build_connection_string(),
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            future=True,
            connect_args=connect_args,
        )
        SqlEngine._session_factory = sessionmaker(
            bind=SqlEngine.engine, autoflush=False, autocommit=False, future=True
        )

    @staticmethod
    def get_engine() -> Engine:
        if SqlEngine.engine is None:
            SqlEngine.init_engine()
        assert SqlEngine.engine is not None
        return SqlEngine.engine

    @staticmethod
    def reset_engine() -> None:
        if SqlEngine.engine is not None:
            SqlEngine.engine.dispose()
        SqlEngine.engine = None
        SqlEngine._session_factory = None


def get_sqlalchemy_engine() -> Engine:
    return SqlEngine.get_engine()


def _set_search_path(session: Session, tenant_id: str | None) -> None:
    schema = tenant_id or POSTGRES_DEFAULT_SCHEMA
    session.execute(text(f'SET search_path TO "{schema}"'))


@contextmanager
def get_session() -> Iterator[Session]:
    SqlEngine.init_engine()
    assert SqlEngine._session_factory is not None
    session = SqlEngine._session_factory()
    try:
        _set_search_path(session, POSTGRES_DEFAULT_SCHEMA)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_session_with_tenant(tenant_id: str) -> Iterator[Session]:
    SqlEngine.init_engine()
    assert SqlEngine._session_factory is not None
    session = SqlEngine._session_factory()
    try:
        _set_search_path(session, tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_with_current_tenant() -> Iterator[Session]:
    return get_session_with_tenant(get_current_tenant_id())


@contextmanager
def get_session_with_current_tenant_if_none(
    db_session: Session | None = None,
) -> Iterator[Session]:
    if db_session is not None:
        yield db_session
        return
    with get_session_with_current_tenant() as session:
        yield session
