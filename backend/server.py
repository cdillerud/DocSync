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

# ==================== WORKFLOW ENDPOINTS ====================

@api_router.get("/workflows")
async def list_workflows(skip: int = Query(0), limit: int = Query(50), status: str = Query(None)):
    fq = {}
    if status:
        fq["status"] = status
    workflows = await db.hub_workflow_runs.find(fq, {"_id": 0}).sort("started_utc", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.hub_workflow_runs.count_documents(fq)
    return {"workflows": workflows, "total": total}

@api_router.get("/workflows/{wf_id}")
async def get_workflow(wf_id: str):
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf

@api_router.post("/workflows/{wf_id}/retry")
async def retry_workflow(wf_id: str):
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    doc_id = wf.get("document_id")
    if not doc_id:
        raise HTTPException(status_code=400, detail="No document associated with this workflow")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Associated document not found")
    if doc.get("sharepoint_share_link_url") and (doc.get("bc_record_id") or doc.get("bc_document_no")):
        result = await _link_document(doc_id)
        return {"message": "Retry completed", "result": result}
    return {"message": "Cannot retry - document missing SharePoint link or BC reference"}


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

@api_router.post("/admin/backfill-sales-mailbox")
async def backfill_sales_mailbox(
    days_back: int = Query(30, description="How many days back to search"),
    max_messages: int = Query(50, description="Maximum messages to process"),
    dry_run: bool = Query(False, description="If true, only report what would be processed")
):
    """
    One-time backfill of existing Sales mailbox emails into the Document Hub.
    
    SAFE DESIGN:
    - Read-only Graph access
    - Does NOT mark messages as read
    - Does NOT move or delete messages
    - Uses idempotency (internetMessageId + attachment hash) to prevent duplicates
    - Processes all attachment types (not just PDFs)
    
    Use this to seed Shadow Mode with real production data.
    """
    run_id = uuid.uuid4().hex[:8]
    
    if not SALES_EMAIL_POLLING_USER:
        raise HTTPException(status_code=400, detail="SALES_EMAIL_POLLING_USER not configured in .env")
    
    stats = {
        "run_id": run_id,
        "dry_run": dry_run,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mailbox": SALES_EMAIL_POLLING_USER,
        "days_back": days_back,
        "max_messages": max_messages,
        "messages_found": 0,
        "messages_with_attachments": 0,
        "attachments_found": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_inline": 0,
        "errors": [],
        "ingested_documents": []
    }
    
    logger.info("[SalesBackfill:%s] Starting Sales mailbox backfill (days=%d, max=%d, dry_run=%s)", 
                run_id, days_back, max_messages, dry_run)
    
    try:
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats
        
        start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        filter_query = f"receivedDateTime ge {start_date}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": max_messages,
                    "$orderby": "receivedDateTime desc"
                }
            )
            
            if messages_resp.status_code != 200:
                error_msg = f"Graph API error {messages_resp.status_code}: {messages_resp.text[:200]}"
                stats["errors"].append(error_msg)
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_found"] = len(messages)
            
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_with_attachments"] = len(messages_with_attachments)
            
            logger.info("[SalesBackfill:%s] Found %d messages, %d with attachments", 
                        run_id, len(messages), len(messages_with_attachments))
            
            for msg in messages_with_attachments:
                msg_id = msg.get("id")
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                try:
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for message: {subject[:50]}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    stats["attachments_found"] += len(attachments)
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        is_inline = att.get("isInline", False)
                        size_bytes = att.get("size", 0)
                        
                        # Skip inline images and signatures
                        if is_inline or content_type.startswith("image/"):
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Skip very small files (likely signatures)
                        if size_bytes < 1000:
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        if dry_run:
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "subject": subject,
                                "sender": sender,
                                "size_bytes": size_bytes,
                                "status": "WOULD_INGEST"
                            })
                            stats["attachments_ingested"] += 1
                            continue
                        
                        # Fetch attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            
                            if att_content_resp.status_code != 200:
                                stats["errors"].append(f"Failed to fetch content for {filename}")
                                continue
                            
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                            content_bytes = base64.b64decode(content_b64)
                            content_hash = hashlib.sha256(content_bytes).hexdigest()
                            
                        except Exception as e:
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        # Check idempotency
                        is_dup = await check_sales_duplicate(internet_msg_id, content_hash)
                        if is_dup:
                            stats["attachments_skipped_duplicate"] += 1
                            continue
                        
                        # Ingest document
                        try:
                            result = await ingest_sales_document(
                                file_content=content_bytes,
                                filename=filename,
                                source="backfill",
                                email_sender=sender,
                                email_subject=subject,
                                email_body=body_preview,
                                email_message_id=internet_msg_id,
                                correlation_id=run_id
                            )
                            
                            doc_id = result.get("document_id")
                            
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Ingested",
                                document_id=doc_id
                            )
                            
                            stats["attachments_ingested"] += 1
                            stats["ingested_documents"].append({
                                "filename": filename,
                                "document_id": doc_id,
                                "document_type": result.get("document_type"),
                                "subject": subject,
                                "sender": sender,
                                "status": "INGESTED"
                            })
                            
                            logger.info("[SalesBackfill:%s] Ingested %s → %s (%s)", 
                                       run_id, filename, doc_id, result.get("document_type"))
                            
                        except Exception as e:
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                            logger.error("[SalesBackfill:%s] Intake failed for %s: %s", run_id, filename, str(e))
                
                except Exception as e:
                    stats["errors"].append(f"Error processing message {subject[:30]}: {str(e)}")
    
    except Exception as e:
        stats["errors"].append(f"Backfill error: {str(e)}")
        logger.error("[SalesBackfill:%s] Error: %s", run_id, str(e))
    
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info("[SalesBackfill:%s] Complete: found=%d, ingested=%d, skipped_dup=%d, errors=%d",
                run_id, stats["messages_with_attachments"], stats["attachments_ingested"],
                stats["attachments_skipped_duplicate"], len(stats["errors"]))
    
    return stats


# ==================== MIGRATE SALES DOCUMENTS TO UNIFIED COLLECTION ====================

@api_router.post("/admin/migrate-sales-to-unified")
async def migrate_sales_documents_to_unified():
    """
    One-time migration to move sales_documents into the main hub_documents collection.
    This unifies all documents into a single pipeline with category-based routing.
    
    Documents from sales_documents will be:
    - Copied to hub_documents with category="Sales"
    - Original sales_documents collection will NOT be deleted (kept for reference)
    - Duplicates (by document_id) will be skipped
    """
    run_id = uuid.uuid4().hex[:8]
    
    stats = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sales_documents_found": 0,
        "migrated": 0,
        "skipped_duplicate": 0,
        "errors": [],
        "migrated_documents": []
    }
    
    try:
        # Get all sales documents
        sales_docs = await db.sales_documents.find({}, {"_id": 0}).to_list(1000)
        stats["sales_documents_found"] = len(sales_docs)
        
        logger.info("[Migration:%s] Found %d sales documents to migrate", run_id, len(sales_docs))
        
        for sdoc in sales_docs:
            doc_id = sdoc.get("document_id")
            
            # Check if already exists in hub_documents
            existing = await db.hub_documents.find_one({"id": doc_id})
            if existing:
                stats["skipped_duplicate"] += 1
                continue
            
            # Map sales document to hub_documents schema
            now = datetime.now(timezone.utc).isoformat()
            
            hub_doc = {
                "id": doc_id,
                "source": sdoc.get("source", "email"),
                "file_name": sdoc.get("file_name"),
                "sha256_hash": sdoc.get("file_hash"),
                "file_size": sdoc.get("file_size"),
                "content_type": "application/octet-stream",
                "email_sender": sdoc.get("email_sender"),
                "email_subject": sdoc.get("email_subject"),
                "email_id": sdoc.get("email_message_id"),
                "email_received_utc": sdoc.get("created_utc"),
                "sharepoint_drive_id": None,
                "sharepoint_item_id": None,
                "sharepoint_web_url": None,
                "sharepoint_share_link_url": None,
                "document_type": sdoc.get("document_type"),
                "category": "Sales",
                "suggested_job_type": sdoc.get("document_type"),
                "ai_confidence": sdoc.get("ai_confidence"),
                "extracted_fields": sdoc.get("extracted_fields", {}),
                "validation_results": None,
                "automation_decision": "manual",
                "bc_record_type": None,
                "bc_company_id": None,
                "bc_record_id": None,
                "bc_document_no": None,
                "status": sdoc.get("status", "NeedsReview"),
                "workflow_state": sdoc.get("workflow_state", "Classified"),
                "validation_errors": sdoc.get("validation_errors", []),
                "validation_warnings": sdoc.get("validation_warnings", []),
                "created_utc": sdoc.get("created_utc", now),
                "updated_utc": now,
                "last_error": None,
                "classification_reasoning": sdoc.get("classification_reasoning"),
                "customer_id_sales": sdoc.get("customer_id"),
                "customer_name_extracted": sdoc.get("customer_name_extracted"),
                "correlation_id": sdoc.get("correlation_id"),
                "migrated_from": "sales_documents",
                "migrated_at": now,
                # Pilot metadata (added if pilot mode enabled)
                **get_pilot_metadata()
            }
            
            try:
                await db.hub_documents.insert_one(hub_doc)
                stats["migrated"] += 1
                stats["migrated_documents"].append({
                    "document_id": doc_id,
                    "document_type": sdoc.get("document_type"),
                    "file_name": sdoc.get("file_name")
                })
            except Exception as e:
                stats["errors"].append(f"Failed to migrate {doc_id}: {str(e)}")
        
        stats["ended_at"] = datetime.now(timezone.utc).isoformat()
        
        logger.info("[Migration:%s] Complete: found=%d, migrated=%d, skipped=%d, errors=%d",
                   run_id, stats["sales_documents_found"], stats["migrated"],
                   stats["skipped_duplicate"], len(stats["errors"]))
        
    except Exception as e:
        stats["errors"].append(f"Migration error: {str(e)}")
        logger.error("[Migration:%s] Error: %s", run_id, str(e))
    
    return stats


# ==================== JOB TYPE CONFIGURATION ENDPOINTS ====================

# ==================== SALES EMAIL POLLING ====================

async def run_sales_email_poll():
    """
    Poll the Sales intake mailbox for new documents.
    
    Similar to AP email polling but routes to Sales document pipeline.
    All documents classified and stored, none auto-processed.
    """
    run_id = str(uuid.uuid4())[:8]
    
    if not SALES_EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "SALES_EMAIL_POLLING_USER not configured"}
    
    stats = {
        "run_id": run_id,
        "mailbox": SALES_EMAIL_POLLING_USER,
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_dup": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        logger.info("[SalesPoll:%s] Starting poll for %s", run_id, SALES_EMAIL_POLLING_USER)
        
        # Get email access token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email access token")
            return stats
        
        # Calculate lookback window
        lookback = EMAIL_POLLING_LOOKBACK_MINUTES
        buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=lookback)).isoformat()
        filter_query = f"receivedDateTime ge {buffer_time}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Query messages
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                stats["errors"].append(f"Graph API error: {messages_resp.status_code}")
                return stats
            
            messages = messages_resp.json().get("value", [])
            stats["messages_detected"] = len(messages)
            
            for msg in messages:
                msg_id = msg.get("id")
                has_attachments = msg.get("hasAttachments", False)
                
                if not has_attachments:
                    continue
                
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                body_preview = msg.get("bodyPreview", "")
                
                try:
                    # Fetch attachments
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for {msg_id}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        is_inline = att.get("isInline", False)
                        size_bytes = att.get("size", 0)
                        
                        # Skip inline images and signatures
                        if is_inline or content_type.startswith("image/"):
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Skip very small files (likely signatures)
                        if size_bytes < 1000:
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Fetch attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{SALES_EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            if att_content_resp.status_code != 200:
                                stats["attachments_failed"] += 1
                                continue
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        content_bytes = base64.b64decode(content_b64)
                        content_hash = hashlib.sha256(content_bytes).hexdigest()
                        
                        # Check idempotency
                        is_dup = await check_sales_duplicate(internet_msg_id, content_hash)
                        if is_dup:
                            stats["attachments_skipped_dup"] += 1
                            continue
                        
                        # Ingest document
                        try:
                            result = await ingest_sales_document(
                                file_content=content_bytes,
                                filename=filename,
                                source="email",
                                email_sender=sender,
                                email_subject=subject,
                                email_body=body_preview,
                                email_message_id=internet_msg_id,
                                correlation_id=run_id
                            )
                            
                            # Log intake
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Ingested",
                                document_id=result.get("document_id")
                            )
                            
                            stats["attachments_ingested"] += 1
                            logger.info("[SalesPoll:%s] Ingested: %s -> %s", run_id, filename, result.get("document_type"))
                            
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Ingestion failed for {filename}: {str(e)}")
                            await record_sales_mail_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=content_hash,
                                filename=filename,
                                status="Failed",
                                error=str(e)
                            )
                            
                except Exception as e:
                    stats["errors"].append(f"Error processing message {msg_id}: {str(e)}")
                    
    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[SalesPoll:%s] Run failed: %s", run_id, str(e))
    
    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    # Record poll run - make a copy to avoid _id mutation affecting response
    stats_to_store = {**stats}
    await db.sales_mail_poll_runs.insert_one(stats_to_store)
    
    logger.info("[SalesPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
                run_id, stats["messages_detected"], stats["attachments_ingested"],
                stats["attachments_skipped_dup"], stats["attachments_skipped_inline"], stats["attachments_failed"])
    
    return stats


