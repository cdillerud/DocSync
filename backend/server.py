from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import Response
from dotenv import load_dotenv
load_dotenv()  # Load .env file before any os.environ calls
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import hashlib
import base64
import re
import asyncio
import csv
import io
import copy
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx
from dateutil import parser as date_parser

# Sales Module (Phase 0)
from sales_module import (
    sales_router, 
    set_db as set_sales_db, 
    initialize_sales_indexes,
    configure_sales_email_polling,
    ingest_sales_document,
    check_sales_duplicate,
    record_sales_mail_log,
    _sales_email_config
)

# File Ingestion Service
from services.file_ingestion_service import (
    file_ingestion_service, set_file_ingestion_db, IngestionType
)

# Workflow Engine Service
from services.workflow_engine import (
    WorkflowEngine, WorkflowStatus, WorkflowEvent, 
    DocType, SourceSystem, CaptureChannel, DocumentClassifier
)
from services.ai_classifier import (
    classify_doc_type_with_ai, apply_ai_classification, 
    DEFAULT_CONFIDENCE_THRESHOLD, AIClassificationResult as AIClassifierResult
)
from services.bc_sandbox_service import (
    search_vendors_by_name, BCLookupStatus
)

# Migration Service
from services.migration import (
    MigrationJob, MigrationResult, LegacyDocumentSource, 
    JsonFileSource, InMemorySource, WorkflowInitializer
)
from services.migration.job import MigrationMode, MigrationJobBuilder
from services.migration.sources import create_sample_migration_file

# Square9 Workflow Alignment
from services.square9_workflow import (
    Square9Stage, DEFAULT_WORKFLOW_CONFIG,
    initialize_retry_state, increment_retry, reset_retry_counter,
    validate_location_code, determine_square9_stage, get_square9_stage_info,
    validate_required_fields, should_retry, get_workflow_summary
)

# Pilot Configuration
from services.pilot_config import (
    PILOT_MODE_ENABLED, CURRENT_PILOT_PHASE,
    get_pilot_metadata, is_pilot_document, get_pilot_capture_channel,
    is_export_blocked, is_bc_validation_blocked, is_external_write_blocked,
    create_pilot_workflow_entry, create_pilot_log_entry, get_pilot_status,
    get_stuck_threshold_hours, STUCK_THRESHOLDS
)

# Email and Summary Services
from services.email_service import EmailService, set_email_service
from services.pilot_summary import (
    generate_daily_pilot_summary, send_daily_pilot_summary,
    PILOT_SUMMARY_RECIPIENTS, DAILY_PILOT_EMAIL_ENABLED,
    PILOT_SUMMARY_CRON_HOUR_UTC
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection + config
# MOVED to core/db.py and core/config.py during routes/ migration (see
# MIGRATION_PROGRESS.md). Imported here unchanged so nothing else in this
# file has to change - same names, same values, just relocated.
from core.db import db, client, mongo_url
from core import config as _core_config  # module ref, used to write through on settings updates
from core.config import (
    DEMO_MODE, JWT_SECRET, ENABLE_CREATE_DRAFT_HEADER,
    AI_CLASSIFICATION_ENABLED, AI_CLASSIFICATION_THRESHOLD,
    EMAIL_POLLING_ENABLED, EMAIL_POLLING_INTERVAL_MINUTES, EMAIL_POLLING_USER,
    EMAIL_POLLING_LOOKBACK_MINUTES, EMAIL_POLLING_MAX_MESSAGES, EMAIL_POLLING_MAX_ATTACHMENT_MB,
    SALES_EMAIL_POLLING_ENABLED, SALES_EMAIL_POLLING_USER, SALES_EMAIL_POLLING_INTERVAL_MINUTES,
    EMAIL_CLIENT_ID, EMAIL_CLIENT_SECRET, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME,
    BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
    SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME,
)

app = FastAPI(title="GPI Document Hub API")
api_router = APIRouter(prefix="/api")

# Global polling task references
_email_polling_task = None
_sales_polling_task = None
_pilot_summary_task = None

# ==================== AUTH ====================
# NOTE: Auth endpoints moved to routes/auth.py
from routes.auth import router as auth_router

# ==================== AP REVIEW ====================
from routes.ap_review import ap_review_router, set_dependencies as set_ap_review_deps
from services.business_central_service import BusinessCentralService, get_bc_service

# ==================== AUTO-POST SERVICE ====================
from services.auto_post_service import (
    AUTO_POST_ENABLED, 
    check_auto_post_eligibility, 
    attempt_auto_post,
    AutoPostResult,
    AUTO_CREATE_SALES_ORDER_ENABLED,
    check_sales_order_eligibility,
    attempt_auto_create_sales_order
)

# ==================== SHAREPOINT MIGRATION ====================
from routes.sharepoint_migration import router as sharepoint_migration_router
import routes.sharepoint_migration as sharepoint_migration_module

# ==================== SPIRO INTEGRATION ====================
from routes.spiro import spiro_router, set_spiro_routes_db
from services.spiro.spiro_sync import set_spiro_db

import jwt as pyjwt

TEST_USER = {"username": "admin", "password": "admin", "display_name": "Hub Admin", "role": "administrator"}

class LoginRequest(BaseModel):
    username: str
    password: str

class DocumentUpdate(BaseModel):
    document_type: Optional[str] = None
    bc_record_type: Optional[str] = None
    bc_record_id: Optional[str] = None
    bc_document_no: Optional[str] = None

def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc).timestamp() + 86400}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

# Auth endpoints are now in routes/auth.py - keeping these for backward compatibility during migration
@api_router.post("/auth/login")
async def login(req: LoginRequest):
    if req.username == TEST_USER["username"] and req.password == TEST_USER["password"]:
        token = create_token(req.username)
        return {"token": token, "user": {"username": TEST_USER["username"], "display_name": TEST_USER["display_name"], "role": TEST_USER["role"]}}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@api_router.get("/auth/me")
async def get_me():
    return {"username": TEST_USER["username"], "display_name": TEST_USER["display_name"], "role": TEST_USER["role"]}

# ==================== MICROSOFT SERVICES (MOCK/REAL) ====================
# MOVED to core/legacy_hub_helpers.py during routes/ migration (see
# MIGRATION_PROGRESS.md). Imported unchanged - same names/behavior, just
# relocated so routes/*.py modules can use them without importing server.py.
from core.legacy_hub_helpers import (
    FOLDER_MAP, MOCK_COMPANIES, MOCK_SALES_ORDERS,
    get_graph_token, get_email_token, get_bc_token,
    upload_to_sharepoint, create_sharing_link,
    get_bc_companies, get_bc_sales_orders, link_document_to_bc,
    run_upload_and_link_workflow,
)
from core.paths import UPLOAD_DIR

# ==================== JOB CONFIG / INGESTION ENGINE ====================
# MOVED to core/job_config.py and services/ingestion_engine.py during
# routes/ migration (see MIGRATION_PROGRESS.md, Group 9). Imported back here
# because on_document_ingested (dead code, never called - verified) and
# several not-yet-migrated groups (email polling, admin backfill, pilot
# reingest, aliases, metrics) still call these directly as plain functions.
from core.job_config import (
    DEFAULT_JOB_TYPES, VENDOR_ALIAS_MAP, TransactionAction,
    AutomationLevel, POValidationMode, VendorMatchMethod, DRAFT_CREATION_CONFIG,
    MailboxSource, EmailWatchConfig, JobTypeConfig, DocumentIntake,
    AIClassificationResult, ValidationCheck,
)
from services.ingestion_engine import (
    classify_document_with_ai, classify_document_type, _get_category_for_doc_type,
    normalize_extracted_fields, compute_ap_normalized_fields, lookup_vendor_alias,
    check_duplicate_document, compute_ap_validation, compute_ap_status,
    compute_canonical_fields, compute_draft_candidate_flag, normalize_vendor_name,
    calculate_fuzzy_score, match_vendor_in_bc, match_customer_in_bc,
    validate_bc_match, make_automation_decision,
    _update_standard_workflow_status, _update_ap_workflow_status,
    _internal_intake_document,
)
from routes.ingestion import router as ingestion_router

# ==================== EMAIL POLLING / GRAPH WEBHOOK ====================
# MOVED to services/email_polling_engine.py and routes/email_ingestion.py
# during routes/ migration (see MIGRATION_PROGRESS.md, Group 10). Imported
# back here because _email_polling_task lifecycle (start/stop on
# app startup/shutdown) and several not-yet-migrated groups (job-types/
# email-watcher settings, sales backfill, sales email polling) still call
# these directly.
from services.email_polling_engine import (
    get_email_watcher_config, subscribe_to_mailbox_notifications,
    fetch_email_with_attachments, move_email_to_folder,
    on_document_ingested,  # dead code, never called - kept importable anyway
    process_incoming_email, poll_mailbox_for_attachments, email_polling_worker,
    record_mail_intake_log, check_duplicate_mail_intake, should_skip_attachment,
)
from routes.email_ingestion import router as email_ingestion_router

# ==================== SALES BACKFILL / MIGRATE / POLLING ====================
# MOVED to services/sales_polling_engine.py and routes/sales_admin.py during
# routes/ migration (see MIGRATION_PROGRESS.md, Group 11). Imported back
# here because _sales_polling_task lifecycle (startup/shutdown) still
# references run_sales_email_poll/_sales_email_polling_worker.
from services.sales_polling_engine import run_sales_email_poll, _sales_email_polling_worker
from routes.sales_admin import router as sales_admin_router

# ==================== JOB TYPE + EMAIL WATCHER SETTINGS ====================
# MOVED to routes/job_type_settings.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 12). 6 endpoints.
from routes.job_type_settings import router as job_type_settings_router

# ==================== WORKFLOW ENDPOINTS (generic list/get/retry) ====================
# MOVED to routes/workflows.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 13a). 3 endpoints.
from routes.workflows import router as workflows_router

# ==================== AP INVOICE + GENERIC WORKFLOWS ====================
# MOVED to routes/ap_workflows.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 13b). 24 endpoints.
from routes.ap_workflows import router as ap_workflows_router

# ==================== MIGRATION TOOLS ====================
# MOVED to routes/migration_tools.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 14). 5 endpoints.
from routes.migration_tools import router as migration_tools_router

# ==================== VENDOR ALIASES ====================
# MOVED to routes/aliases.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 15). 4 endpoints.
from routes.aliases import router as aliases_router

# ==================== METRICS / REPORTING ====================
# MOVED to routes/metrics.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 16). 16 endpoints.
from routes.metrics import router as metrics_router

# ==================== DOCUMENT + SQUARE9 ENDPOINTS ====================
# MOVED to routes/documents.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 5). 15 endpoints: /documents/upload,
# /documents (list/get/put/delete/file), /documents/{id}/square9-status,
# /documents/{id}/retry, /documents/{id}/reset-retries, /square9/config,
# /square9/stage-counts, /documents/{id}/resubmit, /documents/{id}/link.
from routes.documents import router as documents_router
from routes.documents import link_document as _link_document

# ==================== DASHBOARD ENDPOINTS ====================
# MOVED to routes/dashboard.py during routes/ migration (see
# MIGRATION_PROGRESS.md, Group 6). 3 endpoints: /dashboard/stats,
# /dashboard/document-types, /dashboard/document-types/export.
from routes.dashboard import router as dashboard_router

# ==================== BC PROXY ====================
# MOVED to routes/bc.py during routes/ migration (see MIGRATION_PROGRESS.md,
# Group 7). 2 endpoints: /bc/companies, /bc/sales-orders.
from routes.bc import router as bc_router


# ==================== SETTINGS ====================

CONFIG_KEYS = [
    "TENANT_ID", "BC_ENVIRONMENT", "BC_COMPANY_NAME", "BC_CLIENT_ID",
    "BC_CLIENT_SECRET", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
    "SHAREPOINT_SITE_HOSTNAME", "SHAREPOINT_SITE_PATH", "SHAREPOINT_LIBRARY_NAME",
    "DEMO_MODE"
]
SECRET_KEYS = {"BC_CLIENT_SECRET", "GRAPH_CLIENT_SECRET"}

