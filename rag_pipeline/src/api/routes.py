import logging
from fastapi import APIRouter, HTTPException, Depends, Form, Cookie, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, EmailStr
from typing import Optional
from src.auth.jwt_auth import (
    hash_password, verify_password, create_token, get_current_user, decode_token
)

logger = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    department_id: str = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def create_router(svc):
    router = APIRouter()

    # ── Auth ──────────────────────────────────────────────────────────────────

    @router.post("/auth/register")
    async def register(req: RegisterRequest):
        dept_id = req.department_id or svc.rbac.get_or_create_default_dept()
        existing = svc.rbac.get_user_by_email(req.email)
        if existing:
            raise HTTPException(409, "Email already registered")
        user_id = svc.rbac.create_user(
            email=req.email,
            name=req.name,
            password_hash=hash_password(req.password),
            department_id=dept_id,
        )
        token = create_token(user_id, req.email, dept_id)
        return JSONResponse({"token": token, "user_id": user_id, "dept_id": dept_id, "name": req.name})

    @router.post("/auth/login")
    async def login(req: LoginRequest):
        user = svc.rbac.get_user_by_email(req.email)
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(401, "Invalid email or password")
        if not user["is_active"]:
            raise HTTPException(403, "Account is disabled")
        svc.rbac.update_last_login(str(user["id"]))
        dept_id = str(user["department_id"])
        token = create_token(str(user["id"]), user["email"], dept_id)
        return JSONResponse({
            "token": token,
            "user_id": str(user["id"]),
            "dept_id": dept_id,
            "name": user["name"],
            "role": user["role"],
            "is_super_admin": user["is_super_admin"],
        })

    @router.get("/auth/departments")
    async def list_departments():
        return JSONResponse(svc.rbac.list_departments())

    # ── Query ─────────────────────────────────────────────────────────────────

    @router.post("/query")
    async def rag_query(
        request: Request,
        user: dict = Depends(get_current_user),
    ):
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body = await request.json()
            question = body.get("question", "")
            chat_id = body.get("chat_id") or None
        else:
            form = await request.form()
            question = form.get("question", "")
            chat_id = form.get("chat_id") or None
            if chat_id == "null":
                chat_id = None
        try:
            result = svc.query(
                question=question,
                user_id=user["sub"],
                dept_id=user["dept_id"],
                chat_id=chat_id,
            )
            return JSONResponse(result)
        except Exception as e:
            logger.error(f"Query error: {e}", exc_info=True)
            raise HTTPException(500, detail=str(e))

    # ── Chat history ──────────────────────────────────────────────────────────

    @router.get("/chats")
    async def get_chats(user: dict = Depends(get_current_user)):
        chats = svc.rbac.get_user_chats(user["sub"], user["dept_id"])
        return JSONResponse(chats)

    @router.post("/chats/create")
    async def create_chat_session(user: dict = Depends(get_current_user)):
        chat_id = svc.rbac.create_chat(user["sub"], user["dept_id"], title=None)
        return JSONResponse({"chat_session_id": chat_id})

    @router.get("/chats/{chat_id}/messages")
    async def get_messages(chat_id: str, user: dict = Depends(get_current_user)):
        msgs = svc.rbac.get_messages_full(chat_id, user["dept_id"])
        return JSONResponse(msgs)

    @router.get("/chats/{chat_id}/meta")
    async def get_chat_meta(chat_id: str, user: dict = Depends(get_current_user)):
        meta = svc.rbac.get_chat_meta(chat_id, user["sub"])
        if not meta:
            raise HTTPException(404, "Chat not found")
        return JSONResponse(meta)

    @router.put("/chats/{chat_id}/rename")
    async def rename_chat(chat_id: str, request: Request, user: dict = Depends(get_current_user)):
        body = await request.json()
        title = body.get("name", "")
        svc.rbac.rename_chat(chat_id, user["sub"], title)
        return JSONResponse({"ok": True})

    @router.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str, user: dict = Depends(get_current_user)):
        svc.rbac.delete_chat(chat_id, user["sub"])
        return JSONResponse({"ok": True})

    # ── Document redirect ─────────────────────────────────────────────────────

    @router.get("/api/documents/{doc_id}")
    async def get_document(doc_id: str):
        """Redirect to SeaweedFS URL for the document."""
        import os
        from fastapi.responses import RedirectResponse
        from src.config import cfg as _cfg

        conn = svc.rbac._get_conn()
        try:
            cur = svc.rbac._cur(conn)
            cur.execute("SELECT file_name, file_path FROM documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            cur.close()
        finally:
            svc.rbac._put_conn(conn)

        if not row:
            raise HTTPException(404, "Document not found")

        file_name, file_path = row["file_name"], row["file_path"]
        basename = os.path.basename(file_path)
        uuid_part = basename[:36]
        filename = basename[37:]
        seaweed_url = f"{_cfg.seaweedfs_filer_url}/buckets/{_cfg.seaweedfs_bucket}/raw/{uuid_part}/{filename}"

        return RedirectResponse(url=seaweed_url, status_code=302)

    # ── Health ────────────────────────────────────────────────────────────────

    @router.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    @router.get("/api/health")
    async def api_health():
        return JSONResponse({"status": "ok"})

    # ── Web-app compat endpoints (called server-side by Next.js) ─────────────

    @router.get("/api/auth/type")
    async def auth_type():
        return JSONResponse({
            "auth_type": "basic",
            "requires_verification": False,
            "anonymous_user_enabled": False,
            "password_min_length": 8,
            "has_users": True,
            "oauth_enabled": False,
        })

    @router.get("/api/me")
    async def web_me(request: Request):
        token = request.cookies.get("fastapiusersauth")
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            payload = decode_token(token)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = svc.rbac.get_user_by_id(payload["sub"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        name = user.get("name", "")
        return JSONResponse({
            "id": str(user["id"]),
            "email": user["email"],
            "is_active": user["is_active"],
            "is_superuser": user.get("is_super_admin", False),
            "is_verified": True,
            "role": "admin",
            "is_anonymous_user": False,
            "team_name": None,
            "password_configured": True,
            "preferences": {
                "auto_scroll": True,
                "temperature_override_enabled": False,
                "default_app_mode": "chat",
            },
            "personalization": {
                "name": name,
                "theme_preference": None,
                "auto_scroll": True,
                "default_app_mode": "chat",
                "pinned_assistants": None,
            },
        })

    @router.get("/api/chat/get-chat-session/{chat_id}")
    async def get_chat_session_compat(chat_id: str, request: Request):
        """Compat endpoint: Next.js rewrite forwards /api/chat/get-chat-session/{id} here.
        Accepts token from Authorization header OR fastapiusersauth cookie."""
        token = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = request.cookies.get("fastapiusersauth")
        if not token:
            raise HTTPException(401, "Not authenticated")
        try:
            user = decode_token(token)
        except HTTPException:
            raise HTTPException(401, "Invalid token")
        import re as _re
        _SINGLE_PREFIX_RE = _re.compile(
            r'^\*\*[^*]+\.(pdf|xlsx?|docx?|csv|txt)\*\*\n',
            _re.IGNORECASE,
        )
        _MULTI_PREFIX_RE = _re.compile(
            r'\n\n\*\*[^*]+\.(pdf|xlsx?|docx?|csv|txt)\*\*\n',
            _re.IGNORECASE,
        )
        def _strip_prefix(content: str, role: str) -> str:
            if role != "assistant":
                return content
            # Only strip single-source prefix (multi-source keeps file headers for attribution)
            if _SINGLE_PREFIX_RE.match(content) and not _MULTI_PREFIX_RE.search(content):
                return _SINGLE_PREFIX_RE.sub("", content, count=1).strip()
            return content

        msgs = svc.rbac.get_messages_full(chat_id, user["dept_id"])
        meta = svc.rbac.get_chat_meta(chat_id, user["sub"]) or {}
        messages = [
            {
                "message_id": idx + 1,
                "message_type": "user" if m["role"] == "user" else "assistant",
                "research_type": None,
                "parent_message": idx if idx > 0 else None,
                "latest_child_message": idx + 2 if idx < len(msgs) - 1 else None,
                "message": _strip_prefix(m["content"], m["role"]),
                "rephrased_query": None,
                "context_docs": None,
                "time_sent": m.get("created_at"),
                "overridden_model": "",
                "alternate_assistant_id": None,
                "chat_session_id": chat_id,
                "citations": None,
                "files": [],
                "tool_call": None,
                "current_feedback": None,
                "sub_questions": [],
                "comments": None,
                "parentMessageId": None,
                "refined_answer_improvement": None,
                "is_agentic": None,
            }
            for idx, m in enumerate(msgs)
        ]
        return JSONResponse({
            "chat_session_id": chat_id,
            "description": meta.get("title") or "New Chat",
            "persona_id": 0,
            "persona_name": "Virchow Assistant",
            "messages": messages,
            "time_created": meta.get("created_at"),
            "time_updated": meta.get("updated_at"),
            "shared_status": "private",
            "current_temperature_override": None,
            "current_alternate_model": "",
            "owner_name": None,
            "packets": [],
        })

    @router.get("/api/settings")
    async def web_settings():
        return JSONResponse({
            "anonymous_user_enabled": False,
            "invite_only_enabled": False,
            "notifications": [],
            "needs_reindexing": False,
            "gpu_enabled": False,
            "application_status": "active",
            "auto_scroll": True,
            "temperature_override_enabled": False,
            "query_history_type": "disabled",
        })

    @router.get("/api/enterprise-settings")
    async def web_enterprise_settings():
        return JSONResponse({
            "whitelabeling": None,
            "custom_header_content": None,
            "custom_header_logo": None,
            "two_factor_auth_enabled": False,
            "anonymous_user_enabled": False,
            "enable_paid_enterprise_edition_features": False,
        })

    # ── Frontend (single-page chat app) ───────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def frontend():
        return HTMLResponse(content=_HTML)

    return router


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Virchow — Knowledge Assistant</title>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: rgba(255,255,255,0.08);
    --primary: #3b82f6; --primary-dim: rgba(59,130,246,0.15);
    --text: #f1f5f9; --muted: #64748b; --success: #10b981; --error: #ef4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui,sans-serif; background: var(--bg); color: var(--text);
         height: 100vh; overflow: hidden; }
  #app { display: flex; height: 100vh; }

  /* ── Auth overlay ── */
  #auth-overlay {
    position: fixed; inset: 0; background: var(--bg);
    display: flex; align-items: center; justify-content: center; z-index: 999;
  }
  .auth-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 1rem; padding: 2.5rem; width: 380px;
  }
  .auth-card h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }
  .auth-card p  { color: var(--muted); font-size: 0.9rem; margin-bottom: 1.75rem; }
  .field { margin-bottom: 1rem; }
  .field label { display: block; font-size: 0.75rem; color: var(--muted);
                 text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem; }
  .field input, .field select {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    border-radius: 0.5rem; padding: 0.65rem 0.85rem; color: var(--text);
    font-size: 0.95rem; outline: none;
  }
  .field input:focus, .field select:focus { border-color: var(--primary); }
  .btn {
    width: 100%; padding: 0.75rem; border: none; border-radius: 0.5rem;
    background: var(--primary); color: #fff; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: opacity 0.15s;
  }
  .btn:hover { opacity: 0.9; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .tab-row { display: flex; gap: 0.5rem; margin-bottom: 1.75rem; }
  .tab {
    flex: 1; padding: 0.5rem; border: 1px solid var(--border); border-radius: 0.5rem;
    background: none; color: var(--muted); cursor: pointer; font-size: 0.9rem;
  }
  .tab.active { background: var(--primary-dim); color: var(--primary); border-color: var(--primary); }
  .auth-msg { margin-top: 1rem; font-size: 0.85rem; text-align: center; min-height: 1.2em; }

  /* ── Sidebar ── */
  aside {
    width: 240px; background: var(--surface); border-right: 1px solid var(--border);
    display: flex; flex-direction: column; flex-shrink: 0;
  }
  .sidebar-header {
    padding: 1.25rem 1rem; border-bottom: 1px solid var(--border);
    font-weight: 700; font-size: 1.1rem;
    background: linear-gradient(to right, #60a5fa, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .new-chat-btn {
    margin: 0.75rem; padding: 0.6rem; border: 1px dashed var(--border);
    border-radius: 0.5rem; background: none; color: var(--muted); cursor: pointer;
    font-size: 0.85rem; text-align: left;
  }
  .new-chat-btn:hover { border-color: var(--primary); color: var(--primary); }
  #chat-list { flex: 1; overflow-y: auto; padding: 0 0.5rem; }
  .chat-item {
    padding: 0.6rem 0.75rem; border-radius: 0.5rem; cursor: pointer;
    font-size: 0.85rem; color: var(--muted); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.25rem;
  }
  .chat-item:hover, .chat-item.active { background: var(--primary-dim); color: var(--text); }
  .sidebar-footer {
    padding: 1rem; border-top: 1px solid var(--border); font-size: 0.8rem; color: var(--muted);
  }
  .logout-btn {
    margin-top: 0.5rem; background: none; border: 1px solid var(--border);
    border-radius: 0.4rem; color: var(--muted); padding: 0.35rem 0.75rem;
    cursor: pointer; font-size: 0.8rem;
  }
  .logout-btn:hover { color: var(--error); border-color: var(--error); }

  /* ── Main chat area ── */
  main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  #messages {
    flex: 1; overflow-y: auto; padding: 1.5rem;
    display: flex; flex-direction: column; gap: 1rem;
  }
  .bubble {
    max-width: 720px; padding: 0.9rem 1.1rem; border-radius: 1rem;
    line-height: 1.65; font-size: 0.95rem; white-space: pre-wrap;
  }
  .bubble.user { align-self: flex-end; background: var(--primary); color: #fff;
                  border-bottom-right-radius: 4px; }
  .bubble.bot  { align-self: flex-start; background: var(--surface);
                  border-bottom-left-radius: 4px; }
  .bubble .sources {
    margin-top: 0.6rem; padding-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.1);
    font-size: 0.75rem; color: #93c5fd;
  }
  .typing-dots { display: flex; gap: 5px; padding: 0.9rem 1.1rem;
                  background: var(--surface); border-radius: 1rem; width: fit-content; }
  .dot { width: 7px; height: 7px; background: var(--muted); border-radius: 50%;
          animation: bounce 1.3s infinite ease-in-out; }
  .dot:nth-child(2) { animation-delay: 0.15s; }
  .dot:nth-child(3) { animation-delay: 0.3s; }
  @keyframes bounce { 0%,80%,100% { transform: scale(0.6); } 40% { transform: scale(1); } }

  #input-area {
    padding: 1rem 1.5rem; border-top: 1px solid var(--border);
    display: flex; gap: 0.75rem; align-items: flex-end;
  }
  #msg-input {
    flex: 1; background: var(--surface); border: 1px solid var(--border);
    border-radius: 0.75rem; padding: 0.75rem 1rem; color: var(--text);
    font-size: 0.95rem; font-family: inherit; resize: none; outline: none;
    max-height: 160px;
  }
  #msg-input:focus { border-color: var(--primary); }
  #send-btn {
    width: 42px; height: 42px; border-radius: 0.65rem; border: none;
    background: var(--primary); color: #fff; cursor: pointer; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
  }
  #send-btn:disabled { opacity: 0.5; cursor: default; }

  .empty-state {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: center; color: var(--muted);
    gap: 0.5rem;
  }
  .empty-state h2 { font-size: 1.4rem; color: var(--text); }