async def _sales_email_polling_worker():
    """Background worker that polls sales mailbox periodically."""
    while True:
        try:
            if SALES_EMAIL_POLLING_ENABLED and SALES_EMAIL_POLLING_USER:
                await run_sales_email_poll()
        except Exception as e:
            logger.error("Sales email polling worker error: %s", str(e))
        
        await asyncio.sleep(SALES_EMAIL_POLLING_INTERVAL_MINUTES * 60)


@api_router.get("/settings/job-types")
async def get_job_types():
    """Get all job type configurations."""
    job_types = await db.hub_job_types.find({}, {"_id": 0}).to_list(100)
    
    # Merge with defaults for any missing types
    result = dict(DEFAULT_JOB_TYPES)
    for jt in job_types:
        result[jt["job_type"]] = jt
    
    return {"job_types": list(result.values())}

@api_router.get("/settings/job-types/{job_type}")
async def get_job_type(job_type: str):
    """Get a specific job type configuration."""
    jt = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not jt:
        jt = DEFAULT_JOB_TYPES.get(job_type)
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
    return jt

@api_router.put("/settings/job-types/{job_type}")
async def update_job_type(job_type: str, config: JobTypeConfig):
    """Update a job type configuration."""
    update_data = config.model_dump()
    update_data["job_type"] = job_type
    
    await db.hub_job_types.update_one(
        {"job_type": job_type},
        {"$set": update_data},
        upsert=True
    )
    
    return await get_job_type(job_type)

@api_router.get("/settings/email-watcher")
async def get_email_watcher_settings():
    """Get email watcher configuration."""
    return await get_email_watcher_config()

@api_router.put("/settings/email-watcher")
async def update_email_watcher_settings(config: EmailWatchConfig):
    """Update email watcher configuration."""
    update_data = config.model_dump()
    update_data["_key"] = "email_watcher"
    
    logger.info("Saving email watcher config: %s", update_data)
    
    result = await db.hub_config.update_one(
        {"_key": "email_watcher"},
        {"$set": update_data},
        upsert=True
    )
    
    logger.info("MongoDB update result: matched=%s, modified=%s", result.matched_count, result.modified_count)
    
    return await get_email_watcher_config()

@api_router.post("/settings/email-watcher/subscribe")
async def subscribe_email_watcher(webhook_url: str = Query(...)):
    """Create Graph subscription for email notifications."""
    config = await get_email_watcher_config()
    
    if not config.get("mailbox_address"):
        raise HTTPException(status_code=400, detail="Mailbox address not configured")
    
    result = await subscribe_to_mailbox_notifications(config["mailbox_address"], webhook_url)
    
    if result.get("status") == "ok":
        await db.hub_config.update_one(
            {"_key": "email_watcher"},
            {"$set": {
                "webhook_subscription_id": result.get("subscription_id"),
                "webhook_expiration": result.get("expiration")
            }}
        )
    
    return result

# ==================== AP INVOICE WORKFLOW QUEUES ====================

class SetVendorRequest(BaseModel):
    """Request body for manual vendor resolution."""
    vendor_id: str
    vendor_name: Optional[str] = None
    vendor_alias_used: Optional[str] = None
    reason: Optional[str] = None

class UpdateFieldsRequest(BaseModel):
    """Request body for manual data correction."""
    invoice_number: Optional[str] = None
    amount: Optional[float] = None
    po_number: Optional[str] = None
    due_date: Optional[str] = None
    vendor_name: Optional[str] = None
    reason: Optional[str] = None

class BCValidationOverrideRequest(BaseModel):
    """Request body for BC validation override."""
    override_reason: str
    override_user: str

class ApprovalActionRequest(BaseModel):
    """Request body for approval actions."""
    reason: Optional[str] = None
    approver: Optional[str] = None


@api_router.get("/workflows/ap_invoice/status-counts")
async def get_ap_workflow_status_counts():
    """Get counts of AP_INVOICE documents by workflow status."""
    pipeline = [
        {"$match": {"$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}  # Backward compatibility
        ]}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(100)
    
    # Convert to dict format
    counts = {r["_id"] or "none": r["count"] for r in results}
    
    return {
        "status_counts": counts,
        "total": sum(counts.values()),
        "exception_queue_total": sum(
            counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses(DocType.AP_INVOICE.value)
        )
    }


@api_router.get("/workflows/ap_invoice/vendor-pending")
async def get_vendor_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_raw: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Get AP_INVOICE documents in vendor_pending status.
    These are documents where the vendor could not be automatically matched.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.VENDOR_PENDING.value
    }
    
    if vendor_raw:
        fq["vendor_raw"] = {"$regex": vendor_raw, "$options": "i"}
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    if date_from:
        fq["created_utc"] = {"$gte": date_from}
    if date_to:
        fq.setdefault("created_utc", {})["$lte"] = date_to
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "vendor_pending"}


@api_router.get("/workflows/ap_invoice/bc-validation-pending")
async def get_bc_validation_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    """
    Get AP_INVOICE documents awaiting BC validation.
    These documents have matched vendors and are being validated against BC.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_PENDING.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "bc_validation_pending"}


@api_router.get("/workflows/ap_invoice/bc-validation-failed")
async def get_bc_validation_failed_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    validation_error: Optional[str] = Query(None)
):
    """
    Get AP_INVOICE documents that failed BC validation.
    These need manual override or data correction.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_FAILED.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if validation_error:
        fq["validation_errors"] = {"$elemMatch": {"$regex": validation_error, "$options": "i"}}
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "bc_validation_failed"}


@api_router.get("/workflows/ap_invoice/data-correction-pending")
async def get_data_correction_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50)
):
    """
    Get AP_INVOICE documents that need manual data correction.
    These have incomplete or low-confidence extraction results.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.DATA_CORRECTION_PENDING.value
    }
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "data_correction_pending"}


@api_router.get("/workflows/ap_invoice/ready-for-approval")
async def get_ready_for_approval_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    """
    Get AP_INVOICE documents ready for approval.
    These have passed all validations and are waiting for human approval.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.READY_FOR_APPROVAL.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "ready_for_approval"}


# ==================== GENERIC WORKFLOW QUEUE API ====================

@api_router.get("/workflows/generic/queue")
async def get_workflow_queue(
    doc_type: str = Query(..., description="Document type (required): AP_INVOICE, SALES_INVOICE, PURCHASE_ORDER, etc."),
    status: Optional[str] = Query(None, description="Workflow status filter"),
    vendor: Optional[str] = Query(None, description="Vendor name filter"),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50)
):
    """
    Generic workflow queue endpoint supporting all document types.
    Use this as a single entry point for building work queues for any doc_type.
    
    Required: doc_type
    Optional: status (workflow_status), vendor, amount range, date range
    """
    fq = {"doc_type": doc_type}
    
    if status:
        fq["workflow_status"] = status
    if vendor:
        fq["$or"] = [
            {"vendor_raw": {"$regex": vendor, "$options": "i"}},
            {"vendor_canonical": {"$regex": vendor, "$options": "i"}}
        ]
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    if date_from:
        fq["created_utc"] = {"$gte": date_from}
    if date_to:
        fq.setdefault("created_utc", {})["$lte"] = date_to
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {
        "documents": docs,
        "total": total,
        "doc_type": doc_type,
        "status": status,
        "skip": skip,
        "limit": limit
    }


@api_router.get("/workflows/generic/status-counts-by-type")
async def get_status_counts_by_doc_type():
    """
    Get document counts grouped by doc_type and workflow_status.
    Returns a nested structure for metrics dashboards.
    """
    pipeline = [
        {"$group": {
            "_id": {
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.doc_type": 1, "_id.workflow_status": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Structure the results by doc_type
    documents_by_type_and_status = {}
    for r in results:
        doc_type = r["_id"].get("doc_type") or "unknown"
        status = r["_id"].get("workflow_status") or "none"
        count = r["count"]
        
        if doc_type not in documents_by_type_and_status:
            documents_by_type_and_status[doc_type] = {"statuses": {}, "total": 0}
        
        documents_by_type_and_status[doc_type]["statuses"][status] = count
        documents_by_type_and_status[doc_type]["total"] += count
    
    return {
        "documents_by_type_and_status": documents_by_type_and_status,
        "supported_doc_types": WorkflowEngine.get_all_doc_types(),
        "supported_statuses": WorkflowEngine.get_all_statuses()
    }


@api_router.get("/workflows/generic/metrics-by-type")
async def get_workflow_metrics_by_doc_type(
    days: int = Query(30, description="Number of days for metrics"),
    doc_type: Optional[str] = Query(None, description="Filter by specific doc_type")
):
    """
    Get workflow metrics grouped by document type.
    Includes extraction rates, time-in-status, and completion rates per type.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Build match filter
    match_filter = {"created_utc": {"$gte": cutoff}}
    if doc_type:
        match_filter["doc_type"] = doc_type
    
    # Aggregation for status distribution by type
    status_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": {
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(500)
    
    # Aggregation for extraction rates by type
    extraction_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": "$doc_type",
            "total": {"$sum": 1},
            "extracted": {"$sum": {"$cond": [{"$ne": ["$extracted_fields", None]}, 1, 0]}},
            "high_confidence": {"$sum": {"$cond": [{"$gte": ["$ai_confidence", 0.8]}, 1, 0]}},
            "avg_confidence": {"$avg": {"$ifNull": ["$ai_confidence", 0]}}
        }}
    ]
    extraction_results = await db.hub_documents.aggregate(extraction_pipeline).to_list(50)
    
    # Structure results
    metrics_by_type = {}
    
    # Process status counts
    for r in status_results:
        dt = r["_id"].get("doc_type") or "unknown"
        status = r["_id"].get("workflow_status") or "none"
        
        if dt not in metrics_by_type:
            metrics_by_type[dt] = {
                "status_counts": {},
                "total": 0,
                "extraction_rate": 0,
                "high_confidence_rate": 0,
                "avg_confidence": 0
            }
        
        metrics_by_type[dt]["status_counts"][status] = r["count"]
        metrics_by_type[dt]["total"] += r["count"]
    
    # Add extraction metrics
    for r in extraction_results:
        dt = r["_id"] or "unknown"
        if dt in metrics_by_type:
            total = r["total"] or 1
            metrics_by_type[dt]["extraction_rate"] = round((r["extracted"] / total) * 100, 2)
            metrics_by_type[dt]["high_confidence_rate"] = round((r["high_confidence"] / total) * 100, 2)
            metrics_by_type[dt]["avg_confidence"] = round(r["avg_confidence"] * 100, 2)
    
    return {
        "period_days": days,
        "metrics_by_type": metrics_by_type,
        "cutoff_date": cutoff
    }


# ==================== AP INVOICE WORKFLOW MUTATIONS ====================

@api_router.post("/workflows/ap_invoice/{doc_id}/set-vendor")
async def set_vendor_for_document(doc_id: str, request: SetVendorRequest):
    """
    Manually set/resolve vendor for a document in vendor_pending status.
    This moves the document from vendor_pending to bc_validation_pending.
    Only for AP_INVOICE documents.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Check doc_type (with backward compatibility for document_type)
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else None)
    if doc_type != DocType.AP_INVOICE.value:
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_INVOICE documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.VENDOR_PENDING.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Document is in status '{current_status}', expected 'vendor_pending'"
        )
    
    # Update vendor fields
    update_data = {
        "vendor_canonical": request.vendor_id,
        "vendor_match_method": "manual",
        "vendor_match_score": 1.0,
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if request.vendor_name:
        update_data["vendor_resolved_name"] = request.vendor_name
    
    # Create vendor alias if provided
    if request.vendor_alias_used and doc.get("vendor_normalized"):
        alias_doc = {
            "alias_string": request.vendor_alias_used,
            "normalized_alias": doc.get("vendor_normalized"),
            "canonical_vendor_id": request.vendor_id,
            "vendor_name": request.vendor_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": "manual_resolution"
        }
        await db.vendor_aliases.update_one(
            {"normalized_alias": doc.get("vendor_normalized")},
            {"$set": alias_doc},
            upsert=True
        )
    
    # Advance workflow
    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_VENDOR_RESOLVED.value,
        context={
            "reason": request.reason or "Vendor manually resolved",
            "metadata": {"vendor_id": request.vendor_id}
        },
        actor="user"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    # Exclude _id from response
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Vendor set to {request.vendor_id}, document moved to bc_validation_pending"
    }


@api_router.post("/workflows/ap_invoice/{doc_id}/update-fields")
async def update_document_fields(doc_id: str, request: UpdateFieldsRequest):
    """
    Manually update/correct fields on a document.
    Re-runs validation and advances workflow based on new data.
    Works for any document type, but AP-specific validation only runs for AP_INVOICE.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.DATA_CORRECTION_PENDING.value,
        WorkflowStatus.BC_VALIDATION_FAILED.value,
        WorkflowStatus.VENDOR_PENDING.value,
        WorkflowStatus.REVIEW_PENDING.value,
        WorkflowStatus.EXTRACTED.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', field updates allowed in: {valid_statuses}"
        )
    
    # Update fields
    update_data = {"updated_utc": datetime.now(timezone.utc).isoformat()}
    extracted_fields = doc.get("extracted_fields", {})
    
    if request.invoice_number is not None:
        extracted_fields["invoice_number"] = request.invoice_number
        update_data["invoice_number_clean"] = re.sub(r'[^a-zA-Z0-9]', '', request.invoice_number.upper())
    
    if request.amount is not None:
        extracted_fields["amount"] = str(request.amount)
        update_data["amount_float"] = request.amount
    
    if request.po_number is not None:
        extracted_fields["po_number"] = request.po_number
        update_data["po_number_clean"] = re.sub(r'[^a-zA-Z0-9]', '', request.po_number.upper()) if request.po_number else None
    
    if request.due_date is not None:
        extracted_fields["due_date"] = request.due_date
    
    if request.vendor_name is not None:
        extracted_fields["vendor"] = request.vendor_name
        update_data["vendor_raw"] = request.vendor_name
        update_data["vendor_normalized"] = normalize_vendor_name(request.vendor_name)
    
    update_data["extracted_fields"] = extracted_fields
    
    # Determine which event to fire based on current status
    if current_status == WorkflowStatus.DATA_CORRECTION_PENDING.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    elif current_status == WorkflowStatus.BC_VALIDATION_FAILED.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    else:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    
    # Apply updates and advance workflow
    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        event,
        context={
            "reason": request.reason or "Fields manually updated",
            "metadata": {"updated_fields": list(request.model_dump(exclude_none=True).keys())}
        },
        actor="user"
    )
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict() if success else None,
        "message": "Fields updated" + (", workflow advanced" if success else "")
    }


@api_router.post("/workflows/ap_invoice/{doc_id}/override-bc-validation")
async def override_bc_validation(doc_id: str, request: BCValidationOverrideRequest):
    """
    Override a failed BC validation and move document to ready_for_approval.
    This is a privileged action that bypasses normal validation rules.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.BC_VALIDATION_FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'bc_validation_failed'"
        )
    
    # Record the override
    override_record = {
        "override_reason": request.override_reason,
        "override_user": request.override_user,
        "override_utc": datetime.now(timezone.utc).isoformat(),
        "original_validation_errors": doc.get("validation_errors", [])
    }
    
    doc["bc_validation_override"] = override_record
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value,
        context={
            "reason": request.override_reason,
            "metadata": {"override_user": request.override_user}
        },
        actor=request.override_user
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"BC validation overridden by {request.override_user}, document moved to ready_for_approval"
    }


