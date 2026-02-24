"""
GPI Document Hub - Main Server (Simplified)

This is the refactored entry point. Routes are organized in /routes/.
"""

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from contextlib import asynccontextmanager
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ROUTERS ====================
from routes import documents, ingestion, workflows, dashboard, config

# ==================== SERVICES ====================
from services.workflow_engine import WorkflowEngine
from services.ai_classifier import AIClassifier

# ==================== DATABASE ====================
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_hub")

db = None
mongo_client = None


# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global db, mongo_client
    
    # Startup
    logger.info("Starting GPI Document Hub...")
    
    # Connect to MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    db = mongo_client[DB_NAME]
    
    # Initialize routers with database
    documents.set_db(db)
    ingestion.set_dependencies(db, classify_document, route_to_workflow)
    workflows.set_dependencies(db, WorkflowEngine)
    dashboard.set_db(db)
    config.set_db(db)
    
    # Create indexes
    await create_indexes()
    
    logger.info("GPI Document Hub started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down GPI Document Hub...")
    if mongo_client:
        mongo_client.close()


async def create_indexes():
    """Create database indexes."""
    # Documents
    await db.hub_documents.create_index("id", unique=True)
    await db.hub_documents.create_index("doc_type")
    await db.hub_documents.create_index("status")
    await db.hub_documents.create_index("workflow_status")
    await db.hub_documents.create_index("source")
    await db.hub_documents.create_index("content_hash")
    await db.hub_documents.create_index("created_utc")
    
    # Mailboxes
    await db.mailbox_sources.create_index("id", unique=True)
    await db.mailbox_sources.create_index("email_address")
    
    # Vendor aliases
    await db.vendor_aliases.create_index("id", unique=True)
    await db.vendor_aliases.create_index("alias_normalized")
    
    logger.info("Database indexes created")


# ==================== CLASSIFICATION ====================
async def classify_document(file_content: bytes, file_name: str, category_hint: str = None) -> dict:
    """
    Classify a document using AI or deterministic rules.
    
    Returns:
        {
            "doc_type": "AP_INVOICE",
            "category": "AP",
            "confidence": 0.95,
            "method": "ai",
            "extracted_fields": {...}
        }
    """
    try:
        # Try AI classification
        classifier = AIClassifier()
        result = await classifier.classify(file_content, file_name)
        
        return {
            "doc_type": result.get("suggested_job_type", "OTHER"),
            "category": result.get("category", category_hint or "UNKNOWN"),
            "confidence": result.get("confidence", 0),
            "method": "ai",
            "extracted_fields": result.get("extracted_fields", {}),
            "reasoning": result.get("reasoning", "")
        }
    except Exception as e:
        logger.warning(f"AI classification failed: {e}")
        
        # Fallback to category hint
        return {
            "doc_type": "OTHER",
            "category": category_hint or "UNKNOWN",
            "confidence": 0,
            "method": "fallback",
            "extracted_fields": {},
            "error": str(e)
        }


async def route_to_workflow(doc_id: str, doc_type: str):
    """
    Route document to appropriate workflow based on doc_type.
    
    This triggers the workflow engine to start processing.
    """
    logger.info(f"Routing document {doc_id} to {doc_type} workflow")
    
    # The workflow engine handles state transitions
    # For now, just log - actual implementation in workflow_engine.py
    pass


# ==================== APP SETUP ====================
app = FastAPI(
    title="GPI Document Hub",
    description="Unified document processing and workflow management",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Router with /api prefix
api_router = APIRouter(prefix="/api")

# Include route modules
api_router.include_router(documents.router)
api_router.include_router(ingestion.router)
api_router.include_router(workflows.router)
api_router.include_router(dashboard.router)
api_router.include_router(config.router)

# Mount to app
app.include_router(api_router)


# ==================== ROOT ENDPOINTS ====================
@app.get("/")
async def root():
    return {
        "service": "GPI Document Hub",
        "version": "2.0.0",
        "status": "running"
    }


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "gpi-document-hub"
    }


# ==================== AUTH (Simplified) ====================
from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

@api_router.post("/auth/login")
async def login(req: LoginRequest):
    """Simple auth for demo mode."""
    if req.username == "admin" and req.password == "admin":
        return {
            "token": "demo-token-12345",
            "user": {"username": "admin", "role": "admin"}
        }
    return {"error": "Invalid credentials"}

@api_router.get("/auth/me")
async def get_me():
    return {"username": "admin", "role": "admin"}
