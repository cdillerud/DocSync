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
import logging
import os

# -- Load .env FIRST so the validator sees the right values -------------------
from dotenv import load_dotenv

load_dotenv()

# -- Startup secret validation (fail-fast) ------------------------------------
# Runs at import time BEFORE anything else. If JWT_SECRET / ADMIN_EMAIL /
# ADMIN_PASSWORD / MONGO_URL are missing or insecure defaults, the process
# crashes with a clear checklist rather than booting silently insecure.
from services.startup_validator import validate_startup_secrets

validate_startup_secrets()

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
from routers.vendor_resolution import router as vendor_resolution_router
from routers.readiness import router as readiness_router
from routers.dashboard import router as dashboard_router
from routers.sharepoint import router as sharepoint_admin_router
from routers.square9 import router as square9_router
from routers.email_polling import router as email_polling_router
from routers.vendors import router as vendors_router
from routers.migration_routes import router as migration_routes_router
from routers.sales_dashboard import router as sales_dashboard_router
from routers.sales_pipeline_demo import router as sales_pipeline_demo_router
from routers.salesperson_dashboard import router as salesperson_dashboard_router
from routers.inventory_ledger import router as inventory_ledger_router, incoming_supply_router
from routers.inventory_items import router as inventory_items_router
from routers.stable_vendor import router as stable_vendor_router
from routers.aliases import router as aliases_router
from routers.mailbox_sources import router as mailbox_sources_router
from routers.file_import import router as file_import_router
from routers.bc_integration import router as bc_integration_router
from routers.gpi_integration import router as gpi_integration_router
from routers.knowledge_seed import router as knowledge_seed_router
from routers.documents import router as documents_router, register_server_routes as register_doc_routes
from routers.workflows import router as workflows_router, register_server_routes as register_wf_routes
from routers.reference_intelligence import router as ref_intel_router, register_server_routes as register_ri_routes
from routers.document_intelligence import router as document_intelligence_router
from routers.auth import router as auth_router
from routers.ap_review import ap_review_router
from routers.spiro import spiro_router
from routers.ar_release import router as ar_release_router
from routers.automation_intelligence import router as automation_intelligence_router
from routers.vendor_reprocess import router as vendor_reprocess_router
from routers.workflow_fix import router as workflow_fix_router
from routers.dedup import router as dedup_router
from routers.vendor_profile_rebuild import router as vendor_profile_rebuild_router
from routers.auto_clear_reprocess import router as auto_clear_reprocess_router
from routers.file_integrity import router as file_integrity_router
from routers.auto_approve import router as auto_approve_router
from routers.sharepoint_routing import router as sharepoint_routing_router
from routers.po_resolution import router as po_resolution_router
from routers.bakeoff import router as bakeoff_router
from routers.feedback_health import router as feedback_health_router
from routers.reprocess_comparison import router as reprocess_comparison_router
from routers.posting_patterns import router as posting_patterns_router
from routers.explain import router as explain_router
from routers.dev_tools import router as dev_tools_router
from routers.ap_advisory import router as ap_advisory_router
from routers.governance import router as governance_router
from routers.inside_sales_pilot import router as inside_sales_pilot_router
from routers.inventory_xls import router as inventory_xls_router
from routers.intake_learning import router as intake_learning_router
from routers.learning_core import router as learning_core_router
from routers.workflow_observer import router as workflow_observer_router
from routers.cp_item_registry import router as cp_item_registry_router
from routers.consigned_item_registry import router as consigned_item_registry_router

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
app.include_router(vendor_resolution_router, prefix="/api")
app.include_router(readiness_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(sharepoint_admin_router, prefix="/api")
app.include_router(square9_router, prefix="/api")
app.include_router(email_polling_router, prefix="/api")
app.include_router(vendors_router, prefix="/api")
app.include_router(migration_routes_router, prefix="/api")
app.include_router(sales_dashboard_router, prefix="/api")
app.include_router(sales_pipeline_demo_router, prefix="/api")
app.include_router(salesperson_dashboard_router, prefix="/api")
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
app.include_router(ar_release_router, prefix="/api")
app.include_router(automation_intelligence_router, prefix="/api")
app.include_router(vendor_reprocess_router, prefix="/api")
app.include_router(workflow_fix_router, prefix="/api")
app.include_router(dedup_router, prefix="/api")
app.include_router(vendor_profile_rebuild_router, prefix="/api")
app.include_router(auto_clear_reprocess_router, prefix="/api")
app.include_router(file_integrity_router, prefix="/api")
app.include_router(auto_approve_router, prefix="/api")
app.include_router(sharepoint_routing_router, prefix="/api")
app.include_router(po_resolution_router, prefix="/api")
app.include_router(bakeoff_router, prefix="/api")
app.include_router(feedback_health_router, prefix="/api")
app.include_router(reprocess_comparison_router, prefix="/api")
app.include_router(knowledge_seed_router, prefix="/api")
app.include_router(posting_patterns_router, prefix="/api")
app.include_router(explain_router, prefix="/api")
app.include_router(dev_tools_router, prefix="/api")
app.include_router(ap_advisory_router, prefix="/api")
app.include_router(governance_router, prefix="/api")
app.include_router(inside_sales_pilot_router, prefix="/api")
app.include_router(inventory_xls_router, prefix="/api")
app.include_router(intake_learning_router, prefix="/api")
app.include_router(learning_core_router, prefix="/api")
app.include_router(workflow_observer_router, prefix="/api")
app.include_router(cp_item_registry_router, prefix="/api")
app.include_router(consigned_item_registry_router, prefix="/api")

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

    # ── Auth: expose DB on app.state and seed admin user ───────────────────
    # ``services.auth_deps.get_current_user`` resolves the request user by
    # pulling ``request.app.state.db``. Attach the Motor DB and then seed
    # the admin account from ADMIN_EMAIL / ADMIN_PASSWORD env vars.
    from deps import get_db
    from services.auth_deps import seed_admin_user
    app.state.db = get_db()
    try:
        seed_result = await seed_admin_user(app.state.db)
        logger.info("[Auth] Admin seed: %s", seed_result)
    except Exception as e:
        logger.error("[Auth] Admin seed FAILED: %s", e)
        raise

    # Register server.py handler functions directly on app (deferred to avoid circular import)
    register_doc_routes(app)
    register_wf_routes(app)
    register_ri_routes(app)
    # Inventory ledger indexes
    try:
        from workflows.inventory.ledger.service import ensure_indexes as inv_ensure_indexes
        from deps import get_db
        await inv_ensure_indexes(get_db())
    except Exception as e:
        logger.warning("Inventory ledger index creation failed: %s", e)

    # Inventory XLS staging + learning indexes
    try:
        from workflows.inventory.planning.staging import ensure_indexes as inv_xls_ensure_indexes
        from deps import get_db
        await inv_xls_ensure_indexes(get_db())
    except Exception as e:
        logger.warning("Inventory XLS staging index creation failed: %s", e)

    # Customer-Owned Ware (COW) CP-item registry indexes — Lane C Step 1
    try:
        from workflows.inventory.ownership import ensure_indexes as cow_ensure_indexes
        from deps import get_db
        await cow_ensure_indexes(get_db())
    except Exception as e:
        logger.warning("CP-item registry index creation failed: %s", e)

    # Vendor consignment registry indexes — Lane C Step 2
    try:
        from workflows.inventory.ownership import ensure_consignment_indexes
        from deps import get_db
        await ensure_consignment_indexes(get_db())
    except Exception as e:
        logger.warning("Consigned-item registry index creation failed: %s", e)

    # Vendor matching: backfill name_normalized on cached BC vendors
    try:
        from services.vendor_matching import backfill_bc_vendor_normalized
        backfilled = await backfill_bc_vendor_normalized()
        if backfilled > 0:
            logger.info("Backfilled name_normalized for %d BC vendor records", backfilled)
    except Exception as e:
        logger.warning("Vendor normalized backfill failed: %s", e)

    # Initialize classification feedback service
    try:
        from services.classification_feedback_service import init_classification_feedback
        from deps import get_db
        init_classification_feedback(get_db())
        logger.info("Classification feedback service initialized")
    except Exception as e:
        logger.warning("Classification feedback init failed: %s", e)

    # A1 (Lane A): one-time migration of legacy bc_posting_error strings into
    # append-only bc_posting_attempts[] history. Idempotent — safe on every
    # startup; does nothing after the first run converts the backlog.
    try:
        from services.bc_posting_attempts import migrate_legacy_bc_posting_error
        from deps import get_db
        stats = await migrate_legacy_bc_posting_error(get_db())
        if stats["migrated"]:
            logger.info(
                "[bc_posting_attempts] legacy migration on startup: scanned=%d migrated=%d",
                stats["scanned"], stats["migrated"],
            )
    except Exception as e:
        logger.warning("bc_posting_attempts legacy migration failed: %s", e)

    logger.info("main.py startup complete")


@app.on_event("shutdown")
async def shutdown():
    """Delegate to server.py's cleanup."""
    logger.info("main.py shutdown — delegating to server.shutdown_db_client()")
    await server.shutdown_db_client()
    logger.info("main.py shutdown complete")