# ==================== AP INVOICE APPROVAL WORKFLOW ====================

@api_router.post("/workflows/ap_invoice/{doc_id}/start-approval")
async def start_approval(doc_id: str, request: ApprovalActionRequest):
    """
    Start the approval process for a document.
    Moves from ready_for_approval to approval_in_progress.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.READY_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'ready_for_approval'"
        )
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approval_started_utc"] = datetime.now(timezone.utc).isoformat()
    
    if request.approver:
        doc["assigned_approver"] = request.approver
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": request.reason or "Approval process started",
            "metadata": {"approver": request.approver}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started"
    }


@api_router.post("/workflows/ap_invoice/{doc_id}/approve")
async def approve_document(doc_id: str, request: ApprovalActionRequest):
    """
    Approve a document. Moves to 'approved' status.
    Can be called from ready_for_approval (auto-approval) or approval_in_progress.
    Works for all document types.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,  # Allow approval from extracted for non-AP docs
        WorkflowStatus.REVIEW_PENDING.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', approval allowed from: {valid_statuses}"
        )
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_by"] = request.approver or "system"
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": request.reason or "Document approved",
            "metadata": {"approver": request.approver, "doc_type": doc_type}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document approved by {request.approver or 'system'}"
    }


@api_router.post("/workflows/ap_invoice/{doc_id}/reject")
async def reject_document(doc_id: str, request: ApprovalActionRequest):
    """
    Reject a document. Moves to 'rejected' status.
    Works for all document types.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,
        WorkflowStatus.REVIEW_PENDING.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', rejection allowed from: {valid_statuses}"
        )
    
    if not request.reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_by"] = request.approver or "system"
    doc["rejection_reason"] = request.reason
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": request.reason,
            "metadata": {"rejector": request.approver, "doc_type": doc_type}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {request.reason}"
    }


# ==================== GENERIC WORKFLOW MUTATION ENDPOINTS ====================

@api_router.post("/workflows/{doc_id}/mark-ready-for-review")
async def mark_ready_for_review(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as ready for review.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER
    
    Triggers: on_mark_ready_for_review event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value,
        context={
            "reason": reason or "Marked ready for review",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot transition to ready_for_review from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked ready for review"
    }


@api_router.post("/workflows/{doc_id}/mark-reviewed")
async def mark_reviewed(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as reviewed.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC
    
    Triggers: on_reviewed event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REVIEWED.value,
        context={
            "reason": reason or "Document reviewed",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot mark as reviewed from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked as reviewed"
    }


@api_router.post("/workflows/{doc_id}/start-approval")
async def start_approval_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Start approval process for a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC
    
    Triggers: on_approval_started event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/start-approval"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": reason or "Approval process started",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot start approval from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started"
    }


@api_router.post("/workflows/{doc_id}/approve")
async def approve_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Approve a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO
    
    Triggers: on_approved event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/approve"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": reason or "Document approved",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot approve from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document approved"
    }


@api_router.post("/workflows/{doc_id}/reject")
async def reject_generic(
    doc_id: str,
    reason: str = Query(..., description="Reason for rejection (required)"),
    user: Optional[str] = None
):
    """
    Reject a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC
    
    Triggers: on_rejected event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/reject"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": reason,
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot reject from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {reason}"
    }


@api_router.post("/workflows/{doc_id}/complete-triage")
async def complete_triage(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Complete triage for an OTHER document.
    Applicable to: OTHER
    
    Triggers: on_triage_completed event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    if doc_type != DocType.OTHER.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Triage completion is only applicable to OTHER documents, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_TRIAGE_COMPLETED.value,
        context={
            "reason": reason or "Triage completed",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot complete triage from status '{doc.get('workflow_status')}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Triage completed"
    }


@api_router.post("/workflows/{doc_id}/link-credit-to-invoice")
async def link_credit_to_invoice(
    doc_id: str,
    invoice_id: str = Query(..., description="ID of the original invoice"),
    user: Optional[str] = None
):
    """
    Link a credit memo to its original invoice.
    Applicable to: SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO
    
    Triggers: on_credit_linked_to_invoice event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    valid_types = [DocType.SALES_CREDIT_MEMO.value, DocType.PURCHASE_CREDIT_MEMO.value]
    if doc_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invoice linkage is only applicable to credit memos, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value,
        context={
            "reason": f"Linked to invoice {invoice_id}",
            "metadata": {
                "triggered_by": actor,
                "linked_invoice_id": invoice_id
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot link to invoice from status '{doc.get('workflow_status')}'"
        )
    
    # Store the linked invoice reference
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "linked_invoice_id": invoice_id
        }}
    )
    
    updated_doc["linked_invoice_id"] = invoice_id
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Credit memo linked to invoice {invoice_id}"
    }


@api_router.post("/workflows/{doc_id}/tag-quality")
async def tag_quality_doc(
    doc_id: str,
    tags: List[str] = Query(..., description="Quality tags to apply"),
    user: Optional[str] = None
):
    """
    Tag a quality document for categorization.
    Applicable to: QUALITY_DOC
    
    Triggers: on_quality_tagged event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    if doc_type != DocType.QUALITY_DOC.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Quality tagging is only applicable to QUALITY_DOC, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_QUALITY_TAGGED.value,
        context={
            "reason": f"Tagged with: {', '.join(tags)}",
            "metadata": {
                "triggered_by": actor,
                "tags": tags
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot tag from status '{doc.get('workflow_status')}'"
        )
    
    # Store the tags
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "quality_tags": tags
        }}
    )
    
    updated_doc["quality_tags"] = tags
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Quality document tagged: {', '.join(tags)}"
    }


@api_router.post("/workflows/{doc_id}/export")
async def export_document(
    doc_id: str,
    export_destination: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as exported (generic version).
    Applicable to all document types.
    
    Triggers: on_exported event
    
    Note: During pilot mode, actual exports are blocked but status transitions
    are recorded for observation.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # Pilot mode guard: Block actual export but allow workflow transition
    pilot_blocked = is_export_blocked(doc)
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_EXPORTED.value,
        context={
            "reason": f"Exported to: {export_destination or 'default'}" + (" [PILOT: actual export blocked]" if pilot_blocked else ""),
            "metadata": {
                "triggered_by": actor,
                "export_destination": export_destination,
                "pilot_mode": pilot_blocked,
                "pilot_blocked_action": "external_export" if pilot_blocked else None
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot export from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "exported_utc": datetime.now(timezone.utc).isoformat(),
            "export_destination": export_destination
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document exported"
    }


# ==================== LEGACY MIGRATION ENDPOINTS ====================

class MigrationRequest(BaseModel):
    """Request model for starting a migration job."""
    source_file: Optional[str] = None
    source_filter: Optional[str] = None  # "SQUARE9" or "ZETADOCS"
    doc_type_filter: Optional[str] = None
    limit: Optional[int] = None
    mode: str = "dry_run"  # "dry_run" or "real"


@api_router.post("/migration/run")
async def run_migration_job(
    request: MigrationRequest,
    background_tasks: BackgroundTasks
):
    """
    Start a migration job to import legacy documents.
    
    The job reads documents from the specified source file and imports them
    into GPI Hub with proper classification and workflow initialization.
    
    Modes:
    - dry_run: Validate and preview without writing to database
    - real: Actually write documents to database
    
    Returns migration result with statistics and sample documents.
    """
    # Determine source
    if request.source_file:
        source_path = Path(request.source_file)
        if not source_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Source file not found: {request.source_file}"
            )
        source = JsonFileSource(request.source_file)
    else:
        # Use default sample migration file
        sample_path = "/app/backend/data/sample_migration.json"
        if not Path(sample_path).exists():
            # Create sample file if it doesn't exist
            Path(sample_path).parent.mkdir(parents=True, exist_ok=True)
            create_sample_migration_file(sample_path)
        source = JsonFileSource(sample_path)
    
    # Determine mode
    try:
        mode = MigrationMode(request.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode}. Use 'dry_run' or 'real'"
        )
    
    # Create job
    job = MigrationJob(
        source=source,
        db_collection=db.hub_documents if mode == MigrationMode.REAL else None,
        skip_duplicates=True,
        batch_size=100
    )
    
    # Run job
    result = await job.run(
        mode=mode,
        source_filter=request.source_filter,
        doc_type_filter=request.doc_type_filter,
        limit=request.limit
    )
    
    return result.to_dict()


@api_router.get("/migration/preview")
async def preview_migration(
    source_file: Optional[str] = None,
    source_filter: Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    limit: int = Query(10, le=100)
):
    """
    Preview legacy documents before migration.
    
    Returns a sample of documents that would be migrated, with their
    classification and workflow status preview.
    """
    # Determine source
    if source_file:
        source_path = Path(source_file)
        if not source_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Source file not found: {source_file}"
            )
        source = JsonFileSource(source_file)
    else:
        sample_path = "/app/backend/data/sample_migration.json"
        if not Path(sample_path).exists():
            Path(sample_path).parent.mkdir(parents=True, exist_ok=True)
            create_sample_migration_file(sample_path)
        source = JsonFileSource(sample_path)
    
    # Get document count
    total_count = source.get_document_count(source_filter, doc_type_filter)
    
    # Preview documents
    documents = []
    for legacy_doc in source.iter_documents(source_filter, doc_type_filter, limit):
        # Show raw legacy data and what it would become
        preview = {
            "legacy": legacy_doc.to_dict(),
            "preview": {}
        }
        
        # Classify
        metadata = legacy_doc.metadata
        from services.workflow_engine import ZETADOCS_SET_MAPPING, SQUARE9_WORKFLOW_MAPPING
        
        doc_type = DocType.OTHER.value
        if metadata.legacy_zetadocs_set_code:
            result = ZETADOCS_SET_MAPPING.get(metadata.legacy_zetadocs_set_code)
            if result:
                doc_type = result[0].value
        elif metadata.legacy_workflow_name:
            result = SQUARE9_WORKFLOW_MAPPING.get(metadata.legacy_workflow_name)
            if result:
                doc_type = result.value
        
        # Get workflow preview
        workflow_result = WorkflowInitializer.initialize(doc_type, metadata)
        
        preview["preview"] = {
            "doc_type": doc_type,
            "workflow_status": workflow_result.workflow_status,
            "workflow_reason": workflow_result.reason
        }
        
        documents.append(preview)
    
    return {
        "source_name": source.get_source_name(),
        "total_count": total_count,
        "preview_count": len(documents),
        "filters": {
            "source_filter": source_filter,
            "doc_type_filter": doc_type_filter,
            "limit": limit
        },
        "documents": documents
    }


