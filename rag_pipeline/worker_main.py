import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root and sibling dots_ocr to sys.path
_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_root))
sys.path.append(str(_root.parent)) # for dots_ocr if it's a sibling

env_path = _root / ".env"
print(f"DEBUG: ROOT={_root}")
print(f"DEBUG: ENV_PATH={env_path}")
print(f"DEBUG: PG_HOST before load_dotenv: {os.getenv('PG_HOST')}")
load_dotenv(dotenv_path=str(env_path))
print(f"DEBUG: PG_HOST after load_dotenv: {os.getenv('PG_HOST')}")

import logging
import signal
import threading
from src.database.postgres_db import get_pg_pool
from src.database.redis_db import RedisStateManager
from src.storage.seaweedfs_client import SeaweedFSClient
from src.storage.storage_service import StorageService
from src.services.rag_pipeline import RAGPipeline
from src.worker.pool import WorkerPool
from src.config import cfg

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("rag_worker")

def run_worker():
    """Initialise and start the background worker pool."""
    logger.info("Starting Enterprise RAG Ingestion Worker Pool...")

    # 1. Shared Infrastructure
    pool = get_pg_pool(minconn=1, maxconn=10)
    rsm = RedisStateManager()
    
    # 2. SeaweedFS Object Storage
    sw_client = SeaweedFSClient(filer_url=cfg.SEAWEEDFS_FILER_URL, master_url=cfg.SEAWEEDFS_MASTER_URL)
    storage = StorageService(sw_client)

    # 3. Pipeline
    pipeline = RAGPipeline(conn=pool, rsm=rsm, storage=storage)

    # 4. Worker Pool
    # We use 4 dedicated workers for CPU-bound OCR and Embedding
    n_workers = int(getattr(cfg, "upload_workers", 4))
    worker_pool = WorkerPool(rsm=rsm, pipeline=pipeline, n=n_workers)
    
    # 5. Graceful Shutdown
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received. Stopping worker pool...")
        worker_pool.stop(timeout=15.0)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    worker_pool.start()
    
    # Keep main alive
    while True:
        try:
            threading.Event().wait(1.0)
        except KeyboardInterrupt:
            signal_handler(None, None)

if __name__ == "__main__":
    run_worker()