def _mask(val: str) -> str:
    """Mask a secret value showing only first 4 and last 4 chars."""
    if not val or len(val) < 10:
        return "****" if val else ""
    return val[:4] + "*" * (len(val) - 8) + val[-4:]

def _current_config():
    """Read live module-level config vars."""
    return {
        "TENANT_ID": TENANT_ID,
        "BC_ENVIRONMENT": BC_ENVIRONMENT,
        "BC_COMPANY_NAME": BC_COMPANY_NAME,
        "BC_CLIENT_ID": BC_CLIENT_ID,
        "BC_CLIENT_SECRET": BC_CLIENT_SECRET,
        "GRAPH_CLIENT_ID": GRAPH_CLIENT_ID,
        "GRAPH_CLIENT_SECRET": GRAPH_CLIENT_SECRET,
        "SHAREPOINT_SITE_HOSTNAME": SHAREPOINT_SITE_HOSTNAME,
        "SHAREPOINT_SITE_PATH": SHAREPOINT_SITE_PATH,
        "SHAREPOINT_LIBRARY_NAME": SHAREPOINT_LIBRARY_NAME,
        "DEMO_MODE": str(DEMO_MODE).lower(),
    }

async def _load_config_from_db():
    """Load saved config from MongoDB and apply to module globals."""
    global DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME
    global BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    global SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME

    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0, "_key": 0})
    if not saved:
        return
    if saved.get("TENANT_ID"):
        TENANT_ID = saved["TENANT_ID"]
    if saved.get("BC_ENVIRONMENT"):
        BC_ENVIRONMENT = saved["BC_ENVIRONMENT"]
    if saved.get("BC_COMPANY_NAME"):
        BC_COMPANY_NAME = saved["BC_COMPANY_NAME"]
    if saved.get("BC_CLIENT_ID"):
        BC_CLIENT_ID = saved["BC_CLIENT_ID"]
    if saved.get("BC_CLIENT_SECRET"):
        BC_CLIENT_SECRET = saved["BC_CLIENT_SECRET"]
    if saved.get("GRAPH_CLIENT_ID"):
        GRAPH_CLIENT_ID = saved["GRAPH_CLIENT_ID"]
    if saved.get("GRAPH_CLIENT_SECRET"):
        GRAPH_CLIENT_SECRET = saved["GRAPH_CLIENT_SECRET"]
    if saved.get("SHAREPOINT_SITE_HOSTNAME"):
        SHAREPOINT_SITE_HOSTNAME = saved["SHAREPOINT_SITE_HOSTNAME"]
    if saved.get("SHAREPOINT_SITE_PATH"):
        SHAREPOINT_SITE_PATH = saved["SHAREPOINT_SITE_PATH"]
    if saved.get("SHAREPOINT_LIBRARY_NAME"):
        SHAREPOINT_LIBRARY_NAME = saved["SHAREPOINT_LIBRARY_NAME"]
    if "DEMO_MODE" in saved:
        DEMO_MODE = str(saved["DEMO_MODE"]).lower() == "true"

    # Write through to core.config so functions moved to core/legacy_hub_helpers.py
    # (and any routes/*.py modules) see the same reloaded values. See
    # MIGRATION_PROGRESS.md - this keeps hot-reload-without-restart working
    # now that BC/Graph helper functions live in a separate module.
    _core_config.TENANT_ID = TENANT_ID
    _core_config.BC_ENVIRONMENT = BC_ENVIRONMENT
    _core_config.BC_COMPANY_NAME = BC_COMPANY_NAME
    _core_config.BC_CLIENT_ID = BC_CLIENT_ID
    _core_config.BC_CLIENT_SECRET = BC_CLIENT_SECRET
    _core_config.GRAPH_CLIENT_ID = GRAPH_CLIENT_ID
    _core_config.GRAPH_CLIENT_SECRET = GRAPH_CLIENT_SECRET
    _core_config.SHAREPOINT_SITE_HOSTNAME = SHAREPOINT_SITE_HOSTNAME
    _core_config.SHAREPOINT_SITE_PATH = SHAREPOINT_SITE_PATH
    _core_config.SHAREPOINT_LIBRARY_NAME = SHAREPOINT_LIBRARY_NAME
    _core_config.DEMO_MODE = DEMO_MODE

@api_router.get("/settings/status")
async def get_settings_status():
    return {
        "demo_mode": DEMO_MODE,
        "connections": {
            "mongodb": {"status": "connected", "detail": "Configured"},
            "sharepoint": {
                "status": "configured" if (GRAPH_CLIENT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "site": SHAREPOINT_SITE_HOSTNAME or "Not set",
                "path": SHAREPOINT_SITE_PATH or "Not set",
                "library": SHAREPOINT_LIBRARY_NAME
            },
            "business_central": {
                "status": "configured" if (BC_CLIENT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "environment": BC_ENVIRONMENT or "Not set",
                "company": BC_COMPANY_NAME or "Not set"
            },
            "entra_id": {
                "status": "configured" if (TENANT_ID and not DEMO_MODE) else ("demo" if DEMO_MODE else "not_configured"),
                "tenant_id": (TENANT_ID[:8] + "...") if TENANT_ID else "Not set"
            }
        },
        "sharepoint_folders": list(set(FOLDER_MAP.values())),
        # Phase 4: Draft creation feature flag
        "features": {
            "create_draft_header": {
                "enabled": ENABLE_CREATE_DRAFT_HEADER,
                "description": "Phase 4: Create Purchase Invoice draft headers for high-confidence AP Invoice matches",
                "safety_thresholds": DRAFT_CREATION_CONFIG
            }
        }
    }

@api_router.get("/settings/config")
async def get_settings_config():
    """Return current config with secrets masked."""
    raw = _current_config()
    masked = {}
    for k, v in raw.items():
        masked[k] = _mask(v) if k in SECRET_KEYS else v
    return {"config": masked}

class ConfigUpdate(BaseModel):
    TENANT_ID: Optional[str] = None
    BC_ENVIRONMENT: Optional[str] = None
    BC_COMPANY_NAME: Optional[str] = None
    BC_CLIENT_ID: Optional[str] = None
    BC_CLIENT_SECRET: Optional[str] = None
    GRAPH_CLIENT_ID: Optional[str] = None
    GRAPH_CLIENT_SECRET: Optional[str] = None
    SHAREPOINT_SITE_HOSTNAME: Optional[str] = None
    SHAREPOINT_SITE_PATH: Optional[str] = None
    SHAREPOINT_LIBRARY_NAME: Optional[str] = None
    DEMO_MODE: Optional[str] = None

@api_router.put("/settings/config")
async def update_settings_config(update: ConfigUpdate):
    """Save config to MongoDB and reload in-memory. No .env write = no server restart."""
    global DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME
    global BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    global SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME

    # Load current saved config from DB
    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0}) or {"_key": "credentials"}

    # Merge updates — skip masked placeholder values, strip whitespace
    update_dict = update.model_dump(exclude_none=True)
    for key, val in update_dict.items():
        if val is not None and "****" not in val:
            saved[key] = val.strip() if isinstance(val, str) else val

    # Upsert into MongoDB
    await db.hub_config.update_one(
        {"_key": "credentials"},
        {"$set": saved},
        upsert=True
    )

    # Reload in-memory immediately
    TENANT_ID = saved.get("TENANT_ID", TENANT_ID)
    BC_ENVIRONMENT = saved.get("BC_ENVIRONMENT", BC_ENVIRONMENT)
    BC_COMPANY_NAME = saved.get("BC_COMPANY_NAME", BC_COMPANY_NAME)
    BC_CLIENT_ID = saved.get("BC_CLIENT_ID", BC_CLIENT_ID)
    BC_CLIENT_SECRET = saved.get("BC_CLIENT_SECRET", BC_CLIENT_SECRET)
    GRAPH_CLIENT_ID = saved.get("GRAPH_CLIENT_ID", GRAPH_CLIENT_ID)
    GRAPH_CLIENT_SECRET = saved.get("GRAPH_CLIENT_SECRET", GRAPH_CLIENT_SECRET)
    SHAREPOINT_SITE_HOSTNAME = saved.get("SHAREPOINT_SITE_HOSTNAME", SHAREPOINT_SITE_HOSTNAME)
    SHAREPOINT_SITE_PATH = saved.get("SHAREPOINT_SITE_PATH", SHAREPOINT_SITE_PATH)
    SHAREPOINT_LIBRARY_NAME = saved.get("SHAREPOINT_LIBRARY_NAME", SHAREPOINT_LIBRARY_NAME)
    DEMO_MODE = str(saved.get("DEMO_MODE", "true")).lower() == "true"

    # Write through to core.config - see note in _load_config_from_db above
    # and MIGRATION_PROGRESS.md.
    _core_config.TENANT_ID = TENANT_ID
    _core_config.BC_ENVIRONMENT = BC_ENVIRONMENT
    _core_config.BC_COMPANY_NAME = BC_COMPANY_NAME
    _core_config.BC_CLIENT_ID = BC_CLIENT_ID
    _core_config.BC_CLIENT_SECRET = BC_CLIENT_SECRET
    _core_config.GRAPH_CLIENT_ID = GRAPH_CLIENT_ID
    _core_config.GRAPH_CLIENT_SECRET = GRAPH_CLIENT_SECRET
    _core_config.SHAREPOINT_SITE_HOSTNAME = SHAREPOINT_SITE_HOSTNAME
    _core_config.SHAREPOINT_SITE_PATH = SHAREPOINT_SITE_PATH
    _core_config.SHAREPOINT_LIBRARY_NAME = SHAREPOINT_LIBRARY_NAME
    _core_config.DEMO_MODE = DEMO_MODE

    logger.info("Configuration updated via UI. Demo mode: %s", DEMO_MODE)

    # Return fresh masked config
    raw = _current_config()
    masked = {k: (_mask(v) if k in SECRET_KEYS else v) for k, v in raw.items()}
    return {"message": "Configuration saved successfully", "config": masked}

