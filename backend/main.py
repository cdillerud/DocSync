"""
GPI Document Hub - Main Application Entry Point (Authoritative)

Single entry point for the application. Composes the app from:
  1. Modular routers in /routers/  (all domain modules)
  2. Sales module router

server.py is imported as a utility library — it provides startup/shutdown
lifecycle hooks, helper functions, and handler implementations consumed
by router modules.  It does NOT register any routes itself.
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
# We treat server.py as a utility library, NOT as a served app or router.
# ---------------------------------------------------------------------------
import server

# Sales module router (standalone)
from sales_module import sales_router

# ---------------------------------------------------------------------------
# All routers live under /routers/ (single convention)
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
from routers.sales_dashboard import router as sales_dashboard_router
from routers.inventory_ledger import router as inventory_ledger_router, incoming_supply_router
from routers.inventory_items import router as inventory_items_router
from routers.stable_vendor import router as stable_vendor_router
from routers.aliases import router as aliases_router
from routers.mailbox_sources import router as mailbox_sources_router
from routers.file_import import router as file_import_router
from routers.bc_integration import router as bc_integration_router
from routers.gpi_integration import router as gpi_integration_router
from routers.documents import router as documents_router, register_server_routes as register_doc_routes
from routers.workflows import router as workflows_router, register_server_routes as register_wf_routes
from routers.reference_intelligence import router as ref_intel_router, register_server_routes as register_ri_routes
from routers.document_intelligence import router as document_intelligence_router
from routers.auth import router as auth_router
from routers.ap_review import ap_review_router, set_dependencies as set_ap_review_deps
from routers.spiro import spiro_router

# ==================== APP ====================
app = FastAPI(title="GPI Document Hub API")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ALL ROUTERS (prefix /api) ====================
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
app.include_router(sales_dashboard_router, prefix="/api")
app.include_router(inventory_ledger_router, prefix="/api")
app.include_router(incoming_supply_router, prefix="/api")
app.include_router(inventory_items_router, prefix="/api")
app.include_router(stable_vendor_router, prefix="/api")
app.include_router(aliases_router, prefix="/api")
app.include_router(mailbox_sources_router, prefix="/api")
app.include_router(file_import_router, prefix="/api")
app.include_router(bc_integration_router, prefix="/api")
app.include_router(gpi_integration_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(workflows_router, prefix="/api")
app.include_router(ref_intel_router, prefix="/api")
app.include_router(document_intelligence_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(ap_review_router, prefix="/api")
app.include_router(spiro_router, prefix="/api")

# ==================== SALES MODULE ====================
app.include_router(sales_router)


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
    # Register server.py handler functions directly on app (deferred to avoid circular import)
    register_doc_routes(app)
    register_wf_routes(app)
    register_ri_routes(app)
    # Inventory ledger indexes
    try:
        from services.inventory_ledger_service import ensure_indexes as inv_ensure_indexes
        from deps import get_db
        await inv_ensure_indexes(get_db())
    except Exception as e:
        logger.warning("Inventory ledger index creation failed: %s", e)
    logger.info("main.py startup complete")


@app.on_event("shutdown")
async def shutdown():
    """Delegate to server.py's cleanup."""
    logger.info("main.py shutdown — delegating to server.shutdown_db_client()")
    await server.shutdown_db_client()
    logger.info("main.py shutdown complete")