@api_router.post("/migration/generate-sample")
async def generate_sample_migration_file(
    output_path: str = Query(default="/app/backend/data/sample_migration.json")
):
    """
    Generate a sample migration JSON file for testing.
    
    Creates a file with realistic legacy documents from Square9 and Zetadocs.
    """
    try:
        create_sample_migration_file(output_path)
        return {
            "success": True,
            "path": output_path,
            "message": "Sample migration file created successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create sample file: {str(e)}"
        )


@api_router.get("/migration/stats")
async def get_migration_stats():
    """
    Get statistics about migrated documents in the system.
    """
    # Count migrated documents by source system
    pipeline = [
        {"$match": {"is_migrated": True}},
        {"$group": {
            "_id": {
                "legacy_system": "$legacy_system",
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.legacy_system": 1, "_id.doc_type": 1}}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Organize results
    by_system = {}
    by_doc_type = {}
    by_status = {}
    total = 0
    
    for r in results:
        system = r["_id"].get("legacy_system", "UNKNOWN")
        doc_type = r["_id"].get("doc_type", "OTHER")
        status = r["_id"].get("workflow_status", "unknown")
        count = r["count"]
        
        by_system[system] = by_system.get(system, 0) + count
        by_doc_type[doc_type] = by_doc_type.get(doc_type, 0) + count
        by_status[status] = by_status.get(status, 0) + count
        total += count
    
    return {
        "total_migrated": total,
        "by_legacy_system": by_system,
        "by_doc_type": by_doc_type,
        "by_workflow_status": by_status
    }


@api_router.get("/migration/supported-types")
async def get_supported_migration_types():
    """
    Get information about document types supported by the migration job.
    """
    return {
        "supported_doc_types": WorkflowInitializer.get_supported_doc_types(),
        "source_systems": ["SQUARE9", "ZETADOCS"],
        "zetadocs_mappings": {
            "ZD00015": "AP_INVOICE",
            "ZD00007": "SALES_INVOICE",
            "ZD00002": "PURCHASE_ORDER",
            "ZD00006": "SALES_INVOICE (Order Confirmations)",
            "ZD00009": "SALES_CREDIT_MEMO",
            "ZD00010": "SALES_INVOICE (Blanket Orders)",
        },
        "square9_mappings": {
            "AP_Invoice": "AP_INVOICE",
            "AP Invoice": "AP_INVOICE",
            "Purchase Invoice": "AP_INVOICE",
            "Sales Invoice": "SALES_INVOICE",
            "Sales_Invoice": "SALES_INVOICE",
            "Purchase Order": "PURCHASE_ORDER",
            "PO": "PURCHASE_ORDER",
            "Credit Memo": "SALES_CREDIT_MEMO",
            "Statement": "STATEMENT",
            "Reminder": "REMINDER",
            "Quality": "QUALITY_DOC",
        }
    }


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


# ==================== VENDOR ALIAS ENGINE ====================

class VendorAlias(BaseModel):
    alias_string: str
    vendor_no: str
    vendor_name: Optional[str] = None
    confidence_override: Optional[float] = None  # If set, use this instead of calculated
    notes: Optional[str] = None

@api_router.get("/aliases/vendors")
async def get_vendor_aliases():
    """Get all vendor aliases."""
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    return {"aliases": aliases, "count": len(aliases)}

@api_router.post("/aliases/vendors")
async def create_vendor_alias(alias: VendorAlias):
    """Create a new vendor alias mapping."""
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Normalize the alias string for matching
    normalized = normalize_vendor_name(alias.alias_string)
    
    # Check for existing alias
    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": alias.alias_string},
            {"normalized_alias": normalized}
        ]
    })
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Alias already exists for '{alias.alias_string}'")
    
    alias_doc = {
        "alias_id": alias_id,
        "alias_string": alias.alias_string,
        "normalized_alias": normalized,
        "vendor_no": alias.vendor_no,
        "vendor_name": alias.vendor_name,
        "confidence_override": alias.confidence_override,
        "notes": alias.notes,
        "created_by": "system",  # Could be user ID in future
        "created_at": now,
        "usage_count": 0,
        "last_used_at": None
    }
    
    await db.vendor_aliases.insert_one(alias_doc)
    
    # Update global alias map
    VENDOR_ALIAS_MAP[alias.alias_string] = alias.vendor_name or alias.vendor_no
    VENDOR_ALIAS_MAP[normalized] = alias.vendor_name or alias.vendor_no
    
    return {"alias_id": alias_id, "message": "Alias created successfully"}

@api_router.delete("/aliases/vendors/{alias_id}")
async def delete_vendor_alias(alias_id: str):
    """Delete a vendor alias."""
    result = await db.vendor_aliases.delete_one({"alias_id": alias_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"message": "Alias deleted"}

@api_router.get("/aliases/vendors/suggest")
async def suggest_alias_creation(vendor_name: str, resolved_vendor_no: str, resolved_vendor_name: str):
    """
    Called when user manually resolves a vendor match.
    Returns suggestion to save as alias.
    """
    normalized = normalize_vendor_name(vendor_name)
    
    # Check if alias already exists
    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": vendor_name},
            {"normalized_alias": normalized}
        ]
    }, {"_id": 0})
    
    if existing:
        return {
            "suggest_alias": False,
            "reason": "Alias already exists",
            "existing_alias": existing
        }
    
    return {
        "suggest_alias": True,
        "suggested_alias": {
            "alias_string": vendor_name,
            "normalized_alias": normalized,
            "vendor_no": resolved_vendor_no,
            "vendor_name": resolved_vendor_name
        },
        "message": f"Would you like to save '{vendor_name}' as an alias for '{resolved_vendor_name}'?"
    }

# Update resolve endpoint to increment alias usage
async def record_alias_usage(alias_string: str):
    """Record when an alias is used for matching."""
    await db.vendor_aliases.update_one(
        {"alias_string": alias_string},
        {
            "$inc": {"usage_count": 1},
            "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}
        }
    )

# ==================== AUTOMATION METRICS ENGINE ====================

async def _get_automation_metrics_internal(days: int = 30, job_type: str = None):
    """
    Internal helper function to get automation metrics without FastAPI Query parameters.
    Used by other endpoints to aggregate metrics.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Build query filter
    query = {"created_utc": {"$gte": cutoff_date}}
    if job_type:
        query["suggested_job_type"] = job_type
    
    # Total documents
    total = await db.hub_documents.count_documents(query)
    
    # Status distribution
    status_counts = {}
    for status in ["Received", "StoredInSP", "Classified", "NeedsReview", "LinkedToBC", "Exception"]:
        status_query = {**query, "status": status}
        status_counts[status] = await db.hub_documents.count_documents(status_query)
    
    # Percentages
    status_percentages = {
        status: round((count / total * 100) if total > 0 else 0, 1)
        for status, count in status_counts.items()
    }
    
    # Job type breakdown
    job_type_breakdown = {}
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({**query, "suggested_job_type": jt})
        if count > 0:
            job_type_breakdown[jt] = count
    
    # Confidence distribution
    confidence_ranges = {
        "high_0.9_1.0": 0,
        "medium_0.7_0.9": 0,
        "low_0_0.7": 0
    }
    
    docs_with_confidence = await db.hub_documents.find(
        {**query, "ai_confidence": {"$exists": True}},
        {"ai_confidence": 1, "_id": 0}
    ).to_list(10000)
    
    for doc in docs_with_confidence:
        conf = doc.get("ai_confidence") or 0
        if conf >= 0.9:
            confidence_ranges["high_0.9_1.0"] += 1
        elif conf >= 0.7:
            confidence_ranges["medium_0.7_0.9"] += 1
        else:
            confidence_ranges["low_0_0.7"] += 1
    
    # Average confidence
    total_confidence = sum((doc.get("ai_confidence") or 0) for doc in docs_with_confidence)
    avg_confidence = round(total_confidence / len(docs_with_confidence), 3) if docs_with_confidence else 0
    
    # Duplicate prevention count
    duplicate_prevented = await db.hub_documents.count_documents({
        **query,
        "validation_results.checks": {
            "$elemMatch": {"check_name": "duplicate_check", "passed": False}
        }
    })
    
    # Match method breakdown
    match_method_breakdown = {
        "exact_no": 0, "exact_name": 0, "normalized": 0,
        "alias": 0, "fuzzy": 0, "manual": 0, "none": 0
    }
    
    docs_with_match = await db.hub_documents.find(
        query, {"match_method": 1, "status": 1, "_id": 0}
    ).to_list(10000)
    
    alias_auto_linked = 0
    alias_needs_review = 0
    
    for doc in docs_with_match:
        method = doc.get("match_method", "none")
        if method in match_method_breakdown:
            match_method_breakdown[method] += 1
        else:
            match_method_breakdown["none"] += 1
        
        if method == "alias":
            if doc.get("status") == "LinkedToBC":
                alias_auto_linked += 1
            elif doc.get("status") == "NeedsReview":
                alias_needs_review += 1
    
    total_alias = alias_auto_linked + alias_needs_review
    alias_exception_rate = round((alias_needs_review / total_alias * 100) if total_alias > 0 else 0, 1)
    
    # Draft creation metrics
    draft_created_count = await db.hub_documents.count_documents({
        **query, "transaction_action": TransactionAction.DRAFT_CREATED
    })
    
    linked_only_count = await db.hub_documents.count_documents({
        **query, "transaction_action": TransactionAction.LINKED_ONLY
    })
    
    linked_total = status_counts.get("LinkedToBC", 0)
    draft_creation_rate = round((draft_created_count / linked_total * 100) if linked_total > 0 else 0, 1)
    
    return {
        "period_days": days,
        "total_documents": total,
        "status_distribution": {
            "counts": status_counts,
            "percentages": status_percentages
        },
        "job_type_breakdown": job_type_breakdown,
        "confidence_distribution": confidence_ranges,
        "average_confidence": avg_confidence,
        "duplicate_prevented": duplicate_prevented,
        "automation_rate": status_percentages.get("LinkedToBC", 0),
        "review_rate": status_percentages.get("NeedsReview", 0),
        "match_method_breakdown": match_method_breakdown,
        "alias_auto_linked": alias_auto_linked,
        "alias_exception_rate": alias_exception_rate,
        "draft_created_count": draft_created_count,
        "linked_only_count": linked_only_count,
        "draft_creation_rate": draft_creation_rate,
        "draft_feature_enabled": ENABLE_CREATE_DRAFT_HEADER,
        "header_only_flag": True
    }


@api_router.get("/metrics/automation")
async def get_automation_metrics(
    days: int = Query(30, description="Number of days to include"),
    job_type: Optional[str] = Query(None, description="Filter by job type")
):
    """
    Get comprehensive automation metrics for the audit dashboard.
    """
    return await _get_automation_metrics_internal(days=days, job_type=job_type)

@api_router.get("/metrics/vendors")
async def get_vendor_friction_metrics(days: int = Query(30)):
    """
    Get vendor friction index - shows where alias mapping will have biggest ROI.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get all documents with vendor info
    docs = await db.hub_documents.find(
        {
            "created_utc": {"$gte": cutoff_date},
            "extracted_fields.vendor": {"$exists": True}
        },
        {"extracted_fields.vendor": 1, "status": 1, "ai_confidence": 1, "match_method": 1, "_id": 0}
    ).to_list(5000)
    
    # Get existing aliases
    aliases = await db.vendor_aliases.find({}, {"alias_string": 1, "vendor_name": 1}).to_list(500)
    alias_strings = set(a.get("alias_string", "").lower() for a in aliases)
    
    # Aggregate by vendor
    vendor_stats = {}
    for doc in docs:
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {
                "total": 0,
                "linked": 0,
                "needs_review": 0,
                "exception": 0,
                "total_confidence": 0,
                "alias_matches": 0,
                "has_alias": vendor.lower() in alias_strings
            }
        
        vendor_stats[vendor]["total"] += 1
        vendor_stats[vendor]["total_confidence"] += doc.get("ai_confidence", 0)
        
        # Track alias-based matches
        if doc.get("match_method") == "alias":
            vendor_stats[vendor]["alias_matches"] += 1
        
        status = doc.get("status", "")
        if status == "LinkedToBC":
            vendor_stats[vendor]["linked"] += 1
        elif status == "NeedsReview":
            vendor_stats[vendor]["needs_review"] += 1
        elif status == "Exception":
            vendor_stats[vendor]["exception"] += 1
    
    # Calculate friction index and ROI hints
    vendor_friction = []
    for vendor, stats in vendor_stats.items():
        total = stats["total"]
        if total > 0:
            exception_rate = stats["needs_review"] / total
            avg_confidence = stats["total_confidence"] / total
            auto_rate = stats["linked"] / total
            
            # Friction index: higher = more manual intervention needed
            friction_index = round(exception_rate * 100, 1)
            
            # ROI hint: estimate potential improvement if alias is created
            # If no alias exists and high friction, alias could help
            potential_auto_rate = None
            roi_hint = None
            
            if not stats["has_alias"] and friction_index > 50 and avg_confidence >= 0.85:
                # Documents with high confidence but failing vendor match
                # Would likely auto-link if alias existed
                potential_docs = stats["needs_review"]
                potential_auto_rate = round((stats["linked"] + potential_docs) / total * 100, 1)
                roi_hint = f"Creating alias could reduce review rate from {friction_index}% to ~{100 - potential_auto_rate}%"
            elif stats["has_alias"]:
                roi_hint = "Alias exists - monitoring impact"
            
            vendor_friction.append({
                "vendor": vendor,
                "total_documents": total,
                "auto_linked": stats["linked"],
                "needs_review": stats["needs_review"],
                "alias_matches": stats["alias_matches"],
                "auto_rate": round(auto_rate * 100, 1),
                "avg_confidence": round(avg_confidence, 3),
                "friction_index": friction_index,
                "has_alias": stats["has_alias"],
                "potential_auto_rate": potential_auto_rate,
                "roi_hint": roi_hint
            })
    
    # Sort by friction index (highest first = most opportunity)
    vendor_friction.sort(key=lambda x: x["friction_index"], reverse=True)
    
    return {
        "period_days": days,
        "vendor_count": len(vendor_friction),
        "vendors": vendor_friction[:20],  # Top 20 friction vendors
        "total_analyzed": len(docs)
    }