@api_router.post("/settings/test-connection")
async def test_connection(service: str = Query(...)):
    """Quick connectivity test with detailed permission diagnostics."""
    if service == "graph":
        try:
            token = await get_graph_token()
            if token == "mock-graph-token":
                return {"service": "graph", "status": "demo", "detail": "Running in demo mode"}
            # Test site resolution (format: sites/{hostname}:/{server-relative-path}:)
            async with httpx.AsyncClient(timeout=15.0) as c:
                site_resp = await c.get(
                    f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
                    headers={"Authorization": f"Bearer {token}"})
                if site_resp.status_code == 200:
                    site_data = site_resp.json()
                    return {"service": "graph", "status": "ok", "detail": f"Connected. Site: {site_data.get('displayName', 'OK')}"}
                elif site_resp.status_code in (401, 403):
                    return {"service": "graph", "status": "error",
                        "detail": f"Permission denied (HTTP {site_resp.status_code}). Your app registration needs 'Sites.ReadWrite.All' (Application permission, NOT Delegated). Go to Azure Portal > App Registrations > API Permissions > Add permission > Microsoft Graph > Application > Sites.ReadWrite.All > then click 'Grant admin consent'."}
                elif site_resp.status_code == 404:
                    return {"service": "graph", "status": "error",
                        "detail": f"Site not found (HTTP 404). Verify hostname='{SHAREPOINT_SITE_HOSTNAME}' and path='{SHAREPOINT_SITE_PATH}'. The path should be like '/sites/YourSiteName' (not a full URL)."}
                else:
                    error_body = site_resp.text[:500]
                    try:
                        error_json = site_resp.json()
                        error_msg = error_json.get('error', {}).get('message', error_body)
                        error_code = error_json.get('error', {}).get('code', '')
                    except:
                        error_msg = error_body
                        error_code = ''
                    logger.error(f"Graph site resolution failed (HTTP {site_resp.status_code}): {error_msg}")
                    return {"service": "graph", "status": "error",
                        "detail": f"HTTP {site_resp.status_code}: {error_msg}",
                        "error_code": error_code,
                        "hint": f"URL tried: https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:"}
        except Exception as e:
            return {"service": "graph", "status": "error", "detail": str(e)}
    elif service == "bc":
        try:
            token = await get_bc_token()
            if token == "mock-bc-token":
                return {"service": "bc", "status": "demo", "detail": "Running in demo mode"}
            async with httpx.AsyncClient(timeout=15.0) as c:
                resp = await c.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies",
                    headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        return {"service": "bc", "status": "error", "detail": f"BC returned non-JSON response (HTTP 200): {resp.text[:200]}"}
                    companies = data.get("value", [])
                    return {"service": "bc", "status": "ok", "detail": f"Connected. Found {len(companies)} companies: {', '.join(c.get('displayName', c.get('name','?')) for c in companies[:3])}"}
                elif resp.status_code == 404:
                    if "NoEnvironment" in resp.text:
                        return {"service": "bc", "status": "error",
                            "detail": f"Environment '{BC_ENVIRONMENT}' does not exist. Check the exact name in BC admin center (it's case-sensitive)."}
                    return {"service": "bc", "status": "error", "detail": f"BC API not found (404): {resp.text[:200]}"}
                elif resp.status_code in (401, 403):
                    return {"service": "bc", "status": "error",
                        "detail": f"Permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role, and API.ReadWrite.All permission is granted."}
                else:
                    return {"service": "bc", "status": "error",
                        "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"service": "bc", "status": "error", "detail": str(e)}
    return {"service": service, "status": "unknown", "detail": "Unknown service"}

# ==================== PHASE 4: DRAFT CREATION FEATURE TOGGLE ====================

class DraftFeatureToggle(BaseModel):
    enabled: bool

@api_router.post("/settings/features/create-draft-header")
async def toggle_draft_creation_feature(toggle: DraftFeatureToggle):
    """
    Toggle the CREATE_DRAFT_HEADER feature flag.
    This is for SANDBOX testing only - production should use environment variables.
    
    IMPORTANT: This is a safety-critical feature. Only enable in sandbox environment.
    """
    global ENABLE_CREATE_DRAFT_HEADER
    
    old_value = ENABLE_CREATE_DRAFT_HEADER
    ENABLE_CREATE_DRAFT_HEADER = toggle.enabled
    _core_config.ENABLE_CREATE_DRAFT_HEADER = toggle.enabled  # write through - see MIGRATION_PROGRESS.md
    
    # Log the change
    logger.info(
        "CREATE_DRAFT_HEADER feature toggled: %s -> %s (by UI toggle)",
        old_value, ENABLE_CREATE_DRAFT_HEADER
    )
    
    return {
        "feature": "create_draft_header",
        "previous_value": old_value,
        "current_value": ENABLE_CREATE_DRAFT_HEADER,
        "message": f"Draft creation feature {'enabled' if ENABLE_CREATE_DRAFT_HEADER else 'disabled'}",
        "safety_thresholds": DRAFT_CREATION_CONFIG if ENABLE_CREATE_DRAFT_HEADER else None
    }

@api_router.get("/settings/features/create-draft-header")
async def get_draft_creation_feature_status():
    """
    Get the current status of the CREATE_DRAFT_HEADER feature.
    """
    return {
        "feature": "create_draft_header",
        "enabled": ENABLE_CREATE_DRAFT_HEADER,
        "safety_thresholds": DRAFT_CREATION_CONFIG,
        "eligible_match_methods": DRAFT_CREATION_CONFIG["eligible_match_methods"],
        "min_match_score": DRAFT_CREATION_CONFIG["min_match_score_for_draft"],
        "min_confidence": DRAFT_CREATION_CONFIG["min_confidence_for_draft"],
        "supported_job_types": ["AP_Invoice"]
    }

# ==================== PHASE 2: EMAIL PARSER AGENT ====================



# ==================== SALES EMAIL BACKFILL ====================


# ==================== PILOT ENDPOINTS ====================

@api_router.get("/pilot/status")
async def get_pilot_status_endpoint():
    """
    Get current pilot mode status and configuration.
    """
    return get_pilot_status()


@api_router.get("/pilot/daily-metrics")
async def get_pilot_daily_metrics(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    date: Optional[str] = Query(default=None, description="Specific date (YYYY-MM-DD) or None for all")
):
    """
    Get daily metrics for the shadow pilot.
    
    Includes:
    - Document counts per doc_type
    - Classification method breakdown (deterministic vs AI)
    - Stuck document counts (>24h in status)
    - Vendor extraction rates
    - Export rates
    """
    # Build date filter
    date_match = {}
    if date:
        date_start = f"{date}T00:00:00"
        date_end = f"{date}T23:59:59"
        date_match = {"pilot_date": {"$gte": date_start, "$lte": date_end}}
    
    # Base match for pilot documents
    base_match = {"pilot_phase": phase, **date_match}
    
    # Total counts by doc_type
    doc_type_pipeline = [
        {"$match": base_match},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "count": {"$sum": 1}
        }}
    ]
    doc_type_results = await db.hub_documents.aggregate(doc_type_pipeline).to_list(20)
    by_doc_type = {r["_id"]: r["count"] for r in doc_type_results}
    
    # Classification method breakdown
    classification_pipeline = [
        {"$match": base_match},
        {"$group": {
            "_id": {"$ifNull": ["$classification_method", "unknown"]},
            "count": {"$sum": 1}
        }}
    ]
    classification_results = await db.hub_documents.aggregate(classification_pipeline).to_list(20)
    by_classification = {r["_id"]: r["count"] for r in classification_results}
    
    # Deterministic vs AI counts
    deterministic_count = sum(c for k, c in by_classification.items() if k.startswith("deterministic"))
    ai_count = sum(c for k, c in by_classification.items() if k.startswith("ai:"))
    other_count = sum(c for k, c in by_classification.items() if not k.startswith("deterministic") and not k.startswith("ai:"))
    
    # Stuck documents (>24h in status)
    now = datetime.now(timezone.utc)
    threshold_24h = (now - timedelta(hours=24)).isoformat()
    
    stuck_statuses = ["vendor_pending", "bc_validation_pending", "extracted", "validation_pending"]
    stuck_pipeline = [
        {"$match": {
            **base_match,
            "workflow_status": {"$in": stuck_statuses},
            "workflow_status_updated_utc": {"$lt": threshold_24h}
        }},
        {"$group": {
            "_id": "$workflow_status",
            "count": {"$sum": 1}
        }}
    ]
    stuck_results = await db.hub_documents.aggregate(stuck_pipeline).to_list(20)
    stuck_by_status = {r["_id"]: r["count"] for r in stuck_results}
    
    # Vendor extraction rate for AP_INVOICE
    ap_total_pipeline = [
        {"$match": {**base_match, "doc_type": "AP_INVOICE"}},
        {"$count": "total"}
    ]
    ap_total_result = await db.hub_documents.aggregate(ap_total_pipeline).to_list(1)
    ap_total = ap_total_result[0]["total"] if ap_total_result else 0
    
    ap_vendor_pipeline = [
        {"$match": {
            **base_match,
            "doc_type": "AP_INVOICE",
            "$or": [
                {"vendor_no": {"$exists": True, "$ne": None}},
                {"vendor_canonical": {"$exists": True, "$ne": None}}
            ]
        }},
        {"$count": "with_vendor"}
    ]
    ap_vendor_result = await db.hub_documents.aggregate(ap_vendor_pipeline).to_list(1)
    ap_with_vendor = ap_vendor_result[0]["with_vendor"] if ap_vendor_result else 0
    
    vendor_extraction_rate = (ap_with_vendor / ap_total * 100) if ap_total > 0 else 0
    
    # Export rate
    exported_pipeline = [
        {"$match": {**base_match, "workflow_status": "exported"}},
        {"$count": "exported"}
    ]
    exported_result = await db.hub_documents.aggregate(exported_pipeline).to_list(1)
    exported_count = exported_result[0]["exported"] if exported_result else 0
    
    total_docs = sum(by_doc_type.values())
    export_rate = (exported_count / total_docs * 100) if total_docs > 0 else 0
    
    # Documents missing required fields
    missing_fields_pipeline = [
        {"$match": {
            **base_match,
            "$or": [
                {"$and": [
                    {"doc_type": "AP_INVOICE"},
                    {"$or": [
                        {"vendor_name": {"$exists": False}},
                        {"vendor_name": None},
                        {"invoice_number_clean": {"$exists": False}},
                        {"invoice_number_clean": None}
                    ]}
                ]},
                {"$and": [
                    {"doc_type": "SALES_INVOICE"},
                    {"$or": [
                        {"customer_no": {"$exists": False}},
                        {"customer_no": None}
                    ]}
                ]}
            ]
        }},
        {"$group": {
            "_id": "$doc_type",
            "count": {"$sum": 1}
        }}
    ]
    missing_results = await db.hub_documents.aggregate(missing_fields_pipeline).to_list(20)
    missing_by_type = {r["_id"]: r["count"] for r in missing_results}
    
    return {
        "phase": phase,
        "date": date or "all",
        "query_timestamp": now.isoformat(),
        "summary": {
            "total_documents": total_docs,
            "deterministic_classified": deterministic_count,
            "ai_classified": ai_count,
            "other_classified": other_count,
            "ai_usage_rate": (ai_count / total_docs * 100) if total_docs > 0 else 0,
            "vendor_extraction_rate": vendor_extraction_rate,
            "export_rate": export_rate
        },
        "by_doc_type": by_doc_type,
        "by_classification_method": by_classification,
        "stuck_documents": {
            "total": sum(stuck_by_status.values()),
            "by_status": stuck_by_status
        },
        "missing_required_fields": missing_by_type,
        "exported_count": exported_count
    }


@api_router.get("/pilot/logs")
async def get_pilot_logs(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    doc_type: Optional[str] = Query(default=None, description="Filter by doc_type"),
    classification_method: Optional[str] = Query(default=None, description="Filter by classification_method")
):
    """
    Get pilot ingestion logs for audit purposes.
    
    Returns documents ingested during the pilot with classification details.
    """
    # Build match
    match = {"pilot_phase": phase}
    if doc_type:
        match["doc_type"] = doc_type
    if classification_method:
        if classification_method == "deterministic":
            match["classification_method"] = {"$regex": "^deterministic"}
        elif classification_method == "ai":
            match["classification_method"] = {"$regex": "^ai:"}
        else:
            match["classification_method"] = classification_method
    
    # Count total
    total = await db.hub_documents.count_documents(match)
    
    # Fetch paginated results
    skip = (page - 1) * page_size
    cursor = db.hub_documents.find(
        match,
        {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "doc_type": 1,
            "source_system": 1,
            "capture_channel": 1,
            "classification_method": 1,
            "ai_classification": 1,
            "workflow_status": 1,
            "pilot_phase": 1,
            "pilot_date": 1,
            "created_utc": 1,
            "workflow_status_updated_utc": 1
        }
    ).sort("pilot_date", -1).skip(skip).limit(page_size)
    
    docs = await cursor.to_list(page_size)
    
    # Add computed fields
    for doc in docs:
        # Calculate time to status initialization
        if doc.get("pilot_date") and doc.get("workflow_status_updated_utc"):
            try:
                pilot_dt = datetime.fromisoformat(doc["pilot_date"].replace("Z", "+00:00"))
                status_dt = datetime.fromisoformat(doc["workflow_status_updated_utc"].replace("Z", "+00:00"))
                doc["time_to_status_initialization_ms"] = int((status_dt - pilot_dt).total_seconds() * 1000)
            except:
                doc["time_to_status_initialization_ms"] = None
    
    return {
        "phase": phase,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
        "logs": docs
    }


