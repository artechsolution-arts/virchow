"""0001_initial_rag_schema

Revision ID: 0001
Revises: None
Create Date: 2026-03-27 12:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    # departments
    op.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)

    # rag_users
    op.execute("""
    CREATE TABLE IF NOT EXISTS rag_users (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        last_login TIMESTAMP
    );
    """)

    # batch_sessions
    op.execute("""
    CREATE TABLE IF NOT EXISTS batch_sessions (
        session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id UUID NOT NULL REFERENCES rag_users(id) ON DELETE CASCADE,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        files_count INTEGER DEFAULT 0,
        batch_status TEXT DEFAULT 'processing',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)

    # file_progress
    op.execute("""
    CREATE TABLE IF NOT EXISTS file_progress (
        file_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        session_id UUID NOT NULL REFERENCES batch_sessions(session_id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT 'queued',
        pct INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)

    # pdf_docs
    op.execute("""
    CREATE TABLE IF NOT EXISTS pdf_docs (
        doc_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        file_reference_id UUID REFERENCES file_progress(file_id) ON DELETE SET NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        raw_content BYTEA,
        extracted_text TEXT,
        page_count INTEGER NOT NULL DEFAULT 0,
        content_hash TEXT,
        department_id UUID REFERENCES departments(id) ON DELETE CASCADE,
        uploaded_by UUID REFERENCES rag_users(id) ON DELETE RESTRICT,
        metadata_json JSONB,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)

    # chunks
    op.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        doc_id UUID NOT NULL REFERENCES pdf_docs(doc_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        token_count INTEGER DEFAULT 0,
        chunk_index INTEGER NOT NULL,
        page_num INTEGER DEFAULT 0,
        metadata_json JSONB
    );
    """)

    # embedded_chunks
    op.execute("""
    CREATE TABLE IF NOT EXISTS embedded_chunks (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chunk_id UUID NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
        embedding JSONB,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embedded_chunks;")
    op.execute("DROP TABLE IF EXISTS chunks;")
    op.execute("DROP TABLE IF EXISTS pdf_docs;")
    op.execute("DROP TABLE IF EXISTS file_progress;")
    op.execute("DROP TABLE IF EXISTS batch_sessions;")
    op.execute("DROP TABLE IF EXISTS rag_users;")
    op.execute("DROP TABLE IF EXISTS departments;")
