from fastapi import APIRouter, Body
from pydantic import BaseModel
from typing import List, Optional
import logging
import uuid

from src.database.postgres_db import RBACManager, get_pg_connection

logger = logging.getLogger(__name__)

# A stub router that returns empty lists/dicts to satisfy frontend
def create_empty_router():
    router = APIRouter()
    
    @router.get("/admin/llm/built-in/options")
    async def get_built_in_options(): return []
    
    @router.get("/admin/kg/exposed")
    async def get_kg_exposed(): return []
    
    @router.get("/manage/users/accepted/all")
    async def get_all_users():
        try:
            conn = get_pg_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT u.id, u.email, u.name, u.role, d.name as department, u.is_active, u.created_at
                FROM users u
                JOIN departments d ON u.department_id = d.id
            """)
            rows = cur.fetchall()
            users = []
            for row in rows:
                users.append({
                    "id": str(row[0]),
                    "email": row[1],
                    "personal_name": row[2],
                    "role": row[3],
                    "department": row[4],
                    "status": "active" if row[5] else "inactive",
                    "is_active": row[5],
                    "is_scim_synced": False,
                    "company": "Virchow",
                    "created_at": row[6].isoformat() if row[6] else None,
                    "updated_at": None,
                    "groups": []
                })
            cur.close()
            conn.close()
            return users
        except Exception as e:
            logger.error(f"Failed to fetch users: {e}")
            return []
    
    @router.get("/manage/users/invited")
    async def get_invited_users(): return []
    
    @router.get("/llm/provider")
    async def get_llm_providers(): return []
    
    @router.get("/manage/users/counts")
    async def get_user_counts(): 
        try:
            conn = get_pg_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return {"count": count}
        except Exception:
            return {"count": 0}
    
    @router.get("/manage/admin/users/add")
    async def get_add_user(): return {}
    
    @router.post("/manage/admin/users/add")
    async def post_add_user(data: dict = Body(...)):
        try:
            conn = get_pg_connection()
            rbac = RBACManager(conn)
            
            # Ensure department exists
            dept_name = data.get("department", "QA")
            cur = conn.cursor()
            cur.execute("SELECT id FROM departments WHERE name = %s", (dept_name,))
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (dept_name,))
                dept_id = cur.fetchone()[0]
            else:
                dept_id = row[0]
            cur.close()
            
            # Create user
            rbac.create_user(
                email=data["email"],
                name=data["personal_name"],
                password_hash=data["password"], # Dev: storing plan text or simple hash
                department_id=dept_id,
                role=data.get("role", "user"),
                mobile_number=data.get("mobile_number")
            )
            conn.close()
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to add user: {e}")
            return {"status": "error", "detail": str(e)}

    @router.get("/health")
    async def health(): return {"status": "ok"}

    @router.get("/state")
    async def state(): return {"status": "ok"}

    @router.get("/admin/enterprise-settings/scim/token")
    async def get_scim_token(): return {"token": None}

    @router.get("/manage/connector-status")
    async def get_connector_status(): return []

    @router.post("/admin/llm/test/default")
    async def test_llm(): return {"status": "ok"}

    @router.post("/chat/create-chat-session")
    async def create_chat_session(_payload: dict = Body(...)):
        return {"chat_session_id": str(uuid.uuid4())}

    @router.get("/chat/get-user-chat-sessions")
    async def get_user_chat_sessions(page_size: int = 50):  # noqa: ARG001
        return {"sessions": [], "has_more": False}

    return router

def configure_app_with_stubs(app):
    stub_router = create_empty_router()
    app.include_router(stub_router)