@api_router.get("/pilot/accuracy")
async def get_pilot_accuracy_report(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query")
):
    """
    Get pilot accuracy report.
    
    Includes:
    - Incorrect classifications (manually corrected)
    - Misrouted workflow statuses
    - Documents with missing required metadata
    - Time-in-status distribution
    """
    base_match = {"pilot_phase": phase}
    
    # Find manually corrected documents (where doc_type was changed after initial classification)
    # These would have multiple entries in workflow_history with different doc_types
    # For now, we look for documents with classification_override or manual_correction fields
    corrected_pipeline = [
        {"$match": {
            **base_match,
            "$or": [
                {"classification_override": {"$exists": True}},
                {"manual_doc_type_correction": {"$exists": True}}
            ]
        }},
        {"$project": {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "original_doc_type": "$ai_classification.suggested_type",
            "corrected_doc_type": "$doc_type",
            "correction_reason": "$classification_override_reason"
        }}
    ]
    corrected_docs = await db.hub_documents.aggregate(corrected_pipeline).to_list(100)
    
    # Time-in-status distribution
    now = datetime.now(timezone.utc)
    time_distribution_pipeline = [
        {"$match": base_match},
        {"$addFields": {
            "status_age_hours": {
                "$divide": [
                    {"$subtract": [now, {"$dateFromString": {"dateString": "$workflow_status_updated_utc"}}]},
                    3600000  # Convert ms to hours
                ]
            }
        }},
        {"$bucket": {
            "groupBy": "$status_age_hours",
            "boundaries": [0, 1, 4, 8, 24, 48, 168, 999999],
            "default": "unknown",
            "output": {
                "count": {"$sum": 1},
                "statuses": {"$push": "$workflow_status"}
            }
        }}
    ]
    
    try:
        time_distribution = await db.hub_documents.aggregate(time_distribution_pipeline).to_list(20)
    except Exception as e:
        logger.warning(f"Time distribution aggregation failed: {e}")
        time_distribution = []
    
    # Format time buckets
    time_buckets = {
        "0-1h": 0,
        "1-4h": 0,
        "4-8h": 0,
        "8-24h": 0,
        "24-48h": 0,
        "48h-1w": 0,
        ">1w": 0
    }
    
    bucket_labels = ["0-1h", "1-4h", "4-8h", "8-24h", "24-48h", "48h-1w", ">1w"]
    for i, bucket in enumerate(time_distribution):
        if i < len(bucket_labels):
            time_buckets[bucket_labels[i]] = bucket.get("count", 0)
    
    # Overall accuracy score (documents correctly classified on first pass)
    total_docs = await db.hub_documents.count_documents(base_match)
    corrected_count = len(corrected_docs)
    accuracy_score = ((total_docs - corrected_count) / total_docs * 100) if total_docs > 0 else 100
    
    return {
        "phase": phase,
        "report_timestamp": now.isoformat(),
        "accuracy_score": round(accuracy_score, 2),
        "total_documents": total_docs,
        "corrected_documents": corrected_count,
        "corrections": corrected_docs[:50],  # Limit to 50
        "time_in_status_distribution": time_buckets,
        "stall_warnings": {
            "description": "Documents in actionable status > 24 hours",
            "threshold_hours": 24
        }
    }