</style>
</head>
<body>

<!-- Auth overlay -->
<div id="auth-overlay">
  <div class="auth-card">
    <h1>Virchow</h1>
    <p>Knowledge Assistant — sign in to continue</p>

    <div class="tab-row">
      <button class="tab active" onclick="showTab('login')">Sign In</button>
      <button class="tab" onclick="showTab('register')">Register</button>
    </div>

    <!-- Login form -->
    <div id="login-form">
      <div class="field"><label>Email</label><input id="l-email" type="email" placeholder="you@example.com"></div>
      <div class="field"><label>Password</label><input id="l-pass" type="password" placeholder="••••••••"></div>
      <button class="btn" onclick="doLogin()">Sign In</button>
    </div>

    <!-- Register form -->
    <div id="register-form" style="display:none">
      <div class="field"><label>Full name</label><input id="r-name" type="text" placeholder="Jane Doe"></div>
      <div class="field"><label>Email</label><input id="r-email" type="email" placeholder="you@example.com"></div>
      <div class="field"><label>Password</label><input id="r-pass" type="password" placeholder="••••••••"></div>
      <div class="field"><label>Department</label>
        <select id="r-dept"><option value="">Loading…</option></select>
      </div>
      <button class="btn" onclick="doRegister()">Create Account</button>
    </div>

    <p class="auth-msg" id="auth-msg"></p>
  </div>