@api_router.get("/metrics/alias-impact")
async def get_alias_impact_metrics():
    """
    Track alias learning impact over time.
    Shows compounding intelligence.
    """
    # Get all aliases with usage stats
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    
    total_aliases = len(aliases)
    total_usage = sum(a.get("usage_count", 0) for a in aliases)
    
    # Get match method distribution from recent documents
    docs = await db.hub_documents.find(
        {"validation_results.checks": {"$exists": True}},
        {"validation_results.checks": 1, "_id": 0}
    ).sort("created_utc", -1).limit(1000).to_list(1000)
    
    match_methods = {
        "exact_no": 0,
        "exact_name": 0,
        "normalized": 0,
        "alias": 0,
        "fuzzy": 0,
        "no_match": 0
    }
    
    for doc in docs:
        checks = doc.get("validation_results", {}).get("checks", [])
        for check in checks:
            if check.get("check_name") in ("vendor_match", "customer_match"):
                method = check.get("match_method", "no_match")
                if method in match_methods:
                    match_methods[method] += 1
                elif not check.get("passed"):
                    match_methods["no_match"] += 1
    
    total_matches = sum(match_methods.values())
    
    return {
        "total_aliases": total_aliases,
        "total_alias_usage": total_usage,
        "top_aliases": sorted(aliases, key=lambda x: x.get("usage_count", 0), reverse=True)[:10],
        "match_method_distribution": match_methods,
        "match_method_percentages": {
            k: round(v / total_matches * 100, 1) if total_matches > 0 else 0
            for k, v in match_methods.items()
        },
        "alias_contribution": round(match_methods.get("alias", 0) / total_matches * 100, 1) if total_matches > 0 else 0
    }

@api_router.get("/metrics/resolution-time")
async def get_resolution_time_metrics(days: int = Query(30)):
    """
    Track time from Received to LinkedToBC.
    Shows efficiency improvements.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get documents that reached LinkedToBC status
    linked_docs = await db.hub_documents.find(
        {
            "created_utc": {"$gte": cutoff_date},
            "status": "LinkedToBC"
        },
        {"created_utc": 1, "updated_utc": 1, "resolved_utc": 1, "suggested_job_type": 1, "_id": 0}
    ).to_list(5000)
    
    resolution_times = []
    by_job_type = {}
    
    for doc in linked_docs:
        try:
            created = datetime.fromisoformat(doc["created_utc"].replace("Z", "+00:00"))
            # Use resolved_utc if available, otherwise updated_utc
            resolved = doc.get("resolved_utc") or doc.get("updated_utc")
            if resolved:
                resolved = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
                minutes = (resolved - created).total_seconds() / 60
                resolution_times.append(minutes)
                
                jt = doc.get("suggested_job_type", "Unknown")
                if jt not in by_job_type:
                    by_job_type[jt] = []
                by_job_type[jt].append(minutes)
        except Exception:
            continue
    
    # Calculate statistics
    if resolution_times:
        resolution_times.sort()
        median_time = resolution_times[len(resolution_times) // 2]
        p95_time = resolution_times[int(len(resolution_times) * 0.95)] if len(resolution_times) > 20 else max(resolution_times)
        avg_time = sum(resolution_times) / len(resolution_times)
    else:
        median_time = 0
        p95_time = 0
        avg_time = 0
    
    # Per job type stats
    job_type_stats = {}
    for jt, times in by_job_type.items():
        if times:
            times.sort()
            job_type_stats[jt] = {
                "count": len(times),
                "median_minutes": round(times[len(times) // 2], 2),
                "avg_minutes": round(sum(times) / len(times), 2)
            }
    
    return {
        "period_days": days,
        "total_resolved": len(resolution_times),
        "median_minutes": round(median_time, 2),
        "p95_minutes": round(p95_time, 2),
        "avg_minutes": round(avg_time, 2),
        "by_job_type": job_type_stats
    }

@api_router.get("/metrics/daily")
async def get_daily_metrics(days: int = Query(14)):
    """
    Get daily aggregated metrics for trend charts.
    """
    daily_metrics = []
    
    for i in range(days):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        start = date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        
        query = {"created_utc": {"$gte": start, "$lte": end}}
        
        total = await db.hub_documents.count_documents(query)
        linked = await db.hub_documents.count_documents({**query, "status": "LinkedToBC"})
        review = await db.hub_documents.count_documents({**query, "status": "NeedsReview"})
        
        daily_metrics.append({
            "date": date_str,
            "total": total,
            "auto_linked": linked,
            "needs_review": review,
            "auto_rate": round(linked / total * 100, 1) if total > 0 else 0
        })
    
    # Reverse to chronological order
    daily_metrics.reverse()
    
    return {"daily_metrics": daily_metrics}

# ==================== ENHANCED DASHBOARD ====================

@api_router.get("/dashboard/email-stats")
async def get_email_stats():
    """Get email processing statistics."""
    total_email = await db.hub_documents.count_documents({"source": "email"})
    needs_review = await db.hub_documents.count_documents({"source": "email", "status": "NeedsReview"})
    auto_linked = await db.hub_documents.count_documents({"source": "email", "status": "LinkedToBC"})
    stored_sp = await db.hub_documents.count_documents({"source": "email", "status": "StoredInSP"})
    
    # Get by job type
    by_job_type = {}
    for jt in DEFAULT_JOB_TYPES.keys():
        count = await db.hub_documents.count_documents({"source": "email", "suggested_job_type": jt})
        if count > 0:
            by_job_type[jt] = count
    
    # Recent email documents
    recent = await db.hub_documents.find(
        {"source": "email"},
        {"_id": 0}
    ).sort("created_utc", -1).limit(10).to_list(10)
    
    return {
        "total_email_documents": total_email,
        "needs_review": needs_review,
        "auto_linked": auto_linked,
        "stored_sp": stored_sp,
        "by_job_type": by_job_type,
        "recent": recent
    }

# ==================== PHASE 6: SHADOW MODE INSTRUMENTATION ====================

@api_router.get("/metrics/match-score-distribution")
async def get_match_score_distribution(
    from_date: str = None,
    to_date: str = None
):
    """
    Get match score distribution histogram for Phase 6 Shadow Mode analysis.
    
    This is the cornerstone metric that tells you whether 0.92 threshold is conservative or tight.
    
    Buckets:
    - 0.95-1.00: Very high confidence (ideal candidates for draft creation)
    - 0.92-0.95: High confidence (meets draft threshold)
    - 0.88-0.92: Near threshold (watch zone)
    - <0.88: Low confidence (not eligible)
    
    Args:
        from_date: Start date (YYYY-MM-DD), defaults to 14 days ago
        to_date: End date (YYYY-MM-DD), defaults to today
    """
    # Default to last 14 days
    if not to_date:
        to_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if not from_date:
        from_date = (datetime.now(timezone.utc) - timedelta(days=14)).strftime('%Y-%m-%d')
    
    query = {
        "created_utc": {
            "$gte": from_date,
            "$lte": to_date + "T23:59:59"
        },
        "match_score": {"$exists": True, "$ne": None}
    }
    
    # Get all documents with match scores in range
    docs = await db.hub_documents.find(
        query,
        {"match_score": 1, "match_method": 1, "status": 1, "_id": 0}
    ).to_list(10000)
    
    # Initialize buckets
    buckets = {
        "0.95_1.00": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "0.92_0.95": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "0.88_0.92": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0},
        "lt_0.88": {"count": 0, "by_method": {}, "linked": 0, "needs_review": 0}
    }
    
    total_docs = len(docs)
    
    for doc in docs:
        score = doc.get("match_score", 0) or 0
        method = doc.get("match_method", "none")
        status = doc.get("status", "Unknown")
        
        # Determine bucket
        if score >= 0.95:
            bucket_key = "0.95_1.00"
        elif score >= 0.92:
            bucket_key = "0.92_0.95"
        elif score >= 0.88:
            bucket_key = "0.88_0.92"
        else:
            bucket_key = "lt_0.88"
        
        buckets[bucket_key]["count"] += 1
        
        # Track method breakdown within bucket
        if method not in buckets[bucket_key]["by_method"]:
            buckets[bucket_key]["by_method"][method] = 0
        buckets[bucket_key]["by_method"][method] += 1
        
        # Track outcome within bucket
        if status == "LinkedToBC":
            buckets[bucket_key]["linked"] += 1
        elif status == "NeedsReview":
            buckets[bucket_key]["needs_review"] += 1
    
    # Calculate high-confidence eligible (>= 0.92)
    high_confidence_count = buckets["0.95_1.00"]["count"] + buckets["0.92_0.95"]["count"]
    high_confidence_pct = round((high_confidence_count / total_docs * 100) if total_docs > 0 else 0, 1)
    
    # Calculate threshold eligibility
    threshold_eligible = high_confidence_count
    near_threshold = buckets["0.88_0.92"]["count"]
    below_threshold = buckets["lt_0.88"]["count"]
    
    # Generate interpretation
    if high_confidence_pct >= 80:
        interpretation = f"Excellent: {high_confidence_pct}% of documents are above 0.92 threshold. Your threshold is conservative and safe for production."
    elif high_confidence_pct >= 60:
        interpretation = f"Good: {high_confidence_pct}% of documents are above 0.92 threshold. Consider monitoring the {near_threshold} documents in the 0.88-0.92 watch zone."
    elif high_confidence_pct >= 40:
        interpretation = f"Moderate: {high_confidence_pct}% of documents are above 0.92 threshold. Investigate the {below_threshold + near_threshold} documents below threshold before enabling draft creation."
    else:
        interpretation = f"Caution: Only {high_confidence_pct}% of documents are above 0.92 threshold. Review vendor data hygiene and alias coverage before enabling draft creation."
    
    return {
        "period": {
            "from_date": from_date,
            "to_date": to_date
        },
        "total_documents": total_docs,
        "buckets": buckets,
        "summary": {
            "high_confidence_eligible": high_confidence_count,
            "high_confidence_pct": high_confidence_pct,
            "near_threshold": near_threshold,
            "below_threshold": below_threshold,
            "interpretation": interpretation
        },
        "threshold_analysis": {
            "current_threshold": 0.92,
            "above_threshold_count": threshold_eligible,
            "above_threshold_pct": high_confidence_pct,
            "near_threshold_count": near_threshold,
            "near_threshold_pct": round((near_threshold / total_docs * 100) if total_docs > 0 else 0, 1)
        }
    }


@api_router.get("/metrics/alias-exceptions")
async def get_alias_exception_metrics(days: int = 14):
    """
    Enhanced alias exception tracking for Phase 6.
    
    This is the second key signal that tells you:
    - Data hygiene ROI is real
    - Alias engine is compounding over time
    
    Returns:
    - Total alias matches vs exceptions
    - Alias exception rate trend
    - Top 10 vendors by alias exceptions
    - Top 10 vendors by alias contribution
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    # Get all documents with match data
    docs = await db.hub_documents.find(
        query,
        {"match_method": 1, "status": 1, "extracted_fields.vendor": 1, "_id": 0}
    ).to_list(10000)
    
    # Calculate overall alias metrics
    alias_matches_total = 0
    alias_matches_success = 0  # LinkedToBC
    alias_matches_needs_review = 0  # NeedsReview (exceptions)
    
    # Vendor-level tracking
    vendor_alias_stats = {}
    
    for doc in docs:
        method = doc.get("match_method", "none")
        status = doc.get("status", "Unknown")
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        
        # Initialize vendor if not seen
        if vendor not in vendor_alias_stats:
            vendor_alias_stats[vendor] = {
                "total_docs": 0,
                "alias_matches": 0,
                "alias_success": 0,
                "alias_exceptions": 0,
                "non_alias_linked": 0
            }
        
        vendor_alias_stats[vendor]["total_docs"] += 1
        
        if method == "alias":
            alias_matches_total += 1
            vendor_alias_stats[vendor]["alias_matches"] += 1
            
            if status == "LinkedToBC":
                alias_matches_success += 1
                vendor_alias_stats[vendor]["alias_success"] += 1
            elif status == "NeedsReview":
                alias_matches_needs_review += 1
                vendor_alias_stats[vendor]["alias_exceptions"] += 1
        elif status == "LinkedToBC":
            vendor_alias_stats[vendor]["non_alias_linked"] += 1
    
    # Calculate alias exception rate
    alias_exception_rate = round(
        (alias_matches_needs_review / alias_matches_total * 100) if alias_matches_total > 0 else 0, 1
    )
    
    # Top 10 vendors by alias exceptions
    top_exception_vendors = sorted(
        [{"vendor": v, **stats} for v, stats in vendor_alias_stats.items() if stats["alias_exceptions"] > 0],
        key=lambda x: x["alias_exceptions"],
        reverse=True
    )[:10]
    
    # Top 10 vendors by alias contribution (alias drives 60%+ of their automation)
    # Calculate alias contribution % per vendor
    for vendor, stats in vendor_alias_stats.items():
        total_linked = stats["alias_success"] + stats["non_alias_linked"]
        stats["alias_contribution_pct"] = round(
            (stats["alias_success"] / total_linked * 100) if total_linked > 0 else 0, 1
        )
    
    high_alias_contribution_vendors = sorted(
        [{"vendor": v, **stats} for v, stats in vendor_alias_stats.items() 
         if stats["alias_contribution_pct"] >= 60 and stats["alias_matches"] >= 2],
        key=lambda x: x["alias_contribution_pct"],
        reverse=True
    )[:10]
    
    # Daily trend (last 7 days)
    daily_alias_trend = []
    for i in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime('%Y-%m-%d')
        day_query = {
            "created_utc": {"$gte": day, "$lt": day + "T23:59:59"},
            "match_method": "alias"
        }
        day_total = await db.hub_documents.count_documents(day_query)
        day_success = await db.hub_documents.count_documents({**day_query, "status": "LinkedToBC"})
        day_exception = await db.hub_documents.count_documents({**day_query, "status": "NeedsReview"})
        
        daily_alias_trend.append({
            "date": day,
            "total": day_total,
            "success": day_success,
            "exceptions": day_exception,
            "exception_rate": round((day_exception / day_total * 100) if day_total > 0 else 0, 1)
        })
    
    # Reverse to show oldest first
    daily_alias_trend.reverse()
    
    return {
        "period_days": days,
        "alias_totals": {
            "alias_matches_total": alias_matches_total,
            "alias_matches_success": alias_matches_success,
            "alias_matches_needs_review": alias_matches_needs_review,
            "alias_exception_rate": alias_exception_rate
        },
        "interpretation": {
            "status": "healthy" if alias_exception_rate < 10 else ("watch" if alias_exception_rate < 25 else "attention"),
            "message": f"Alias exception rate is {alias_exception_rate}%. " + (
                "Alias engine is performing well." if alias_exception_rate < 10 else
                "Monitor vendor data for inconsistencies." if alias_exception_rate < 25 else
                "High alias exceptions suggest alias data hygiene issues."
            )
        },
        "top_exception_vendors": top_exception_vendors,
        "high_alias_contribution_vendors": high_alias_contribution_vendors,
        "daily_trend": daily_alias_trend
    }


