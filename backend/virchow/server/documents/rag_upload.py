import hashlib
import os
import shutil
import uuid
import traceback
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile, Request
from sqlalchemy.orm import Session
from sqlalchemy import select

from virchow.db.engine.sql_engine import get_session
from virchow.db.custom_rag_models import Department, RagUser
from virchow.utils.logger import setup_logger

# ── RAG Pipeline Modular Components ──────────────────────────────────────────
from src.models.schemas import BatchSession as RAGBatch, FileProgress as RAGProgress, JobPayload, STAGE_PCT
from src.database.rabbitmq_broker import publish_batch
from src.config import cfg

logger = setup_logger()
logger.info("Initializing RAG Upload Router...")
router = APIRouter(prefix="/admin/rag")


def _get_or_create_system_user(db_session: Session) -> tuple:
    """Return (dept, rag_user) — creating them if needed. No auth required."""
    dept = db_session.execute(
        select(Department).where(Department.name == "General")
    ).scalars().first()
    if not dept:
        dept = Department(name="General", description="Default department")
        db_session.add(dept)
        db_session.flush()

    rag_user = db_session.execute(
        select(RagUser).where(RagUser.email == "system@virchow.local")
    ).scalars().first()
    if not rag_user:
        rag_user = RagUser(
            email="system@virchow.local",
            name="System",
            password_hash="system_managed",
            department_id=dept.id,
            is_super_admin=True,
        )
        db_session.add(rag_user)
        db_session.flush()

    return dept, rag_user


@router.post("/upload")
def rag_upload_file(
    request: Request,
    files: List[UploadFile] = File(...),
    db_session: Session = Depends(get_session),
) -> dict:
    """Upload files and enqueue them in the modular RAG pipeline."""
    rsm        = request.app.state.rsm
    mq_conn    = request.app.state.mq_conn
    dept, user = _get_or_create_system_user(db_session)
    
    # 1. Create Redis Batch
    batch = RAGBatch(
        user_id=str(user.id),
        dept_id=str(dept.id),
        total=len(files),
        upload_type="admin"
    )
    rsm.create_session(batch)
    
    jobs = []
    results = []
    
    for file in files:
        file_id = str(uuid.uuid4())
        # Save to local shared buffer (volume path)
        save_path = os.path.join("./rag-docs", f"{file_id}_{file.filename}")
        os.makedirs("./rag-docs", exist_ok=True)
        
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        # 2. Register file in Redis for progress tracking
        fp = RAGProgress(
            file_id=file_id,
            session_id=batch.session_id,
            filename=file.filename,
            size_kb=float(os.path.getsize(save_path)) / 1024.0
        )
        rsm.register_file(batch.session_id, fp)
        
        # 3. Create AMQP Job Payload
        job = JobPayload(
            job_id=file_id,
            session_id=batch.session_id,
            file_id=file_id,
            filename=file.filename,
            file_path=os.path.abspath(save_path),
            file_size_kb=fp.size_kb,
            user_id=batch.user_id,
            dept_id=batch.dept_id,
            upload_type=batch.upload_type
        )
        jobs.append(job)
        
        results.append({
            "name": file.filename,
            "id": file_id,
            "status": "QUEUED"
        })

    # 4. Publish Batch to RabbitMQ
    publish_batch(jobs)
    
    return {"session_id": batch.session_id, "results": results}


@router.get("/list")
def list_uploads(
    request: Request,
    limit: int = 50
) -> dict:
    """List all RAG uploads managed by the Redis State Manager."""
    rsm = request.app.state.rsm
    
    # List sessions from Redis
    sessions = rsm.list_sessions(limit=10)
    all_uploads = []
    
    for s in sessions:
        summary = rsm.session_summary(s["session_id"])
        if summary:
            # Re-format for the frontend (FileUploadPage.tsx expects UploadedFileRecord interface)
            for f in summary["files"]:
                all_uploads.append({
                    "id": f["file_id"],
                    "name": f["filename"],
                    "status": (
                        "COMPLETED" if f["stage"] == "done"
                        else "FAILED TO UPLOAD" if f["stage"] == "error"
                        else "IN PROGRESS"
                    ),
                    "type": "application/pdf",
                    "size": int(float(f["size_kb"]) * 1024),
                    "uploaded_by": "System",
                    "uploaded_at": f.get("started_at", "0") if f.get("started_at") else s["created_at"],
                    "version": "v1",
                    "error_message": f.get("error")
                })

    # Sort strictly by ID or time if needed
    return {"uploads": all_uploads[:limit]}