</div>

<!-- Main app -->
<div id="app" style="display:none">
  <aside>
    <div class="sidebar-header">Virchow</div>
    <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
    <div id="chat-list"></div>
    <div class="sidebar-footer">
      <div id="user-label"></div>
      <button class="logout-btn" onclick="logout()">Sign out</button>
    </div>
  </aside>

  <main>
    <div id="messages">
      <div class="empty-state">
        <h2>How can I help you?</h2>
        <p>Ask anything about your knowledge base.</p>
      </div>
    </div>

    <div id="input-area">
      <textarea id="msg-input" rows="1" placeholder="Ask a question…"></textarea>
      <button id="send-btn" onclick="sendMessage()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
  </main>
</div>

<script>
  let token = localStorage.getItem('vk_token');
  let session = JSON.parse(localStorage.getItem('vk_session') || 'null');
  let currentChatId = null;
  let busy = false;

  // ── Boot ──────────────────────────────────────────────────────────────────
  window.onload = async () => {
    await loadDepts();
    if (token && session) enterApp();
    document.getElementById('msg-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  };

  async function loadDepts() {
    try {
      const r = await fetch('/auth/departments');
      const depts = await r.json();
      const sel = document.getElementById('r-dept');
      if (depts.length === 0) {
        sel.innerHTML = '<option value="">Default (auto-created)</option>';
      } else {
        sel.innerHTML = depts.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
      }
    } catch(e) { /* ignore */ }
  }

  // ── Auth tabs ─────────────────────────────────────────────────────────────
  function showTab(t) {
    document.querySelectorAll('.tab').forEach((b,i) => b.classList.toggle('active', (i===0) === (t==='login')));
    document.getElementById('login-form').style.display    = t === 'login'    ? '' : 'none';
    document.getElementById('register-form').style.display = t === 'register' ? '' : 'none';
    document.getElementById('auth-msg').textContent = '';
  }

  function setAuthMsg(txt, ok) {
    const el = document.getElementById('auth-msg');
    el.textContent = txt;
    el.style.color = ok ? 'var(--success)' : 'var(--error)';
  }

  async function doLogin() {
    const email = document.getElementById('l-email').value.trim();
    const pass  = document.getElementById('l-pass').value;
    if (!email || !pass) return setAuthMsg('Fill in all fields', false);
    try {
      const r = await fetch('/auth/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password: pass})
      });
      const d = await r.json();
      if (!r.ok) return setAuthMsg(d.detail || 'Login failed', false);
      saveSession(d);
    } catch(e) { setAuthMsg('Network error', false); }
  }

  async function doRegister() {
    const name  = document.getElementById('r-name').value.trim();
    const email = document.getElementById('r-email').value.trim();
    const pass  = document.getElementById('r-pass').value;
    const dept  = document.getElementById('r-dept').value;
    if (!name || !email || !pass) return setAuthMsg('Fill in all fields', false);
    try {
      const r = await fetch('/auth/register', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, email, password: pass, department_id: dept || null})
      });
      const d = await r.json();
      if (!r.ok) return setAuthMsg(d.detail || 'Registration failed', false);
      saveSession(d);
    } catch(e) { setAuthMsg('Network error', false); }
  }

  function saveSession(d) {
    token = d.token;
    session = {user_id: d.user_id, dept_id: d.dept_id, name: d.name};
    localStorage.setItem('vk_token', token);
    localStorage.setItem('vk_session', JSON.stringify(session));
    enterApp();
  }

  function enterApp() {
    document.getElementById('auth-overlay').style.display = 'none';
    document.getElementById('app').style.display = 'flex';
    document.getElementById('user-label').textContent = session.name;
    loadChats();
  }

  function logout() {
    localStorage.removeItem('vk_token');
    localStorage.removeItem('vk_session');
    location.reload();
  }

  // ── Chats ─────────────────────────────────────────────────────────────────
  async function loadChats() {
    try {
      const r = await authFetch('/chats');
      const chats = await r.json();
      const list = document.getElementById('chat-list');
      list.innerHTML = chats.map(c =>
        `<div class="chat-item" onclick="openChat('${c.id}')">${c.title || 'Untitled'}</div>`
      ).join('');
    } catch(e) { /* ignore */ }
  }

  function newChat() {
    currentChatId = null;
    document.getElementById('messages').innerHTML = `
      <div class="empty-state">
        <h2>How can I help you?</h2>
        <p>Ask anything about your knowledge base.</p>
      </div>`;
    document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
  }

  async function openChat(id) {
    currentChatId = id;
    document.querySelectorAll('.chat-item').forEach(el => {
      el.classList.toggle('active', el.getAttribute('onclick').includes(id));
    });
    try {
      const r = await authFetch(`/chats/${id}/messages`);
      const msgs = await r.json();
      const box = document.getElementById('messages');
      box.innerHTML = '';
      msgs.forEach(m => appendBubble(m.role === 'user' ? 'user' : 'bot', m.content));
      scrollBottom();
    } catch(e) { /* ignore */ }
  }

  // ── Messaging ─────────────────────────────────────────────────────────────
  async function sendMessage() {
    const input = document.getElementById('msg-input');
    const text  = input.value.trim();
    if (!text || busy) return;

    // Clear empty state if present
    const box = document.getElementById('messages');
    if (box.querySelector('.empty-state')) box.innerHTML = '';

    appendBubble('user', text);
    input.value = '';
    input.style.height = '';

    const dots = document.createElement('div');
    dots.className = 'typing-dots';
    dots.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
    box.appendChild(dots);
    scrollBottom();

    busy = true;
    document.getElementById('send-btn').disabled = true;

    try {
      const fd = new FormData();
      fd.append('question', text);
      if (currentChatId) fd.append('chat_id', currentChatId);

      const r = await authFetch('/query', {method: 'POST', body: fd});
      const d = await r.json();
      dots.remove();

      if (!r.ok) throw new Error(d.detail || 'Query failed');

      currentChatId = d.chat_id;
      appendBubble('bot', d.answer, d.citations || []);
      loadChats();
    } catch(e) {
      dots.remove();
      appendBubble('bot', 'Error: ' + e.message);
    } finally {
      busy = false;
      document.getElementById('send-btn').disabled = false;
      scrollBottom();
    }
  }

  function appendBubble(role, text, sources) {
    const b = document.createElement('div');
    b.className = `bubble ${role}`;
    b.textContent = text;
    if (sources && sources.length) {
      const s = document.createElement('div');
      s.className = 'sources';
      s.textContent = 'Sources: ' + sources.join(', ');
      b.appendChild(s);
    }
    document.getElementById('messages').appendChild(b);
  }

  function scrollBottom() {
    const box = document.getElementById('messages');
    box.scrollTop = box.scrollHeight;
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function authFetch(url, opts = {}) {
    return fetch(url, {
      ...opts,
      headers: {...(opts.headers || {}), 'Authorization': 'Bearer ' + token}
    });
  }

  // Auto-resize textarea
  document.addEventListener('DOMContentLoaded', () => {
    const ta = document.getElementById('msg-input');
    if (ta) ta.addEventListener('input', () => {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
    });
  });
</script>
</body>
</html>"""