@api_router.get("/metrics/vendor-stability")
async def get_vendor_stability_analysis(days: int = 14):
    """
    Vendor friction stability analysis for Phase 6.
    
    This informs Vendor Threshold Overrides (future architecture).
    
    Identifies:
    - Vendors consistently under 50% automation
    - Vendors with high match scores but high exception rates (process issue)
    - Vendors with consistently high confidence (candidates for lower thresholds)
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    # Get all documents
    docs = await db.hub_documents.find(
        query,
        {"extracted_fields.vendor": 1, "match_score": 1, "status": 1, "ai_confidence": 1, "_id": 0}
    ).to_list(10000)
    
    # Vendor-level analysis
    vendor_stats = {}
    
    for doc in docs:
        vendor = doc.get("extracted_fields", {}).get("vendor", "Unknown")
        if vendor == "Unknown":
            continue
            
        if vendor not in vendor_stats:
            vendor_stats[vendor] = {
                "total_docs": 0,
                "linked": 0,
                "needs_review": 0,
                "match_scores": [],
                "confidence_scores": []
            }
        
        vendor_stats[vendor]["total_docs"] += 1
        
        if doc.get("status") == "LinkedToBC":
            vendor_stats[vendor]["linked"] += 1
        elif doc.get("status") == "NeedsReview":
            vendor_stats[vendor]["needs_review"] += 1
        
        if doc.get("match_score"):
            vendor_stats[vendor]["match_scores"].append(doc["match_score"])
        if doc.get("ai_confidence"):
            vendor_stats[vendor]["confidence_scores"].append(doc["ai_confidence"])
    
    # Calculate aggregates per vendor
    analyzed_vendors = []
    
    for vendor, stats in vendor_stats.items():
        if stats["total_docs"] < 2:  # Need at least 2 docs for meaningful analysis
            continue
        
        automation_rate = round((stats["linked"] / stats["total_docs"] * 100), 1)
        exception_rate = round((stats["needs_review"] / stats["total_docs"] * 100), 1)
        avg_match_score = round(sum(stats["match_scores"]) / len(stats["match_scores"]), 3) if stats["match_scores"] else 0
        avg_confidence = round(sum(stats["confidence_scores"]) / len(stats["confidence_scores"]), 3) if stats["confidence_scores"] else 0
        
        analyzed_vendors.append({
            "vendor": vendor,
            "total_docs": stats["total_docs"],
            "automation_rate": automation_rate,
            "exception_rate": exception_rate,
            "avg_match_score": avg_match_score,
            "avg_confidence": avg_confidence,
            "min_match_score": min(stats["match_scores"]) if stats["match_scores"] else 0,
            "max_match_score": max(stats["match_scores"]) if stats["match_scores"] else 0,
        })
    
    # Categorize vendors
    low_automation_vendors = [v for v in analyzed_vendors if v["automation_rate"] < 50]
    high_score_high_exception = [v for v in analyzed_vendors 
                                  if v["avg_match_score"] >= 0.85 and v["exception_rate"] >= 40]
    consistently_high_confidence = [v for v in analyzed_vendors 
                                     if v["avg_match_score"] >= 0.92 and v["min_match_score"] >= 0.88 
                                     and v["automation_rate"] >= 80]
    
    # Sort by impact
    low_automation_vendors.sort(key=lambda x: x["total_docs"], reverse=True)
    high_score_high_exception.sort(key=lambda x: x["exception_rate"], reverse=True)
    consistently_high_confidence.sort(key=lambda x: x["avg_match_score"], reverse=True)
    
    return {
        "period_days": days,
        "total_vendors_analyzed": len(analyzed_vendors),
        "categories": {
            "low_automation": {
                "description": "Vendors consistently under 50% automation - need attention",
                "count": len(low_automation_vendors),
                "vendors": low_automation_vendors[:10]
            },
            "high_score_high_exception": {
                "description": "High match scores but high exceptions - likely process or data issue",
                "count": len(high_score_high_exception),
                "vendors": high_score_high_exception[:10]
            },
            "consistently_high_confidence": {
                "description": "Candidates for threshold override (consistent high scores)",
                "count": len(consistently_high_confidence),
                "vendors": consistently_high_confidence[:10]
            }
        },
        "threshold_override_candidates": [
            {
                "vendor": v["vendor"],
                "recommended_threshold": max(0.88, v["min_match_score"] - 0.02),
                "avg_match_score": v["avg_match_score"],
                "min_match_score": v["min_match_score"],
                "automation_rate": v["automation_rate"]
            }
            for v in consistently_high_confidence[:5]
        ]
    }


class ShadowModeConfig(BaseModel):
    """Configuration for shadow mode tracking."""
    shadow_mode_started_at: Optional[str] = None
    shadow_mode_notes: Optional[str] = None


@api_router.get("/settings/shadow-mode")
async def get_shadow_mode_status():
    """
    Get shadow mode status for Phase 6 monitoring.
    
    Returns feature flag status, shadow mode duration, and quick health indicators.
    """
    # Get shadow mode config from settings
    settings = await db.hub_settings.find_one({"type": "shadow_mode"}, {"_id": 0})
    
    if not settings:
        # Initialize shadow mode settings if not exists
        settings = {
            "type": "shadow_mode",
            "shadow_mode_started_at": None,
            "shadow_mode_notes": "",
            "created_utc": datetime.now(timezone.utc).isoformat()
        }
    
    # Calculate days in shadow mode
    days_in_shadow_mode = 0
    if settings.get("shadow_mode_started_at"):
        start_date = datetime.fromisoformat(settings["shadow_mode_started_at"].replace('Z', '+00:00'))
        days_in_shadow_mode = (datetime.now(timezone.utc) - start_date).days
    
    # Get quick health indicators (last 7 days)
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    query_7d = {"created_utc": {"$gte": cutoff_7d}}
    
    # High confidence docs percentage
    docs_with_score = await db.hub_documents.find(
        {**query_7d, "match_score": {"$exists": True, "$ne": None}},
        {"match_score": 1, "_id": 0}
    ).to_list(10000)
    
    high_conf_count = sum(1 for d in docs_with_score if (d.get("match_score") or 0) >= 0.92)
    high_conf_pct = round((high_conf_count / len(docs_with_score) * 100) if docs_with_score else 0, 1)
    
    # Alias exception rate (last 7 days)
    alias_total_7d = await db.hub_documents.count_documents({**query_7d, "match_method": "alias"})
    alias_exceptions_7d = await db.hub_documents.count_documents({
        **query_7d, "match_method": "alias", "status": "NeedsReview"
    })
    alias_exception_rate_7d = round((alias_exceptions_7d / alias_total_7d * 100) if alias_total_7d > 0 else 0, 1)
    
    # Top friction vendor this week
    top_friction_vendor = None
    vendor_friction = await db.hub_documents.aggregate([
        {"$match": {**query_7d, "status": "NeedsReview"}},
        {"$group": {"_id": "$extracted_fields.vendor", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1}
    ]).to_list(1)
    
    if vendor_friction:
        top_friction_vendor = {
            "vendor": vendor_friction[0]["_id"],
            "exception_count": vendor_friction[0]["count"]
        }
    
    return {
        "feature_flags": {
            "CREATE_DRAFT_HEADER": ENABLE_CREATE_DRAFT_HEADER,
            "DEMO_MODE": DEMO_MODE
        },
        "shadow_mode": {
            "started_at": settings.get("shadow_mode_started_at"),
            "days_running": days_in_shadow_mode,
            "notes": settings.get("shadow_mode_notes", ""),
            "is_active": settings.get("shadow_mode_started_at") is not None and not ENABLE_CREATE_DRAFT_HEADER
        },
        "health_indicators_7d": {
            "high_confidence_docs_pct": high_conf_pct,
            "alias_exception_rate": alias_exception_rate_7d,
            "top_friction_vendor": top_friction_vendor,
            "total_docs_processed": len(docs_with_score)
        },
        # Phase C1: Email polling health (passive tap - read-only)
        "email_polling": {
            "enabled": EMAIL_POLLING_ENABLED,
            "mode": "passive_tap",
            "user": EMAIL_POLLING_USER or "(not configured)",
            "interval_minutes": EMAIL_POLLING_INTERVAL_MINUTES,
            "permissions": "Mail.Read (read-only)"
        },
        "readiness_assessment": {
            "high_confidence_ok": high_conf_pct >= 60,
            "alias_exception_ok": alias_exception_rate_7d < 15,
            "sufficient_data": len(docs_with_score) >= 20,
            "recommended_action": (
                "Ready for controlled draft enablement" 
                if high_conf_pct >= 60 and alias_exception_rate_7d < 15 and len(docs_with_score) >= 20
                else "Continue monitoring - need more data or better metrics"
            )
        },
        "draft_creation_thresholds": DRAFT_CREATION_CONFIG
    }


@api_router.post("/settings/shadow-mode")
async def update_shadow_mode_settings(config: ShadowModeConfig):
    """
    Update shadow mode configuration.
    
    Use this to:
    - Set shadow_mode_started_at when deploying to production
    - Add notes about deployments, vendor changes, alias imports
    """
    update_data = {}
    
    if config.shadow_mode_started_at is not None:
        update_data["shadow_mode_started_at"] = config.shadow_mode_started_at
    
    if config.shadow_mode_notes is not None:
        update_data["shadow_mode_notes"] = config.shadow_mode_notes
    
    if update_data:
        update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
        
        await db.hub_settings.update_one(
            {"type": "shadow_mode"},
            {"$set": update_data},
            upsert=True
        )
    
    return await get_shadow_mode_status()


@api_router.get("/reports/shadow-mode-performance")
async def get_shadow_mode_performance_report(days: int = 14):
    """
    Generate comprehensive Shadow Mode Performance report for ELT.
    
    This endpoint produces the complete analysis needed to decide
    whether to enable draft creation.
    
    Returns exportable JSON structure for executive presentation.
    """
    # Gather all metrics
    score_dist = await get_match_score_distribution()
    alias_metrics = await get_alias_exception_metrics(days=days)
    vendor_stability = await get_vendor_stability_analysis(days=days)
    shadow_status = await get_shadow_mode_status()
    automation_metrics = await _get_automation_metrics_internal(days=days)
    
    # Calculate production readiness score (0-100)
    # LOCKED FORMULA - Phase 7 explicit gates (do not modify without business justification)
    # Factor weights: High Conf (35) + Alias Exception (20) + Stable Vendors (25) + Data Volume (20) = 100
    readiness_factors = []
    
    # Factor 1: % docs with match_score >= 0.92 (weight: 35)
    # Target: 60% of documents should be high-confidence
    high_conf_pct = score_dist["summary"]["high_confidence_pct"]
    high_conf_score = min(35, (high_conf_pct / 60) * 35) if high_conf_pct < 60 else 35
    readiness_factors.append({
        "factor": "High Confidence Documents (≥0.92)",
        "value": high_conf_pct,
        "target": "≥60%",
        "score": round(high_conf_score, 1),
        "max_score": 35,
        "gate_passed": high_conf_pct >= 60
    })
    
    # Factor 2: Alias exception rate < 5% (weight: 20)
    # Full score if < 5%, proportional reduction otherwise
    alias_exc_rate = alias_metrics["alias_totals"]["alias_exception_rate"]
    if alias_exc_rate < 5:
        alias_score = 20
    elif alias_exc_rate < 10:
        alias_score = 15  # Partial credit
    elif alias_exc_rate < 20:
        alias_score = 10  # Minimal credit
    else:
        alias_score = 0
    readiness_factors.append({
        "factor": "Alias Exception Rate",
        "value": alias_exc_rate,
        "target": "<5%",
        "score": alias_score,
        "max_score": 20,
        "gate_passed": alias_exc_rate < 5
    })
    
    # Factor 3: ≥ 3 vendors stable (consistently high match scores) (weight: 25)
    # A vendor is "stable" if avg_match_score >= 0.94 and min_match_score >= 0.88
    stable_vendors_count = vendor_stability["categories"]["consistently_high_confidence"]["count"]
    if stable_vendors_count >= 3:
        vendor_score = 25
    elif stable_vendors_count >= 2:
        vendor_score = 18
    elif stable_vendors_count >= 1:
        vendor_score = 10
    else:
        vendor_score = 0
    readiness_factors.append({
        "factor": "Stable Vendors (≥0.94 avg score)",
        "value": stable_vendors_count,
        "target": "≥3",
        "score": vendor_score,
        "max_score": 25,
        "gate_passed": stable_vendors_count >= 3
    })
    
    # Factor 4: ≥ 100 docs observed (weight: 20)
    # Need meaningful volume for statistical confidence
    total_docs = automation_metrics["total_documents"]
    if total_docs >= 100:
        volume_score = 20
    elif total_docs >= 50:
        volume_score = round((total_docs / 100) * 20, 1)
    else:
        volume_score = round((total_docs / 100) * 10, 1)  # Slower ramp-up below 50
    readiness_factors.append({
        "factor": "Data Volume (Observed Docs)",
        "value": total_docs,
        "target": "≥100",
        "score": round(volume_score, 1),
        "max_score": 20,
        "gate_passed": total_docs >= 100
    })
    
    total_readiness_score = round(sum(f["score"] for f in readiness_factors), 1)
    gates_passed = sum(1 for f in readiness_factors if f["gate_passed"])
    
    # Determine recommendation (all 4 gates must pass for full readiness)
    if total_readiness_score >= 80 and gates_passed == 4:
        recommendation = "READY: All gates passed. System validated for controlled vendor enablement."
        recommendation_detail = "Enable CREATE_DRAFT_HEADER for 3 stable vendors (exact_no/exact_name/normalized only)."
    elif total_readiness_score >= 80:
        recommendation = "NEAR READY: Score high but not all gates passed."
        recommendation_detail = f"Review failing gates ({4 - gates_passed} of 4 not passed). Address before enablement."
    elif total_readiness_score >= 60:
        recommendation = "APPROACHING: System is close to production readiness."
        recommendation_detail = "Continue monitoring for 1-2 more weeks. Address failing gates."
    elif total_readiness_score >= 40:
        recommendation = "BUILDING: System needs more time and data."
        recommendation_detail = "Focus on improving alias coverage and vendor data hygiene."
    else:
        recommendation = "EARLY: System is in early shadow mode."
        recommendation_detail = "Continue collecting data. Review vendor friction and alias exceptions."
    
    return {
        "report_title": "Shadow Mode Performance Analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_period_days": days,
        "executive_summary": {
            "readiness_score": total_readiness_score,
            "readiness_max": 100,
            "gates_passed": gates_passed,
            "gates_total": 4,
            "recommendation": recommendation,
            "recommendation_detail": recommendation_detail,
            "shadow_mode_days": shadow_status["shadow_mode"]["days_running"],
            "total_documents_processed": total_docs,
            "high_confidence_pct": high_conf_pct
        },
        "readiness_factors": readiness_factors,
        "match_score_analysis": {
            "buckets": score_dist["buckets"],
            "summary": score_dist["summary"],
            "threshold_analysis": score_dist["threshold_analysis"]
        },
        "alias_engine_performance": {
            "totals": alias_metrics["alias_totals"],
            "interpretation": alias_metrics["interpretation"],
            "daily_trend": alias_metrics["daily_trend"],
            "top_exception_vendors": alias_metrics["top_exception_vendors"][:5],
            "high_contribution_vendors": alias_metrics["high_alias_contribution_vendors"][:5]
        },
        "vendor_friction_analysis": {
            "total_vendors": vendor_stability["total_vendors_analyzed"],
            "low_automation_count": vendor_stability["categories"]["low_automation"]["count"],
            "process_issue_count": vendor_stability["categories"]["high_score_high_exception"]["count"],
            "threshold_override_candidates": vendor_stability["threshold_override_candidates"]
        },
        "shadow_mode_status": shadow_status["shadow_mode"],
        "feature_flags": shadow_status["feature_flags"],
        "health_indicators": shadow_status["health_indicators_7d"],
        "next_steps": [
            "Review match score distribution for threshold confidence",
            "Address top friction vendors",
            "Consider creating aliases for high-exception vendors",
            "Monitor alias exception rate trend",
            "When readiness score >= 80, prepare for controlled enablement"
        ]
    }


@api_router.get("/metrics/extraction-quality")
async def get_extraction_quality_metrics(days: int = 7):
    """
    Phase 7 extraction quality metrics.
    
    Measures:
    - Field extraction completeness rates
    - Ready for draft candidate rate (Phase 7 Week 1)
    - Vendor name variation tracking
    - Canonical fields completeness
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "extracted_fields": 1, 
            "canonical_fields": 1,
            "validation_results.extraction_quality": 1,
            "validation_results.normalized_fields": 1,
            "ai_confidence": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "draft_candidate_score": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    total = len(docs)
    if total == 0:
        return {
            "period_days": days,
            "total_documents": 0,
            "extraction_rates": {},
            "ready_for_draft_rate": 0,
            "vendor_variations": []
        }
    
    # Track field extraction rates
    field_counts = {
        "vendor": 0,
        "invoice_number": 0,
        "amount": 0,
        "po_number": 0,
        "due_date": 0
    }
    
    ready_for_draft = 0
    ready_to_link = 0
    draft_candidates_count = 0  # Phase 7 Week 1: computed flag
    vendor_names = {}  # Track variations
    
    for doc in docs:
        fields = doc.get("extracted_fields", {}) or {}
        norm_fields = doc.get("validation_results", {}).get("normalized_fields", {}) or {}
        canonical = doc.get("canonical_fields", {}) or {}
        
        # Use canonical fields first, then normalized, then raw
        check_fields = canonical if canonical else (norm_fields if norm_fields else fields)
        
        for field in field_counts.keys():
            # Check multiple possible field names
            val = (check_fields.get(field) or 
                   check_fields.get(f"{field}_normalized") or
                   check_fields.get(f"{field}_clean") or
                   fields.get(field))
            if val:
                field_counts[field] += 1
        
        # Check ready for draft (extraction completeness - legacy calc)
        has_vendor = bool(check_fields.get("vendor") or check_fields.get("vendor_normalized") or fields.get("vendor"))
        has_invoice = bool(check_fields.get("invoice_number") or check_fields.get("invoice_number_clean") or fields.get("invoice_number"))
        has_amount = (check_fields.get("amount") is not None or 
                     check_fields.get("amount_float") is not None or
                     fields.get("amount") is not None)
        
        if has_vendor and has_invoice and has_amount:
            ready_for_draft += 1
        
        # Phase 7 Week 1: Count computed draft candidates
        if doc.get("draft_candidate"):
            draft_candidates_count += 1
        
        # Track vendor name variations
        vendor = fields.get("vendor", "").strip() if fields.get("vendor") else ""
        if vendor:
            normalized = normalize_vendor_name(vendor)
            if normalized not in vendor_names:
                vendor_names[normalized] = {"variations": set(), "count": 0}
            vendor_names[normalized]["variations"].add(vendor)
            vendor_names[normalized]["count"] += 1
    
    # Calculate rates
    extraction_rates = {k: round(v / total * 100, 1) for k, v in field_counts.items()}
    
    # Find vendors with multiple name variations
    vendor_variations = [
        {
            "normalized": norm,
            "variations": list(data["variations"]),
            "count": data["count"]
        }
        for norm, data in vendor_names.items()
        if len(data["variations"]) > 1
    ]
    vendor_variations.sort(key=lambda x: x["count"], reverse=True)
    
    # Identify stable vendors (candidates for Phase 8)
    stable_vendors = [
        {
            "normalized": norm,
            "count": data["count"],
            "variations": list(data["variations"])
        }
        for norm, data in vendor_names.items()
        if data["count"] >= 5  # At least 5 docs
    ]
    stable_vendors.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "period_days": days,
        "total_documents": total,
        "extraction_rates": extraction_rates,
        "readiness_metrics": {
            "ready_for_draft": {
                "count": ready_for_draft,
                "rate": round(ready_for_draft / total * 100, 1),
                "description": "Docs with vendor + invoice_number + amount extracted"
            },
            "draft_candidates": {
                "count": draft_candidates_count,
                "rate": round(draft_candidates_count / total * 100, 1),
                "description": "Phase 7: Computed draft_candidate flag (AP + all fields + confidence >= 0.92)"
            },
            "ready_to_link": {
                "count": ready_to_link,
                "rate": round(ready_to_link / total * 100, 1) if total > 0 else 0,
                "description": "Docs matched to existing BC record (match_score >= 0.80)"
            }
        },
        "completeness_summary": {
            "all_required_fields": ready_for_draft,
            "missing_vendor": total - field_counts["vendor"],
            "missing_invoice_number": total - field_counts["invoice_number"],
            "missing_amount": total - field_counts["amount"]
        },
        "vendor_variations": vendor_variations[:20],
        "stable_vendors": stable_vendors[:10],
        "phase_7_recommendation": "Draft Candidates is the primary indicator for Phase 8 readiness. Lead with extraction completeness + confidence."
    }