@api_router.get("/pilot/trend")
async def get_pilot_trend_data(
    phase: str = Query(default=CURRENT_PILOT_PHASE, description="Pilot phase to query"),
    days: int = Query(default=14, ge=1, le=30, description="Number of days to include")
):
    """
    Get daily trend data for pilot documents.
    
    Returns daily counts by doc_type for charting.
    """
    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    
    pipeline = [
        {"$match": {
            "pilot_phase": phase,
            "pilot_date": {"$gte": start_date.isoformat()}
        }},
        {"$addFields": {
            "date": {"$substr": ["$pilot_date", 0, 10]}
        }},
        {"$group": {
            "_id": {
                "date": "$date",
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": 1}}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Organize by date
    trend_data = {}
    all_doc_types = set()
    
    for r in results:
        date = r["_id"]["date"]
        doc_type = r["_id"]["doc_type"]
        count = r["count"]
        
        if date not in trend_data:
            trend_data[date] = {}
        trend_data[date][doc_type] = count
        all_doc_types.add(doc_type)
    
    # Fill in missing dates and doc_types
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        if date_str not in trend_data:
            trend_data[date_str] = {}
        for dt in all_doc_types:
            if dt not in trend_data[date_str]:
                trend_data[date_str][dt] = 0
        current += timedelta(days=1)
    
    # Convert to array format for charting
    chart_data = []
    for date in sorted(trend_data.keys()):
        entry = {"date": date, **trend_data[date]}
        chart_data.append(entry)
    
    return {
        "phase": phase,
        "days": days,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "doc_types": sorted(list(all_doc_types)),
        "trend": chart_data
    }


@api_router.post("/pilot/send-daily-summary")
async def trigger_daily_pilot_summary():
    """
    Manually trigger the daily pilot summary email.
    
    Only allowed when pilot mode is enabled.
    
    Returns:
        Summary data and email send result
    """
    if not PILOT_MODE_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Pilot mode is disabled. Cannot send daily summary."
        )
    
    from services.email_service import get_email_service
    
    email_service = get_email_service()
    result = await send_daily_pilot_summary(db, email_service)
    
    return result


@api_router.get("/pilot/email-logs")
async def get_pilot_email_logs(
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0)
):
    """
    Get logs of sent pilot summary emails.
    
    Useful for verifying email content during the shadow pilot.
    """
    cursor = db.email_logs.find(
        {"subject": {"$regex": "Pilot Summary", "$options": "i"}},
        {"_id": 0}
    ).sort("sent_at", -1).skip(skip).limit(limit)
    
    logs = await cursor.to_list(limit)
    total = await db.email_logs.count_documents(
        {"subject": {"$regex": "Pilot Summary", "$options": "i"}}
    )
    
    return {
        "total": total,
        "logs": logs
    }


@api_router.get("/pilot/email-config")
async def get_pilot_email_config():
    """
    Get current pilot email configuration.
    """
    return {
        "daily_email_enabled": DAILY_PILOT_EMAIL_ENABLED,
        "recipients": PILOT_SUMMARY_RECIPIENTS,
        "cron_hour_utc": PILOT_SUMMARY_CRON_HOUR_UTC,
        "pilot_mode_enabled": PILOT_MODE_ENABLED,
        "current_phase": CURRENT_PILOT_PHASE
    }


# Daily pilot summary scheduler
async def _daily_pilot_summary_scheduler():
    """
    Background task that sends daily pilot summary emails.
    
    Runs continuously, checking every minute if it's time to send.
    Sends at PILOT_SUMMARY_CRON_HOUR_UTC (default: 13:00 UTC = 7 AM CST).
    """
    from services.email_service import get_email_service
    
    last_sent_date = None
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_date = now.strftime("%Y-%m-%d")
            current_hour = now.hour
            
            # Check if it's time to send and we haven't sent today
            should_send = (
                PILOT_MODE_ENABLED and
                DAILY_PILOT_EMAIL_ENABLED and
                current_hour == PILOT_SUMMARY_CRON_HOUR_UTC and
                last_sent_date != current_date
            )
            
            if should_send:
                logger.info("Daily pilot summary cron triggered")
                email_service = get_email_service()
                result = await send_daily_pilot_summary(db, email_service)
                
                if result.get("sent"):
                    last_sent_date = current_date
                    logger.info(f"Daily pilot summary sent successfully: {result.get('message_id')}")
                else:
                    logger.warning(f"Daily pilot summary not sent: {result.get('reason')}")
            
            # Sleep for 60 seconds before checking again
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("Daily pilot summary scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"Error in daily pilot summary scheduler: {e}")
            await asyncio.sleep(60)  # Wait before retrying


# ==================== WORKFLOW METRICS ====================

@api_router.get("/workflows/ap_invoice/metrics")
async def get_ap_workflow_metrics(days: int = Query(30)):
    """
    Get workflow metrics for AP_Invoice documents.
    Includes counts per status and time-in-status averages.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Status counts
    status_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(100)
    status_counts = {r["_id"] or "none": r["count"] for r in status_results}
    
    # Daily workflow status changes
    daily_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$unwind": {"path": "$workflow_history", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {
            "history_date": {"$substr": ["$workflow_history.timestamp", 0, 10]}
        }},
        {"$group": {
            "_id": {"date": "$history_date", "to_status": "$workflow_history.to_status"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": -1}}
    ]
    daily_results = await db.hub_documents.aggregate(daily_pipeline).to_list(1000)
    
    # Group by date
    daily_by_date = {}
    for r in daily_results:
        date = r["_id"]["date"]
        status = r["_id"]["to_status"]
        if date and status:
            if date not in daily_by_date:
                daily_by_date[date] = {}
            daily_by_date[date][status] = r["count"]
    
    return {
        "period_days": days,
        "status_counts": status_counts,
        "total_documents": sum(status_counts.values()),
        "exception_queue_count": sum(
            status_counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses()
        ),
        "daily_transitions": daily_by_date,
        "all_statuses": WorkflowEngine.get_all_statuses()
    }


# ==================== MAILBOX SOURCES CRUD ====================

@api_router.get("/settings/mailbox-sources")
async def list_mailbox_sources():
    """Get all configured mailbox sources."""
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    return {"mailbox_sources": sources, "total": len(sources)}

@api_router.get("/settings/mailbox-sources/polling-status")
async def get_mailbox_polling_status():
    """Get the status of the dynamic mailbox polling worker."""
    global _dynamic_mailbox_polling_task, _mailbox_last_poll_times
    
    worker_running = _dynamic_mailbox_polling_task is not None and not _dynamic_mailbox_polling_task.done()
    
    # Get all mailbox sources with their last poll times
    sources = await db.mailbox_sources.find({}, {"_id": 0}).to_list(100)
    
    mailbox_statuses = []
    for source in sources:
        mailbox_id = source.get("mailbox_id")
        last_poll = _mailbox_last_poll_times.get(mailbox_id)
        
        mailbox_statuses.append({
            "mailbox_id": mailbox_id,
            "name": source.get("name"),
            "email_address": source.get("email_address"),
            "enabled": source.get("enabled", True),
            "polling_interval_minutes": source.get("polling_interval_minutes", 5),
            "last_poll_utc": last_poll.isoformat() if last_poll else None,
            "next_poll_in_seconds": max(0, (source.get("polling_interval_minutes", 5) * 60) - 
                                        ((datetime.now(timezone.utc) - last_poll).total_seconds() if last_poll else 0))
                                   if last_poll else None
        })
    
    return {
        "worker_running": worker_running,
        "mailboxes": mailbox_statuses,
        "legacy_ap_polling_enabled": EMAIL_POLLING_ENABLED,
        "legacy_sales_polling_enabled": SALES_EMAIL_POLLING_ENABLED
    }

@api_router.get("/settings/mailbox-sources/{mailbox_id}")
async def get_mailbox_source(mailbox_id: str):
    """Get a specific mailbox source by ID."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    return source

@api_router.post("/settings/mailbox-sources")
async def create_mailbox_source(source: MailboxSource):
    """Create a new mailbox source."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Generate ID if not provided
    mailbox_id = source.mailbox_id or f"mailbox_{uuid.uuid4().hex[:8]}"
    
    # Check for duplicate email address
    existing = await db.mailbox_sources.find_one({"email_address": source.email_address})
    if existing:
        raise HTTPException(status_code=400, detail=f"Mailbox {source.email_address} already exists")
    
    doc = source.model_dump()
    doc["mailbox_id"] = mailbox_id
    doc["created_utc"] = now
    doc["updated_utc"] = now
    
    await db.mailbox_sources.insert_one(doc)
    
    logger.info("Created mailbox source: %s (%s)", source.name, source.email_address)
    
    # Return without _id
    return await get_mailbox_source(mailbox_id)

@api_router.put("/settings/mailbox-sources/{mailbox_id}")
async def update_mailbox_source(mailbox_id: str, source: MailboxSource):
    """Update an existing mailbox source."""
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    now = datetime.now(timezone.utc).isoformat()
    update_data = source.model_dump()
    update_data["mailbox_id"] = mailbox_id  # Preserve original ID
    update_data["created_utc"] = existing.get("created_utc")  # Preserve creation date
    update_data["updated_utc"] = now
    
    await db.mailbox_sources.update_one(
        {"mailbox_id": mailbox_id},
        {"$set": update_data}
    )
    
    logger.info("Updated mailbox source: %s", mailbox_id)
    
    return await get_mailbox_source(mailbox_id)

@api_router.delete("/settings/mailbox-sources/{mailbox_id}")
async def delete_mailbox_source(mailbox_id: str):
    """Delete a mailbox source."""
    existing = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    await db.mailbox_sources.delete_one({"mailbox_id": mailbox_id})
    
    logger.info("Deleted mailbox source: %s (%s)", existing.get("name"), existing.get("email_address"))
    
    return {"status": "deleted", "mailbox_id": mailbox_id}

@api_router.post("/settings/mailbox-sources/{mailbox_id}/test-connection")
async def test_mailbox_connection(mailbox_id: str):
    """Test connection to a mailbox source."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    email_address = source.get("email_address")
    
    try:
        token = await get_email_token()
        if not token:
            return {"status": "error", "message": "Failed to get email token - check Graph API credentials"}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Try to access the mailbox
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{email_address}/mailFolders/Inbox",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if resp.status_code == 200:
                folder_info = resp.json()
                return {
                    "status": "success",
                    "message": f"Connected successfully to {email_address}",
                    "folder_name": folder_info.get("displayName"),
                    "unread_count": folder_info.get("unreadItemCount"),
                    "total_count": folder_info.get("totalItemCount")
                }
            elif resp.status_code == 404:
                return {"status": "error", "message": f"Mailbox {email_address} not found or no access"}
            else:
                return {"status": "error", "message": f"Graph API error: {resp.status_code} - {resp.text[:200]}"}
    
    except Exception as e:
        return {"status": "error", "message": f"Connection test failed: {str(e)}"}

@api_router.post("/settings/mailbox-sources/{mailbox_id}/poll-now")
async def poll_mailbox_now(mailbox_id: str):
    """Manually trigger polling for a specific mailbox."""
    source = await db.mailbox_sources.find_one({"mailbox_id": mailbox_id}, {"_id": 0})
    if not source:
        raise HTTPException(status_code=404, detail=f"Mailbox source {mailbox_id} not found")
    
    email_address = source.get("email_address")
    category = source.get("category", "AP")
    
    # Use the unified email polling function
    try:
        stats = await poll_mailbox_for_documents(
            mailbox_address=email_address,
            default_category=category,
            source_id=mailbox_id
        )
        return stats
    except Exception as e:
        logger.error("Manual poll failed for %s: %s", mailbox_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def poll_mailbox_for_documents(mailbox_address: str, default_category: str = "AP", source_id: str = None):
    """
    Unified mailbox polling function that ingests documents into the main hub_documents collection.
    """
    run_id = uuid.uuid4().hex[:8]
    
    stats = {
        "run_id": run_id,
        "mailbox": mailbox_address,
        "source_id": source_id,
        "default_category": default_category,
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_dup": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    
    logger.info("[MailboxPoll:%s] Starting poll for %s (category=%s)", run_id, mailbox_address, default_category)
    
    try:
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats
        
        # Look back 1 hour for new emails
        lookback_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"receivedDateTime ge {lookback_time}",
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": 25,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                stats["errors"].append(f"Graph API error: {messages_resp.status_code}")
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_detected"] = len([m for m in messages if m.get("hasAttachments")])
            
            for msg in messages:
                if not msg.get("hasAttachments"):
                    continue
                
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                # Get attachments
                att_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$select": "id,name,contentType,size,isInline"}
                )
                
                if att_resp.status_code != 200:
                    continue
                
                attachments = att_resp.json().get("value", [])
                
                for att in attachments:
                    att_id = att.get("id")
                    filename = att.get("name", "unknown")
                    content_type = att.get("contentType", "")
                    is_inline = att.get("isInline", False)
                    size_bytes = att.get("size", 0)
                    
                    # Skip inline images and tiny files
                    if is_inline or content_type.startswith("image/") or size_bytes < 1000:
                        stats["attachments_skipped_inline"] += 1
                        continue
                    
                    # Check for duplicates
                    existing = await db.mail_intake_log.find_one({
                        "internet_message_id": internet_msg_id,
                        "attachment_name": filename
                    })
                    if existing:
                        stats["attachments_skipped_dup"] += 1
                        continue
                    
                    # Fetch attachment content
                    try:
                        att_content_resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments/{att_id}",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        
                        if att_content_resp.status_code != 200:
                            stats["attachments_failed"] += 1
                            continue
                        
                        content_b64 = att_content_resp.json().get("contentBytes", "")
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()
                        
                        # Ingest through unified pipeline
                        result = await _internal_intake_document(
                            file_content=content_bytes,
                            filename=filename,
                            source="email",
                            sender=sender,
                            subject=subject,
                            email_id=internet_msg_id,
                            content_type=content_type
                        )
                        
                        # Log the intake
                        await db.mail_intake_log.insert_one({
                            "internet_message_id": internet_msg_id,
                            "attachment_name": filename,
                            "attachment_hash": content_hash,
                            "document_id": result.get("document_id"),
                            "mailbox_source": mailbox_address,
                            "source_id": source_id,
                            "status": "Ingested",
                            "created_utc": datetime.now(timezone.utc).isoformat()
                        })
                        
                        stats["attachments_ingested"] += 1
                        
                    except Exception as e:
                        stats["attachments_failed"] += 1
                        stats["errors"].append(f"Failed to process {filename}: {str(e)}")
    
    except Exception as e:
        stats["errors"].append(f"Poll error: {str(e)}")
        logger.error("[MailboxPoll:%s] Error: %s", run_id, str(e))
    
    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info("[MailboxPoll:%s] Complete: ingested=%d, skipped_dup=%d, failed=%d",
                run_id, stats["attachments_ingested"], stats["attachments_skipped_dup"], stats["attachments_failed"])
    
    return stats

# ==================== BC SANDBOX API (READ-ONLY) ====================

from services.bc_sandbox_service import (
    get_vendor, search_vendors_by_name, validate_vendor_exists,
    get_customer, get_purchase_order, get_purchase_invoice, get_sales_invoice,
    validate_invoice_exists, validate_ap_invoice_in_bc, validate_sales_invoice_in_bc,
    validate_purchase_order_in_bc, get_bc_sandbox_status,
    PilotModeWriteBlockedError, BCSandboxError, BCLookupResult
)
from services.workflow_engine import BCValidationHistoryEntry


@api_router.get("/bc-sandbox/status")
async def bc_sandbox_status():
    """Get BC Sandbox service status and configuration."""
    return get_bc_sandbox_status()


@api_router.get("/bc-sandbox/vendors/{vendor_number}")
async def bc_sandbox_get_vendor(vendor_number: str):
    """
    Get vendor details by vendor number.
    READ-ONLY operation.
    """
    result = await get_vendor(vendor_number)
    return result.to_dict()


@api_router.get("/bc-sandbox/vendors/search/{name_fragment}")
async def bc_sandbox_search_vendors(name_fragment: str, limit: int = Query(20, le=100)):
    """
    Search vendors by name fragment (case-insensitive).
    READ-ONLY operation.
    """
    result = await search_vendors_by_name(name_fragment, limit)
    return result.to_dict()


@api_router.get("/bc-sandbox/customers/{customer_number}")
async def bc_sandbox_get_customer(customer_number: str):
    """
    Get customer details by customer number.
    READ-ONLY operation.
    """
    result = await get_customer(customer_number)
    return result.to_dict()


@api_router.get("/bc-sandbox/purchase-orders/{po_number}")
async def bc_sandbox_get_purchase_order(po_number: str):
    """
    Get purchase order details by PO number.
    READ-ONLY operation.
    """
    result = await get_purchase_order(po_number)
    return result.to_dict()


@api_router.get("/bc-sandbox/purchase-invoices/{invoice_number}")
async def bc_sandbox_get_purchase_invoice(invoice_number: str):
    """
    Get purchase invoice details by invoice number.
    READ-ONLY operation.
    """
    result = await get_purchase_invoice(invoice_number)
    return result.to_dict()


@api_router.get("/bc-sandbox/sales-invoices/{invoice_number}")
async def bc_sandbox_get_sales_invoice(invoice_number: str):
    """
    Get sales invoice details by invoice number.
    READ-ONLY operation.
    """
    result = await get_sales_invoice(invoice_number)
    return result.to_dict()


@api_router.post("/bc-sandbox/validate/vendor")
async def bc_sandbox_validate_vendor(vendor_number: str = Query(...)):
    """
    Validate that a vendor exists in BC.
    READ-ONLY operation.
    """
    exists, result = await validate_vendor_exists(vendor_number)
    return {
        "exists": exists,
        "lookup_result": result.to_dict()
    }


@api_router.post("/bc-sandbox/validate/invoice")
async def bc_sandbox_validate_invoice(
    invoice_number: str = Query(...),
    invoice_type: str = Query("purchase", regex="^(purchase|sales)$")
):
    """
    Validate that an invoice exists in BC.
    READ-ONLY operation.
    """
    exists, result = await validate_invoice_exists(invoice_number, invoice_type)
    return {
        "exists": exists,
        "invoice_type": invoice_type,
        "lookup_result": result.to_dict()
    }


@api_router.post("/bc-sandbox/validate/ap-invoice")
async def bc_sandbox_validate_ap_invoice(
    vendor_number: str = Query(...),
    invoice_number: Optional[str] = Query(None),
    po_number: Optional[str] = Query(None)
):
    """
    Full AP invoice validation against BC (observation mode).
    Validates vendor existence, PO reference, etc.
    READ-ONLY operation - results logged but don't block workflow.
    """
    validation_result = await validate_ap_invoice_in_bc(
        vendor_number=vendor_number,
        invoice_number=invoice_number,
        po_number=po_number
    )
    return validation_result


@api_router.post("/bc-sandbox/validate/sales-invoice")
async def bc_sandbox_validate_sales_invoice(
    customer_number: str = Query(...),
    invoice_number: Optional[str] = Query(None)
):
    """
    Full sales invoice validation against BC (observation mode).
    READ-ONLY operation.
    """
    validation_result = await validate_sales_invoice_in_bc(
        customer_number=customer_number,
        invoice_number=invoice_number
    )
    return validation_result


@api_router.post("/bc-sandbox/validate/purchase-order")
async def bc_sandbox_validate_purchase_order(po_number: str = Query(...)):
    """
    Purchase order validation against BC (observation mode).
    READ-ONLY operation.
    """
    validation_result = await validate_purchase_order_in_bc(po_number)
    return validation_result


@api_router.post("/bc/sales-orders/create")
async def create_bc_sales_order(
    customer_number: str = Query(..., description="BC Customer Number (e.g., 'NEW')"),
    external_doc_number: str = Query(None, description="Customer PO number"),
    order_date: str = Query(None, description="Order date (YYYY-MM-DD)"),
    delivery_date: str = Query(None, description="Requested delivery date (YYYY-MM-DD)")
):
    """
    Create a Sales Order in Business Central.
    
    Test endpoint for creating sales orders from customer POs.
    """
    from services.business_central_service import get_bc_service
    
    bc_service = get_bc_service()
    
    order_data = {
        "customerNumber": customer_number,
        "externalDocumentNumber": external_doc_number,
        "orderDate": order_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "requestedDeliveryDate": delivery_date,
        "lines": []  # Empty lines for now - just test header creation
    }
    
    result = await bc_service.create_sales_order(order_data)
    return result


@api_router.post("/bc-sandbox/document/{doc_id}/validate")
async def bc_sandbox_validate_document(doc_id: str, background_tasks: BackgroundTasks):
    """
    Validate a document against BC and add validation results to workflow history.
    This is the main integration point for workflow validation.
    
    READ-ONLY operation in observation mode.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_type = doc.get("doc_type", "OTHER")
    validation_result = None
    history_entry = None
    
    # Run appropriate validation based on doc_type
    if doc_type == "AP_INVOICE":
        vendor_number = doc.get("vendor_canonical") or doc.get("vendor_raw") or doc.get("extracted_data", {}).get("vendor_number")
        invoice_number = doc.get("invoice_number") or doc.get("extracted_data", {}).get("invoice_number")
        po_number = doc.get("po_number") or doc.get("extracted_data", {}).get("po_number")
        
        if vendor_number:
            validation_result = await validate_ap_invoice_in_bc(
                vendor_number=vendor_number,
                invoice_number=invoice_number,
                po_number=po_number
            )
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="ap_invoice",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No vendor number available for validation", "observation_only": True}
            
    elif doc_type == "SALES_INVOICE":
        customer_number = doc.get("customer_number") or doc.get("extracted_data", {}).get("customer_number")
        invoice_number = doc.get("invoice_number") or doc.get("extracted_data", {}).get("invoice_number")
        
        if customer_number:
            validation_result = await validate_sales_invoice_in_bc(
                customer_number=customer_number,
                invoice_number=invoice_number
            )
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="sales_invoice",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No customer number available for validation", "observation_only": True}
            
    elif doc_type == "PURCHASE_ORDER":
        po_number = doc.get("po_number") or doc.get("extracted_data", {}).get("po_number")
        
        if po_number:
            validation_result = await validate_purchase_order_in_bc(po_number)
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="purchase_order",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No PO number available for validation", "observation_only": True}
    else:
        validation_result = {"info": f"No BC validation defined for doc_type: {doc_type}", "observation_only": True}
    
    # Add history entry to document (if we have one)
    if history_entry:
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$push": {"workflow_history": history_entry},
                "$set": {
                    "bc_validation_result": validation_result,
                    "bc_validation_timestamp": datetime.now(timezone.utc).isoformat()
                }
            }
        )
    
    return {
        "document_id": doc_id,
        "doc_type": doc_type,
        "validation_result": validation_result,
        "history_entry_added": history_entry is not None,
        "observation_only": True
    }


# ==================== BC SIMULATION API (Phase 2 Shadow Pilot) ====================

from services.bc_simulation_service import (
    simulate_export_ap_invoice, simulate_create_purchase_invoice,
    simulate_attach_pdf, simulate_sales_invoice_export, simulate_po_linkage,
    run_full_export_simulation, calculate_simulation_summary,
    get_simulation_service_status, SimulationResult, SimulationType, SimulationStatus
)
from services.workflow_engine import SimulationHistoryEntry


@api_router.get("/pilot/simulation/status")
async def get_pilot_simulation_status():
    """Get BC simulation service status."""
    return get_simulation_service_status()


@api_router.post("/pilot/simulation/document/{doc_id}/run")
async def run_simulation_for_document(doc_id: str):
    """
    Run full BC export simulation for a document.
    
    This simulates all applicable BC operations based on doc_type
    and stores results in workflow history and simulation_results collection.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Run full simulation - use 'id' as 'document_id' for simulation
    doc_for_sim = {**doc, "document_id": doc_id}
    simulation_results = run_full_export_simulation(doc_for_sim)
    
    # Convert SimulationResult objects to clean dicts
    # Use JSON round-trip to ensure 100% serializable output
    import json as json_lib
    results_dict = {}
    for sim_key, sim_result in simulation_results.items():
        result_dict = sim_result.to_dict()
        # JSON round-trip to ensure clean dict
        clean_result = json_lib.loads(json_lib.dumps(result_dict))
        results_dict[sim_key] = clean_result
    
    # Create workflow history entry (also JSON-clean)
    history_entry_raw = SimulationHistoryEntry.create_batch_simulation_entry(
        document_id=doc_id,
        simulation_results=results_dict
    )
    history_entry = json_lib.loads(json_lib.dumps(history_entry_raw))
    
    # Store simulation results in dedicated collection
    for sim_type, result in results_dict.items():
        db_copy = json_lib.loads(json_lib.dumps(result))
        db_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
        await db.pilot_simulation_results.insert_one(db_copy)
    
    # Update document with simulation results and history
    results_for_db = json_lib.loads(json_lib.dumps(results_dict))
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$push": {"workflow_history": history_entry},
            "$set": {
                "last_simulation_results": results_for_db,
                "last_simulation_timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    # Calculate summary
    would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
    
    # Return clean dict (another JSON round-trip for safety)
    response_results = json_lib.loads(json_lib.dumps(results_dict))
    
    return {
        "document_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "simulations_run": len(response_results),
        "all_would_succeed": would_succeed,
        "results": response_results,
        "history_entry_added": True
    }


@api_router.post("/pilot/simulation/ap-invoice/{doc_id}")
async def simulate_ap_invoice_export(doc_id: str):
    """Simulate AP invoice export to BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("doc_type") != "AP_INVOICE":
        raise HTTPException(status_code=400, detail=f"Document is {doc.get('doc_type')}, not AP_INVOICE")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_export_ap_invoice(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@api_router.post("/pilot/simulation/sales-invoice/{doc_id}")
async def simulate_sales_invoice_export_endpoint(doc_id: str):
    """Simulate sales invoice export to BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("doc_type") != "SALES_INVOICE":
        raise HTTPException(status_code=400, detail=f"Document is {doc.get('doc_type')}, not SALES_INVOICE")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_sales_invoice_export(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@api_router.post("/pilot/simulation/po-linkage/{doc_id}")
async def simulate_po_linkage_endpoint(doc_id: str):
    """Simulate PO linkage in BC."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_po_linkage(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@api_router.post("/pilot/simulation/attachment/{doc_id}")
async def simulate_attachment_endpoint(doc_id: str):
    """Simulate PDF attachment to BC record."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_for_sim = {**doc, "document_id": doc_id}
    result = simulate_attach_pdf(doc_for_sim)
    result_dict = result.to_dict()
    
    # Store result (deep copy to avoid _id mutation)
    result_copy = copy.deepcopy(result_dict)
    result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.pilot_simulation_results.insert_one(result_copy)
    
    # Add to workflow history
    history_entry = SimulationHistoryEntry.create_simulation_entry(result_dict)
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$push": {"workflow_history": history_entry}}
    )
    
    return result_dict


@api_router.get("/pilot/simulation-results")
async def get_simulation_results(
    doc_type: str = Query(None),
    simulation_type: str = Query(None),
    would_succeed: bool = Query(None),
    limit: int = Query(100, le=500),
    skip: int = Query(0)
):
    """
    Get simulation results from the pilot.
    
    Filter by doc_type, simulation_type, or success status.
    """
    query = {}
    
    if doc_type:
        # Get document IDs for this doc_type
        doc_ids = await db.hub_documents.distinct("document_id", {"doc_type": doc_type})
        query["document_id"] = {"$in": doc_ids}
    
    if simulation_type:
        query["simulation_type"] = simulation_type
    
    if would_succeed is not None:
        query["would_succeed_in_production"] = would_succeed
    
    cursor = db.pilot_simulation_results.find(query, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit)
    results = await cursor.to_list(limit)
    
    total = await db.pilot_simulation_results.count_documents(query)
    
    return {
        "results": results,
        "total": total,
        "limit": limit,
        "skip": skip,
        "filters": {
            "doc_type": doc_type,
            "simulation_type": simulation_type,
            "would_succeed": would_succeed
        }
    }


@api_router.get("/pilot/simulation-summary")
async def get_simulation_summary(
    doc_type: str = Query(None),
    days: int = Query(14, ge=1, le=90)
):
    """
    Get summary statistics for simulation results.
    
    Shows success rates, failure reasons, and breakdown by type.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    query = {"timestamp": {"$gte": cutoff.isoformat()}}
    
    if doc_type:
        doc_ids = await db.hub_documents.distinct("document_id", {"doc_type": doc_type})
        query["document_id"] = {"$in": doc_ids}
    
    # Get all results for the period
    cursor = db.pilot_simulation_results.find(query, {"_id": 0})
    results = await cursor.to_list(10000)
    
    # Calculate summary
    summary = calculate_simulation_summary(results)
    
    # Add time range info
    summary["period_days"] = days
    summary["cutoff_date"] = cutoff.isoformat()
    summary["doc_type_filter"] = doc_type
    
    # Get unique documents simulated
    unique_docs = set(r.get("document_id") for r in results)
    summary["unique_documents_simulated"] = len(unique_docs)
    
    return summary


@api_router.post("/pilot/simulation/batch")
async def run_batch_simulation(
    doc_type: str = Query(...),
    status: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Run simulation for a batch of documents.
    
    Useful for running simulations on all documents of a type.
    """
    query = {"doc_type": doc_type}
    if status:
        query["workflow_status"] = status
    
    # Get documents
    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)
    
    results = []
    for doc in docs:
        doc_id = doc.get("id")
        try:
            doc_for_sim = {**doc, "document_id": doc_id}
            simulation_results = run_full_export_simulation(doc_for_sim)
            results_dict = {k: v.to_dict() for k, v in simulation_results.items()}
            
            # Store results (deep copy to avoid _id mutation)
            for sim_type, result in results_dict.items():
                result_copy = copy.deepcopy(result)
                result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
                await db.pilot_simulation_results.insert_one(result_copy)
            
            # Update document
            history_entry = SimulationHistoryEntry.create_batch_simulation_entry(
                document_id=doc_id,
                simulation_results=results_dict
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {
                    "$push": {"workflow_history": history_entry},
                    "$set": {
                        "last_simulation_results": results_dict,
                        "last_simulation_timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
            would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
            results.append({
                "document_id": doc_id,
                "simulations_run": len(results_dict),
                "all_would_succeed": would_succeed
            })
        except Exception as e:
            results.append({
                "document_id": doc_id,
                "error": str(e)
            })
    
    succeeded = sum(1 for r in results if r.get("all_would_succeed"))
    
    return {
        "doc_type": doc_type,
        "documents_processed": len(results),
        "all_would_succeed": succeeded,
        "would_have_failures": len(results) - succeeded,
        "results": results
    }


# ==================== SIMULATION METRICS API ====================

from services.simulation_metrics_service import (
    SimulationMetricsService, 
    normalize_failure_reason,
    FailureReasonCode
)

# Create singleton metrics service
_simulation_metrics_service = None

def get_simulation_metrics_service():
    global _simulation_metrics_service
    if _simulation_metrics_service is None:
        _simulation_metrics_service = SimulationMetricsService(db)
    return _simulation_metrics_service


@api_router.get("/pilot/simulation/metrics")
async def get_simulation_metrics(
    days: int = Query(14, ge=1, le=90),
    doc_type: str = Query(None),
    source_system: str = Query(None)
):
    """
    Get global simulation metrics summary.
    
    Returns success/failure counts grouped by doc_type, failure_reason,
    source_system, and workflow_status.
    """
    service = get_simulation_metrics_service()
    metrics = await service.get_global_metrics(
        days=days,
        doc_type_filter=doc_type,
        source_system_filter=source_system
    )
    return metrics


@api_router.get("/pilot/simulation/metrics/failures")
async def get_simulation_failure_details(
    failure_reason: str = Query(None, description="Normalized failure reason code"),
    doc_type: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Get detailed list of failed simulations.
    
    Filter by failure_reason code (e.g., VENDOR_NOT_FOUND, MISSING_REQUIRED_FIELDS).
    """
    service = get_simulation_metrics_service()
    return await service.get_failure_details(
        failure_reason=failure_reason,
        doc_type=doc_type,
        limit=limit
    )


@api_router.get("/pilot/simulation/metrics/successes")
async def get_simulation_success_details(
    doc_type: str = Query(None),
    limit: int = Query(50, le=200)
):
    """
    Get detailed list of successful simulations.
    """
    service = get_simulation_metrics_service()
    return await service.get_success_details(doc_type=doc_type, limit=limit)


@api_router.get("/pilot/simulation/metrics/trend")
async def get_simulation_trend(
    days: int = Query(14, ge=1, le=90),
    granularity: str = Query("day", regex="^(day|hour)$")
):
    """
    Get simulation trend data over time for charting.
    """
    service = get_simulation_metrics_service()
    return await service.get_trend_data(days=days, granularity=granularity)


@api_router.get("/pilot/simulation/metrics/pending")
async def get_documents_pending_simulation(
    doc_type: str = Query(None),
    workflow_status: str = Query(None),
    limit: int = Query(100, le=500)
):
    """
    Get documents that haven't been simulated yet.
    """
    service = get_simulation_metrics_service()
    return await service.get_documents_needing_simulation(
        doc_type=doc_type,
        workflow_status=workflow_status,
        limit=limit
    )


@api_router.get("/pilot/simulation/failure-reasons")
async def get_failure_reason_codes():
    """
    Get list of all normalized failure reason codes.
    """
    return {
        "failure_reason_codes": [
            {"code": e.value, "description": e.value.replace("_", " ").title()}
            for e in FailureReasonCode
        ]
    }


# ==================== BATCH RE-INGEST API ====================

# Global state for tracking re-ingest progress
_reingest_state = {
    "running": False,
    "total": 0,
    "processed": 0,
    "current_batch": 0,
    "total_batches": 0,
    "successes": 0,
    "failures": 0,
    "errors": [],
    "started_at": None,
    "completed_at": None
}


@api_router.get("/pilot/reingest/status")
async def get_reingest_status():
    """Get current re-ingest job status."""
    return _reingest_state


@api_router.post("/pilot/reingest/start")
async def start_batch_reingest(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(50, ge=10, le=100),
    doc_type_filter: str = Query(None, description="Optional: only re-ingest specific doc_type")
):
    """
    Start batch re-ingest of all documents.
    
    This will:
    1. Reset workflow_status to initial state
    2. Re-run document classification
    3. Run workflow engine
    4. Run BC simulations
    
    Processes in batches to avoid timeout.
    """
    global _reingest_state
    
    if _reingest_state["running"]:
        raise HTTPException(status_code=409, detail="Re-ingest already in progress")
    
    # Count documents to process
    query = {}
    if doc_type_filter:
        query["doc_type"] = doc_type_filter
    
    total_docs = await db.hub_documents.count_documents(query)
    
    if total_docs == 0:
        return {"message": "No documents to re-ingest", "total": 0}
    
    # Initialize state
    _reingest_state = {
        "running": True,
        "total": total_docs,
        "processed": 0,
        "current_batch": 0,
        "total_batches": (total_docs + batch_size - 1) // batch_size,
        "successes": 0,
        "failures": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "batch_size": batch_size,
        "doc_type_filter": doc_type_filter
    }
    
    # Start background task
    background_tasks.add_task(
        run_batch_reingest,
        batch_size=batch_size,
        doc_type_filter=doc_type_filter
    )
    
    return {
        "message": "Re-ingest started",
        "total_documents": total_docs,
        "batch_size": batch_size,
        "total_batches": _reingest_state["total_batches"],
        "status_endpoint": "/api/pilot/reingest/status"
    }


async def run_batch_reingest(batch_size: int, doc_type_filter: str = None):
    """Background task to run batch re-ingest."""
    global _reingest_state
    
    try:
        query = {}
        if doc_type_filter:
            query["doc_type"] = doc_type_filter
        
        # Get all document IDs
        cursor = db.hub_documents.find(query, {"_id": 0, "id": 1})
        all_docs = await cursor.to_list(10000)
        doc_ids = [d["id"] for d in all_docs]
        
        # Process in batches
        for batch_num in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[batch_num:batch_num + batch_size]
            _reingest_state["current_batch"] = (batch_num // batch_size) + 1
            
            for doc_id in batch_ids:
                try:
                    await reingest_single_document(doc_id)
                    _reingest_state["successes"] += 1
                except Exception as e:
                    _reingest_state["failures"] += 1
                    if len(_reingest_state["errors"]) < 20:  # Keep max 20 errors
                        _reingest_state["errors"].append({
                            "document_id": doc_id,
                            "error": str(e)
                        })
                
                _reingest_state["processed"] += 1
            
            # Small delay between batches to prevent overload
            await asyncio.sleep(0.5)
        
        _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()
        _reingest_state["running"] = False
        
    except Exception as e:
        _reingest_state["running"] = False
        _reingest_state["errors"].append({"global_error": str(e)})
        _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()


async def reingest_single_document(doc_id: str):
    """
    Re-ingest a single document:
    1. Reset workflow status
    2. Re-classify
    3. Run workflow
    4. Run simulation
    """
    # Get document
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document {doc_id} not found")
    
    # Import classification and workflow functions
    from services.workflow_engine import DocType, WorkflowStatus
    from services.bc_simulation_service import run_full_export_simulation
    
    # Step 1: Determine doc_type from existing data or re-classify
    doc_type = doc.get("doc_type", "OTHER")
    
    # If doc_type is missing or OTHER, try to classify based on content
    if doc_type in [None, "OTHER", ""]:
        # Simple rule-based classification based on existing fields
        if doc.get("vendor_canonical") or doc.get("vendor_raw"):
            if doc.get("po_number"):
                doc_type = "PURCHASE_ORDER"
            else:
                doc_type = "AP_INVOICE"
        elif doc.get("customer_number"):
            doc_type = "SALES_INVOICE"
        else:
            doc_type = "OTHER"
    
    # Step 2: Initial workflow status is always "captured"
    initial_status = WorkflowStatus.CAPTURED.value
    
    # Step 3: Create reset workflow history entry
    reset_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "workflow_reset",
        "actor": "batch_reingest",
        "from_status": doc.get("workflow_status"),
        "to_status": initial_status,
        "note": "Document re-ingested during batch reset"
    }
    
    # Step 4: Run simulation
    doc_for_sim = {**doc, "document_id": doc_id, "doc_type": doc_type}
    simulation_results = run_full_export_simulation(doc_for_sim)
    
    # Convert simulation results to dicts
    import json as json_lib
    results_dict = {}
    for sim_key, sim_result in simulation_results.items():
        result_dict = sim_result.to_dict()
        clean_result = json_lib.loads(json_lib.dumps(result_dict))
        results_dict[sim_key] = clean_result
    
    # Store simulation results
    for sim_type, result in results_dict.items():
        result_copy = json_lib.loads(json_lib.dumps(result))
        result_copy["_collection_timestamp"] = datetime.now(timezone.utc).isoformat()
        result_copy["_reingest_batch"] = True
        await db.pilot_simulation_results.insert_one(result_copy)
    
    # Step 5: Create simulation history entry
    from services.workflow_engine import SimulationHistoryEntry
    sim_history_entry = SimulationHistoryEntry.create_batch_simulation_entry(
        document_id=doc_id,
        simulation_results=results_dict
    )
    
    # Step 6: Determine workflow status based on simulation results
    all_would_succeed = all(r.get("would_succeed_in_production") for r in results_dict.values())
    
    # Set workflow status based on doc_type and simulation result
    if doc_type == "AP_INVOICE":
        if all_would_succeed:
            new_status = WorkflowStatus.READY_FOR_APPROVAL.value
        else:
            new_status = WorkflowStatus.DATA_CORRECTION_PENDING.value
    elif doc_type == "SALES_INVOICE":
        if all_would_succeed:
            new_status = "validated"
        else:
            new_status = "validation_failed"
    elif doc_type == "PURCHASE_ORDER":
        if all_would_succeed:
            new_status = "matched"
        else:
            new_status = "unmatched"
    else:
        new_status = initial_status
    
    # Step 7: Update document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "doc_type": doc_type,
                "workflow_status": new_status,
                "last_simulation_results": results_dict,
                "last_simulation_timestamp": datetime.now(timezone.utc).isoformat(),
                "reingest_timestamp": datetime.now(timezone.utc).isoformat(),
                "pilot_phase": "shadow_pilot_v1",
                "pilot_date": datetime.now(timezone.utc).isoformat()
            },
            "$push": {
                "workflow_history": {
                    "$each": [reset_entry, sim_history_entry]
                }
            }
        }
    )


@api_router.post("/pilot/reingest/stop")
async def stop_reingest():
    """Stop the running re-ingest job."""
    global _reingest_state
    
    if not _reingest_state["running"]:
        return {"message": "No re-ingest job running"}
    
    _reingest_state["running"] = False
    _reingest_state["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "message": "Re-ingest stopped",
        "processed": _reingest_state["processed"],
        "total": _reingest_state["total"]
    }


# ==================== FILE INGESTION API ====================

@api_router.post("/sales/file-import/parse")
async def parse_sales_file(
    file: UploadFile = File(...),
    ingestion_type: str = Form("sales_order"),
    sheet_name: Optional[str] = Form(None)
):
    """
    Parse an Excel/CSV file and return preview data with validation.
    
    Supported ingestion types:
    - sales_order: Parse customer POs into order headers and lines
    - inventory_position: Parse inventory snapshot data
    - customer_item: Parse customer SKU mappings
    
    Returns parsed data preview and validation results.
    """
    content = await file.read()
    
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    
    try:
        result = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type=ingestion_type,
            sheet_name=sheet_name
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error parsing file: %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Error parsing file: {str(e)}")


@api_router.post("/sales/file-import/import-orders")
async def import_sales_orders_from_file(
    file: UploadFile = File(...),
    customer_id: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    dry_run: bool = Form(True)
):
    """
    Import sales orders from an Excel/CSV file.
    
    Groups order lines by customer_po into order headers and lines.
    Use dry_run=True to preview without saving to database.
    """
    content = await file.read()
    
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    
    try:
        # First parse the file
        parsed = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type="sales_order",
            sheet_name=sheet_name
        )
        
        if not parsed.success:
            return {
                "success": False,
                "error": parsed.error,
                "validation_errors": parsed.validation_errors,
                "warnings": parsed.warnings
            }
        
        # Then import
        result = await file_ingestion_service.import_sales_orders(
            parsed_result=parsed,
            customer_id=customer_id,
            source="file_import",
            dry_run=dry_run
        )
        
        result["file_name"] = file.filename
        result["ingestion_id"] = parsed.ingestion_id
        result["rows_parsed"] = parsed.rows_parsed
        result["rows_valid"] = parsed.rows_valid
        result["rows_invalid"] = parsed.rows_invalid
        result["validation_errors"] = parsed.validation_errors
        
        return result
        
    except Exception as e:
        logger.exception("Error importing sales orders from file")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/sales/file-import/import-inventory")
async def import_inventory_from_file(
    file: UploadFile = File(...),
    customer_id: Optional[str] = Form(None),
    warehouse_id: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    dry_run: bool = Form(True)
):
    """
    Import inventory positions from an Excel/CSV file.
    
    Use dry_run=True to preview without saving to database.
    """
    content = await file.read()
    
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    
    try:
        # First parse the file
        parsed = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type="inventory_position",
            sheet_name=sheet_name
        )
        
        if not parsed.success:
            return {
                "success": False,
                "error": parsed.error,
                "validation_errors": parsed.validation_errors,
                "warnings": parsed.warnings
            }
        
        # Then import
        result = await file_ingestion_service.import_inventory_positions(
            parsed_result=parsed,
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            dry_run=dry_run
        )
        
        result["file_name"] = file.filename
        result["ingestion_id"] = parsed.ingestion_id
        result["rows_parsed"] = parsed.rows_parsed
        result["rows_valid"] = parsed.rows_valid
        result["rows_invalid"] = parsed.rows_invalid
        result["validation_errors"] = parsed.validation_errors
        
        return result
        
    except Exception as e:
        logger.exception("Error importing inventory from file")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/sales/file-import/excel-sheets")
async def get_excel_sheets(file: UploadFile = File(...)):
    """Get list of sheet names from an Excel file."""
    content = await file.read()
    
    try:
        sheets = file_ingestion_service.get_excel_sheets(content)
        return {"sheets": sheets, "file_name": file.filename}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.get("/sales/file-import/column-mappings")
async def get_column_mappings(ingestion_type: str = Query("sales_order")):
    """Get the expected column mappings for a given ingestion type."""
    from services.file_ingestion_service import COLUMN_MAPPINGS
    
    if ingestion_type not in COLUMN_MAPPINGS:
        raise HTTPException(status_code=400, detail=f"Unknown ingestion type: {ingestion_type}")
    
    config = COLUMN_MAPPINGS[ingestion_type]
    return {
        "ingestion_type": ingestion_type,
        "required_columns": config.get("required_columns", []),
        "optional_columns": config.get("optional_columns", []),
        "known_column_aliases": config.get("known_columns", {})
    }


@api_router.get("/sales/file-import/history")
async def get_import_history(
    ingestion_type: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50)
):
    """Get history of file imports."""
    query = {}
    if ingestion_type:
        query["ingestion_type"] = ingestion_type
    if customer_id:
        query["customer_id"] = customer_id
    
    total = await db.file_ingestion_log.count_documents(query)
    history = await db.file_ingestion_log.find(
        query, {"_id": 0}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"history": history, "total": total}


# ==================== APP SETUP ====================

app.include_router(api_router)
app.include_router(documents_router)
app.include_router(dashboard_router)
app.include_router(bc_router)
app.include_router(ingestion_router)
app.include_router(email_ingestion_router)
app.include_router(sales_admin_router)
app.include_router(job_type_settings_router)
app.include_router(workflows_router)
app.include_router(ap_workflows_router)
app.include_router(migration_tools_router)
app.include_router(aliases_router)
app.include_router(metrics_router)
# Sales Module (Phase 0 - BC disconnected)
app.include_router(sales_router)
# AP Review Module
app.include_router(ap_review_router)
# SharePoint Migration Module
app.include_router(sharepoint_migration_router, prefix="/api")
# Spiro Integration Module
app.include_router(spiro_router)

@app.get("/api/health")
async def health_check():
    """Health check endpoint for Docker/Kubernetes probes."""
    return {"status": "healthy", "service": "gpi-document-hub"}

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== DYNAMIC MAILBOX POLLING WORKER ====================

_dynamic_mailbox_polling_task = None
_mailbox_last_poll_times = {}  # Track last poll time per mailbox

async def dynamic_mailbox_polling_worker():
    """
    Background worker that polls all enabled mailbox sources from the database.
    Each mailbox is polled at its configured interval.
    """
    logger.info("[DynamicMailboxWorker] Starting dynamic mailbox polling worker")
    
    # Initial delay to let the app fully start
    await asyncio.sleep(30)
    
    while True:
        try:
            # Get all enabled mailbox sources
            mailbox_sources = await db.mailbox_sources.find(
                {"enabled": True}, 
                {"_id": 0}
            ).to_list(100)
            
            now = datetime.now(timezone.utc)
            
            for mailbox in mailbox_sources:
                mailbox_id = mailbox.get("mailbox_id")
                email_address = mailbox.get("email_address")
                interval_minutes = mailbox.get("polling_interval_minutes", 5)
                category = mailbox.get("category", "AP")
                
                if not email_address:
                    continue
                
                # Check if it's time to poll this mailbox
                last_poll = _mailbox_last_poll_times.get(mailbox_id)
                if last_poll:
                    elapsed = (now - last_poll).total_seconds() / 60
                    if elapsed < interval_minutes:
                        continue  # Not time yet
                
                # Time to poll!
                logger.info("[DynamicMailboxWorker] Polling %s (%s)", mailbox.get("name"), email_address)
                
                try:
                    stats = await poll_mailbox_for_documents(
                        mailbox_address=email_address,
                        default_category=category,
                        source_id=mailbox_id
                    )
                    
                    _mailbox_last_poll_times[mailbox_id] = now
                    
                    if stats.get("attachments_ingested", 0) > 0:
                        logger.info("[DynamicMailboxWorker] %s: ingested %d documents", 
                                   mailbox.get("name"), stats["attachments_ingested"])
                    
                except Exception as e:
                    logger.error("[DynamicMailboxWorker] Error polling %s: %s", email_address, str(e))
            
            # Sleep for 1 minute before checking again
            await asyncio.sleep(60)
            
        except asyncio.CancelledError:
            logger.info("[DynamicMailboxWorker] Polling worker cancelled")
            break
        except Exception as e:
            logger.error("[DynamicMailboxWorker] Worker error: %s", str(e))
            await asyncio.sleep(60)  # Wait before retrying


@app.on_event("startup")
async def startup():
    global _email_polling_task
    await db.hub_documents.create_index("id", unique=True)
    await db.hub_documents.create_index("status")
    await db.hub_documents.create_index("document_type")
    await db.hub_documents.create_index("created_utc")
    await db.hub_documents.create_index("source")
    await db.hub_documents.create_index("suggested_job_type")
    await db.hub_documents.create_index([("extracted_fields.vendor", 1)])
    # Phase 7: Indexes for new flat normalized fields
    await db.hub_documents.create_index("vendor_normalized")
    await db.hub_documents.create_index("invoice_number_clean")
    await db.hub_documents.create_index("vendor_canonical")
    await db.hub_documents.create_index("draft_candidate")
    await db.hub_documents.create_index("possible_duplicate")
    # AP Review indexes
    await db.hub_documents.create_index("review_status")
    await db.hub_documents.create_index("bc_posting_status")
    await db.hub_documents.create_index("vendor_id")
    # Initialize AP Review router dependencies
    set_ap_review_deps(db, get_bc_service())
    # Legacy indexes (keep for backward compat)
    await db.hub_documents.create_index([("canonical_fields.vendor_normalized", 1)])
    await db.hub_workflow_runs.create_index("id", unique=True)
    await db.hub_workflow_runs.create_index("document_id")
    await db.hub_workflow_runs.create_index("started_utc")
    await db.hub_config.create_index("_key", unique=True)
    await db.hub_job_types.create_index("job_type", unique=True)
    # Vendor aliases indexes
    await db.vendor_aliases.create_index("alias_id", unique=True)
    await db.vendor_aliases.create_index("alias_string", unique=True)
    await db.vendor_aliases.create_index("normalized_alias")
    await db.vendor_aliases.create_index("vendor_no")
    await db.vendor_aliases.create_index("canonical_vendor_id")
    # Phase C1: Mail intake log indexes
    await db.mail_intake_log.create_index("internet_message_id")
    await db.mail_intake_log.create_index("attachment_hash")
    await db.mail_intake_log.create_index([("internet_message_id", 1), ("attachment_hash", 1)])
    await db.mail_intake_log.create_index("processed_at")
    await db.mail_poll_runs.create_index("started_at")
    # Sales Module (Phase 0): Initialize database and indexes
    set_sales_db(db)
    await initialize_sales_indexes(db)
    # File Ingestion Service: Initialize database
    set_file_ingestion_db(db)
    # Spiro Integration: Initialize database
    set_spiro_db(db)
    set_spiro_routes_db(db)
    # Create Spiro indexes
    await db.spiro_contacts.create_index("spiro_id", unique=True)
    await db.spiro_contacts.create_index("email")
    await db.spiro_contacts.create_index("email_domain")
    await db.spiro_contacts.create_index("company_id")
    await db.spiro_companies.create_index("spiro_id", unique=True)
    await db.spiro_companies.create_index("name_normalized")
    await db.spiro_companies.create_index("email_domain")
    await db.spiro_opportunities.create_index("spiro_id", unique=True)
    await db.spiro_opportunities.create_index("company_id")
    await db.spiro_sync_status.create_index("entity_type", unique=True)
    logger.info("Spiro integration initialized")
    # Configure Sales email polling
    configure_sales_email_polling(
        enabled=SALES_EMAIL_POLLING_ENABLED,
        mailbox=SALES_EMAIL_POLLING_USER,
        interval_minutes=SALES_EMAIL_POLLING_INTERVAL_MINUTES
    )
    # Load saved config from MongoDB (overrides .env defaults)
    await _load_config_from_db()
    # Initialize default job types if not present
    for jt_key, jt_config in DEFAULT_JOB_TYPES.items():
        existing = await db.hub_job_types.find_one({"job_type": jt_key})
        if not existing:
            await db.hub_job_types.insert_one(jt_config)
    # Load vendor aliases into memory
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    for alias in aliases:
        VENDOR_ALIAS_MAP[alias["alias_string"]] = alias.get("vendor_name") or alias.get("vendor_no")
        VENDOR_ALIAS_MAP[alias["normalized_alias"]] = alias.get("vendor_name") or alias.get("vendor_no")
    
    # Start dynamic mailbox polling worker (polls mailboxes configured via UI)
    global _dynamic_mailbox_polling_task
    _dynamic_mailbox_polling_task = asyncio.create_task(dynamic_mailbox_polling_worker())
    logger.info("Dynamic mailbox polling worker started")
    
    # Start AP email polling worker if enabled (legacy env var method)
    if EMAIL_POLLING_ENABLED:
        _email_polling_task = asyncio.create_task(email_polling_worker())
        logger.info("AP email polling worker started (interval: %d min, user: %s)", 
                   EMAIL_POLLING_INTERVAL_MINUTES, EMAIL_POLLING_USER)
    # Start Sales email polling worker if enabled (legacy env var method)
    global _sales_polling_task
    if SALES_EMAIL_POLLING_ENABLED and SALES_EMAIL_POLLING_USER:
        _sales_polling_task = asyncio.create_task(_sales_email_polling_worker())
        logger.info("Sales email polling worker started (interval: %d min, user: %s)", 
                   SALES_EMAIL_POLLING_INTERVAL_MINUTES, SALES_EMAIL_POLLING_USER)
    
    # Initialize email service
    email_service = EmailService(db=db)
    set_email_service(email_service)
    await db.email_logs.create_index("message_id")
    await db.email_logs.create_index("sent_at")
    logger.info("Email service initialized (provider: mock)")
    
    # Initialize SharePoint Migration module
    sharepoint_migration_module.db = db
    await db.migration_candidates.create_index("source_item_id", unique=True)
    await db.migration_candidates.create_index("status")
    await db.migration_candidates.create_index("doc_type")
    logger.info("SharePoint Migration module initialized")
    
    # Start daily pilot summary scheduler if enabled
    global _pilot_summary_task
    if PILOT_MODE_ENABLED and DAILY_PILOT_EMAIL_ENABLED:
        _pilot_summary_task = asyncio.create_task(_daily_pilot_summary_scheduler())
        logger.info("Daily pilot summary scheduler started (cron: %d:00 UTC)", PILOT_SUMMARY_CRON_HOUR_UTC)
    
    logger.info("GPI Document Hub started. Demo mode: %s, Loaded %d vendor aliases", DEMO_MODE, len(aliases))

@app.on_event("shutdown")
async def shutdown_db_client():
    global _email_polling_task, _sales_polling_task, _dynamic_mailbox_polling_task, _pilot_summary_task
    # Cancel dynamic mailbox polling worker
    if _dynamic_mailbox_polling_task and not _dynamic_mailbox_polling_task.done():
        _dynamic_mailbox_polling_task.cancel()
        try:
            await _dynamic_mailbox_polling_task
        except asyncio.CancelledError:
            logger.info("Dynamic mailbox polling worker stopped")
    # Cancel AP email polling worker if running
    if _email_polling_task and not _email_polling_task.done():
        _email_polling_task.cancel()
        try:
            await _email_polling_task
        except asyncio.CancelledError:
            logger.info("AP email polling worker stopped")
    # Cancel Sales email polling worker if running
    if _sales_polling_task and not _sales_polling_task.done():
        _sales_polling_task.cancel()
        try:
            await _sales_polling_task
        except asyncio.CancelledError:
            logger.info("Sales email polling worker stopped")
    # Cancel pilot summary scheduler if running
    if _pilot_summary_task and not _pilot_summary_task.done():
        _pilot_summary_task.cancel()
        try:
            await _pilot_summary_task
        except asyncio.CancelledError:
            logger.info("Pilot summary scheduler stopped")
    client.close()
