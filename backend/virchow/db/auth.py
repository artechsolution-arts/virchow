from src.database.postgres_db import get_pg_connection

async def get_user_count():
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

def __getattr__(name):
    return lambda *args, **kwargs: None