@api_router.get("/metrics/extraction-misses")
async def get_extraction_misses(
    field: str = Query("vendor", description="Field to check: vendor, invoice_number, amount"),
    days: int = Query(7),
    limit: int = Query(100)
):
    """
    Phase 7: Diagnostic endpoint for documents missing specific fields.
    
    Filter AP_Invoice documents from the last N days by the given missing field:
    - field=vendor → vendor_normalized missing
    - field=invoice_number → invoice_number_clean missing
    - field=amount → amount_float missing
    
    Returns data needed for debugging extraction during observation mode.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Map field parameter to actual document field
    field_map = {
        "vendor": "vendor_normalized",
        "invoice_number": "invoice_number_clean",
        "amount": "amount_float"
    }
    
    actual_field = field_map.get(field, f"extracted_fields.{field}")
    
    # Build query for AP_Invoice documents missing the specified field
    query = {
        "created_utc": {"$gte": cutoff},
        "document_type": {"$in": ["AP_Invoice", "AP Invoice"]},
        "$or": [
            {actual_field: {"$exists": False}},
            {actual_field: None},
            {actual_field: ""}
        ]
    }
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "file_name": 1,
            "source": 1,
            "document_type": 1,
            "status": 1,
            "ai_confidence": 1,
            "vendor_raw": 1,
            "vendor_normalized": 1,
            "invoice_number_raw": 1,
            "invoice_number_clean": 1,
            "amount_raw": 1,
            "amount_float": 1,
            "due_date_raw": 1,
            "po_number_raw": 1,
            "email_sender": 1,
            "email_subject": 1,
            "created_utc": 1,
            "_id": 0
        }
    ).sort("created_utc", -1).to_list(limit)
    
    results = []
    for d in docs:
        # Build text snippet from email subject
        text_snippet = ""
        if d.get("email_subject"):
            text_snippet = d["email_subject"][:500]
        elif d.get("email_sender"):
            text_snippet = f"From: {d['email_sender']}"
        
        results.append({
            "document_id": d.get("id"),
            "file_name": d.get("file_name"),
            "document_type": d.get("document_type"),
            "status": d.get("status"),
            "vendor_raw": d.get("vendor_raw"),
            "invoice_number_raw": d.get("invoice_number_raw"),
            "amount_raw": d.get("amount_raw"),
            "due_date_raw": d.get("due_date_raw"),
            "po_number_raw": d.get("po_number_raw"),
            "ai_confidence": d.get("ai_confidence"),
            "first_500_chars_text": text_snippet,
            "created_utc": d.get("created_utc")
        })
    
    return {
        "field": field,
        "period_days": days,
        "missing_count": len(results),
        "documents": results,
        "analysis_hints": [
            f"Review these {len(results)} AP_Invoice documents to understand why '{field}' wasn't extracted",
            "Common causes: unusual document format, scanned PDFs, non-standard layouts",
            "Check ai_confidence - low confidence may indicate OCR quality issues"
        ]
    }


@api_router.get("/metrics/stable-vendors")
async def get_stable_vendors(
    min_count: int = Query(5, description="Minimum document count to be stable"),
    min_completeness: float = Query(0.85, description="Minimum field completeness rate (0-1)"),
    max_variants: int = Query(3, description="Maximum allowed name variations"),
    days: int = Query(30)
):
    """
    Phase 7 Week 1: Stable Vendor metric endpoint.
    
    Stable Vendor Criteria (Phase 7 metric only):
    - count >= min_count (default 5)
    - required field completeness >= min_completeness (default 85%)
    - alias variance <= max_variants (default 3 variants)
    - no conflicting invoice numbers
    
    This does NOT enable anything - it only reports candidates for Phase 8.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "extracted_fields": 1,
            "canonical_fields": 1,
            "ai_confidence": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    # Group by normalized vendor
    vendor_data = {}
    
    for doc in docs:
        extracted = doc.get("extracted_fields", {}) or {}
        canonical = doc.get("canonical_fields", {}) or {}
        
        # Get vendor - prefer canonical normalized
        vendor_normalized = canonical.get("vendor_normalized") or ""
        if not vendor_normalized and extracted.get("vendor"):
            vendor_normalized = normalize_vendor_name(extracted.get("vendor", ""))
        
        if not vendor_normalized:
            continue
        
        if vendor_normalized not in vendor_data:
            vendor_data[vendor_normalized] = {
                "variations": set(),
                "count": 0,
                "has_vendor": 0,
                "has_invoice_number": 0,
                "has_amount": 0,
                "invoice_numbers": set(),
                "draft_candidates": 0,
                "high_confidence_count": 0  # ai_confidence >= 0.92
            }
        
        vd = vendor_data[vendor_normalized]
        vd["count"] += 1
        
        # Track variations
        raw_vendor = extracted.get("vendor", "")
        if raw_vendor:
            vd["variations"].add(raw_vendor)
        
        # Field completeness
        if extracted.get("vendor") or canonical.get("vendor_normalized"):
            vd["has_vendor"] += 1
        if extracted.get("invoice_number") or canonical.get("invoice_number_clean"):
            vd["has_invoice_number"] += 1
            inv_num = canonical.get("invoice_number_clean") or extracted.get("invoice_number", "")
            if inv_num:
                vd["invoice_numbers"].add(str(inv_num))
        if extracted.get("amount") is not None or canonical.get("amount_float") is not None:
            vd["has_amount"] += 1
        
        # Draft candidate tracking
        if doc.get("draft_candidate"):
            vd["draft_candidates"] += 1
        
        # High confidence tracking
        confidence = doc.get("ai_confidence", 0)
        if confidence and confidence >= 0.92:
            vd["high_confidence_count"] += 1
    
    # Evaluate stability
    stable_vendors = []
    unstable_vendors = []
    
    for vendor_name, data in vendor_data.items():
        count = data["count"]
        
        # Calculate completeness
        completeness_rate = 0.0
        if count > 0:
            completeness_rate = (
                (data["has_vendor"] + data["has_invoice_number"] + data["has_amount"]) / 
                (count * 3)
            )
        
        # Check for duplicate/conflicting invoice numbers
        has_conflicts = len(data["invoice_numbers"]) < count * 0.5 if count > 2 else False
        
        vendor_record = {
            "vendor_normalized": vendor_name,
            "count": count,
            "variations": list(data["variations"]),
            "variation_count": len(data["variations"]),
            "completeness_rate": round(completeness_rate, 3),
            "field_breakdown": {
                "vendor": data["has_vendor"],
                "invoice_number": data["has_invoice_number"],
                "amount": data["has_amount"]
            },
            "draft_candidates": data["draft_candidates"],
            "draft_candidate_rate": round(data["draft_candidates"] / count, 3) if count > 0 else 0,
            "high_confidence_count": data["high_confidence_count"],
            "high_confidence_rate": round(data["high_confidence_count"] / count, 3) if count > 0 else 0,
            "unique_invoices": len(data["invoice_numbers"]),
            "potential_conflicts": has_conflicts
        }
        
        # Check stability criteria
        is_stable = (
            count >= min_count and
            completeness_rate >= min_completeness and
            len(data["variations"]) <= max_variants and
            not has_conflicts
        )
        
        vendor_record["is_stable"] = is_stable
        
        if is_stable:
            vendor_record["stability_reasons"] = ["Meets all criteria"]
            stable_vendors.append(vendor_record)
        else:
            reasons = []
            if count < min_count:
                reasons.append(f"count {count} < {min_count}")
            if completeness_rate < min_completeness:
                reasons.append(f"completeness {completeness_rate:.1%} < {min_completeness:.0%}")
            if len(data["variations"]) > max_variants:
                reasons.append(f"variations {len(data['variations'])} > {max_variants}")
            if has_conflicts:
                reasons.append("potential invoice conflicts")
            vendor_record["stability_reasons"] = reasons
            unstable_vendors.append(vendor_record)
    
    # Sort by count descending
    stable_vendors.sort(key=lambda x: x["count"], reverse=True)
    unstable_vendors.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "period_days": days,
        "criteria": {
            "min_count": min_count,
            "min_completeness": min_completeness,
            "max_variants": max_variants
        },
        "summary": {
            "total_vendors": len(vendor_data),
            "stable_vendors": len(stable_vendors),
            "unstable_vendors": len(unstable_vendors),
            "stable_rate": round(len(stable_vendors) / len(vendor_data), 3) if vendor_data else 0
        },
        "stable_vendors": stable_vendors[:20],
        "near_stable_vendors": [
            v for v in unstable_vendors 
            if v["count"] >= min_count - 2 and v["completeness_rate"] >= min_completeness - 0.1
        ][:10],
        "phase_8_note": "Stable vendors are candidates for controlled draft enablement in Phase 8. This endpoint is metric-only and does not enable any automation."
    }


