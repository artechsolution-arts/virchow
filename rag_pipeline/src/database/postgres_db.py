import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from src.config import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD, EMBEDDING_DIM, EMBEDDING_MODEL, cfg
import logging

logger = logging.getLogger(__name__)


def get_pg_pool(minconn=2, maxconn=20):
    return pool.ThreadedConnectionPool(
        minconn, maxconn,
        host=PG_HOST, port=PG_PORT,
        dbname=PG_DATABASE, user=PG_USER, password=PG_PASSWORD,
    )


def create_schema(conn):
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS public;")
    cur.execute("SET search_path TO public;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;")
    cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;')

    cur.execute("""CREATE TABLE IF NOT EXISTS departments (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        name TEXT NOT NULL UNIQUE, description TEXT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    cur.execute("""CREATE TABLE IF NOT EXISTS dept_access_grants (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        granting_dept_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        receiving_dept_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        access_type TEXT NOT NULL DEFAULT 'read',
        expires_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE (granting_dept_id, receiving_dept_id));""")

    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        is_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
        role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','hod','user')),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        last_login TIMESTAMP);""")

    cur.execute("""CREATE TABLE IF NOT EXISTS chat (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        title TEXT,
        rag_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    cur.execute("""CREATE TABLE IF NOT EXISTS messages (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chat_id UUID NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user','assistant')),
        content TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    cur.execute("""CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        title TEXT, file_name TEXT NOT NULL,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
        content_hash TEXT, page_count INTEGER NOT NULL DEFAULT 0,
        embed_status TEXT NOT NULL DEFAULT 'completed',
        created_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    cur.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        chunk_token_count INTEGER,
        page_num INTEGER NOT NULL DEFAULT 0);""")

    cur.execute(f"""CREATE TABLE IF NOT EXISTS embeddings (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        embedding vector({EMBEDDING_DIM}),
        embedding_model TEXT NOT NULL DEFAULT '{EMBEDDING_MODEL}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    cur.execute("""CREATE TABLE IF NOT EXISTS rag_retrieval_log (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        chat_id UUID NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        query_text TEXT NOT NULL,
        retrieved_chunk_ids JSONB NOT NULL DEFAULT '[]',
        similarity_scores JSONB NOT NULL DEFAULT '[]',
        created_at TIMESTAMP NOT NULL DEFAULT NOW());""")

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_users_dept     ON users(department_id);",
        "CREATE INDEX IF NOT EXISTS idx_chat_user      ON chat(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_chat_dept      ON chat(department_id);",
        "CREATE INDEX IF NOT EXISTS idx_msg_chat       ON messages(chat_id);",
        "CREATE INDEX IF NOT EXISTS idx_doc_dept       ON documents(department_id);",
        "CREATE INDEX IF NOT EXISTS idx_chunk_doc      ON chunks(document_id);",
        "CREATE INDEX IF NOT EXISTS idx_emb_dept       ON embeddings(department_id);",
        """CREATE INDEX IF NOT EXISTS idx_emb_vector
           ON embeddings USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);""",
    ]:
        cur.execute(sql)

    conn.commit()
    cur.close()
    logger.info("[Schema] Tables + indexes ready")


class RBACManager:
    def __init__(self, conn_or_pool):
        if isinstance(conn_or_pool, pool.AbstractConnectionPool):
            self.pool = conn_or_pool
            self.conn = None
        else:
            self.pool = None
            self.conn = conn_or_pool

    def _get_conn(self):
        if self.pool:
            conn = self.pool.getconn()
            conn.autocommit = True
            return conn
        return self.conn

    def _put_conn(self, conn):
        if self.pool and conn:
            self.pool.putconn(conn)

    def _cur(self, conn):
        return conn.cursor(cursor_factory=RealDictCursor)

    # ── User auth ─────────────────────────────────────────────────────────────

    def get_user_by_email(self, email: str):
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT id, email, name, password_hash, department_id, is_active, is_super_admin, role "
                "FROM users WHERE email=%s", (email,)
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    def get_user_by_id(self, user_id: str):
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT id, email, name, department_id, is_active, is_super_admin, role "
                "FROM users WHERE id=%s", (user_id,)
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    def create_user(self, email: str, name: str, password_hash: str,
                    department_id: str, role: str = "user") -> str:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "INSERT INTO users (email,name,password_hash,department_id,role) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (email, name, password_hash, department_id, role)
            )
            row = cur.fetchone()
            cur.close()
            return str(row["id"])
        finally:
            self._put_conn(conn)

    def update_last_login(self, user_id: str):
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (user_id,))
            cur.close()
        finally:
            self._put_conn(conn)

    def get_or_create_default_dept(self) -> str:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute("SELECT id FROM departments WHERE name='Default' LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.close()
                return str(row["id"])
            cur.execute(
                "INSERT INTO departments (name, description) VALUES ('Default','Default department') RETURNING id"
            )
            row = cur.fetchone()
            cur.close()
            return str(row["id"])
        finally:
            self._put_conn(conn)

    def list_departments(self) -> list:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute("SELECT id::TEXT, name FROM departments WHERE is_active=TRUE ORDER BY name")
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    # ── Chat ──────────────────────────────────────────────────────────────────

    def create_chat(self, user_id: str, department_id: str, title: str = None) -> str:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "INSERT INTO chat (user_id,department_id,title) VALUES (%s,%s,%s) RETURNING id",
                (user_id, department_id, title)
            )
            row = cur.fetchone()
            cur.close()
            return str(row["id"])
        finally:
            self._put_conn(conn)

    def add_message(self, chat_id: str, role: str, content: str) -> str:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "INSERT INTO messages (chat_id,role,content) VALUES (%s,%s,%s) RETURNING id",
                (chat_id, role, content)
            )
            row = cur.fetchone()
            cur.close()
            return str(row["id"])
        finally:
            self._put_conn(conn)

    def get_messages(self, chat_id: str, dept_id: str) -> list:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT m.role, m.content, m.created_at::TEXT "
                "FROM messages m JOIN chat c ON c.id=m.chat_id "
                "WHERE m.chat_id=%s AND c.department_id=%s "
                "ORDER BY m.created_at",
                (chat_id, dept_id)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    def get_user_chats(self, user_id: str, dept_id: str) -> list:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT c.id::TEXT, c.title, c.created_at::TEXT, c.updated_at::TEXT FROM chat c "
                "WHERE c.user_id=%s AND c.department_id=%s "
                "AND EXISTS (SELECT 1 FROM messages m WHERE m.chat_id = c.id) "
                "ORDER BY c.updated_at DESC LIMIT 50",
                (user_id, dept_id)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    def rename_chat(self, chat_id: str, user_id: str, title: str) -> bool:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "UPDATE chat SET title=%s, updated_at=NOW() WHERE id=%s AND user_id=%s",
                (title, chat_id, user_id)
            )
            updated = cur.rowcount > 0
            cur.close()
            return updated
        finally:
            self._put_conn(conn)

    def delete_chat(self, chat_id: str, user_id: str) -> bool:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "DELETE FROM chat WHERE id=%s AND user_id=%s", (chat_id, user_id)
            )
            deleted = cur.rowcount > 0
            cur.close()
            return deleted
        finally:
            self._put_conn(conn)

    def update_chat_title_if_empty(self, chat_id: str, title: str):
        """Set title only when it is currently NULL (auto-title on first message)."""
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "UPDATE chat SET title=%s, updated_at=NOW() WHERE id=%s AND title IS NULL",
                (title[:60], chat_id)
            )
            cur.close()
        finally:
            self._put_conn(conn)

    def get_messages_full(self, chat_id: str, dept_id: str) -> list:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT m.id::TEXT, m.role, m.content, m.created_at::TEXT "
                "FROM messages m JOIN chat c ON c.id=m.chat_id "
                "WHERE m.chat_id=%s AND c.department_id=%s "
                "ORDER BY m.created_at",
                (chat_id, dept_id)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    def get_chat_meta(self, chat_id: str, user_id: str) -> dict:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "SELECT id::TEXT, title, created_at::TEXT, updated_at::TEXT "
                "FROM chat WHERE id=%s AND user_id=%s",
                (chat_id, user_id)
            )
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        finally:
            self._put_conn(conn)

    # ── Vector search ─────────────────────────────────────────────────────────

    def _accessible_dept_clause(self) -> str:
        return """(e.department_id = %s
                   OR e.department_id IN (
                       SELECT granting_dept_id FROM dept_access_grants
                       WHERE receiving_dept_id = %s
                         AND (expires_at IS NULL OR expires_at > NOW())))"""

    def vector_search(self, query_embedding, dept_id: str, top_k: int = 10) -> list:
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                f"""
                SELECT e.chunk_id, c.chunk_text, c.document_id, c.page_num,
                       d.file_name, d.file_path, d.id as document_id,
                       1 - (e.embedding <=> %s::vector) AS similarity
                FROM   embeddings e
                JOIN   chunks c ON c.id = e.chunk_id
                JOIN   documents d ON d.id = c.document_id
                WHERE  {self._accessible_dept_clause()}
                ORDER  BY e.embedding <=> %s::vector
                LIMIT  %s
                """,
                (str(query_embedding), dept_id, dept_id, str(query_embedding), top_k)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    def vector_search_by_filename(self, query_embedding, dept_id: str,
                                   filename_pattern: str, top_k: int = 10) -> list:
        """Vector search restricted to documents whose file_name contains filename_pattern."""
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                f"""
                SELECT e.chunk_id, c.chunk_text, c.document_id, c.page_num,
                       d.file_name, d.file_path, d.id as document_id,
                       1 - (e.embedding <=> %s::vector) AS similarity
                FROM   embeddings e
                JOIN   chunks c ON c.id = e.chunk_id
                JOIN   documents d ON d.id = c.document_id
                WHERE  d.file_name ILIKE %s
                  AND  {self._accessible_dept_clause()}
                ORDER  BY e.embedding <=> %s::vector
                LIMIT  %s
                """,
                (str(query_embedding), f'%{filename_pattern}%',
                 dept_id, dept_id, str(query_embedding), top_k)
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            self._put_conn(conn)

    def keyword_search_in_files(self, keywords: list, dept_id: str,
                                file_names: list, top_k: int = 5) -> list:
        """AND-first keyword search restricted to specific file names (active documents)."""
        if not keywords or not file_names:
            return []
        conn = self._get_conn()
        try:
            patterns = [f'%{kw.lower()}%' for kw in keywords]
            cur = self._cur(conn)
            placeholders = ",".join(["%s"] * len(file_names))
            and_conditions = " AND ".join(["c.chunk_text ILIKE %s"] * len(patterns))
            cur.execute(
                f"""
                SELECT DISTINCT ON (c.id)
                       c.id AS chunk_id, c.chunk_text, c.document_id, c.page_num,
                       d.file_name, d.file_path, d.id AS document_id,
                       0.90 AS similarity
                FROM   chunks c
                JOIN   documents d ON d.id = c.document_id
                JOIN   embeddings e ON e.chunk_id = c.id
                WHERE  {and_conditions}
                  AND  d.file_name IN ({placeholders})
                  AND  {self._accessible_dept_clause()}
                ORDER  BY c.id
                LIMIT  %s
                """,
                patterns + file_names + [dept_id, dept_id, top_k],
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            for r in rows:
                r["_keyword_hit"] = True
            return rows
        finally:
            self._put_conn(conn)

    def keyword_search(self, keywords: list, dept_id: str, top_k: int = 5) -> list:
        """ILIKE keyword search to catch docs with poor embeddings (garbled/HTML content).
        Tries AND (all keywords in same chunk) first; falls back to ANY (at least one) if empty."""
        if not keywords:
            return []
        conn = self._get_conn()
        try:
            patterns = [f'%{kw.lower()}%' for kw in keywords]
            cur = self._cur(conn)

            # ── AND attempt: every keyword must appear in the same chunk ──────────
            and_conditions = " AND ".join(["c.chunk_text ILIKE %s"] * len(patterns))
            and_params = patterns + [dept_id, dept_id, top_k]
            cur.execute(
                f"""
                SELECT DISTINCT ON (c.id)
                       c.id AS chunk_id, c.chunk_text, c.document_id, c.page_num,
                       d.file_name, d.file_path, d.id AS document_id,
                       0.90 AS similarity
                FROM   chunks c
                JOIN   documents d ON d.id = c.document_id
                JOIN   embeddings e ON e.chunk_id = c.id
                WHERE  {and_conditions}
                  AND  {self._accessible_dept_clause()}
                ORDER  BY c.id
                LIMIT  %s
                """,
                and_params,
            )
            rows = [dict(r) for r in cur.fetchall()]

            if not rows:
                # ── ANY fallback: at least one keyword must appear ────────────────
                cur.execute(
                    f"""
                    SELECT DISTINCT ON (c.id)
                           c.id AS chunk_id, c.chunk_text, c.document_id, c.page_num,
                           d.file_name, d.file_path, d.id AS document_id,
                           0.85 AS similarity
                    FROM   chunks c
                    JOIN   documents d ON d.id = c.document_id
                    JOIN   embeddings e ON e.chunk_id = c.id
                    WHERE  c.chunk_text ILIKE ANY(%s)
                      AND  {self._accessible_dept_clause()}
                    ORDER  BY c.id
                    LIMIT  %s
                    """,
                    (patterns, dept_id, dept_id, top_k),
                )
                rows = [dict(r) for r in cur.fetchall()]

            cur.close()
            for r in rows:
                r["_keyword_hit"] = True
            return rows
        finally:
            self._put_conn(conn)

    def keyword_search_by_filename_pattern(self, keywords: list, dept_id: str,
                                            filename_pattern: str, top_k: int = 5) -> list:
        """Keyword search restricted to a filename ILIKE pattern (e.g. 'MAY-U3-RM-24-25-31')."""
        if not keywords or not filename_pattern:
            return []
        conn = self._get_conn()
        try:
            patterns = [f'%{kw.lower()}%' for kw in keywords]
            cur = self._cur(conn)
            and_conditions = " AND ".join(["c.chunk_text ILIKE %s"] * len(patterns))
            cur.execute(
                f"""
                SELECT DISTINCT ON (c.id)
                       c.id AS chunk_id, c.chunk_text, c.document_id, c.page_num,
                       d.file_name, d.file_path, d.id AS document_id,
                       0.90 AS similarity
                FROM   chunks c
                JOIN   documents d ON d.id = c.document_id
                JOIN   embeddings e ON e.chunk_id = c.id
                WHERE  {and_conditions}
                  AND  d.file_name ILIKE %s
                  AND  {self._accessible_dept_clause()}
                ORDER  BY c.id
                LIMIT  %s
                """,
                patterns + [f'%{filename_pattern}%', dept_id, dept_id, top_k],
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            for r in rows:
                r["_keyword_hit"] = True
            return rows
        finally:
            self._put_conn(conn)

    # ── Retrieval log ─────────────────────────────────────────────────────────

    def log_retrieval(self, chat_id, user_id, dept_id, query_text, chunk_ids, scores):
        conn = self._get_conn()
        try:
            cur = self._cur(conn)
            cur.execute(
                "INSERT INTO rag_retrieval_log "
                "(chat_id,user_id,department_id,query_text,retrieved_chunk_ids,similarity_scores) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (chat_id, user_id, dept_id, query_text, Json(chunk_ids), Json(scores))
            )
            cur.close()
        finally:
            self._put_conn(conn)
