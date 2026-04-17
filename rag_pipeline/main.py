import uvicorn
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.config import cfg
from src.database.postgres_db import get_pg_pool, create_schema, RBACManager
from src.database.redis_db import RedisStateManager
from src.database.rabbitmq_broker import rabbit_connect, setup_topology
from src.services.rag_pipeline import RAGPipeline
from src.storage.seaweedfs_client import SeaweedFSClient
from src.storage.storage_service import StorageService
from src.api.routes import create_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("rag_api")

def bootstrap():
    """Initialise all infrastructure connections and services."""
    logger.info("Starting Enterprise RAG API...")

    # 1. PostgreSQL (Metadata & Retrieval)
    pool = get_pg_pool(minconn=5, maxconn=40)
    # Perform cold-start schema update
    with pool.getconn() as conn:
        create_schema(conn)
    
    # 2. Redis (Progress & State)
    rsm = RedisStateManager()
    
    # 3. RabbitMQ (Job Queueing)
    mq_conn = rabbit_connect()
    setup_topology(mq_conn)
    
    # 4. SeaweedFS (Object Storage)
    filer_url = cfg.SEAWEEDFS_FILER_URL
    master_url = cfg.SEAWEEDFS_MASTER_URL
    sw_client = SeaweedFSClient(filer_url=filer_url, master_url=master_url)
    storage = StorageService(sw_client)

    # 5. Pipeline & Router
    pipeline = RAGPipeline(conn=pool, rsm=rsm, storage=storage)
    
    # 6. ID Defaults (from Danswer metadata or system)
    ids = {
        "user_default": "00000000-0000-0000-0000-000000000001",
        "dept_default": "00000000-0000-0000-0000-000000000002"
    }

    app = FastAPI(title="Virchow RAG Full Stack API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    router = create_router(rsm=rsm, ids=ids, pipeline=pipeline, mq_conn=mq_conn)
    app.include_router(router)
    
    return app

app = bootstrap()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
