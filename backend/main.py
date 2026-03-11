"""
GPI Document Hub - Main Application Entry Point

This is the clean, modular entry point for the application.
It composes the app from:
  1. Modular routers in /routers/  (cleanly extracted domain modules)
  2. Legacy api_router from server.py  (routes not yet extracted)
  3. Additional module routers (sales, ap_review, spiro)

server.py is imported as a library — its startup/shutdown functions
handle all service initialization and teardown.
"""

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Import server module (runs module-level code: DB connection, imports, etc.)
# We treat server.py as a library, NOT as the served app.
# ---------------------------------------------------------------------------
import server

# Legacy api_router — contains all document/workflow routes still in server.py
from server import api_router as legacy_api_router

# Additional routers defined outside of /routers/
from sales_module import sales_router
from routes.ap_review import ap_review_router, set_dependencies as set_ap_review_deps
from routes.spiro import spiro_router

# ---------------------------------------------------------------------------
# Modular routers (extracted from the monolith into /routers/)
# ---------------------------------------------------------------------------
from routers.automation_rules import router as automation_rules_router
from routers.freight_routing import router as freight_routing_router
from routers.label_corrections import router as label_corrections_router
from routers.alerts import router as alerts_router
from routers.vendor_extraction_profiles import router as vep_router
from routers.layout_fingerprints import router as layout_fp_router
from routers.vendor_intelligence import router as vendor_intel_router
from routers.cache import router as cache_router
from routers.metrics import router as metrics_router
from routers.bc_sandbox import router as bc_sandbox_router
from routers.ap_validation import router as ap_validation_router
from routers.pilot import router as pilot_router
from routers.events import router as events_router
from routers.settings import router as settings_router
from routers.admin import router as admin_router
from routers.auto_clear import router as auto_clear_router
from routers.dashboard import router as dashboard_router
from routers.sharepoint import router as sharepoint_admin_router
from routers.square9 import router as square9_router
from routers.email_polling import router as email_polling_router
from routers.vendors import router as vendors_router
from routers.migration_routes import router as migration_routes_router
from routers.stable_vendor import router as stable_vendor_router

# ---------------------------------------------------------------------------
# NEW: Thin-wrapper routers extracted from server.py (Phase 2 refactor)
# ---------------------------------------------------------------------------
from routers.auth_routes import router as auth_routes_router
from routers.documents_routes import router as documents_routes_router
from routers.workflows_routes import router as workflows_routes_router
from routers.bc_routes import router as bc_routes_router
from routers.mailbox_routes import router as mailbox_routes_router
from routers.aliases_routes import router as aliases_routes_router
from routers.spiro_routes import router as spiro_routes_router
from routers.file_import_routes import router as file_import_routes_router
from routers.reference_intelligence_v2 import router as ref_intel_v2_router
from routers.processors import router as processors_router
from routers.transaction_graph import router as transaction_graph_router
from routers.processor_specs import router as processor_specs_router
from routers.transaction_search import router as transaction_search_router

# ==================== APP ====================
app = FastAPI(title="GPI Document Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== MODULAR ROUTERS (prefix /api) ====================
app.include_router(automation_rules_router, prefix="/api")
app.include_router(freight_routing_router, prefix="/api")
app.include_router(label_corrections_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(vep_router, prefix="/api")
app.include_router(layout_fp_router, prefix="/api")
app.include_router(vendor_intel_router, prefix="/api")
app.include_router(cache_router, prefix="/api")
app.include_router(metrics_router, prefix="/api")
app.include_router(bc_sandbox_router, prefix="/api")
app.include_router(ap_validation_router, prefix="/api")
app.include_router(pilot_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(auto_clear_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(sharepoint_admin_router, prefix="/api")
app.include_router(square9_router, prefix="/api")
app.include_router(email_polling_router, prefix="/api")
app.include_router(vendors_router, prefix="/api")
app.include_router(migration_routes_router, prefix="/api")
app.include_router(stable_vendor_router, prefix="/api")

# NEW: Thin-wrapper routers from server.py extraction (loaded before legacy)
app.include_router(auth_routes_router, prefix="/api")
app.include_router(documents_routes_router, prefix="/api")
app.include_router(workflows_routes_router, prefix="/api")
app.include_router(bc_routes_router, prefix="/api")
app.include_router(mailbox_routes_router, prefix="/api")
app.include_router(aliases_routes_router, prefix="/api")
app.include_router(spiro_routes_router, prefix="/api")
app.include_router(file_import_routes_router, prefix="/api")
app.include_router(ref_intel_v2_router, prefix="/api")
app.include_router(processors_router, prefix="/api")
app.include_router(transaction_graph_router, prefix="/api")
app.include_router(processor_specs_router, prefix="/api")
app.include_router(transaction_search_router, prefix="/api")

# ==================== LEGACY ROUTERS ====================
# api_router has prefix="/api" — document, workflow, alias, BC, sales-file-import routes
app.include_router(legacy_api_router)
# Sales Module (Phase 0)
app.include_router(sales_router)
# AP Review Module
app.include_router(ap_review_router)
# Spiro Integration Module
app.include_router(spiro_router)


# ==================== HEALTH CHECK ====================
@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "gpi-document-hub"}


# ==================== LIFECYCLE ====================
@app.on_event("startup")
async def startup():
    """Delegate to server.py's comprehensive startup initialization."""
    logger.info("main.py startup — delegating to server.startup()")
    await server.startup()
    # Part 6: BC environment startup validation + fingerprint
    from services.bc_config import validate_and_log
    validate_and_log()
    logger.info("main.py startup complete")


@app.on_event("shutdown")
async def shutdown():
    """Delegate to server.py's cleanup."""
    logger.info("main.py shutdown — delegating to server.shutdown_db_client()")
    await server.shutdown_db_client()
    logger.info("main.py shutdown complete")