@api_router.get("/metrics/draft-candidates")
async def get_draft_candidate_metrics(days: int = Query(7)):
    """
    Phase 7 Week 1: Draft Candidate metrics endpoint.
    
    Shows distribution of draft candidate flags computed at ingestion.
    This is NON-OPERATIONAL - it only reports what WOULD be ready for draft creation.
    
    Dashboard can show:
    - ReadyForDraftCandidate: X%
    - ReadyToLink: Y%  
    - NeedsHumanReview: Z%
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = {"created_utc": {"$gte": cutoff}}
    
    docs = await db.hub_documents.find(
        query,
        {
            "id": 1,
            "document_type": 1,
            "draft_candidate": 1,
            "draft_candidate_score": 1,
            "draft_candidate_reason": 1,
            "ai_confidence": 1,
            "status": 1,
            "match_method": 1,
            "match_score": 1,
            "_id": 0
        }
    ).to_list(10000)
    
    total = len(docs)
    if total == 0:
        return {
            "period_days": days,
            "total_documents": 0,
            "draft_candidate_rate": 0,
            "readiness_breakdown": {}
        }
    
    # Count draft candidates
    draft_candidates = sum(1 for d in docs if d.get("draft_candidate"))
    
    # Count by score bucket
    score_buckets = {
        "100_ready": 0,      # Perfect score, draft ready
        "75_needs_confidence": 0,   # Missing confidence only
        "50_needs_fields": 0,       # Missing 1-2 fields
        "25_not_ap": 0,             # Not AP_Invoice
        "0_missing_all": 0          # Multiple issues
    }
    
    # Count by missing reason
    missing_reasons = {
        "missing vendor": 0,
        "missing invoice_number": 0,
        "missing amount": 0,
        "low_confidence": 0,
        "wrong_doc_type": 0
    }
    
    # Count ready to link
    ready_to_link = 0
    needs_review = 0
    
    for doc in docs:
        score = doc.get("draft_candidate_score", 0)
        reasons = doc.get("draft_candidate_reason", [])
        status = doc.get("status", "")
        
        # Bucket by score
        if score == 100:
            score_buckets["100_ready"] += 1
        elif score >= 75:
            score_buckets["75_needs_confidence"] += 1
        elif score >= 50:
            score_buckets["50_needs_fields"] += 1
        elif score >= 25:
            score_buckets["25_not_ap"] += 1
        else:
            score_buckets["0_missing_all"] += 1
        
        # Track missing reasons
        for reason in reasons:
            if "vendor" in reason.lower():
                missing_reasons["missing vendor"] += 1
            if "invoice_number" in reason.lower():
                missing_reasons["missing invoice_number"] += 1
            if "amount" in reason.lower():
                missing_reasons["missing amount"] += 1
            if "confidence" in reason.lower():
                missing_reasons["low_confidence"] += 1
            if "document_type" in reason.lower() or "not AP" in reason:
                missing_reasons["wrong_doc_type"] += 1
        
        # Track status
        if status in ("ReadyToLink", "LinkedToBC"):
            ready_to_link += 1
        elif status == "NeedsReview":
            needs_review += 1
    
    return {
        "period_days": days,
        "total_documents": total,
        "draft_candidate_summary": {
            "draft_candidates": draft_candidates,
            "draft_candidate_rate": round(draft_candidates / total * 100, 1),
            "description": "Documents that WOULD be ready for draft creation if Phase 8 was enabled"
        },
        "readiness_breakdown": {
            "ReadyForDraftCandidate": round(draft_candidates / total * 100, 1),
            "ReadyToLink": round(ready_to_link / total * 100, 1),
            "NeedsHumanReview": round(needs_review / total * 100, 1),
            "Other": round((total - draft_candidates - ready_to_link - needs_review) / total * 100, 1)
        },
        "score_distribution": {
            k: {"count": v, "rate": round(v / total * 100, 1)} 
            for k, v in score_buckets.items()
        },
        "missing_field_analysis": missing_reasons,
        "phase_7_note": "This is observation-only. Draft creation is NOT enabled. Use this data to improve extraction quality."
    }


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
