from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, BackgroundTasks, Body
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

# Folder Routing Service (Accounting folder structure)
from services.folder_routing_service import (
    determine_folder_path, get_all_folder_paths, get_folder_structure_summary,
    FOLDER_STRUCTURE, VENDOR_FOLDER_MAPPING
)

# Auto-Clear Service (Square9/Zetadocs aligned)
from services.auto_clear_service import (
    evaluate_auto_clear, get_auto_clear_update, get_auto_clear_summary,
    AutoClearDecision, AUTO_CLEAR_CONFIG, get_threshold_for_type,
    update_threshold, get_auto_clear_config
)

# Spiro Vendor Matching
from services.spiro_vendor_matcher import (
    match_vendor_with_spiro, get_spiro_matcher, SpiroVendorMatcher
)

# Unified Vendor Matcher (ALL sources: Spiro, BC, SharePoint, Doc History)
from services.unified_vendor_matcher import (
    match_vendor_unified, get_unified_vendor_matcher, UnifiedVendorMatcher
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

# Event-Driven Workflow Services (Phase 1 & 2)
from services.event_service import (
    EventService, WorkflowEvent as WFEvent, EventStatus,
    set_event_service, get_event_service, initialize_event_indexes,
    emit_document_received, emit_classification_completed, emit_vendor_match,
    emit_bc_validation, emit_sharepoint_upload, emit_automation_decision
)
from services.derived_state_service import (
    DerivedStateService, ValidationState, WorkflowState, AutomationState,
    set_derived_state_service, get_derived_state_service, format_state_for_display
)

# AP Invoice Validation + BC Reference Resolution + Write Safety Guard
from services.ap_validation_service import (
    APValidationService, APValidationResult, APValidationState,
    validate_ap_invoice_sync
)
from services.bc_reference_resolver import (
    BCReferenceResolver, ReferenceResolutionResult, ReferenceType,
    get_reference_resolver
)
from services.bc_write_safety_guard import (
    BCWriteSafetyGuard, BC_WRITE_ENABLED, IS_PRODUCTION_ENVIRONMENT,
    get_write_guard, set_write_guard, check_bc_write_allowed
)
from services.reference_intelligence_service import (
    ReferenceIntelligenceService,
    get_reference_intelligence_service, set_reference_intelligence_service,
    extract_references_from_extracted_fields, extract_references_from_text,
    normalize_reference, get_search_strategy
)
from services.bc_reference_cache_service import (
    BCReferenceCacheService, get_cache_service, set_cache_service
)
from services.auto_resolution_service import (
    AutoResolutionService, get_auto_resolve_service, set_auto_resolve_service,
    is_eligible_for_auto_resolution, needs_resolution
)
from services.vendor_intelligence_service import (
    VendorIntelligenceService, get_vendor_intelligence_service, set_vendor_intelligence_service
)
from services.automation_rules_service import (
    AutomationRulesService, get_automation_rules_service, set_automation_rules_service
)
from services.freight_gl_routing_service import (
    FreightGLRoutingService, get_freight_gl_service, set_freight_gl_service
)
from services.label_correction_service import (
    LabelCorrectionService, get_label_correction_service, set_label_correction_service
)
from services.alert_pattern_service import (
    AlertPatternService, get_alert_pattern_service, set_alert_pattern_service
)
from services.vendor_extraction_profile_service import (
    VendorExtractionProfileService, get_vep_service, set_vep_service
)
from services.layout_fingerprint_service import (
    LayoutFingerprintService, get_layout_fingerprint_service, set_layout_fingerprint_service
)
from models.document_types import TransactionAction, DRAFT_CREATION_CONFIG, DEFAULT_JOB_TYPES

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Config
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
JWT_SECRET = os.environ.get('JWT_SECRET', 'gpi-hub-secret-key')
# Feature flag for Phase 4: CREATE_DRAFT_HEADER (Sandbox only)
ENABLE_CREATE_DRAFT_HEADER = os.environ.get('ENABLE_CREATE_DRAFT_HEADER', 'false').lower() == 'true'
# AI Classification Config
AI_CLASSIFICATION_ENABLED = os.environ.get('AI_CLASSIFICATION_ENABLED', 'true').lower() == 'true'
AI_CLASSIFICATION_THRESHOLD = float(os.environ.get('AI_CLASSIFICATION_THRESHOLD', '0.8'))
# Phase 7 C1: Email Polling Config (Observation Infrastructure)
EMAIL_POLLING_ENABLED = os.environ.get('EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('EMAIL_POLLING_INTERVAL_MINUTES', '5'))
EMAIL_POLLING_USER = os.environ.get('EMAIL_POLLING_USER', '')  # ap@gamerpackaging.com
EMAIL_POLLING_LOOKBACK_MINUTES = int(os.environ.get('EMAIL_POLLING_LOOKBACK_MINUTES', '60'))
EMAIL_POLLING_MAX_MESSAGES = int(os.environ.get('EMAIL_POLLING_MAX_MESSAGES', '25'))
EMAIL_POLLING_MAX_ATTACHMENT_MB = int(os.environ.get('EMAIL_POLLING_MAX_ATTACHMENT_MB', '25'))
# Sales Email Polling Config (Shadow Mode)
SALES_EMAIL_POLLING_ENABLED = os.environ.get('SALES_EMAIL_POLLING_ENABLED', 'false').lower() == 'true'
SALES_EMAIL_POLLING_USER = os.environ.get('SALES_EMAIL_POLLING_USER', '')  # hub-sales-intake@gamerpackaging.com
SALES_EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get('SALES_EMAIL_POLLING_INTERVAL_MINUTES', '5'))
# Separate email app credentials (for Mail.Read access)
EMAIL_CLIENT_ID = os.environ.get('EMAIL_CLIENT_ID', '')
EMAIL_CLIENT_SECRET = os.environ.get('EMAIL_CLIENT_SECRET', '')
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')  # For WRITES (Sandbox)
BC_READ_ENVIRONMENT = os.environ.get('BC_PROD_ENVIRONMENT', os.environ.get('BC_ENVIRONMENT', ''))  # For READS (Production)
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET', '')
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME', 'gamerpackaging.sharepoint.com')
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH', '/sites/GPI-DocumentHub-Test')
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Documents')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# ---------------------------------------------------------------------------
# server.py is used as a LIBRARY by main.py, not as a served app.
# The FastAPI app instance lives in main.py.
# Route handler functions are defined here and registered by router modules
# in /routers/ via add_api_route().
# ---------------------------------------------------------------------------

# Global polling task references
_email_polling_task = None
_sales_polling_task = None
_pilot_summary_task = None

# ==================== AUTH ====================
# NOTE: Auth endpoints are in routers/auth.py, registered by main.py
from routers.auth import router as auth_router

# ==================== AP REVIEW ====================
from routers.ap_review import ap_review_router, set_dependencies as set_ap_review_deps
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
# Module does not currently exist; kept as None for forward-compatibility.
sharepoint_migration_router = None
sharepoint_migration_module = None

# ==================== SPIRO INTEGRATION ====================
from routers.spiro import spiro_router, set_spiro_routes_db
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

# Auth endpoints moved to routes/auth.py — registered in main.py

# ==================== MICROSOFT SERVICES (MOCK/REAL) ====================

FOLDER_MAP = {
    "SalesOrder": "Sales", "SalesInvoice": "Sales",
    "PurchaseInvoice": "Purchase", "PurchaseOrder": "Purchase",
    "Shipment": "Warehouse", "Receipt": "Warehouse",
    "Other": "Incoming"
}

MOCK_COMPANIES = [
    {"id": "c1d2e3f4-0000-0000-0000-000000000001", "name": "GPI Packaging Ltd", "displayName": "GPI Packaging Ltd"},
    {"id": "c1d2e3f4-0000-0000-0000-000000000002", "name": "GPI Test Company", "displayName": "GPI Test Company"}
]

MOCK_SALES_ORDERS = [
    {"id": "a1b2c3d4-1111-0000-0000-000000000001", "number": "SO-1001", "orderDate": "2025-11-15", "customerName": "Acme Corp", "status": "Open", "totalAmountIncludingVAT": 1250.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000002", "number": "SO-1002", "orderDate": "2025-11-16", "customerName": "Widget Co", "status": "Open", "totalAmountIncludingVAT": 3400.50},
    {"id": "a1b2c3d4-1111-0000-0000-000000000003", "number": "SO-1003", "orderDate": "2025-12-01", "customerName": "TechnoServ Ltd", "status": "Released", "totalAmountIncludingVAT": 8900.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000004", "number": "SO-1004", "orderDate": "2025-12-05", "customerName": "PackRight Inc", "status": "Open", "totalAmountIncludingVAT": 520.75},
    {"id": "a1b2c3d4-1111-0000-0000-000000000005", "number": "SO-1005", "orderDate": "2026-01-10", "customerName": "Global Foods Ltd", "status": "Released", "totalAmountIncludingVAT": 12300.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000006", "number": "SO-1006", "orderDate": "2026-01-15", "customerName": "MediPack Solutions", "status": "Open", "totalAmountIncludingVAT": 4560.25},
    {"id": "a1b2c3d4-1111-0000-0000-000000000007", "number": "SO-1007", "orderDate": "2026-02-01", "customerName": "EuroPack GmbH", "status": "Open", "totalAmountIncludingVAT": 7800.00},
]

async def get_graph_token():
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return "mock-graph-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": GRAPH_CLIENT_ID, "client_secret": GRAPH_CLIENT_SECRET, "scope": "https://graph.microsoft.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Graph token error: {error_desc}")
        return data["access_token"]

async def get_email_token():
    """Get Graph token specifically for email access (Mail.Read)"""
    # Use EMAIL_CLIENT_ID/SECRET if configured, otherwise fall back to GRAPH credentials
    client_id = EMAIL_CLIENT_ID or GRAPH_CLIENT_ID
    client_secret = EMAIL_CLIENT_SECRET or GRAPH_CLIENT_SECRET
    
    if DEMO_MODE or not client_id:
        return "mock-email-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret, "scope": "https://graph.microsoft.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Email token error: {error_desc}")
        return data["access_token"]

async def get_bc_token():
    if DEMO_MODE or not BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": BC_CLIENT_ID, "client_secret": BC_CLIENT_SECRET, "scope": "https://api.businesscentral.dynamics.com/.default"})
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]

async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id, "item_id": item_id,
            "web_url": f"https://{SHAREPOINT_SITE_HOSTNAME}{SHAREPOINT_SITE_PATH}/{SHAREPOINT_LIBRARY_NAME}/{folder}/{file_name}",
            "name": file_name
        }
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Step 1: Resolve site (format: sites/{hostname}:/{server-relative-path}:)
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        site_data = site_resp.json()
        if site_resp.status_code == 401 or site_resp.status_code == 403:
            raise Exception(
                f"Graph API permission denied (HTTP {site_resp.status_code}). "
                f"The app registration needs 'Sites.ReadWrite.All' (Application) permission with admin consent. "
                f"Go to Azure Portal > App Registrations > {GRAPH_CLIENT_ID} > API Permissions > Add 'Sites.ReadWrite.All' > Grant admin consent."
            )
        if site_resp.status_code == 404 or "id" not in site_data:
            error = site_data.get("error", {})
            raise Exception(
                f"SharePoint site not found (HTTP {site_resp.status_code}). "
                f"Check SHAREPOINT_SITE_HOSTNAME='{SHAREPOINT_SITE_HOSTNAME}' and SHAREPOINT_SITE_PATH='{SHAREPOINT_SITE_PATH}'. "
                f"Detail: {error.get('message', error.get('code', 'unknown'))}"
            )
        if "id" not in site_data:
            raise Exception(f"Unexpected Graph response: {str(site_data)[:200]}")
        site_id = site_data["id"]

        # Step 2: Resolve drive
        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives_data = drives_resp.json()
        if drives_resp.status_code in (401, 403):
            raise Exception(f"Graph permission denied listing drives (HTTP {drives_resp.status_code}). Ensure 'Sites.ReadWrite.All' permission is granted.")
        if "error" in drives_data:
            raise Exception(f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}")
        drives = drives_data.get("value", [])
        drive = next((d for d in drives if d["name"] == SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            raise Exception(f"Document library '{SHAREPOINT_LIBRARY_NAME}' not found. Available: {[d['name'] for d in drives]}")
        drive_id = drive["id"]

        # Step 3: Upload file
        upload_resp = await c.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder}/{file_name}:/content",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=file_content)
        item = upload_resp.json()
        if upload_resp.status_code in (401, 403):
            raise Exception(f"Upload permission denied (HTTP {upload_resp.status_code}). Ensure app has 'Files.ReadWrite.All' or 'Sites.ReadWrite.All'.")
        if "id" not in item:
            error = item.get("error", {})
            raise Exception(f"Upload failed (HTTP {upload_resp.status_code}): {error.get('message', error.get('code', item))}")
        return {"drive_id": drive_id, "item_id": item["id"], "web_url": item.get("webUrl", ""), "name": file_name}


async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:
    """
    Ensure a folder exists in SharePoint, creating it and any parent folders if needed.
    Returns True if folder exists or was created successfully.
    """
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return True
    
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Get site and drive
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        if site_resp.status_code != 200:
            logger.warning("Could not resolve SharePoint site for folder creation")
            return False
        site_id = site_resp.json()["id"]
        
        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives = drives_resp.json().get("value", [])
        drive = next((d for d in drives if d["name"] == SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            return False
        drive_id = drive["id"]
        
        # Create folder path (Graph API auto-creates parent folders)
        # We use a folder creation endpoint
        folder_parts = folder_path.split("/")
        current_path = ""
        
        for part in folder_parts:
            if not part:
                continue
            parent_path = current_path if current_path else "root"
            current_path = f"{current_path}/{part}" if current_path else part
            
            # Check if folder exists
            check_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{current_path}"
            check_resp = await c.get(check_url, headers={"Authorization": f"Bearer {token}"})
            
            if check_resp.status_code == 404:
                # Folder doesn't exist, create it
                if parent_path == "root":
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                else:
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{'/'.join(folder_parts[:folder_parts.index(part)])}:/children"
                
                create_resp = await c.post(
                    create_url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
                )
                
                if create_resp.status_code not in (200, 201, 409):  # 409 = already exists (race condition)
                    logger.warning("Failed to create folder %s: %s", current_path, create_resp.text[:200])
                    # Continue anyway, might work
                else:
                    logger.info("Created SharePoint folder: %s", current_path)
        
        return True


async def upload_to_sharepoint_with_routing(
    file_content: bytes, 
    file_name: str, 
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False
) -> Dict[str, Any]:
    """
    Upload a file to SharePoint using the accounting folder routing logic.
    
    Args:
        file_content: The file bytes
        file_name: Name of the file
        doc: Document dictionary with extracted fields for routing
        freight_direction: "inbound", "outbound", or None
        is_international: Whether the shipment is international
        
    Returns:
        Dict with drive_id, item_id, web_url, name, folder_path, routing_reason
    """
    # Determine the correct folder using accounting rules
    folder_path, routing_reason, routing_details = determine_folder_path(
        doc, 
        freight_direction=freight_direction,
        is_international=is_international
    )
    
    logger.info("[Folder Routing] Doc %s -> %s (reason: %s)", 
                doc.get("id", "unknown"), folder_path, routing_reason)
    
    # Ensure the folder exists
    await ensure_sharepoint_folder_exists(folder_path)
    
    # Upload to the determined folder
    result = await upload_to_sharepoint(file_content, file_name, folder_path)
    
    # Add routing info to result
    result["folder_path"] = folder_path
    result["routing_reason"] = routing_reason
    result["routing_details"] = routing_details
    
    return result

async def create_sharing_link(drive_id: str, item_id: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return f"https://{SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/createLink",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "view", "scope": "organization"})
        data = resp.json()
        if "error" in data:
            raise Exception(f"Sharing link error: {data['error'].get('message', data['error'])}")
        return data.get("link", {}).get("webUrl", "")

async def get_bc_companies():
    if DEMO_MODE or not BC_CLIENT_ID:
        return MOCK_COMPANIES
    token = await get_bc_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Use BC_READ_ENVIRONMENT for reads (Production)
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies",
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            # BC returns XML for missing environments
            if "NoEnvironment" in resp.text:
                raise Exception(f"BC environment '{BC_READ_ENVIRONMENT}' does not exist. Check the environment name in Settings.")
            raise Exception(f"BC API not found (404): {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise Exception(f"BC permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC companies error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])

async def get_bc_sales_orders(order_no: str = None):
    if DEMO_MODE or not BC_CLIENT_ID:
        orders = MOCK_SALES_ORDERS
        if order_no:
            orders = [o for o in orders if order_no.lower() in o["number"].lower()]
        return orders
    token = await get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        raise Exception("No BC companies found")
    company_id = companies[0]["id"]
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Use BC_READ_ENVIRONMENT for reads (Production)
        url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders"
        if order_no:
            url += f"?$filter=contains(number,'{order_no}')"
        resp = await c.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (401, 403):
            raise Exception(f"BC sales orders permission denied (HTTP {resp.status_code}). Ensure the app has D365 AUTOMATION role in BC.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC sales orders error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])

async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str, file_content: bytes = None, content_type: str = None, bc_entity: str = "salesOrders"):
    """
    Attach a document to a BC record using the documentAttachments API.
    
    Args:
        bc_record_id: The GUID of the BC record
        share_link: SharePoint sharing link (stored in attachment notes if possible)
        file_name: Name of the file to attach
        file_content: Binary content of the file to upload
        content_type: MIME type of the file (e.g., 'application/pdf')
        bc_entity: The BC entity type (e.g., 'salesOrders', 'purchaseInvoices', 'salesInvoices')
    
    Returns:
        dict with success status and attachment details
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"success": True, "method": "mock", "note": f"In production: file will be attached to BC {bc_entity} via documentAttachments API"}
    
    if not file_content:
        return {"success": False, "method": "api", "error": "No file content provided for attachment"}
    
    token = await get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        return {"success": False, "method": "api", "error": "No BC companies found"}
    
    company_id = companies[0]["id"]
    
    async with httpx.AsyncClient(timeout=60.0) as c:
        # Step 1: Create the attachment metadata record
        # Using documentAttachments entity bound to the specified bc_entity
        attach_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments"
        
        # Determine content type
        if not content_type:
            ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
            content_type_map = {
                'pdf': 'application/pdf',
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'gif': 'image/gif',
                'doc': 'application/msword',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xls': 'application/vnd.ms-excel',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'txt': 'text/plain',
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')
        
        # Create attachment metadata
        attachment_payload = {
            "fileName": file_name
        }
        
        create_resp = await c.post(
            attach_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json=attachment_payload
        )
        
        if create_resp.status_code == 401 or create_resp.status_code == 403:
            return {
                "success": False, 
                "method": "api", 
                "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC."
            }
        
        if create_resp.status_code not in (200, 201):
            try:
                error_data = create_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = create_resp.text[:500]
            return {
                "success": False,
                "method": "api",
                "error": f"Failed to create attachment record (HTTP {create_resp.status_code}): {error_msg}"
            }
        
        attachment_data = create_resp.json()
        attachment_id = attachment_data.get("id")
        
        if not attachment_id:
            return {
                "success": False,
                "method": "api",
                "error": f"No attachment ID returned from BC: {attachment_data}"
            }
        
        # Step 2: Upload the actual file content using PATCH with attachmentContent
        content_url = f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"
        
        upload_resp = await c.patch(
            content_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "If-Match": "*"
            },
            content=file_content
        )
        
        if upload_resp.status_code not in (200, 204):
            try:
                error_data = upload_resp.json()
                error_msg = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_msg = upload_resp.text[:500]
            return {
                "success": False,
                "method": "api",
                "error": f"Failed to upload attachment content (HTTP {upload_resp.status_code}): {error_msg}"
            }
        
        logger.info("Successfully attached document '%s' to BC %s %s", file_name, bc_entity, bc_record_id)
        
        return {
            "success": True,
            "method": "api",
            "attachment_id": attachment_id,
            "file_name": file_name,
            "bc_entity": bc_entity,
            "note": f"Document attached to {bc_entity} in BC. SharePoint link: {share_link}"
        }

# ==================== PHASE 4: CREATE_DRAFT_HEADER ====================

async def check_duplicate_purchase_invoice(vendor_no: str, external_doc_no: str, company_id: str, token: str) -> dict:
    """
    Check if a Purchase Invoice already exists with the same vendor and external document number.
    This is a hard duplicate check that MUST stop draft creation.
    
    Args:
        vendor_no: BC Vendor number
        external_doc_no: External Document Number (Invoice Number from vendor)
        company_id: BC Company ID
        token: BC API token
    
    Returns:
        dict with found status, existing invoice details if found
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"found": False, "method": "demo"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            # Check for existing purchase invoices with same vendor + external doc no
            # This checks both posted and unposted invoices
            filter_query = f"vendorNumber eq '{vendor_no}' and vendorInvoiceNumber eq '{external_doc_no}'"
            
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": filter_query, "$select": "id,number,vendorNumber,vendorInvoiceNumber,status,totalAmountIncludingTax"}
            )
            
            if resp.status_code == 200:
                invoices = resp.json().get("value", [])
                if invoices:
                    existing = invoices[0]
                    return {
                        "found": True,
                        "existing_invoice_id": existing.get("id"),
                        "existing_invoice_no": existing.get("number"),
                        "vendor_invoice_no": existing.get("vendorInvoiceNumber"),
                        "status": existing.get("status", "Unknown"),
                        "amount": existing.get("totalAmountIncludingTax"),
                        "method": "api"
                    }
            elif resp.status_code in (401, 403):
                logger.warning("BC permission denied during duplicate check")
                return {"found": False, "error": "Permission denied", "method": "api"}
            
            return {"found": False, "method": "api"}
            
    except Exception as e:
        logger.error("Duplicate check failed: %s", str(e))
        return {"found": False, "error": str(e), "method": "api"}


async def create_purchase_invoice_header(
    vendor_no: str,
    external_doc_no: str,
    document_date: str = None,
    due_date: str = None,
    currency_code: str = None,
    posting_date: str = None,
    company_id: str = None,
    token: str = None
) -> dict:
    """
    Create a Purchase Invoice HEADER only in Business Central.
    
    SAFETY RULES:
    - Creates ONLY the header, NO lines
    - Sets document to Draft status (does NOT post)
    - Adds comment marking it as automation-created
    - Does NOT set quantities or GL accounts
    
    Args:
        vendor_no: BC Vendor Number (required)
        external_doc_no: External Document Number / Vendor Invoice Number (required)
        document_date: Document date from invoice (optional, defaults to today)
        due_date: Payment due date (optional)
        currency_code: Currency code if not local currency (optional)
        posting_date: Posting date (optional, defaults to today)
        company_id: BC Company ID
        token: BC API token
    
    Returns:
        dict with success status, created invoice ID, and details
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        # Return mock success for demo mode
        mock_invoice_id = str(uuid.uuid4())
        return {
            "success": True,
            "method": "demo",
            "invoice_id": mock_invoice_id,
            "invoice_no": f"PI-DEMO-{mock_invoice_id[:6].upper()}",
            "status": "Draft",
            "note": "Demo mode: Purchase Invoice header would be created in production"
        }
    
    if not company_id or not token:
        # Fetch if not provided
        try:
            token = await get_bc_token()
            companies = await get_bc_companies()
            if not companies:
                return {"success": False, "error": "No BC companies found"}
            company_id = companies[0]["id"]
        except Exception as e:
            return {"success": False, "error": f"Failed to get BC token/company: {str(e)}"}
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            # Build invoice header payload - HEADER FIELDS ONLY
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
            invoice_payload = {
                "vendorNumber": vendor_no,
                "vendorInvoiceNumber": external_doc_no,
            }
            
            # Add optional fields if provided
            if document_date:
                invoice_payload["documentDate"] = document_date
            else:
                invoice_payload["documentDate"] = today
            
            if due_date:
                invoice_payload["dueDate"] = due_date
            
            if posting_date:
                invoice_payload["postingDate"] = posting_date
            else:
                invoice_payload["postingDate"] = today
            
            if currency_code and currency_code.upper() not in ('', 'USD', 'GBP', 'EUR'):
                invoice_payload["currencyCode"] = currency_code.upper()
            
            # Create the Purchase Invoice (header only)
            create_resp = await c.post(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=invoice_payload
            )
            
            if create_resp.status_code == 401 or create_resp.status_code == 403:
                return {
                    "success": False,
                    "method": "api",
                    "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC."
                }
            
            if create_resp.status_code not in (200, 201):
                try:
                    error_data = create_resp.json()
                    error_msg = error_data.get("error", {}).get("message", str(error_data))
                except Exception:
                    error_msg = create_resp.text[:500]
                return {
                    "success": False,
                    "method": "api",
                    "error": f"Failed to create Purchase Invoice (HTTP {create_resp.status_code}): {error_msg}"
                }
            
            invoice_data = create_resp.json()
            invoice_id = invoice_data.get("id")
            invoice_no = invoice_data.get("number")
            
            if not invoice_id:
                return {
                    "success": False,
                    "method": "api",
                    "error": f"No invoice ID returned from BC: {invoice_data}"
                }
            
            logger.info(
                "Created Purchase Invoice draft header: ID=%s, No=%s, Vendor=%s, ExtDoc=%s",
                invoice_id, invoice_no, vendor_no, external_doc_no
            )
            
            return {
                "success": True,
                "method": "api",
                "invoice_id": invoice_id,
                "invoice_no": invoice_no,
                "vendor_no": vendor_no,
                "external_doc_no": external_doc_no,
                "status": "Draft",
                "header_only": True,
                "note": "Created by GPI Hub Automation - Header only, no lines"
            }
            
    except Exception as e:
        logger.error("Failed to create Purchase Invoice header: %s", str(e))
        return {
            "success": False,
            "method": "api",
            "error": f"Exception creating Purchase Invoice: {str(e)}"
        }


def is_eligible_for_draft_creation(
    job_type: str,
    match_method: str,
    match_score: float,
    ai_confidence: float,
    validation_results: dict,
    doc: dict
) -> tuple:
    """
    Check if a document meets ALL preconditions for draft creation.
    
    PRECONDITIONS (ALL must be true):
    1. Feature flag ENABLE_CREATE_DRAFT_HEADER is true
    2. Job type is AP_Invoice (only supported type for now)
    3. match_method is in eligible methods (exact_no, exact_name, normalized, alias)
    4. match_score >= 0.92
    5. AI confidence >= 0.92
    6. duplicate_check passed (no existing invoice)
    7. vendor_match passed
    8. PO validation passed (if required by mode)
    9. Document status != LinkedToBC (not already linked)
    10. bc_record_id not already set (no draft already created)
    
    Returns:
        (is_eligible: bool, reason: str)
    """
    config = DRAFT_CREATION_CONFIG
    
    # 1. Feature flag check
    if not ENABLE_CREATE_DRAFT_HEADER:
        return (False, "Feature flag ENABLE_CREATE_DRAFT_HEADER is disabled")
    
    # 2. Job type check
    if job_type != "AP_Invoice":
        return (False, f"Draft creation only supported for AP_Invoice, got {job_type}")
    
    # 3. Match method check
    if match_method not in config["eligible_match_methods"]:
        return (False, f"Match method '{match_method}' not eligible for draft (requires: {config['eligible_match_methods']})")
    
    # 4. Match score check
    if match_score < config["min_match_score_for_draft"]:
        return (False, f"Match score {match_score:.2%} below draft threshold {config['min_match_score_for_draft']:.2%}")
    
    # 5. AI confidence check
    if ai_confidence < config["min_confidence_for_draft"]:
        return (False, f"AI confidence {ai_confidence:.2%} below draft threshold {config['min_confidence_for_draft']:.2%}")
    
    # 6-8. Check validation results
    if not validation_results.get("all_passed", False):
        failed_checks = [c["check_name"] for c in validation_results.get("checks", []) 
                        if not c.get("passed", True) and c.get("required", True)]
        return (False, f"Validation failed: {', '.join(failed_checks)}")
    
    # Check specific critical checks
    checks = validation_results.get("checks", [])
    for check in checks:
        if check["check_name"] == "duplicate_check" and not check.get("passed", True):
            return (False, "Duplicate invoice check failed - hard stop")
        if check["check_name"] == "vendor_match" and not check.get("passed", True):
            return (False, "Vendor match failed - cannot create draft without matched vendor")
    
    # 9. Status check - don't create draft for already linked documents
    doc_status = doc.get("status", "")
    if doc_status == "LinkedToBC":
        return (False, "Document already linked to BC - no draft needed")
    
    # 10. bc_record_id check - don't create duplicate draft
    if doc.get("bc_record_id"):
        return (False, f"BC record already exists: {doc.get('bc_record_id')} - idempotency guard")
    
    # All checks passed
    return (True, "All preconditions met for draft creation")


# ==================== WORKFLOW ENGINE ====================

async def run_upload_and_link_workflow(doc_id: str, file_content: bytes, file_name: str, doc_type: str, bc_record_id: str = None, bc_document_no: str = None):
    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []
    
    # Determine BC entity from document type
    doc_type_to_bc_entity = {
        "SalesOrder": "salesOrders",
        "SalesInvoice": "salesInvoices",
        "PurchaseInvoice": "purchaseInvoices",
        "PurchaseOrder": "purchaseOrders"
    }
    bc_entity = doc_type_to_bc_entity.get(doc_type, "salesOrders")

    try:
        # Step 1: Upload to SharePoint
        folder = FOLDER_MAP.get(doc_type, "Incoming")
        step1_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "upload_to_sharepoint", "status": "running", "started": step1_start})
        sp_result = await upload_to_sharepoint(file_content, file_name, folder)
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"drive_id": sp_result["drive_id"], "item_id": sp_result["item_id"], "folder": folder}

        # Step 2: Create sharing link
        step2_start = datetime.now(timezone.utc).isoformat()
        steps.append({"step": "create_sharing_link", "status": "running", "started": step2_start})
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        steps[-1]["status"] = "completed"
        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
        steps[-1]["result"] = {"share_link": share_link}

        # Step 3: Validate and link BC record
        bc_linked = False
        bc_error = None
        if bc_record_id or bc_document_no:
            step3_start = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "validate_bc_record", "status": "running", "started": step3_start})
            try:
                orders = await get_bc_sales_orders(order_no=bc_document_no)
                if orders:
                    steps[-1]["status"] = "completed"
                    steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                    steps[-1]["result"] = {"found": True, "order_number": orders[0]["number"], "customer": orders[0]["customerName"]}

                    step4_start = datetime.now(timezone.utc).isoformat()
                    steps.append({"step": "link_to_bc", "status": "running", "started": step4_start})
                    link_result = await link_document_to_bc(
                        bc_record_id=bc_record_id or orders[0]["id"], 
                        share_link=share_link, 
                        file_name=file_name,
                        file_content=file_content,
                        bc_entity=bc_entity
                    )
                    # Check if BC attachment succeeded
                    if link_result.get("success"):
                        steps[-1]["status"] = "completed"
                        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                        steps[-1]["result"] = link_result
                        bc_linked = True
                    else:
                        steps[-1]["status"] = "failed"
                        steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                        steps[-1]["error"] = link_result.get("error", "Unknown error attaching to BC")
                        bc_error = link_result.get("error", "Unknown error attaching to BC")
                else:
                    steps[-1]["status"] = "warning"
                    steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                    steps[-1]["result"] = {"found": False, "note": "BC record not found"}
                    bc_error = "BC record not found"
            except Exception as bc_exc:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = str(bc_exc)
                bc_error = str(bc_exc)

        # Determine final status — SharePoint success is preserved even if BC fails
        if bc_record_id or bc_document_no:
            new_status = "LinkedToBC" if bc_linked else "Classified"
        else:
            new_status = "Classified"

        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "sharepoint_drive_id": sp_result["drive_id"],
            "sharepoint_item_id": sp_result["item_id"],
            "sharepoint_web_url": sp_result["web_url"],
            "sharepoint_share_link_url": share_link,
            "status": new_status,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "last_error": bc_error
        }})

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "upload_and_link",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Completed" if bc_linked else ("CompletedWithWarnings" if not bc_error else "PartialSuccess"),
            "steps": steps, "correlation_id": correlation_id, 
            "error": bc_error
        }
        await db.hub_workflow_runs.insert_one(workflow)
        return workflow_id, new_status

    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e), "ended": datetime.now(timezone.utc).isoformat()})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "upload_and_link",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e)
        }
        await db.hub_workflow_runs.insert_one(workflow)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "Exception", "last_error": str(e), "updated_utc": datetime.now(timezone.utc).isoformat()
        }})
        return workflow_id, "Exception"

# ==================== DOCUMENT ENDPOINTS ====================

# Upload storage path
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Document routes moved to routers/documents.py — REMOVED (Domain 7)
# Simple routes (list, get, update, delete, events, timeline, derived-state, refresh-state,
# file, square9-status, reset-retries) are implemented directly in routers/documents.py.
# Complex routes below remain as functions (no decorator) for thin-wrapper import.

# upload_document — registered via add_api_route in routers/documents.py
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("Other"),
    bc_record_id: str = Form(None),
    bc_document_no: str = Form(None),
    bc_company_id: str = Form(None),
    source: str = Form("manual_upload")
):
    file_content = await file.read()
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    correlation_id = str(uuid.uuid4())  # For event correlation

    # Persist file to disk for potential resubmit
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    # Determine doc_type from document_type parameter
    doc_type_value = DocumentClassifier.classify_from_ai_result(document_type or "").value if document_type else DocType.OTHER.value
    
    # Apply pilot capture channel if pilot mode is enabled
    base_capture_channel = CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel

    doc = {
        "id": doc_id, "source": source, "file_name": file.filename,
        "sha256_hash": sha256_hash, "file_size": len(file_content),
        "content_type": file.content_type,
        "sharepoint_drive_id": None, "sharepoint_item_id": None,
        "sharepoint_web_url": None, "sharepoint_share_link_url": None,
        "document_type": document_type,
        "category": None,
        # Document classification fields
        "doc_type": doc_type_value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": capture_channel,
        "bc_record_type": "SalesOrder" if document_type == "SalesOrder" else None,
        "bc_company_id": bc_company_id, "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": f"Document captured from {source}",
            "metadata": {"source": source, "doc_type": doc_type_value}
        }],
        "workflow_status_updated_utc": now,
        # Square9 workflow alignment
        **initialize_retry_state({}),
        "status": "Received", "created_utc": now, "updated_utc": now, "last_error": None,
        # Derived state fields (Phase 2)
        "validation_state": "pending",
        "workflow_state": "received",
        "automation_state": "manual",
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)
    
    # Emit document.received event (Phase 1)
    event_service = get_event_service()
    if event_service:
        await emit_document_received(
            event_service, doc_id, source,
            file.filename, file.content_type or "application/octet-stream",
            len(file_content), correlation_id
        )

    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, file.filename, document_type, bc_record_id, bc_document_no
    )
    
    # Update derived state after workflow
    derived_state_service = get_derived_state_service()
    if derived_state_service:
        await derived_state_service.update_document_derived_state(doc_id)
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}

# list_documents — moved to routers/documents.py (Domain 7)


# get_document — moved to routers/documents.py (Domain 7)


# =============================================================================
# EVENT-DRIVEN WORKFLOW ENDPOINTS — moved to routers/documents.py (Domain 7)
# =============================================================================

# get_document_events — moved to routers/documents.py

# get_document_timeline — moved to routers/documents.py

# get_document_derived_state — moved to routers/documents.py

# refresh_document_state — moved to routers/documents.py




# Moved to routers/reference_intelligence.py (Domain 9)
async def resolve_bc_reference(
    reference_number: str = Query(..., description="Reference number to resolve"),
    tables: Optional[str] = Query(None, description="Comma-separated tables to check")
):
    """
    Resolve a reference number against BC tables.
    
    Checks in order: Purchase Orders, Posted Purchase Invoices, 
    Sales Orders, Posted Sales Invoices, Posted Sales Shipments.
    """
    resolver = get_reference_resolver()
    
    check_tables = tables.split(",") if tables else None
    
    result = await resolver.resolve_reference(reference_number, check_tables)
    
    # Emit event
    event_service = get_event_service()
    if event_service:
        await event_service.emit(
            event_type="reference.resolve.completed",
            document_id="api_call",
            status="completed" if result.status == "found" else "warning",
            source_service="bc_reference_resolver",
            payload=result.to_dict()
        )
    
    return result.to_dict()


# Moved to routers/reference_intelligence.py (Domain 9)
async def resolve_document_reference(doc_id: str):
    """
    Resolve PO/Order reference for a specific document.
    
    Looks up extracted PO number or order reference and resolves against BC.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Get reference number from document
    reference_number = (
        doc.get("po_number_clean") or
        doc.get("extracted_fields", {}).get("po_number") or
        doc.get("bol_number") or
        doc.get("extracted_fields", {}).get("bol_number")
    )
    
    if not reference_number:
        return {
            "document_id": doc_id,
            "status": "no_reference",
            "message": "No PO or BOL reference found in document"
        }
    
    resolver = get_reference_resolver()
    result = await resolver.resolve_reference(reference_number)
    
    # Update document with resolution result
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "reference_resolution": result.to_dict(),
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Emit event
    event_service = get_event_service()
    if event_service:
        await event_service.emit(
            event_type="reference.resolve.completed",
            document_id=doc_id,
            status="completed" if result.status == "found" else "warning",
            source_service="bc_reference_resolver",
            payload=result.to_dict()
        )
    
    return {
        "document_id": doc_id,
        **result.to_dict()
    }


# =============================================================================
# REFERENCE INTELLIGENCE ENDPOINTS
# =============================================================================

# Moved to routers/reference_intelligence.py (Domain 9)
async def resolve_document_intelligence(doc_id: str):
    """
    Full AI-Assisted Reference Intelligence resolution for a document.
    
    Extracts all candidate references, classifies them, resolves against BC 
    with document-type-aware strategy, and scores matches.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    ref_service = get_reference_intelligence_service()
    if not ref_service:
        raise HTTPException(status_code=503, detail="Reference Intelligence Service not initialized")
    
    # Build extracted fields from document
    extracted_fields = doc.get("extracted_fields", {})
    if not extracted_fields:
        extracted_fields = {}
    # Merge top-level extracted fields into extracted_fields dict
    for fld in ["po_number", "bol_number", "invoice_number", "order_number", "shipment_number"]:
        if doc.get(fld) and not extracted_fields.get(fld):
            extracted_fields[fld] = doc[fld]
    if doc.get("po_number_clean") and not extracted_fields.get("po_number"):
        extracted_fields["po_number"] = doc["po_number_clean"]
    if doc.get("invoice_number_clean") and not extracted_fields.get("invoice_number"):
        extracted_fields["invoice_number"] = doc["invoice_number_clean"]
    
    # Get document text if available
    document_text = doc.get("extracted_text") or doc.get("raw_text") or ""
    
    # Run full reference intelligence resolution
    resolution = await ref_service.resolve_document_references(
        document=doc,
        extracted_fields=extracted_fields,
        document_text=document_text
    )
    
    # Update document with results
    await ref_service.update_document_references(doc_id, resolution)
    
    return resolution.to_dict()


# Moved to routers/reference_intelligence.py (Domain 9)
async def get_document_reference_intelligence(doc_id: str):
    """
    Get stored reference intelligence data for a document.
    Returns the last resolution result without re-running.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    ref_intel = doc.get("reference_intelligence")
    if not ref_intel:
        return {
            "document_id": doc_id,
            "status": "not_resolved",
            "message": "Reference intelligence has not been run for this document. POST to /resolve-intelligence to trigger."
        }
    
    return ref_intel






# Moved to routers/reference_intelligence.py (Domain 9)
async def trigger_auto_resolve(doc_id: str):
    """Manually enqueue a document for auto-resolution (re-run)."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    svc = get_auto_resolve_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Auto-resolution service not initialized")
    
    # Force re-run by setting status to not_run
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"reference_intelligence_status": "not_run"}}
    )
    await svc.enqueue(doc_id)
    
    return {"status": "queued", "document_id": doc_id}


# =============================================================================
# VENDOR INTELLIGENCE ENDPOINTS
# =============================================================================





# automation-rules routes moved to routers/automation_rules.py — REMOVED (duplicate)

















# Moved to routers/reference_intelligence.py (Domain 9)
async def get_matching_debug(doc_id: str):
    """
    Get full matching diagnostics for a document.
    Shows: extraction, normalization, resolver strategy, cache/API results,
    candidate scores with breakdown, decision and failure reasons.
    """
    # Check persisted diagnostics first
    diag = await db.matching_diagnostics.find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    
    # Also get doc-level reference intelligence
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "reference_intelligence": 1, "reference_candidates": 1,
         "reference_match_outcome": 1, "reference_best_match": 1,
         "document_type": 1, "vendor_canonical": 1, "vendor_raw": 1,
         "unified_vendor_match": 1, "freight_gl_classification": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    ref_intel = doc.get("reference_intelligence", {})
    
    # Fetch label corrections for this document
    label_corrections = []
    lc_svc = get_label_correction_service()
    if lc_svc:
        label_corrections = await lc_svc.get_corrections_for_document(doc_id)
    
    # Fetch vendor correction patterns
    vendor_patterns = None
    vendor_id = doc.get("vendor_canonical") or doc.get("vendor_raw") or ""
    if lc_svc and vendor_id:
        vendor_patterns = await lc_svc.get_vendor_patterns(vendor_id)
    
    # Fetch vendor extraction profile
    vep_data = None
    vep_svc = get_vep_service()
    if vep_svc and vendor_id:
        vep_data = await vep_svc.get_resolver_adjustments(vendor_id)
        # Fallback: try the raw vendor name if vendor_no didn't match
        if not vep_data or not vep_data.get("has_profile"):
            alt_vendor = doc.get("vendor_raw") or doc.get("matched_vendor_name") or ""
            if alt_vendor and alt_vendor != vendor_id:
                vep_data = await vep_svc.get_resolver_adjustments(alt_vendor)
    
    # Fetch layout fingerprint for this document
    layout_fp_data = None
    layout_svc = get_layout_fingerprint_service()
    if layout_svc:
        layout_fp_data = await layout_svc.get_fingerprint_for_document(doc_id)
        # If we have a family, get family details
        if layout_fp_data and layout_fp_data.get("layout_family_id"):
            family_detail = await layout_svc.get_family_detail(layout_fp_data["layout_family_id"])
            if family_detail:
                layout_fp_data["family_detail"] = {
                    "documents_count": family_detail.get("documents_count", 0),
                    "first_seen": family_detail.get("first_seen"),
                    "last_seen": family_detail.get("last_seen"),
                    "performance_metrics": family_detail.get("performance_metrics", {}),
                }
    
    return {
        "document_id": doc_id,
        "document_type": doc.get("document_type"),
        "vendor": vendor_id,
        "is_freight_carrier": (doc.get("unified_vendor_match") or {}).get("is_freight_carrier", False),
        "match_outcome": doc.get("reference_match_outcome") or ref_intel.get("match_outcome"),
        "diagnostics": diag,
        "reference_intelligence": ref_intel,
        "freight_gl": doc.get("freight_gl_classification"),
        "label_corrections": label_corrections,
        "vendor_correction_patterns": vendor_patterns,
        "vendor_extraction_profile": vep_data,
        "layout_fingerprint": layout_fp_data,
    }


# Moved to routers/reference_intelligence.py (Domain 9)
async def rerun_matching_with_diagnostics(doc_id: str):
    """
    Rerun reference resolution with full diagnostics capture.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    svc = get_reference_intelligence_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Reference intelligence not initialized")
    
    result = await svc.resolve_document_references(
        document=doc,
        extracted_fields=doc.get("extracted_fields"),
        capture_diagnostics=True
    )
    
    # Save result and diagnostics
    await svc.update_document_references(doc_id, result)
    
    # Trigger label correction feedback loop (learn from this resolution)
    lc_svc = get_label_correction_service()
    if lc_svc and result.best_match:
        try:
            corrections = await lc_svc.detect_and_record(
                document_id=doc_id,
                resolution_result=result.to_dict(),
                document=doc,
            )
            if corrections:
                # Update vendor profiles with correction patterns
                vendor_intel = get_vendor_intelligence_service()
                uvm = doc.get("unified_vendor_match") or {}
                vid = uvm.get("bc_vendor_no") or doc.get("vendor_raw") or ""
                if vendor_intel and vid:
                    for c in corrections:
                        try:
                            await vendor_intel.update_label_correction_patterns(vid, c)
                        except Exception:
                            pass
        except Exception:
            pass
    
    return result.to_dict()















# vendor-extraction-profiles route moved to routers/vendor_extraction_profiles.py — REMOVED (duplicate)














# update_document — moved to routers/documents.py (Domain 7)

# delete_document — moved to routers/documents.py (Domain 7)


# get_document_file — moved to routers/documents.py (Domain 7)


# =============================================================================
# SQUARE9 WORKFLOW ENDPOINTS — status/reset moved to routers/documents.py (Domain 7)
# =============================================================================

# get_square9_status — moved to routers/documents.py (Domain 7)


# retry_document — registered via add_api_route in routers/documents.py
async def retry_document(doc_id: str, reason: str = "Manual retry"):
    """
    Retry a document's workflow processing.
    Increments retry counter and re-runs workflow if within limits.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check if retry is allowed
    can_do_retry, retry_reason = should_retry(doc)
    if not can_do_retry:
        return {
            "success": False,
            "message": retry_reason,
            "document_id": doc_id,
            "retry_count": doc.get("retry_count", 0),
            "max_retries": doc.get("max_retries", DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"]),
        }
    
    # Increment retry counter
    update_dict, escalated, message = increment_retry(doc, reason)
    update_dict["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
    
    if escalated:
        return {
            "success": False,
            "escalated": True,
            "message": message,
            "document_id": doc_id,
            "retry_count": update_dict["retry_count"],
        }
    
    # Re-run workflow (using existing resubmit logic)
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        return {
            "success": False,
            "message": "Stored file not found - cannot retry",
            "document_id": doc_id,
        }
    
    # Read file and re-run workflow
    file_content = file_path.read_bytes()
    file_name = doc.get("file_name", f"{doc_id}.pdf")
    document_type = doc.get("document_type", "Invoice")
    bc_record_id = doc.get("bc_record_id")
    bc_document_no = doc.get("bc_document_no")
    
    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, file_name, document_type, bc_record_id, bc_document_no
    )
    
    # Update Square9 stage after workflow
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    new_stage = determine_square9_stage(updated_doc) if updated_doc else None
    
    if new_stage:
        await db.hub_documents.update_one(
            {"id": doc_id}, 
            {"$set": {"square9_stage": new_stage}}
        )
    
    return {
        "success": True,
        "message": message,
        "document_id": doc_id,
        "workflow_id": workflow_id,
        "final_status": final_status,
        "retry_count": update_dict["retry_count"],
        "square9_stage": new_stage,
    }


async def reset_document_retries(doc_id: str, reason: str = "Manual reset"):
    """Reset retry counter for a document (after manual intervention)."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    update_dict = reset_retry_counter(doc, reason)
    update_dict["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
    
    return {
        "success": True,
        "message": f"Retry counter reset: {reason}",
        "document_id": doc_id,
        "retry_count": 0,
    }





# Moved to routers/documents.py — resubmit_document
async def resubmit_document(doc_id: str):
    """Re-submit a failed document: re-run the full workflow using the stored file."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Read stored file from disk
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found on server. Please upload again via the Upload page.")
    file_content = file_path.read_bytes()
    now = datetime.now(timezone.utc).isoformat()

    # Reset document status
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "status": "Received",
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "last_error": None,
        "updated_utc": now,
    }})

    # Re-run the full workflow with existing metadata
    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"),
        doc.get("bc_document_no")
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}

# Moved to routers/documents.py — link_document
async def link_document(doc_id: str):
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.get("sharepoint_share_link_url"):
        raise HTTPException(status_code=400, detail="Document has no SharePoint link yet")
    bc_record_id = doc.get("bc_record_id")
    bc_document_no = doc.get("bc_document_no")
    if not bc_record_id and not bc_document_no:
        raise HTTPException(status_code=400, detail="No BC record reference set on this document")

    # Load the stored file for attachment
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()

    # Determine BC entity from document type or job_type
    doc_type = doc.get("document_type", "Other")
    job_type = doc.get("suggested_job_type", "")
    
    # Try to get bc_entity from job config first
    job_config = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if job_config:
        bc_entity = job_config.get("bc_entity", "salesOrders")
    else:
        # Fallback mapping
        doc_type_to_bc_entity = {
            "SalesOrder": "salesOrders",
            "SalesInvoice": "salesInvoices", 
            "PurchaseInvoice": "purchaseInvoices",
            "PurchaseOrder": "purchaseOrders",
            "AP_Invoice": "purchaseInvoices"
        }
        bc_entity = doc_type_to_bc_entity.get(doc_type, doc_type_to_bc_entity.get(job_type, "salesOrders"))

    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    try:
        steps.append({"step": "validate_bc_record", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
        orders = await get_bc_sales_orders(order_no=bc_document_no)
        if orders:
            steps[-1]["status"] = "completed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "link_to_bc", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id or orders[0]["id"], 
                share_link=doc["sharepoint_share_link_url"], 
                file_name=doc["file_name"],
                file_content=file_content,
                bc_entity=bc_entity
            )
            if link_result.get("success"):
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = link_result
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "LinkedToBC", "updated_utc": datetime.now(timezone.utc).isoformat(), "last_error": None}})
                wf_status = "Completed"
            else:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = link_result.get("error", "Unknown error")
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": link_result.get("error"), "updated_utc": datetime.now(timezone.utc).isoformat()}})
                wf_status = "Failed"
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": "BC record not found", "updated_utc": datetime.now(timezone.utc).isoformat()}})
            wf_status = "Failed"

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": wf_status, "steps": steps, "correlation_id": correlation_id,
            "error": None if wf_status == "Completed" else steps[-1].get("error", "BC record not found")
        }
        await db.hub_workflow_runs.insert_one(workflow)
    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e)})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e)
        }
        await db.hub_workflow_runs.insert_one(workflow)

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": doc, "workflow_id": workflow_id}

# ==================== WORKFLOW ENDPOINTS ====================

# Moved to routers/workflows.py (Domain 8)
async def list_workflows(skip: int = Query(0), limit: int = Query(50), status: str = Query(None)):
    fq = {}
    if status:
        fq["status"] = status
    workflows = await db.hub_workflow_runs.find(fq, {"_id": 0}).sort("started_utc", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.hub_workflow_runs.count_documents(fq)
    return {"workflows": workflows, "total": total}

# Moved to routers/workflows.py (Domain 8)
async def get_workflow(wf_id: str):
    wf = await db.hub_workflow_runs.find_one({"id": wf_id}, {"_id": 0})
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf

# Moved to routers/workflows.py (Domain 8)
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
        result = await link_document(doc_id)
        return {"message": "Retry completed", "result": result}
    return {"message": "Cannot retry - document missing SharePoint link or BC reference"}

# ==================== DASHBOARD ====================



async def _aggregate_document_types_data(
    source_system: Optional[str] = None, 
    doc_type: Optional[str] = None,
    classification: Optional[str] = None
) -> Dict:
    """
    Shared aggregation logic for document types dashboard.
    Reused by both the JSON endpoint and CSV export endpoint.
    
    Args:
        source_system: Filter by source system (SQUARE9, ZETADOCS, GPI_HUB_NATIVE)
        doc_type: Filter by specific document type
        classification: Filter by classification method: "deterministic", "ai", "all"
    """
    # Build base match filter
    base_match = {}
    if source_system:
        base_match["source_system"] = source_system
    if doc_type:
        base_match["doc_type"] = doc_type
    
    # Add classification filter
    if classification == "deterministic":
        # Deterministic: legacy_ai, zetadocs, square9, mailbox (NOT ai:*)
        base_match["$and"] = [
            {"classification_method": {"$exists": True}},
            {"classification_method": {"$not": {"$regex": "^ai:"}}}
        ]
    elif classification == "ai":
        # AI-assisted: classification_method starts with "ai:"
        base_match["classification_method"] = {"$regex": "^ai:"}
    
    # Aggregate status counts by doc_type
    status_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]},
                "workflow_status": {"$ifNull": ["$workflow_status", "none"]}
            },
            "count": {"$sum": 1}
        }}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(500)
    
    # Aggregate extraction field presence by doc_type
    extraction_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "total": {"$sum": 1},
            "has_vendor": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$vendor_raw", None]},
                {"$ne": ["$vendor_canonical", None]}
            ]}, 1, 0]}},
            "has_invoice_number": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$invoice_number_raw", None]},
                {"$ne": ["$invoice_number_clean", None]}
            ]}, 1, 0]}},
            "has_amount": {"$sum": {"$cond": [{"$ne": ["$amount_float", None]}, 1, 0]}},
            "has_po_number": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$po_number_raw", None]},
                {"$ne": ["$po_number_clean", None]}
            ]}, 1, 0]}},
            "has_due_date": {"$sum": {"$cond": [{"$or": [
                {"$ne": ["$due_date_raw", None]},
                {"$ne": ["$due_date_iso", None]}
            ]}, 1, 0]}},
            "avg_confidence": {"$avg": {"$ifNull": ["$ai_confidence", 0]}}
        }}
    ]
    extraction_results = await db.hub_documents.aggregate(extraction_pipeline).to_list(50)
    
    # Aggregate match_method distribution by doc_type
    match_method_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {
                "doc_type": {"$ifNull": ["$doc_type", "OTHER"]},
                "match_method": {"$ifNull": ["$vendor_match_method", "none"]}
            },
            "count": {"$sum": 1}
        }}
    ]
    match_method_results = await db.hub_documents.aggregate(match_method_pipeline).to_list(200)
    
    # Aggregate source_system counts for the filter dropdown
    source_system_pipeline = [
        {"$group": {
            "_id": {"$ifNull": ["$source_system", "UNKNOWN"]},
            "count": {"$sum": 1}
        }}
    ]
    source_system_results = await db.hub_documents.aggregate(source_system_pipeline).to_list(20)
    
    # Aggregate classification method counts by doc_type
    classification_pipeline = [
        {"$match": base_match} if base_match else {"$match": {}},
        {"$group": {
            "_id": {"$ifNull": ["$doc_type", "OTHER"]},
            "total": {"$sum": 1},
            # Count deterministic classifications (legacy_ai, zetadocs, square9, mailbox, default - NOT ai:*)
            "deterministic_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": [{"$ifNull": ["$classification_method", ""]}, ""]},
                    {"$not": [{"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}}]}
                ]},
                1, 0
            ]}},
            # Count AI-assisted classifications (classification_method starts with "ai:")
            "ai_count": {"$sum": {"$cond": [
                {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}},
                1, 0
            ]}},
            # Count other/missing (classification_method is null or empty)
            "other_count": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": [{"$ifNull": ["$classification_method", ""]}, ""]},
                    {"$eq": ["$classification_method", None]}
                ]},
                1, 0
            ]}},
            # AI assisted: ai_classification exists AND doc_type != OTHER AND classification_method starts with "ai:"
            "ai_assisted_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$ai_classification", None]},
                    {"$ne": [{"$ifNull": ["$doc_type", "OTHER"]}, "OTHER"]},
                    {"$regexMatch": {"input": {"$ifNull": ["$classification_method", ""]}, "regex": "^ai:"}}
                ]},
                1, 0
            ]}},
            # AI suggested but rejected: ai_classification exists AND doc_type == OTHER
            "ai_suggested_but_rejected_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$ai_classification", None]},
                    {"$eq": [{"$ifNull": ["$doc_type", "OTHER"]}, "OTHER"]}
                ]},
                1, 0
            ]}}
        }}
    ]
    classification_results = await db.hub_documents.aggregate(classification_pipeline).to_list(50)
    
    # Build the response structure
    by_type = {}
    
    # Initialize with all supported doc_types
    for dt in WorkflowEngine.get_all_doc_types():
        by_type[dt] = {
            "total": 0,
            "status_counts": {},
            "extraction": {
                "vendor": {"rate": 0.0, "count": 0},
                "invoice_number": {"rate": 0.0, "count": 0},
                "amount": {"rate": 0.0, "count": 0},
                "po_number": {"rate": 0.0, "count": 0},
                "due_date": {"rate": 0.0, "count": 0}
            },
            "match_methods": {},
            "avg_confidence": 0.0,
            # NEW: Classification method breakdown
            "classification_counts": {
                "deterministic": 0,
                "ai": 0,
                "other": 0
            },
            "ai_assisted_count": 0,
            "ai_suggested_but_rejected_count": 0,
            # NEW: Active queue count (non-terminal statuses)
            "active_queue_count": 0
        }
    
    # Terminal statuses (documents no longer in active processing)
    terminal_statuses = ["approved", "exported", "archived", "rejected", "failed"]
    
    # Populate status counts
    for r in status_results:
        dt = r["_id"]["doc_type"]
        status = r["_id"]["workflow_status"]
        count = r["count"]
        
        if dt not in by_type:
            by_type[dt] = {
                "total": 0,
                "status_counts": {},
                "extraction": {
                    "vendor": {"rate": 0.0, "count": 0},
                    "invoice_number": {"rate": 0.0, "count": 0},
                    "amount": {"rate": 0.0, "count": 0},
                    "po_number": {"rate": 0.0, "count": 0},
                    "due_date": {"rate": 0.0, "count": 0}
                },
                "match_methods": {},
                "avg_confidence": 0.0,
                "classification_counts": {"deterministic": 0, "ai": 0, "other": 0},
                "ai_assisted_count": 0,
                "ai_suggested_but_rejected_count": 0,
                "active_queue_count": 0
            }
        
        by_type[dt]["status_counts"][status] = count
        by_type[dt]["total"] += count
        
        # Compute active queue count (non-terminal statuses)
        if status not in terminal_statuses:
            by_type[dt]["active_queue_count"] += count
    
    # Populate extraction rates
    for r in extraction_results:
        dt = r["_id"]
        if dt not in by_type:
            continue
        
        total = r["total"] or 1
        by_type[dt]["extraction"]["vendor"]["count"] = r.get("has_vendor", 0)
        by_type[dt]["extraction"]["vendor"]["rate"] = round(r.get("has_vendor", 0) / total, 2)
        by_type[dt]["extraction"]["invoice_number"]["count"] = r.get("has_invoice_number", 0)
        by_type[dt]["extraction"]["invoice_number"]["rate"] = round(r.get("has_invoice_number", 0) / total, 2)
        by_type[dt]["extraction"]["amount"]["count"] = r.get("has_amount", 0)
        by_type[dt]["extraction"]["amount"]["rate"] = round(r.get("has_amount", 0) / total, 2)
        by_type[dt]["extraction"]["po_number"]["count"] = r.get("has_po_number", 0)
        by_type[dt]["extraction"]["po_number"]["rate"] = round(r.get("has_po_number", 0) / total, 2)
        by_type[dt]["extraction"]["due_date"]["count"] = r.get("has_due_date", 0)
        by_type[dt]["extraction"]["due_date"]["rate"] = round(r.get("has_due_date", 0) / total, 2)
        by_type[dt]["avg_confidence"] = round(r.get("avg_confidence", 0), 2)
    
    # Populate match methods
    for r in match_method_results:
        dt = r["_id"]["doc_type"]
        method = r["_id"]["match_method"]
        count = r["count"]
        
        if dt not in by_type:
            continue
        
        by_type[dt]["match_methods"][method] = count
    
    # Populate classification counts
    for r in classification_results:
        dt = r["_id"]
        if dt not in by_type:
            continue
        
        by_type[dt]["classification_counts"]["deterministic"] = r.get("deterministic_count", 0)
        by_type[dt]["classification_counts"]["ai"] = r.get("ai_count", 0)
        by_type[dt]["classification_counts"]["other"] = r.get("other_count", 0)
        by_type[dt]["ai_assisted_count"] = r.get("ai_assisted_count", 0)
        by_type[dt]["ai_suggested_but_rejected_count"] = r.get("ai_suggested_but_rejected_count", 0)
    
    # Build source system filter options
    source_systems = {r["_id"]: r["count"] for r in source_system_results}
    
    return {
        "by_type": by_type,
        "source_systems": source_systems,
        "source_system_filter": source_system,
        "doc_type_filter": doc_type,
        "classification_filter": classification
    }









# Spiro vendor matching routes moved to routes/spiro.py — REMOVED (Domain 6)

# BC company/sales-order routes moved to routers/bc_integration.py — REMOVED (Domain 5)

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

class DraftFeatureToggle(BaseModel):
    enabled: bool


# ==================== JOB TYPE MODELS ====================

class AutomationLevel:
    MANUAL_ONLY = 0       # Store + classify only, no auto-linking
    AUTO_LINK = 1         # Auto-link to existing BC records
    AUTO_CREATE_DRAFT = 2 # Create draft BC documents
    ADVANCED = 3          # Future: auto-populate lines, etc.

class POValidationMode:
    PO_REQUIRED = "PO_REQUIRED"           # PO must exist and match in BC
    PO_IF_PRESENT = "PO_IF_PRESENT"       # Validate PO if extracted, but don't fail if missing
    PO_NOT_REQUIRED = "PO_NOT_REQUIRED"   # Skip PO validation entirely

class VendorMatchMethod:
    EXACT_NO = "exact_no"           # Exact match on Vendor No
    EXACT_NAME = "exact_name"       # Exact match on Vendor Name
    NORMALIZED = "normalized"       # Normalized match (strip Inc, LLC, punctuation)
    ALIAS = "alias"                 # Alias lookup table
    FUZZY = "fuzzy"                 # Fuzzy match with score

VENDOR_ALIAS_MAP = {
    # "Alias on Invoice": "Vendor Name in BC"
    # Add company-specific aliases here
}

# ==================== MAILBOX SOURCE CONFIGURATION ====================

class MailboxSource(BaseModel):
    """Configuration for a document intake mailbox source."""
    mailbox_id: Optional[str] = None  # Auto-generated if not provided
    name: str  # Display name (e.g., "AP Invoices", "Sales Orders")
    email_address: str  # The mailbox to monitor
    category: str = "AP"  # Default category for documents from this mailbox (AP, Sales, etc.)
    enabled: bool = True
    polling_interval_minutes: int = 5
    watch_folder: str = "Inbox"
    needs_review_folder: str = "Needs Review"
    processed_folder: str = "Processed"
    description: Optional[str] = None
    created_utc: Optional[str] = None
    updated_utc: Optional[str] = None

# Email config schema (legacy - kept for backward compatibility)
class EmailWatchConfig(BaseModel):
    mailbox_address: str
    watch_folder: str = "Inbox"
    needs_review_folder: str = "Needs Review"
    processed_folder: str = "Processed"
    enabled: bool = True
    interval_minutes: int = 5  # Polling interval in minutes

class JobTypeConfig(BaseModel):
    job_type: str
    display_name: str
    automation_level: int = 1
    min_confidence_to_auto_link: float = 0.85
    min_confidence_to_auto_create_draft: float = 0.95
    # PO Validation: PO_REQUIRED, PO_IF_PRESENT, PO_NOT_REQUIRED
    po_validation_mode: str = "PO_IF_PRESENT"
    allow_duplicate_check_override: bool = False
    requires_human_review_if_exception: bool = True
    # Vendor matching
    vendor_match_threshold: float = 0.80
    vendor_match_strategies: List[str] = ["exact_no", "exact_name", "normalized", "fuzzy"]
    sharepoint_folder: str
    bc_entity: str
    required_extractions: List[str]
    optional_extractions: List[str] = []
    enabled: bool = True

class DocumentIntake(BaseModel):
    source: str = "email"
    sender: Optional[str] = None
    subject: Optional[str] = None
    attachment_name: str
    content_hash: str
    email_id: Optional[str] = None
    email_received_utc: Optional[str] = None

class AIClassificationResult(BaseModel):
    suggested_job_type: str
    confidence: float
    extracted_fields: dict
    validation_results: dict
    automation_decision: str  # "auto_link", "auto_create", "needs_review", "manual"
    reasoning: str

class ValidationCheck(BaseModel):
    check_name: str
    passed: bool
    details: str
    required: bool = True

# ==================== AI CLASSIFICATION SERVICE ====================

async def classify_document_with_ai(file_path: str, file_name: str) -> dict:
    """Compatibility wrapper — delegates to document_intel_helpers."""
    from services.document_intel_helpers import classify_document_with_ai as _impl
    return await _impl(file_path, file_name)

# ==================== FIELD NORMALIZATION ====================

def normalize_extracted_fields(fields: dict) -> dict:
    """Compatibility wrapper — delegates to document_intel_helpers."""
    from services.document_intel_helpers import normalize_extracted_fields as _impl
    return _impl(fields)


def compute_ap_normalized_fields(extracted_fields: dict) -> dict:
    """Compatibility wrapper — delegates to document_intel_helpers."""
    from services.document_intel_helpers import compute_ap_normalized_fields as _impl
    return _impl(extracted_fields)

async def lookup_vendor_alias(vendor_normalized: str) -> dict:
    """
    Phase 7: Look up vendor in alias collection, BC cache, or live BC API.
    
    Returns:
    - vendor_canonical: the canonical_vendor_id if found, else None
    - vendor_match_method: "alias", "exact_name", "bc_search", "fuzzy_bc", or "none"
    - vendor_name: matched vendor name
    - vendor_no: matched vendor number
    """
    if not vendor_normalized:
        return {"vendor_canonical": None, "vendor_match_method": "none"}
    
    # Check vendor_aliases collection
    alias_doc = await db.vendor_aliases.find_one({
        "$or": [
            {"normalized": vendor_normalized},
            {"normalized_alias": vendor_normalized},
            {"alias_string": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}}
        ]
    }, {"_id": 0})
    
    if alias_doc:
        canonical_id = alias_doc.get("canonical_vendor_id") or alias_doc.get("vendor_no") or alias_doc.get("vendor_name")
        return {
            "vendor_canonical": canonical_id,
            "vendor_match_method": "alias",
            "vendor_name": alias_doc.get("vendor_name"),
            "vendor_no": alias_doc.get("vendor_no")
        }
    
    # Check if exact match in cached BC vendors (if available)
    bc_vendor = await db.hub_bc_vendors.find_one({
        "$or": [
            {"name_normalized": vendor_normalized},
            {"displayName": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}}
        ]
    }, {"_id": 0})
    
    if bc_vendor:
        return {
            "vendor_canonical": bc_vendor.get("number") or bc_vendor.get("id"),
            "vendor_match_method": "exact_name",
            "vendor_name": bc_vendor.get("displayName"),
            "vendor_no": bc_vendor.get("number")
        }
    
    # Try live BC search with different search terms
    try:
        # Get the original vendor name (before normalization) for better matching
        vendor_search_term = vendor_normalized.title()  # Convert to title case
        
        # Try BC API search
        bc_result = await search_vendors_by_name(vendor_search_term, limit=10)
        
        if bc_result.status == BCLookupStatus.SUCCESS:
            vendors = bc_result.data.get("vendors", [])
            
            if vendors:
                # Try to find best match
                for vendor in vendors:
                    bc_name = vendor.get("displayName", "").lower()
                    # Check if normalized names match (case-insensitive)
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    if bc_normalized == vendor_normalized:
                        # Exact match found
                        return {
                            "vendor_canonical": vendor.get("number") or vendor.get("id"),
                            "vendor_match_method": "bc_search",
                            "vendor_name": vendor.get("displayName"),
                            "vendor_no": vendor.get("number")
                        }
                
                # If no exact match, try fuzzy matching
                best_match = None
                best_score = 0
                
                for vendor in vendors:
                    bc_name = vendor.get("displayName", "").lower()
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    # Simple similarity: check if all words from search are in BC name or vice versa
                    search_words = set(vendor_normalized.split())
                    bc_words = set(bc_normalized.split())
                    
                    # Calculate overlap score
                    overlap = len(search_words & bc_words)
                    total = len(search_words | bc_words)
                    score = overlap / total if total > 0 else 0
                    
                    if score > best_score and score >= 0.6:  # At least 60% overlap
                        best_score = score
                        best_match = vendor
                
                if best_match:
                    return {
                        "vendor_canonical": best_match.get("number") or best_match.get("id"),
                        "vendor_match_method": "fuzzy_bc",
                        "vendor_name": best_match.get("displayName"),
                        "vendor_no": best_match.get("number"),
                        "match_score": best_score
                    }
        
        # Try with first word only (company name often starts with key identifier)
        first_word = vendor_normalized.split()[0] if vendor_normalized else ""
        if first_word and len(first_word) >= 3:
            bc_result2 = await search_vendors_by_name(first_word.title(), limit=10)
            
            if bc_result2.status == BCLookupStatus.SUCCESS:
                vendors2 = bc_result2.data.get("vendors", [])
                
                for vendor in vendors2:
                    bc_name = vendor.get("displayName", "").lower()
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    # Check if vendor name starts with same word
                    if bc_normalized.startswith(first_word):
                        search_words = set(vendor_normalized.split())
                        bc_words = set(bc_normalized.split())
                        overlap = len(search_words & bc_words)
                        total = len(search_words | bc_words)
                        score = overlap / total if total > 0 else 0
                        
                        if score >= 0.5:  # At least 50% overlap for partial match
                            return {
                                "vendor_canonical": vendor.get("number") or vendor.get("id"),
                                "vendor_match_method": "fuzzy_bc",
                                "vendor_name": vendor.get("displayName"),
                                "vendor_no": vendor.get("number"),
                                "match_score": score
                            }
                            
    except Exception as e:
        logger.warning(f"BC vendor search failed: {e}")
    
    return {"vendor_canonical": None, "vendor_match_method": "none"}


async def check_duplicate_document(vendor_normalized: str, vendor_canonical: str, invoice_number_clean: str, current_doc_id: str) -> dict:
    """
    Phase 7: Check for potential duplicate AP invoice in the Hub.
    
    A document is a possible duplicate if another non-deleted doc exists with:
    - same vendor_canonical (if set) OR same vendor_normalized
    - same invoice_number_clean
    
    Returns:
    - possible_duplicate: boolean
    - duplicate_of_document_id: id of existing doc or None
    """
    if not invoice_number_clean:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}
    
    # Build query
    vendor_match = {}
    if vendor_canonical:
        vendor_match = {"$or": [
            {"vendor_canonical": vendor_canonical},
            {"vendor_normalized": vendor_normalized}
        ]}
    elif vendor_normalized:
        vendor_match = {"vendor_normalized": vendor_normalized}
    else:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}
    
    query = {
        **vendor_match,
        "invoice_number_clean": invoice_number_clean,
        "id": {"$ne": current_doc_id},  # Exclude current document
        "status": {"$nin": ["Deleted", "Rejected"]}  # Exclude deleted
    }
    
    existing = await db.hub_documents.find_one(query, {"id": 1, "_id": 0})
    
    if existing:
        return {
            "possible_duplicate": True,
            "duplicate_of_document_id": existing.get("id")
        }
    
    return {"possible_duplicate": False, "duplicate_of_document_id": None}


def compute_ap_validation(
    document_type: str,
    vendor_normalized: str,
    invoice_number_clean: str,
    amount_float: float,
    po_number_clean: str,
    ai_confidence: float,
    possible_duplicate: bool
) -> dict:
    """
    Phase 7: Compute validation_errors, validation_warnings, and draft_candidate for AP invoices.
    
    Required fields for AP invoice header readiness:
    - vendor_normalized
    - invoice_number_clean
    - amount_float
    
    draft_candidate = True when all three required fields are present and valid
    
    This does NOT create drafts or change status logic (handled separately).
    """
    validation_errors = []
    validation_warnings = []
    
    # Only process AP_Invoice documents
    if document_type not in ("AP_Invoice", "AP Invoice"):
        return {
            "draft_candidate": False,
            "validation_errors": [],
            "validation_warnings": []
        }
    
    # Check required fields
    if not vendor_normalized:
        validation_errors.append("missing_vendor")
    
    if not invoice_number_clean:
        validation_errors.append("missing_invoice_number")
    
    if amount_float is None:
        validation_errors.append("missing_amount")
    
    # Check confidence
    if ai_confidence is not None and ai_confidence < 0.90:
        validation_errors.append("low_classification_confidence")
    
    # Check duplicate
    if possible_duplicate:
        validation_errors.append("potential_duplicate_invoice")
    
    # Warnings (non-blocking)
    if not po_number_clean:
        validation_warnings.append("missing_po_number")
    
    # draft_candidate is True only when all required fields present and no errors
    draft_candidate = (
        len(validation_errors) == 0 and
        vendor_normalized is not None and
        invoice_number_clean is not None and
        amount_float is not None
    )
    
    return {
        "draft_candidate": draft_candidate,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings
    }


def compute_ap_status(
    document_type: str,
    ai_confidence: float,
    validation_errors: list,
    draft_candidate: bool,
    current_status: str
) -> str:
    """
    Phase 7: Determine status for AP_Invoice documents.
    
    Status logic (observation mode - conservative):
    - If not AP_Invoice: unchanged (let other workflows handle)
    - If ai_confidence < 0.90: NeedsReview
    - If any validation_errors: NeedsReview
    - Else (no errors, draft_candidate=True): NeedsReview (but draft_candidate flag visible)
    
    In Phase 7, we do NOT auto-advance to any status that triggers BC writes.
    """
    if document_type not in ("AP_Invoice", "AP Invoice"):
        return current_status  # Unchanged for non-AP
    
    # All AP_Invoice documents stay in NeedsReview during Phase 7
    # The draft_candidate flag indicates readiness without changing status
    return "NeedsReview"


# Legacy wrapper for backward compatibility
def compute_canonical_fields(extracted_fields: dict) -> dict:
    """Legacy wrapper - calls compute_ap_normalized_fields"""
    return compute_ap_normalized_fields(extracted_fields)


def compute_draft_candidate_flag(
    document_type: str,
    extracted_fields: dict,
    canonical_fields: dict,
    ai_confidence: float
) -> dict:
    """
    Legacy wrapper for backward compatibility.
    Now delegates to compute_ap_validation.
    """
    # Extract normalized values
    vendor_normalized = canonical_fields.get("vendor_normalized")
    invoice_number_clean = canonical_fields.get("invoice_number_clean")
    amount_float = canonical_fields.get("amount_float")
    po_number_clean = canonical_fields.get("po_number_clean")
    
    result = compute_ap_validation(
        document_type=document_type,
        vendor_normalized=vendor_normalized,
        invoice_number_clean=invoice_number_clean,
        amount_float=amount_float,
        po_number_clean=po_number_clean,
        ai_confidence=ai_confidence,
        possible_duplicate=False  # Legacy doesn't have this
    )
    
    # Map to legacy format
    return {
        "draft_candidate": result["draft_candidate"],
        "draft_candidate_reason": result["validation_errors"] + result["validation_warnings"],
        "draft_candidate_score": 100.0 if result["draft_candidate"] else 0.0
    }


def normalize_vendor_name(name: str) -> str:
    """
    Normalize vendor name for matching.
    Strips common suffixes, punctuation, and converts to lowercase.
    """
    if not name:
        return ""
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove common business suffixes
    suffixes = [
        r'\s*,?\s*(inc\.?|incorporated)$',
        r'\s*,?\s*(llc\.?|l\.l\.c\.?)$',
        r'\s*,?\s*(ltd\.?|limited)$',
        r'\s*,?\s*(corp\.?|corporation)$',
        r'\s*,?\s*(co\.?|company)$',
        r'\s*,?\s*(plc\.?)$',
        r'\s*,?\s*(gmbh)$',
        r'\s*,?\s*(ag)$',
    ]
    
    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    
    # Remove punctuation and extra spaces
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def calculate_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy match score between two strings.
    Uses simple token overlap ratio.
    Also handles BC vendor names that include vendor codes like "TUMALOC - Tumalo Creek"
    """
    if not name1 or not name2:
        return 0.0
    
    # Strip potential vendor code prefixes (e.g., "TUMALOC - " from "TUMALOC - Tumalo Creek")
    # BC sometimes stores vendors as "CODE - Name"
    def clean_bc_name(name):
        n = name
        if ' - ' in n:
            # Try removing code prefix
            parts = n.split(' - ', 1)
            if len(parts) == 2 and len(parts[0]) <= 10:  # Short code prefix
                n = parts[1]
        return n
    
    name1_clean = clean_bc_name(name1)
    name2_clean = clean_bc_name(name2)
    
    tokens1 = set(normalize_vendor_name(name1_clean).split())
    tokens2 = set(normalize_vendor_name(name2_clean).split())
    
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    
    base_score = len(intersection) / len(union)
    
    # Also try matching original names (in case the code IS the match)
    orig_tokens1 = set(normalize_vendor_name(name1).split())
    orig_tokens2 = set(normalize_vendor_name(name2).split())
    orig_intersection = orig_tokens1 & orig_tokens2
    orig_union = orig_tokens1 | orig_tokens2
    orig_score = len(orig_intersection) / len(orig_union) if orig_union else 0
    
    # Return the better of the two scores
    return max(base_score, orig_score)

# ==================== BC MATCHING SERVICE ====================

async def match_vendor_in_bc(
    vendor_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """
    Multi-strategy vendor matching against BC.
    Uses server-side filtering for efficient matching.
    Returns candidates and best match.
    """
    result = {
        "matched": False,
        "match_method": None,
        "selected_vendor": None,
        "vendor_candidates": [],
        "score": 0.0
    }
    
    if not vendor_name:
        return result
    
    normalized_input = normalize_vendor_name(vendor_name)
    
    # Extract key search terms for server-side filtering
    # Use the longest word (likely the most distinctive) for filtering
    search_terms = [w for w in normalized_input.split() if len(w) >= 3]
    primary_search_term = max(search_terms, key=len) if search_terms else None
    
    async with httpx.AsyncClient(timeout=30.0) as c:
        vendors = []
        
        # Strategy 1: Try server-side search with contains() filter
        # Use BC_READ_ENVIRONMENT for reads (Production)
        if primary_search_term and len(primary_search_term) >= 4:
            # Use OData $filter to narrow down results server-side
            filter_query = f"contains(displayName, '{primary_search_term}')"
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$filter": filter_query, "$top": "100"}
            )
            
            if resp.status_code == 200:
                vendors = resp.json().get("value", [])
                logger.info("BC vendor search for '%s' returned %d candidates (env=%s)", primary_search_term, len(vendors), BC_READ_ENVIRONMENT)
        
        # Strategy 2: If no results from filtered search, fall back to broader fetch
        if not vendors:
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$top": "1000"}
            )
            
            if resp.status_code != 200:
                return result
            
            vendors = resp.json().get("value", [])
        
        # Check alias map first (case-insensitive)
        if "alias" in strategies:
            # Try exact match, then lowercase, then normalized
            alias_target = (
                VENDOR_ALIAS_MAP.get(vendor_name) or 
                VENDOR_ALIAS_MAP.get(vendor_name.lower()) or 
                VENDOR_ALIAS_MAP.get(normalized_input)
            )
            if alias_target:
                # alias_target is the vendor_name or vendor_no from the alias
                for v in vendors:
                    v_display = v.get("displayName", "")
                    v_number = v.get("number", "")
                    # Match against vendor name or number
                    if (v_display.lower() == alias_target.lower() or 
                        v_number.lower() == alias_target.lower()):
                        result["matched"] = True
                        result["match_method"] = "alias"
                        result["selected_vendor"] = v
                        result["score"] = 1.0
                        return result
        
        # Try each strategy in order
        candidates = []
        
        for vendor in vendors:
            vendor_display = vendor.get("displayName", "")
            vendor_number = vendor.get("number", "")
            
            # Exact match on number
            if "exact_no" in strategies:
                if vendor_number.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_no"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Exact match on name
            if "exact_name" in strategies:
                if vendor_display.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_name"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Normalized match
            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(vendor_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_vendor"] = vendor
                    result["score"] = 0.95
                    return result
            
            # Fuzzy match - collect all candidates
            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(vendor_name, vendor_display)
                if score > 0.3:  # Minimum threshold for candidate list
                    candidates.append({
                        "vendor": vendor,
                        "score": score,
                        "display_name": vendor_display,
                        "vendor_id": vendor.get("id")
                    })
        
        # Sort candidates by score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["vendor_candidates"] = candidates[:5]  # Top 5
        
        # Check if best fuzzy match meets threshold
        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_vendor"] = candidates[0]["vendor"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            # Have candidates but below threshold - needs review
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0
    
    return result

async def match_customer_in_bc(
    customer_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """Compatibility wrapper — delegates to bc_validation_service."""
    from services.bc_validation_service import _match_customer_in_bc, _normalize_vendor_name
    from services.bc_access import get_bc_adapter
    adapter = get_bc_adapter()
    def _api_url(resource, cid=company_id):
        return adapter.api_url(resource, cid)
    return await _match_customer_in_bc(
        customer_name, strategies, threshold, token, company_id, _api_url,
    )

async def validate_bc_match(job_type: str, extracted_fields: dict, job_config: dict) -> dict:
    """Compatibility wrapper — delegates to bc_validation_service."""
    from services.bc_validation_service import validate_bc_match as _impl
    return await _impl(job_type, extracted_fields, job_config)

# ==================== AUTOMATION DECISION ENGINE ====================

def make_automation_decision(
    job_config: dict,
    ai_confidence: float,
    validation_results: dict
) -> tuple:
    """Compatibility wrapper — delegates to document_intel_helpers."""
    from services.document_intel_helpers import make_automation_decision as _impl
    return _impl(job_config, ai_confidence, validation_results)

async def get_email_watcher_config() -> dict:
    """Load email watcher configuration from database."""
    config = await db.hub_config.find_one({"_key": "email_watcher"}, {"_id": 0})
    if not config:
        return {
            "mailbox_address": "",
            "watch_folder": "Inbox",
            "needs_review_folder": "Needs Review",
            "processed_folder": "Processed",
            "enabled": False,
            "interval_minutes": 5,
            "webhook_subscription_id": None,
            "last_poll_utc": None
        }
    # Ensure interval_minutes has a default
    if "interval_minutes" not in config:
        config["interval_minutes"] = 5
    return config

async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """
    Create a Microsoft Graph subscription for email notifications.
    """
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "message": "Running in demo mode"}
    
    try:
        token = await get_graph_token()
        
        # Create subscription for new messages
        subscription_payload = {
            "changeType": "created",
            "notificationUrl": webhook_url,
            "resource": f"users/{mailbox_address}/mailFolders/Inbox/messages",
            "expirationDateTime": (datetime.now(timezone.utc).replace(hour=23, minute=59) + timedelta(days=2)).isoformat() + "Z",
            "clientState": "gpi-document-hub-secret"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(
                "https://graph.microsoft.com/v1.0/subscriptions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=subscription_payload
            )
            
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "status": "ok",
                    "subscription_id": data.get("id"),
                    "expiration": data.get("expirationDateTime")
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create subscription (HTTP {resp.status_code}): {resp.text[:500]}"
                }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def fetch_email_with_attachments(email_id: str, mailbox_address: str) -> dict:
    """Fetch a specific email and its attachments from Graph API."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo", "email": None, "attachments": []}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=60.0) as c:
            # Get email details
            email_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if email_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to fetch email: {email_resp.status_code}"}
            
            email_data = email_resp.json()
            
            # Get attachments
            attachments_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/attachments",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            attachments = []
            if attachments_resp.status_code == 200:
                for att in attachments_resp.json().get("value", []):
                    if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                        attachments.append({
                            "id": att.get("id"),
                            "name": att.get("name"),
                            "content_type": att.get("contentType"),
                            "size": att.get("size"),
                            "content_bytes": att.get("contentBytes")  # Base64 encoded
                        })
            
            return {
                "status": "ok",
                "email": {
                    "id": email_data.get("id"),
                    "subject": email_data.get("subject"),
                    "sender": email_data.get("from", {}).get("emailAddress", {}).get("address"),
                    "received_utc": email_data.get("receivedDateTime"),
                    "has_attachments": email_data.get("hasAttachments", False)
                },
                "attachments": attachments
            }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def move_email_to_folder(email_id: str, mailbox_address: str, folder_name: str) -> dict:
    """Move an email to a specific folder."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return {"status": "demo"}
    
    try:
        token = await get_graph_token()
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            # First, find the folder ID
            folders_resp = await c.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if folders_resp.status_code != 200:
                return {"status": "error", "message": f"Failed to list folders: {folders_resp.status_code}"}
            
            folder_id = None
            for folder in folders_resp.json().get("value", []):
                if folder.get("displayName") == folder_name:
                    folder_id = folder.get("id")
                    break
            
            if not folder_id:
                # Create the folder if it doesn't exist
                create_resp = await c.post(
                    f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json={"displayName": folder_name}
                )
                if create_resp.status_code in (200, 201):
                    folder_id = create_resp.json().get("id")
                else:
                    return {"status": "error", "message": f"Failed to create folder: {create_resp.status_code}"}
            
            # Move the email
            move_resp = await c.post(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{email_id}/move",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={"destinationId": folder_id}
            )
            
            if move_resp.status_code in (200, 201):
                return {"status": "ok", "folder": folder_name}
            else:
                return {"status": "error", "message": f"Failed to move email: {move_resp.status_code}"}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==================== AUTOMATIC WORKFLOW TRIGGER ====================

async def on_document_ingested(doc_id: str, source: str = "unknown"):
    """
    Triggered automatically after every successful document ingestion.
    Runs validation workflow and creates audit trail.
    
    Called by all ingestion paths:
    - Manual upload
    - Email polling  
    - Backfill
    - API upload
    
    Safety: Does NOT create BC drafts in Phase 7 (controlled by ENABLE_CREATE_DRAFT_HEADER flag)
    """
    run_id = uuid.uuid4().hex[:8]
    correlation_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    
    logger.info("[Workflow:%s] Auto-triggered for doc %s (source: %s)", run_id, doc_id, source)
    
    try:
        # Get document
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            logger.error("[Workflow:%s] Document not found: %s", run_id, doc_id)
            return
        
        old_status = doc.get("status", "Unknown")
        job_type = doc.get("suggested_job_type", "AP_Invoice")
        extracted_fields = doc.get("extracted_fields", {})
        
        # Get job config
        job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])
        
        # Run BC validation
        validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
        
        # Make automation decision
        confidence = doc.get("ai_confidence", 0.0)
        decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
        
        # Determine new status based on decision
        new_status = old_status
        if decision == "auto_link" and validation_results.get("all_passed"):
            new_status = "ReadyToLink"
        elif decision == "needs_review":
            new_status = "NeedsReview"
        elif decision == "manual":
            new_status = "NeedsReview"
        elif decision == "exception":
            new_status = "Exception"
        
        # Update document
        update_data = {
            "validation_results": validation_results,
            "automation_decision": decision,
            "match_method": validation_results.get("match_method", "none"),
            "match_score": validation_results.get("match_score", 0.0),
            "vendor_candidates": decision_metadata.get("vendor_candidates", []),
            "customer_candidates": decision_metadata.get("customer_candidates", []),
            "warnings": decision_metadata.get("warnings", []),
            "status": new_status,
            "workflow_state": "Validated",
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }
        
        await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
        
        # Create workflow audit trail entry
        duration = (datetime.now(timezone.utc) - started_at).total_seconds()
        
        await db.hub_workflow_runs.insert_one({
            "run_id": run_id,
            "correlation_id": correlation_id,
            "document_id": doc_id,
            "workflow_type": "auto_validation",
            "source": source,
            "status": "Completed",
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
            "steps": [
                {
                    "step": "Validation",
                    "status": "Completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": {
                        "old_status": old_status,
                        "new_status": new_status,
                        "match_method": validation_results.get("match_method", "none"),
                        "match_score": validation_results.get("match_score", 0.0),
                        "automation_decision": decision,
                        "reasoning": reasoning
                    }
                }
            ]
        })
        
        logger.info("[Workflow:%s] Complete: %s → %s (decision: %s, score: %.2f)", 
                    run_id, old_status, new_status, decision, validation_results.get("match_score", 0.0))
        
    except Exception as e:
        # Log error but don't fail silently - create an error audit entry
        logger.error("[Workflow:%s] Error processing doc %s: %s", run_id, doc_id, str(e))
        
        try:
            await db.hub_workflow_runs.insert_one({
                "run_id": run_id,
                "correlation_id": correlation_id,
                "document_id": doc_id,
                "workflow_type": "auto_validation",
                "source": source,
                "status": "Failed",
                "started_at": started_at.isoformat(),
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "steps": []
            })
        except:
            pass  # Don't let audit logging failure mask the original error


# ==================== EMAIL INTAKE ENDPOINTS ====================

async def _update_standard_workflow_status(
    doc_id: str,
    doc_type: str,
    confidence: float,
    normalized_fields: Dict
):
    """
    Update workflow status for non-AP document types.
    Implements Square9-style workflow for warehouse and sales documents.
    
    Warehouse Workflow (SHIPMENT, RECEIPT):
    - Import -> Classification -> PO Validation -> Location Validation -> Export
    
    Sales Workflow (SALES_ORDER, SALES_INVOICE):
    - Import -> Classification -> Customer Match -> BC Validation -> Export/Create
    """
    from services.square9_workflow import (
        initialize_retry_state, increment_retry, validate_location_code,
        validate_required_fields, determine_square9_stage, Square9Stage,
        reset_retry_counter
    )
    
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Initialize retry state if not present
    if "retry_count" not in doc:
        retry_state = initialize_retry_state(doc)
        doc.update(retry_state)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": retry_state})
    
    # Step 1: Classification done - move from captured to classified
    if confidence > 0:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
            context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
        )
    else:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value,
            context={"reason": "Classification failed or returned Unknown"}
        )
        # Save and return early for failed classification
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": doc.get("workflow_status"),
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "square9_stage": Square9Stage.UNCLASSIFIED.value
            }}
        )
        return
    
    # =============== WAREHOUSE WORKFLOW (Square9-aligned) ===============
    # Follows Square9 diagram exactly:
    # 1. PO Number Is Empty? -> Set WF Status to "Missing PO Number"
    # 2. Invoice Number Is Empty? -> Set WF Status to "Missing Invoice Number" (BOL# for shipping)
    # 3. Document Date Is Empty? -> Set WF Status to "Missing Location"
    # 4. Counter >= 4? -> Delete Document
    # 5. All pass -> Send to SharePoint
    
    if doc_type in [DocType.SHIPMENT.value, DocType.RECEIPT.value, "Shipping_Document", "Warehouse_Document"]:
        
        # Helper function to handle validation failure with retry/delete logic
        async def handle_warehouse_validation_failure(doc, doc_id, field_name, stage, status_label):
            """Handle validation failure - increment retry, delete if max reached"""
            update_dict, should_delete, message = increment_retry(doc, status_label, stage)
            
            if should_delete and update_dict.get("square9_stage") == Square9Stage.DELETED.value:
                # Counter >= 4: DELETE DOCUMENT (Square9 behavior)
                logger.warning("[Warehouse Workflow] Doc %s: MAX RETRIES REACHED - DELETING. Reason: %s", doc_id, status_label)
                await db.hub_documents.delete_one({"id": doc_id})
                # Also delete from workflows collection
                await db.hub_workflows.delete_many({"document_id": doc_id})
                return True  # Document deleted
            else:
                # Counter < 4: Set status and wait for retry
                update_dict["workflow_status"] = "data_correction_pending"
                update_dict["status"] = "NeedsReview"
                update_dict["square9_stage"] = stage
                update_dict["workflow_status_updated_utc"] = now
                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
                logger.info("[Warehouse Workflow] Doc %s: %s - %s", doc_id, status_label, message)
                return False  # Document not deleted, needs review
        
        # Extract fields
        po_number = (normalized_fields.get("po_number_clean") or 
                    normalized_fields.get("po_number_raw") or 
                    normalized_fields.get("po_number"))
        
        # For shipping docs, "Invoice Number" = BOL Number
        bol_number = (normalized_fields.get("bol_number") or 
                     normalized_fields.get("tracking_number") or
                     normalized_fields.get("pro_number"))
        
        # Document Date = Ship Date
        document_date = (normalized_fields.get("ship_date") or 
                        normalized_fields.get("document_date") or
                        normalized_fields.get("delivery_date"))
        
        # ===== STEP 1: PO Number Is Empty? =====
        if not po_number or str(po_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "po_number", 
                Square9Stage.MISSING_PO.value, 
                "Missing PO Number"
            )
            if deleted:
                return  # Document was deleted
            return  # Needs review
        
        # ===== STEP 2: Invoice Number (BOL#) Is Empty? =====
        if not bol_number or str(bol_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "bol_number",
                Square9Stage.MISSING_INVOICE.value,
                "Missing Invoice Number"  # Square9 label (BOL# for shipping docs)
            )
            if deleted:
                return
            return
        
        # ===== STEP 3: Document Date Is Empty? -> "Missing Location" (Square9 quirk) =====
        if not document_date or str(document_date).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "document_date",
                Square9Stage.MISSING_LOCATION.value,  # Square9 uses "Missing Location" for date
                "Missing Location"  # Square9 label
            )
            if deleted:
                return
            return
        
        # ===== ALL VALIDATIONS PASSED - Send to SharePoint =====
        
        # Location code validation (optional, use fallback if missing)
        location_code = normalized_fields.get("location_code") or normalized_fields.get("warehouse")
        is_valid_location, location_msg, resolved_location = validate_location_code(location_code, doc_type)
        
        if not is_valid_location:
            normalized_fields["location_code_resolved"] = resolved_location
            logger.info("[Warehouse Workflow] Doc %s: %s - using fallback: %s", doc_id, location_msg, resolved_location)
        
        # Reset retry counter on success
        reset_update = reset_retry_counter(doc, "Validation passed")
        
        # Advance workflow to exported
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Warehouse document validated - PO, BOL, Date all present"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Warehouse validation complete - sending to SharePoint"}
        )
        
        # Mark as completed and archived
        final_update = {
            **reset_update,
            "workflow_status": "exported",
            "status": "Completed",
            "square9_stage": Square9Stage.EXPORTED.value,
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "location_code_resolved": resolved_location if not is_valid_location else location_code,
            "bol_number_extracted": bol_number,
            "po_number_extracted": po_number,
            "document_date_extracted": document_date,
            "archived": True,
            "archived_utc": now
        }
        
        await db.hub_documents.update_one({"id": doc_id}, {"$set": final_update})
        logger.info("[Warehouse Workflow] Doc %s: COMPLETED - PO=%s, BOL=%s, Date=%s, archived to SharePoint", 
                   doc_id, po_number, bol_number, document_date)
        return
    
    # =============== SALES WORKFLOW ===============
    elif doc_type in [DocType.SALES_ORDER.value, DocType.SALES_INVOICE.value, "SalesOrder", "SalesInvoice"]:
        # Step 2: Check Customer
        customer = normalized_fields.get("customer") or normalized_fields.get("customer_raw")
        if not customer:
            update_dict, escalated, message = increment_retry(doc, "Missing Customer", Square9Stage.MISSING_VENDOR.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_VENDOR.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Customer - %s", doc_id, message)
            return
        
        # Step 3: Check Order/Invoice Number
        order_number = (normalized_fields.get("order_number") or 
                       normalized_fields.get("invoice_number_clean") or
                       normalized_fields.get("customer_po"))
        if not order_number:
            update_dict, escalated, message = increment_retry(doc, "Missing Order/Invoice Number", Square9Stage.MISSING_INVOICE.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_INVOICE.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Order Number - %s", doc_id, message)
            return
        
        # All sales validations passed - mark as validated
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Sales document validated successfully"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Sales validation complete - ready for BC creation"}
        )
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": "validated",
                "status": "Validated",
                "square9_stage": Square9Stage.VALID.value,
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "bc_create_ready": True,
                "customer_extracted": customer,
                "order_number_extracted": order_number
            }}
        )
        logger.info("[Sales Workflow] Doc %s: VALIDATED - ready for BC Sales Order creation", doc_id)
        
        # AUTO-CREATE: Attempt to create BC Sales Order
        if AUTO_CREATE_SALES_ORDER_ENABLED:
            try:
                # Refresh document after validation update
                updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if updated_doc:
                    bc_service = get_bc_service()
                    auto_create_result = await attempt_auto_create_sales_order(doc_id, updated_doc, db, bc_service)
                    
                    if auto_create_result.eligible:
                        if auto_create_result.success:
                            logger.info("AUTO-CREATE: Document %s auto-created as BC Sales Order %s", 
                                       doc_id, auto_create_result.bc_document_number)
                        else:
                            logger.warning("AUTO-CREATE: Document %s eligible but failed: %s", 
                                          doc_id, auto_create_result.error)
                    else:
                        logger.debug("AUTO-CREATE: Document %s not eligible: %s", 
                                    doc_id, auto_create_result.reason)
            except Exception as e:
                logger.error("AUTO-CREATE: Exception for %s: %s", doc_id, str(e))
        
        return
    
    # =============== DEFAULT/OTHER WORKFLOW ===============
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized") or normalized_fields.get("vendor_raw")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    # For non-AP types, we're more lenient on required fields
    has_basic_data = any([vendor, invoice_number, amount is not None])
    
    if not has_basic_data or confidence < 0.3:
        # Low confidence or no data - needs review
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_FAILED.value,
            context={
                "reason": "Extraction incomplete or very low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        
        # For standard workflow types (not AP), skip vendor/BC validation
        # Move directly to ready_for_approval or auto-approve based on doc_type
        if doc_type in [DocType.STATEMENT.value, DocType.REMINDER.value, 
                        DocType.FINANCE_CHARGE_MEMO.value, DocType.QUALITY_DOC.value,
                        DocType.OTHER.value]:
            # Simplified types can go directly to extracted -> exportable
            pass  # Stay at extracted, can be approved/exported manually
        else:
            # Standard business docs (Sales, PO, Credit Memo) advance to ready_for_approval
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_REVIEW_COMPLETE.value,
                context={"reason": f"Automatic review complete for {doc_type}"}
            )
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "square9_stage": determine_square9_stage(doc)
        }}
    )


async def _update_ap_workflow_status(
    doc_id: str,
    confidence: float,
    normalized_fields: Dict,
    vendor_alias_result: Dict,
    validation_results: Dict,
    ap_validation: Dict
):
    """
    Update workflow status for AP_Invoice documents based on processing results.
    This implements the Square9-style workflow routing.
    """
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    workflow_updates = []
    
    # Step 1: Classification done - move from captured to classified
    WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
        context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
    )
    workflow_updates.append("classified")
    
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    if not all([vendor, invoice_number, amount is not None]) or confidence < 0.5:
        # Low confidence or missing required fields - needs data correction
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value,
            context={
                "reason": "Extraction incomplete or low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
        workflow_updates.append("data_correction_pending")
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        workflow_updates.append("extracted")
        
        # Step 3: Check vendor match
        vendor_canonical = vendor_alias_result.get("vendor_canonical")
        vendor_match_method = vendor_alias_result.get("vendor_match_method")
        
        if not vendor_canonical or vendor_match_method == "none":
            # Vendor not matched - needs manual resolution
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MISSING.value,
                context={
                    "reason": "Vendor could not be matched automatically",
                    "metadata": {"vendor_raw": normalized_fields.get("vendor_raw")}
                }
            )
            workflow_updates.append("vendor_pending")
        else:
            # Vendor matched
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MATCHED.value,
                context={
                    "reason": f"Vendor matched via {vendor_match_method}",
                    "metadata": {
                        "vendor_canonical": vendor_canonical,
                        "match_method": vendor_match_method
                    }
                }
            )
            workflow_updates.append("bc_validation_pending")
            
            # Step 4: Check BC validation
            all_passed = validation_results.get("all_passed", False)
            draft_candidate = ap_validation.get("draft_candidate", False)
            
            if all_passed or draft_candidate:
                # BC validation passed - ready for approval
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_VALID.value,
                    context={
                        "reason": "BC validation passed",
                        "metadata": {
                            "all_passed": all_passed,
                            "draft_candidate": draft_candidate
                        }
                    }
                )
                workflow_updates.append("ready_for_approval")
            else:
                # BC validation failed
                validation_errors = ap_validation.get("validation_errors", [])
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_INVALID.value,
                    context={
                        "reason": "BC validation failed",
                        "metadata": {"validation_errors": validation_errors}
                    }
                )
                workflow_updates.append("bc_validation_failed")
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now
        }}
    )
    
    logger.info("[Workflow] Document %s workflow updated: %s", doc_id, " -> ".join(workflow_updates))


async def classify_document_type(
    document: Dict,
    extracted_fields: Dict,
    suggested_type: str,
    confidence: float,
    metadata: Optional[Dict] = None
) -> Dict:
    """
    Deterministic-first document type classification pipeline.
    
    Step 1: Run deterministic rules (Zetadocs codes, Square9 workflows, mailbox category)
    Step 2: If doc_type is not OTHER, keep it and skip AI
    Step 3: If doc_type is OTHER and AI classification is enabled, try AI
    Step 4: Apply AI result if confidence >= threshold
    
    Args:
        document: The document dict
        extracted_fields: Fields extracted from the document
        suggested_type: Legacy suggested_job_type from classification
        confidence: Legacy AI classification confidence
        metadata: Additional metadata (zetadocs_set, square9_workflow, mailbox_category)
    
    Returns:
        Dict with doc_type, category, ai_classification (if used)
    """
    metadata = metadata or {}
    result = {
        "doc_type": DocType.OTHER.value,
        "category": "Other",
        "ai_classification": None,
        "classification_method": "default"
    }
    
    # Step 1a: Check Zetadocs set code
    zetadocs_set = metadata.get("zetadocs_set") or document.get("zetadocs_set_code")
    if zetadocs_set:
        doc_type, capture_channel = DocumentClassifier.classify_from_zetadocs_set(zetadocs_set)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"zetadocs:{zetadocs_set}"
            logger.info("Deterministic classification: Zetadocs set %s -> %s", zetadocs_set, doc_type.value)
    
    # Step 1b: Check Square9 workflow name
    if result["doc_type"] == DocType.OTHER.value:
        square9_workflow = metadata.get("square9_workflow") or document.get("square9_workflow_name")
        if square9_workflow:
            doc_type = DocumentClassifier.classify_from_square9_workflow(square9_workflow)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"square9:{square9_workflow}"
                logger.info("Deterministic classification: Square9 workflow %s -> %s", square9_workflow, doc_type.value)
    
    # Step 1c: Check mailbox category (from email polling config)
    if result["doc_type"] == DocType.OTHER.value:
        mailbox_category = metadata.get("mailbox_category") or document.get("mailbox_category")
        if mailbox_category:
            doc_type = DocumentClassifier.classify_from_mailbox_category(mailbox_category)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"mailbox:{mailbox_category}"
                logger.info("Deterministic classification: Mailbox category %s -> %s", mailbox_category, doc_type.value)
    
    # Step 1d: Check legacy suggested_job_type from existing AI extraction
    if result["doc_type"] == DocType.OTHER.value and suggested_type and suggested_type != "Unknown":
        doc_type = DocumentClassifier.classify_from_ai_result(suggested_type)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"legacy_ai:{suggested_type}"
            logger.info("Classification from legacy AI: %s -> %s", suggested_type, doc_type.value)
    
    # Step 2: If we have a definitive type, set category and return
    if result["doc_type"] != DocType.OTHER.value:
        result["category"] = _get_category_for_doc_type(result["doc_type"])
        return result
    
    # Step 3: doc_type is still OTHER - try AI classification if enabled
    if AI_CLASSIFICATION_ENABLED and os.environ.get("EMERGENT_LLM_KEY"):
        logger.info("Deterministic classification returned OTHER, invoking AI classifier for doc %s", document.get("id"))
        
        try:
            ai_result = await classify_doc_type_with_ai(
                document=document,
                extracted_text=extracted_fields.get("raw_text"),
                metadata=metadata
            )
            
            # Always record the AI classification attempt
            result["ai_classification"] = ai_result.to_dict()
            
            # Step 4: Apply if confidence meets threshold
            if ai_result.should_accept(AI_CLASSIFICATION_THRESHOLD):
                result["doc_type"] = ai_result.proposed_doc_type
                result["classification_method"] = f"ai:{ai_result.model_name}:{ai_result.confidence:.2f}"
                logger.info(
                    "AI classification accepted for doc %s: %s (confidence: %.2f)",
                    document.get("id"), ai_result.proposed_doc_type, ai_result.confidence
                )
            else:
                logger.info(
                    "AI classification NOT accepted for doc %s: %s (confidence: %.2f, threshold: %.2f)",
                    document.get("id"), ai_result.proposed_doc_type, ai_result.confidence, AI_CLASSIFICATION_THRESHOLD
                )
        except Exception as e:
            logger.error("AI classification failed for doc %s: %s", document.get("id"), str(e))
            result["ai_classification"] = {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    # Final category assignment
    result["category"] = _get_category_for_doc_type(result["doc_type"])
    
    return result


def _get_category_for_doc_type(doc_type: str) -> str:
    """Map doc_type to category for backward compatibility."""
    if doc_type == DocType.AP_INVOICE.value:
        return "AP"
    elif doc_type in [DocType.SALES_INVOICE.value, DocType.SALES_CREDIT_MEMO.value]:
        return "Sales"
    elif doc_type == DocType.PURCHASE_ORDER.value:
        return "Purchase"
    else:
        return "Other"


async def _internal_intake_document(
    file_content: bytes,
    filename: str,
    content_type: str,
    source: str = "email_poll",
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    email_id: Optional[str] = None
) -> dict:
    """
    Internal function to process document intake from email polling.
    Similar to intake_document but accepts raw bytes instead of UploadFile.
    """
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    correlation_id = str(uuid.uuid4())  # For event correlation
    
    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)
    
    # Apply pilot capture channel if pilot mode is enabled
    base_capture_channel = CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel
    
    # Create document record with workflow tracking
    doc = {
        "id": doc_id,
        "source": source,
        "file_name": filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "content_type": content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": now,
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "document_type": None,
        "category": None,
        "suggested_job_type": None,
        "ai_confidence": None,
        "extracted_fields": None,
        "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None,
        "bc_company_id": None,
        "bc_record_id": None,
        "bc_document_no": None,
        "status": "Received",
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": "Document captured from " + source,
            "metadata": {"source": source, "sender": sender}
        }],
        "workflow_status_updated_utc": now,
        # Derived state fields (Phase 2)
        "validation_state": "pending",
        "workflow_state": "received",
        "automation_state": "manual",
        "created_utc": now,
        "updated_utc": now,
        "last_error": None,
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)
    
    # Emit document.received event (Phase 1)
    event_service = get_event_service()
    if event_service:
        await emit_document_received(
            event_service, doc_id, source,
            filename, content_type or "application/octet-stream",
            len(file_content), correlation_id
        )
    
    # Run AI extraction (for field extraction, not doc_type classification)
    logger.info("Running AI field extraction for document %s", doc_id)
    classification = await classify_document_with_ai(str(file_path), filename)
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Deterministic-first document type classification
    # Step 1: Try deterministic rules (Zetadocs, Square9, mailbox category)
    # Step 2: If still OTHER, try AI classification if enabled
    classification_result = await classify_document_type(
        document=doc,
        extracted_fields=extracted_fields,
        suggested_type=suggested_type,
        confidence=confidence,
        metadata={
            "mailbox_category": doc.get("mailbox_category"),
            "zetadocs_set": doc.get("zetadocs_set_code"),
            "square9_workflow": doc.get("square9_workflow_name")
        }
    )
    
    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")
    
    logger.info(
        "Document %s classified as %s (category: %s, method: %s)",
        doc_id, doc_type_value, category, classification_method
    )
    
    # Phase 7: Compute normalized fields (flat, stored on document)
    normalized_fields = compute_ap_normalized_fields(extracted_fields)
    
    # Phase 7: Vendor alias lookup
    vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))

    # Phase 8: Spiro context enrichment (Shadow Mode - logs only, doesn't affect decisions)
    spiro_context_dict = None
    try:
        from services.spiro import get_spiro_context_for_document
        from services.spiro.spiro_client import is_spiro_enabled
        
        if is_spiro_enabled():
            doc_metadata = {
                "vendor_raw": normalized_fields.get("vendor_raw"),
                "vendor_normalized": normalized_fields.get("vendor_normalized"),
                "extracted_fields": extracted_fields
            }
            spiro_context = await get_spiro_context_for_document(doc_metadata)
            spiro_context_dict = spiro_context.to_dict()
            
            if spiro_context.matched_companies:
                best = spiro_context.matched_companies[0]
                logger.info("Spiro match for %s: %s (%.2f, ISR: %s)", 
                           doc_id[:8], best.name, best.match_score, best.data.get("assigned_isr"))
    except Exception as e:
        logger.debug("Spiro context skipped: %s", str(e))

    
    # Phase 7: Duplicate check
    duplicate_result = await check_duplicate_document(
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        vendor_canonical=vendor_alias_result.get("vendor_canonical"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        current_doc_id=doc_id
    )
    
    # Phase 7: Compute validation errors/warnings and draft_candidate
    ap_validation = compute_ap_validation(
        document_type=suggested_type,
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        amount_float=normalized_fields.get("amount_float"),
        po_number_clean=normalized_fields.get("po_number_clean"),
        ai_confidence=confidence,
        possible_duplicate=duplicate_result.get("possible_duplicate", False)
    )
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation (existing logic)
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Get freight direction for routing
    freight_direction = validation_results.get("freight_direction")
    
    # Build doc dict for routing
    routing_doc = {
        "id": doc_id,
        "document_type": suggested_type,
        "suggested_job_type": suggested_type,
        "vendor_canonical": doc.get("vendor_canonical") or normalized_fields.get("vendor"),
        "po_number_extracted": normalized_fields.get("po_number") or extracted_fields.get("po_number"),
        "bol_number_extracted": normalized_fields.get("bol_number") or extracted_fields.get("bol_number"),
        "extracted_fields": extracted_fields,
        "normalized_fields": normalized_fields,
        "ai_extraction": doc.get("ai_extraction", {}),
        "file_name": filename,
        "status": doc.get("status"),
        "approved": doc.get("approved", False)
    }
    
    # Upload to SharePoint using accounting folder routing
    sp_result = None
    share_link = None
    sp_error = None
    folder_path = None
    routing_reason = None
    
    try:
        sp_result = await upload_to_sharepoint_with_routing(
            file_content, 
            filename, 
            routing_doc,
            freight_direction=freight_direction,
            is_international=False  # TODO: detect from document
        )
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        folder_path = sp_result.get("folder_path")
        routing_reason = sp_result.get("routing_reason")
        logger.info("Document %s stored in SharePoint: %s (folder: %s, reason: %s)", 
                   doc_id, sp_result.get("web_url"), folder_path, routing_reason)
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)
    
    # Phase 7: Determine status for AP_Invoice using new logic
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        # All AP_Invoice documents stay in NeedsReview during Phase 7
        # The draft_candidate flag indicates readiness
        final_status = "NeedsReview"
    else:
        # Non-AP documents use existing logic
        if decision == "auto_link" and validation_results.get("all_passed"):
            final_status = "ReadyToLink"
        elif decision in ("needs_review", "manual"):
            final_status = "NeedsReview"
        elif decision == "exception":
            final_status = "Exception"
        elif sp_result:
            final_status = "StoredInSP"
        else:
            final_status = "Classified"
    
    # Get the category from job type config (fallback to our computed category)
    doc_category = category if category != "Other" else job_configs.get("category", category)
    
    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "category": doc_category,
        # Document classification fields
        "doc_type": doc_type_value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": capture_channel,  # Use pilot-aware channel
        "classification_method": classification_method,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        # Phase 7: Flat normalized fields on document
        "vendor_raw": normalized_fields.get("vendor_raw"),
        "vendor_normalized": normalized_fields.get("vendor_normalized"),
        "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
        "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
        "amount_raw": normalized_fields.get("amount_raw"),
        "amount_float": normalized_fields.get("amount_float"),
        "due_date_raw": normalized_fields.get("due_date_raw"),
        "due_date_iso": normalized_fields.get("due_date_iso"),
        "po_number_raw": normalized_fields.get("po_number_raw"),
        "po_number_clean": normalized_fields.get("po_number_clean"),
        # Phase 8: Invoice date and line items for automatic BC posting
        "invoice_date": normalized_fields.get("invoice_date"),
        "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
        "line_items": normalized_fields.get("line_items", []),
        # Phase 7: Vendor alias results
        "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
        "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
        # Phase 7: Duplicate detection
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        # Phase 7: Validation errors/warnings and draft_candidate
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        # Legacy fields (keep for backward compat)
        "canonical_fields": normalized_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": validation_results.get("match_method", "none"),
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "warnings": decision_metadata.get("warnings", []),
        "status": final_status,
        "workflow_state": "Validated",
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if sp_result:
        update_data["sharepoint_drive_id"] = sp_result["drive_id"]
        update_data["sharepoint_item_id"] = sp_result["item_id"]
        update_data["sharepoint_web_url"] = sp_result["web_url"]
        update_data["sharepoint_share_link_url"] = share_link
        # Folder routing info (accounting structure)
        update_data["sharepoint_folder_path"] = sp_result.get("folder_path")
        update_data["folder_routing_reason"] = sp_result.get("routing_reason")
        update_data["folder_routing_details"] = sp_result.get("routing_details")
        update_data["freight_direction"] = freight_direction
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"
    
    # Add AI classification audit trail if AI was invoked
    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit
    
    # Phase 8: Save Spiro context to document (Shadow Mode)
    if spiro_context_dict:
        update_data["spiro_context"] = spiro_context_dict
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Update workflow status based on processing results and doc_type
    if doc_type_value == DocType.AP_INVOICE.value:
        # Full AP workflow with vendor matching, BC validation, etc.
        await _update_ap_workflow_status(
            doc_id, 
            confidence, 
            normalized_fields, 
            vendor_alias_result, 
            validation_results,
            ap_validation
        )
        
        # AUTO-POST: Attempt automatic posting to BC for eligible AP invoices
        if AUTO_POST_ENABLED:
            # Refresh document after workflow update to get latest state
            updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            if updated_doc:
                try:
                    bc_service = get_bc_service()
                    auto_post_result = await attempt_auto_post(doc_id, updated_doc, db, bc_service)
                    
                    if auto_post_result.eligible:
                        if auto_post_result.success:
                            logger.info("AUTO-POST: Document %s auto-posted to BC as %s", 
                                       doc_id, auto_post_result.bc_document_number)
                            final_status = "Posted"  # Update final status for return
                        else:
                            logger.warning("AUTO-POST: Document %s eligible but failed: %s", 
                                          doc_id, auto_post_result.error)
                    else:
                        logger.debug("AUTO-POST: Document %s not eligible: %s", 
                                    doc_id, auto_post_result.reason)
                except Exception as e:
                    logger.error("AUTO-POST: Exception for %s: %s", doc_id, str(e))
    else:
        # For non-AP documents, use simplified workflow
        await _update_standard_workflow_status(
            doc_id, 
            doc_type_value,
            confidence, 
            normalized_fields
        )
    
    # Create workflow audit trail entry
    workflow_run_id = uuid.uuid4().hex[:8]
    workflow = {
        "id": str(uuid.uuid4()),
        "run_id": workflow_run_id,
        "document_id": doc_id,
        "workflow_name": source,
        "workflow_type": "intake_validation",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "correlation_id": uuid.uuid4().hex[:8],
        "steps": [
            {"step": "AI Classification", "status": "Completed", "timestamp": now, 
             "details": {"document_type": suggested_type, "confidence": confidence}},
            {"step": "SharePoint Upload", "status": "Completed" if sp_result else "Failed", 
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": sp_result if sp_result else {"error": sp_error}},
            {"step": "BC Validation", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {
                 "match_method": validation_results.get("match_method", "none"),
                 "match_score": validation_results.get("match_score", 0.0),
                 "all_passed": validation_results.get("all_passed", False)
             }},
            {"step": "Automation Decision", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {"decision": decision, "reasoning": reasoning, "final_status": final_status}}
        ],
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    logger.info("[Workflow:%s] Intake complete: %s → status=%s, decision=%s, score=%.2f", 
                workflow_run_id, filename, final_status, decision, validation_results.get("match_score", 0.0))
    
    # =================================================================
    # AUTO-CLEAR EVALUATION (Square9/Zetadocs aligned)
    # Evaluate if document should be auto-cleared from queue
    # =================================================================
    auto_clear_result = None
    try:
        # Refresh document to get latest state
        doc_for_eval = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if doc_for_eval:
            auto_clear_decision, auto_clear_reason, auto_clear_details = evaluate_auto_clear(
                doc_for_eval,
                validation_results=validation_results
            )
            
            # Apply auto-clear update
            auto_clear_update = get_auto_clear_update(auto_clear_decision, auto_clear_details)
            await db.hub_documents.update_one({"id": doc_id}, {"$set": auto_clear_update})
            
            auto_clear_result = {
                "decision": auto_clear_decision.value,
                "reason": auto_clear_reason,
                "cleared": auto_clear_decision == AutoClearDecision.CLEARED
            }
            
            if auto_clear_decision == AutoClearDecision.CLEARED:
                final_status = "Completed"  # Override final status
                logger.info("[Auto-Clear] Document %s AUTO-CLEARED: %s", doc_id, auto_clear_reason)
            else:
                logger.debug("[Auto-Clear] Document %s NOT cleared: %s", doc_id, auto_clear_reason)
    except Exception as e:
        logger.error("[Auto-Clear] Error evaluating document %s: %s", doc_id, str(e))
    
    # Emit workflow events (Phase 1)
    try:
        await _emit_intake_events(
            doc_id, correlation_id, classification, validation_results,
            sp_result, decision, auto_clear_result
        )
    except Exception as e:
        logger.error("[Events] Error emitting events for document %s: %s", doc_id, str(e))
    
    # =================================================================
    # AUTO-RESOLUTION: Queue background reference intelligence
    # Non-blocking — enqueue and return immediately
    # =================================================================
    try:
        auto_resolve = get_auto_resolve_service()
        if auto_resolve:
            await auto_resolve.enqueue(doc_id)
    except Exception as e:
        logger.error("[AutoResolve] Error queueing document %s: %s", doc_id, str(e))
    
    return {
        "document": {"id": doc_id, "status": final_status},
        "classification": classification,
        "automation_decision": decision,
        "sharepoint": sp_result,
        "auto_clear": auto_clear_result
    }


async def _emit_intake_events(
    doc_id: str, 
    correlation_id: str,
    classification: dict,
    validation_results: dict,
    sp_result: dict,
    decision: str,
    auto_clear_result: dict
):
    """
    Emit events for the intake pipeline.
    This is called after the main intake processing to record events.
    """
    event_service = get_event_service()
    if not event_service:
        return
    
    # Classification event
    await emit_classification_completed(
        event_service, doc_id,
        classification.get("suggested_job_type", "Unknown"),
        classification.get("confidence", 0.0),
        classification.get("classification_method", "ai"),
        classification.get("model"),
        correlation_id
    )
    
    # Vendor match event
    matched_vendor = validation_results.get("matched_vendor_no")
    await emit_vendor_match(
        event_service, doc_id,
        matched=bool(matched_vendor),
        vendor_name=validation_results.get("matched_vendor_name"),
        vendor_no=matched_vendor,
        match_method=validation_results.get("match_method", "none"),
        match_score=validation_results.get("match_score", 0.0),
        correlation_id=correlation_id
    )
    
    # BC validation event
    await emit_bc_validation(
        event_service, doc_id,
        passed=validation_results.get("all_passed", False),
        checks=validation_results.get("checks", []),
        warnings=validation_results.get("warnings"),
        correlation_id=correlation_id
    )
    
    # SharePoint upload event
    if sp_result:
        await emit_sharepoint_upload(
            event_service, doc_id,
            success=True,
            folder_path=sp_result.get("folder_path", ""),
            drive_id=sp_result.get("drive_id"),
            item_id=sp_result.get("item_id"),
            share_link=sp_result.get("share_link"),
            correlation_id=correlation_id
        )
    
    # Automation decision event
    auto_cleared = auto_clear_result and auto_clear_result.get("cleared", False)
    await emit_automation_decision(
        event_service, doc_id,
        decision=decision,
        reason=auto_clear_result.get("reason") if auto_clear_result else "",
        auto_clear=auto_cleared,
        auto_post=False,
        correlation_id=correlation_id
    )
    
    # Update derived state
    derived_state_service = get_derived_state_service()
    if derived_state_service:
        await derived_state_service.update_document_derived_state(doc_id)


# Moved to routers/documents.py (Domain 7)
async def intake_document(
    file: UploadFile = File(...),
    source: str = Form("email"),
    sender: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    attachment_name: Optional[str] = Form(None),
    content_hash: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    email_received_utc: Optional[str] = Form(None)
):
    """
    Receive a document from email or other source.
    Runs AI classification and automation decision matrix.
    """
    file_content = await file.read()
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Use provided attachment name or fall back to filename
    final_filename = attachment_name or file.filename
    
    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)
    
    # Create document record with workflow tracking
    doc = {
        "id": doc_id,
        "source": source,
        "file_name": final_filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "content_type": file.content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": email_received_utc,
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "document_type": None,
        "category": None,
        "suggested_job_type": None,
        "ai_confidence": None,
        "extracted_fields": None,
        "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None,
        "bc_company_id": None,
        "bc_record_id": None,
        "bc_document_no": None,
        "status": "Received",
        # Document classification fields (will be updated after AI classification)
        "doc_type": DocType.OTHER.value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": get_pilot_capture_channel(CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value) if PILOT_MODE_ENABLED else (CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value),
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": f"Document captured from {source}",
            "metadata": {"source": source, "sender": sender}
        }],
        "workflow_status_updated_utc": now,
        "created_utc": now,
        "updated_utc": now,
        "last_error": None,
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)
    
    # Run AI field extraction (for extracting vendor, amount, etc.)
    logger.info("Running AI field extraction for document %s", doc_id)
    classification = await classify_document_with_ai(str(file_path), final_filename)
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Deterministic-first document type classification
    # Step 1: Try deterministic rules (Zetadocs, Square9, mailbox category)
    # Step 2: If still OTHER, try AI classification if enabled
    classification_result = await classify_document_type(
        document=doc,
        extracted_fields=extracted_fields,
        suggested_type=suggested_type,
        confidence=confidence,
        metadata={
            "mailbox_category": doc.get("mailbox_category"),
            "zetadocs_set": doc.get("zetadocs_set_code"),
            "square9_workflow": doc.get("square9_workflow_name")
        }
    )
    
    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")
    
    logger.info(
        "Document %s classified as %s (category: %s, method: %s)",
        doc_id, doc_type_value, category, classification_method
    )
    
    # Phase 7: Compute normalized fields (flat, stored on document)
    normalized_fields = compute_ap_normalized_fields(extracted_fields)
    
    # Phase 7: Vendor alias lookup
    vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
    
    # Phase 7: Duplicate check
    duplicate_result = await check_duplicate_document(
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        vendor_canonical=vendor_alias_result.get("vendor_canonical"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        current_doc_id=doc_id
    )
    
    # Phase 7: Compute validation errors/warnings and draft_candidate
    ap_validation = compute_ap_validation(
        document_type=suggested_type,
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        amount_float=normalized_fields.get("amount_float"),
        po_number_clean=normalized_fields.get("po_number_clean"),
        ai_confidence=confidence,
        possible_duplicate=duplicate_result.get("possible_duplicate", False)
    )
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision (returns 3-tuple with metadata)
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Get BC entity for linking
    bc_entity = job_configs.get("bc_entity", "salesOrders")
    
    # ALWAYS upload to SharePoint first - regardless of validation status
    # This ensures document is preserved even if BC linking fails
    folder = job_configs.get("sharepoint_folder", "Incoming")
    sp_result = None
    share_link = None
    sp_error = None
    
    try:
        sp_result = await upload_to_sharepoint(file_content, final_filename, folder)
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        logger.info("Document %s stored in SharePoint: %s", doc_id, sp_result.get("web_url"))
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)
    
    # Phase 7: Determine status for AP_Invoice using new logic
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        # All AP_Invoice documents stay in NeedsReview during Phase 7
        final_status = "NeedsReview"
    else:
        # Non-AP documents use existing logic
        if sp_result:
            final_status = "StoredInSP"
        else:
            final_status = "Classified"
    
    # Update document with classification + SharePoint results
    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        # Document classification fields
        "doc_type": doc_type_value,
        "category": category,
        "classification_method": classification_method,
        # Phase 7: Flat normalized fields on document
        "vendor_raw": normalized_fields.get("vendor_raw"),
        "vendor_normalized": normalized_fields.get("vendor_normalized"),
        "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
        "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
        "amount_raw": normalized_fields.get("amount_raw"),
        "amount_float": normalized_fields.get("amount_float"),
        "due_date_raw": normalized_fields.get("due_date_raw"),
        "due_date_iso": normalized_fields.get("due_date_iso"),
        "po_number_raw": normalized_fields.get("po_number_raw"),
        "po_number_clean": normalized_fields.get("po_number_clean"),
        # Phase 8: Invoice date and line items for automatic BC posting
        "invoice_date": normalized_fields.get("invoice_date"),
        "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
        "line_items": normalized_fields.get("line_items", []),
        # Phase 7: Vendor alias results
        "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
        "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
        # Phase 7: Duplicate detection
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        # Phase 7: Validation errors/warnings and draft_candidate
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        # Legacy fields for backward compat
        "canonical_fields": normalized_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": validation_results.get("match_method", "none"),
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "warnings": decision_metadata.get("warnings", []),
        "status": final_status,
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Add SharePoint info if successful
    if sp_result:
        update_data["sharepoint_drive_id"] = sp_result["drive_id"]
        update_data["sharepoint_item_id"] = sp_result["item_id"]
        update_data["sharepoint_web_url"] = sp_result["web_url"]
        update_data["sharepoint_share_link_url"] = share_link
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"
    
    # Add AI classification audit trail if AI was invoked
    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Create workflow run for intake
    workflow_steps = [
        {"step": "receive_document", "status": "completed", "result": {"source": source, "hash": computed_hash}},
        {"step": "ai_classification", "status": "completed", "result": classification},
        {"step": "sharepoint_upload", "status": "completed" if sp_result else "failed", 
         "result": sp_result if sp_result else {"error": sp_error}},
        {"step": "bc_validation", "status": "completed", "result": {
            "all_passed": validation_results.get("all_passed"),
            "match_method": validation_results.get("match_method", "none"),
            "checks_count": len(validation_results.get("checks", [])),
            "vendor_candidates_count": len(validation_results.get("vendor_candidates", [])),
            "warnings_count": len(validation_results.get("warnings", []))
        }},
        {"step": "automation_decision", "status": "completed", "result": {"decision": decision, "reasoning": reasoning}}
    ]
    
    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "email_intake",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": workflow_steps,
        "correlation_id": str(uuid.uuid4()),
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    # Execute BC action based on decision (only if SharePoint upload succeeded)
    final_status = update_data["status"]
    transaction_action = TransactionAction.NONE
    draft_result = None
    
    if sp_result and (decision == "auto_link" or decision == "auto_create"):
        bc_record_id = validation_results.get("bc_record_id")
        match_method = validation_results.get("match_method", "none")
        match_score = validation_results.get("match_score", 0.0)
        
        # Check if eligible for draft creation (Phase 4)
        # Fetch current doc state for eligibility check
        current_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        is_draft_eligible, draft_reason = is_eligible_for_draft_creation(
            job_type=suggested_type,
            match_method=match_method,
            match_score=match_score,
            ai_confidence=confidence,
            validation_results=validation_results,
            doc=current_doc
        )
        
        if is_draft_eligible and suggested_type == "AP_Invoice":
            # CREATE DRAFT HEADER - Phase 4
            logger.info("Document %s eligible for draft creation: %s", doc_id, draft_reason)
            
            # Get vendor info for draft
            vendor_info = validation_results.get("bc_record_info", {})
            vendor_no = vendor_info.get("number", "")
            normalized_fields = validation_results.get("normalized_fields", {})
            external_doc_no = normalized_fields.get("invoice_number") or extracted_fields.get("invoice_number", "")
            
            if vendor_no and external_doc_no:
                # Run duplicate check one more time (defense in depth)
                token = await get_bc_token()
                companies = await get_bc_companies()
                company_id = companies[0]["id"] if companies else None
                
                dup_check = await check_duplicate_purchase_invoice(
                    vendor_no=vendor_no,
                    external_doc_no=external_doc_no,
                    company_id=company_id,
                    token=token
                )
                
                if dup_check.get("found"):
                    # Duplicate found - hard stop
                    logger.warning(
                        "Duplicate invoice found during draft creation for doc %s: %s",
                        doc_id, dup_check.get("existing_invoice_no")
                    )
                    final_status = "NeedsReview"
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "status": "NeedsReview",
                        "transaction_action": TransactionAction.NONE,
                        "last_error": f"Duplicate invoice exists: {dup_check.get('existing_invoice_no')}",
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }})
                else:
                    # Create the draft
                    draft_result = await create_purchase_invoice_header(
                        vendor_no=vendor_no,
                        external_doc_no=external_doc_no,
                        document_date=normalized_fields.get("invoice_date") or normalized_fields.get("due_date_raw"),
                        due_date=normalized_fields.get("due_date"),
                        posting_date=None,  # Let BC use today
                        company_id=company_id,
                        token=token
                    )
                    
                    if draft_result.get("success"):
                        final_status = "LinkedToBC"
                        transaction_action = TransactionAction.DRAFT_CREATED
                        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                            "bc_record_id": draft_result.get("invoice_id"),
                            "bc_document_no": draft_result.get("invoice_no"),
                            "bc_record_type": "PurchaseInvoice",
                            "transaction_action": TransactionAction.DRAFT_CREATED,
                            "draft_creation_result": draft_result,
                            "status": "LinkedToBC",
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }})
                        logger.info(
                            "Draft Purchase Invoice created for doc %s: %s",
                            doc_id, draft_result.get("invoice_no")
                        )
                    else:
                        # Draft creation failed - fallback to needs review
                        logger.error(
                            "Draft creation failed for doc %s: %s",
                            doc_id, draft_result.get("error")
                        )
                        final_status = "NeedsReview"
                        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                            "status": "NeedsReview",
                            "transaction_action": TransactionAction.NONE,
                            "last_error": f"Draft creation failed: {draft_result.get('error')}",
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }})
            else:
                # Missing required fields for draft - fallback to link only
                logger.warning("Missing vendor_no or external_doc_no for draft creation, falling back to link")
                if bc_record_id:
                    try:
                        link_result = await link_document_to_bc(
                            bc_record_id=bc_record_id,
                            share_link=share_link,
                            file_name=final_filename,
                            file_content=file_content,
                            bc_entity=bc_entity
                        )
                        if link_result.get("success"):
                            final_status = "LinkedToBC"
                            transaction_action = TransactionAction.LINKED_ONLY
                            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                                "bc_record_id": bc_record_id,
                                "transaction_action": TransactionAction.LINKED_ONLY,
                                "status": "LinkedToBC",
                                "updated_utc": datetime.now(timezone.utc).isoformat()
                            }})
                    except Exception as e:
                        logger.error("BC linking failed for document %s: %s", doc_id, str(e))
        
        elif bc_record_id:
            # Standard auto-link flow (Level 1 or not eligible for draft)
            try:
                link_result = await link_document_to_bc(
                    bc_record_id=bc_record_id,
                    share_link=share_link,
                    file_name=final_filename,
                    file_content=file_content,
                    bc_entity=bc_entity
                )
                if link_result.get("success"):
                    final_status = "LinkedToBC"
                    transaction_action = TransactionAction.LINKED_ONLY
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "bc_record_id": bc_record_id,
                        "transaction_action": TransactionAction.LINKED_ONLY,
                        "status": "LinkedToBC",
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }})
            except Exception as e:
                logger.error("BC linking failed for document %s: %s", doc_id, str(e))
    
    elif decision == "needs_review":
        final_status = "NeedsReview"
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "NeedsReview",
            "transaction_action": TransactionAction.NONE,
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }})
    
    # Return result
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "draft_result": draft_result,
        "transaction_action": transaction_action
    }

# Moved to routers/documents.py (Domain 7)
async def classify_document(doc_id: str):
    """Re-run AI classification on an existing document."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")
    
    classification = await classify_document_with_ai(str(file_path), doc["file_name"])
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "classification_method": f"ai:{classification.get('model', 'gemini-3-flash-preview')}",
        "ai_model": classification.get("model", "gemini-3-flash-preview"),
        "extracted_fields": extracted_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }})
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "candidates": {
            "vendors": decision_metadata.get("vendor_candidates", []),
            "customers": decision_metadata.get("customer_candidates", [])
        }
    }

# ==================== RESOLVE AND LINK ENDPOINT ====================

class ResolveRequest(BaseModel):
    selected_vendor_id: Optional[str] = None
    selected_customer_id: Optional[str] = None
    selected_po_number: Optional[str] = None
    mark_no_po: bool = False  # Mark as non-PO invoice
    notes: Optional[str] = None

# Moved to routers/documents.py (Domain 7)
async def resolve_and_link_document(doc_id: str, resolve: ResolveRequest):
    """
    Resolve a NeedsReview document by selecting vendor/customer from candidates.
    Then link to BC and update status.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("status") not in ("NeedsReview", "StoredInSP", "Classified"):
        raise HTTPException(status_code=400, detail=f"Document status must be NeedsReview, StoredInSP, or Classified. Current: {doc.get('status')}")
    
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()
    
    # Determine what BC record to link to
    bc_record_id = None
    bc_record_type = doc.get("suggested_job_type", "AP_Invoice")
    
    if resolve.selected_vendor_id:
        bc_record_id = resolve.selected_vendor_id
    elif resolve.selected_customer_id:
        bc_record_id = resolve.selected_customer_id
    elif doc.get("validation_results", {}).get("bc_record_id"):
        # Use existing validated record
        bc_record_id = doc["validation_results"]["bc_record_id"]
    
    # Ensure document is in SharePoint
    share_link = doc.get("sharepoint_share_link_url")
    if not share_link and file_content:
        # Upload to SharePoint now
        job_configs = await db.hub_job_types.find_one({"job_type": bc_record_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(bc_record_type, DEFAULT_JOB_TYPES["AP_Invoice"])
        
        folder = job_configs.get("sharepoint_folder", "Incoming")
        bc_entity = job_configs.get("bc_entity", "salesOrders")
        try:
            sp_result = await upload_to_sharepoint(file_content, doc["file_name"], folder)
            share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
            
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "sharepoint_drive_id": sp_result["drive_id"],
                "sharepoint_item_id": sp_result["item_id"],
                "sharepoint_web_url": sp_result["web_url"],
                "sharepoint_share_link_url": share_link,
                "status": "StoredInSP",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SharePoint upload failed: {str(e)}")
    
    # Link to BC if we have a record and file content
    link_success = False
    link_error = None
    
    if bc_record_id and file_content:
        try:
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id,
                share_link=share_link or "",
                file_name=doc["file_name"],
                file_content=file_content,
                bc_entity=bc_entity
            )
            link_success = link_result.get("success", False)
            if not link_success:
                link_error = link_result.get("error", "Unknown error")
        except Exception as e:
            link_error = str(e)
    
    # Update document status
    final_status = "LinkedToBC" if link_success else "StoredInSP"
    update_data = {
        "status": final_status,
        "bc_record_id": bc_record_id,
        "resolve_notes": resolve.notes,
        "resolved_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if resolve.mark_no_po:
        update_data["po_status"] = "not_applicable"
    
    if link_error:
        update_data["last_error"] = link_error
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Log workflow
    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "resolve_and_link",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed" if link_success else "PartialSuccess",
        "steps": [
            {"step": "resolve_selection", "status": "completed", "result": {
                "vendor_id": resolve.selected_vendor_id,
                "customer_id": resolve.selected_customer_id,
                "mark_no_po": resolve.mark_no_po
            }},
            {"step": "bc_link", "status": "completed" if link_success else "failed", 
             "result": {"success": link_success, "error": link_error}}
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": link_error
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": link_success,
        "document": updated_doc,
        "message": "Document linked to BC" if link_success else f"Document stored in SharePoint. BC linking failed: {link_error}"
    }

# ==================== SAFE REPROCESS ENDPOINT ====================

# Moved to routers/documents.py (Domain 7)
async def reprocess_document(doc_id: str, reclassify: bool = Query(False)):
    """
    Safe reprocess endpoint - re-runs validation + vendor match only.
    Set reclassify=true to also re-run AI classification.
    
    Rules:
    - Do NOT duplicate SharePoint uploads
    - Do NOT create new BC records if already linked
    - Do NOT create draft invoices (drafts only during initial intake)
    - If alias now matches → transition from NeedsReview → LinkedToBC (via linking, not draft)
    - Must be idempotent
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Cannot reprocess already-linked documents
    if doc.get("status") == "LinkedToBC":
        return {
            "reprocessed": False,
            "reason": "Document already linked to BC - no reprocessing needed",
            "document": doc
        }
    
    # Idempotency check: If bc_record_id exists, document was already processed
    if doc.get("bc_record_id"):
        return {
            "reprocessed": False,
            "reason": f"BC record already exists ({doc.get('bc_record_id')}) - idempotency guard",
            "document": doc
        }
    
    # Get the file content for BC linking (if needed)
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()
    
    # Re-run AI classification if requested
    if reclassify and file_path.exists():
        logger.info("Re-running AI classification for document %s", doc_id)
        classification = await classify_document_with_ai(str(file_path), doc["file_name"])
        
        # Update document with new classification
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "document_type": classification.get("suggested_job_type", "Unknown"),
                "suggested_job_type": classification.get("suggested_job_type", "Unknown"),
                "ai_confidence": classification.get("confidence", 0.0),
                "extracted_fields": classification.get("extracted_fields", {}),
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        # Reload the document
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    # Get job config
    job_type = doc.get("suggested_job_type", "AP_Invoice")
    job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Get extracted fields
    extracted_fields = doc.get("extracted_fields", {})
    
    # Re-run BC validation (this will use any new aliases)
    old_match_method = doc.get("match_method", "none")
    validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
    new_match_method = validation_results.get("match_method", "none")
    
    # Make new automation decision
    confidence = doc.get("ai_confidence", 0.0)
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Determine if status should change
    old_status = doc.get("status")
    new_status = old_status
    transaction_action = doc.get("transaction_action", TransactionAction.NONE)
    
    # Square9 Workflow Alignment:
    # Reprocess validates data and confirms SharePoint storage.
    # It does NOT create BC records or attach documents to BC.
    # BC record creation/attachment happens outside this workflow (manual or separate process).
    share_link = doc.get("sharepoint_share_link_url")
    
    if validation_results.get("all_passed"):
        # Validation passed - document is ready for downstream processing
        if share_link:
            # Document is validated AND stored in SharePoint - success per Square9 workflow
            new_status = "Validated"
            transaction_action = TransactionAction.VALIDATED
        else:
            # Validation passed but no SharePoint link yet - needs SP upload
            new_status = "ValidationPassed"
    elif decision == "needs_review":
        new_status = "NeedsReview"
    
    # Update document
    # Map status to workflow_status for consistency in queue display
    workflow_status_map = {
        "Validated": "validated",
        "ValidationPassed": "validation_passed",
        "NeedsReview": "needs_review",
        "LinkedToBC": "linked_to_bc",
        "Posted": "posted",
        "ReadyForPost": "ready_for_post"
    }
    new_workflow_status = workflow_status_map.get(new_status, new_status.lower() if new_status else "pending")
    
    update_data = {
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": new_match_method,
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "status": new_status,
        "workflow_status": new_workflow_status,  # Keep workflow_status in sync
        "square9_stage": new_workflow_status,    # Also update square9_stage
        "transaction_action": transaction_action,
        "reprocessed_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "last_error": None  # Clear any previous errors on successful reprocess
    }
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Log reprocess workflow (Square9 aligned)
    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "reprocess",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": [
            {
                "step": "revalidation",
                "status": "completed",
                "result": {
                    "old_match_method": old_match_method,
                    "new_match_method": new_match_method,
                    "validation_passed": validation_results.get("all_passed"),
                    "decision": decision,
                    "square9_aligned": True,
                    "reason": "Square9 workflow: validate data, confirm SharePoint storage. BC attachment handled separately."
                }
            },
            {
                "step": "status_transition",
                "status": "completed" if new_status != old_status else "no_change",
                "result": {
                    "old_status": old_status,
                    "new_status": new_status,
                    "sharepoint_stored": bool(share_link)
                }
            }
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    return {
        "reprocessed": True,
        "status_changed": old_status != new_status,
        "old_status": old_status,
        "new_status": new_status,
        "match_method_changed": old_match_method != new_match_method,
        "old_match_method": old_match_method,
        "new_match_method": new_match_method,
        "validation_passed": validation_results.get("all_passed"),
        "sharepoint_stored": bool(share_link),
        "document": updated_doc,
        "reasoning": reasoning
    }


# =============================================================================
# BATCH REVALIDATION - Re-run validation on all documents using Production BC
# =============================================================================

# Moved to routers/documents.py (Domain 7)
async def batch_revalidate_documents(
    doc_types: List[str] = Query(default=["AP_Invoice", "AP_INVOICE", "Remittance"]),
    limit: int = Query(default=500, le=1000),
    skip_completed: bool = Query(default=True),
    background_tasks: BackgroundTasks = None
):
    """
    Batch re-validate all documents against Production BC.
    
    - Re-runs vendor matching using Production BC as source
    - Updates validation_results and match status
    - Does NOT create BC records or upload to SharePoint
    
    Args:
        doc_types: Document types to revalidate (default: AP invoices)
        limit: Maximum documents to process
        skip_completed: Skip documents already in Completed/Posted status
    """
    
    # Build query
    query = {"doc_type": {"$in": doc_types}}
    if skip_completed:
        query["status"] = {"$nin": ["Completed", "Posted", "Archived", "LinkedToBC"]}
    
    # Get documents
    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)
    
    if not docs:
        return {"message": "No documents to revalidate", "count": 0}
    
    results = {
        "total": len(docs),
        "success": 0,
        "failed": 0,
        "improved": 0,
        "unchanged": 0,
        "details": []
    }
    
    for doc in docs:
        doc_id = doc.get("id")
        try:
            # Get job config
            job_type = doc.get("suggested_job_type", doc.get("doc_type", "AP_Invoice"))
            job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES.get("AP_Invoice", {}))
            
            # Get extracted fields
            extracted_fields = doc.get("extracted_fields", {})
            vendor_name = extracted_fields.get("vendor", doc.get("vendor_canonical", ""))
            
            # Record old state
            old_match_method = doc.get("match_method", doc.get("validation_results", {}).get("match_method", "none"))
            old_validation_passed = doc.get("validation_results", {}).get("all_passed", False)
            
            # Re-run BC validation (now uses Production)
            validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
            new_match_method = validation_results.get("match_method", "none")
            new_validation_passed = validation_results.get("all_passed", False)
            
            # Make new automation decision
            confidence = doc.get("ai_confidence", 0.0)
            decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
            
            # Update document with new validation results
            update_data = {
                "validation_results": validation_results,
                "match_method": new_match_method,
                "match_score": validation_results.get("match_score", 0.0),
                "automation_decision": decision,
                "vendor_candidates": decision_metadata.get("vendor_candidates", []),
                "revalidated_utc": datetime.now(timezone.utc).isoformat(),
                "revalidated_from": "batch_revalidate_production"
            }
            
            # Update vendor canonical if we found a match
            if validation_results.get("bc_record_info"):
                bc_info = validation_results["bc_record_info"]
                update_data["vendor_canonical"] = bc_info.get("displayName", vendor_name)
                update_data["bc_vendor_number"] = bc_info.get("number")
            
            # Check for unified vendor match details
            if validation_results.get("unified_vendor_match"):
                update_data["unified_vendor_match"] = validation_results["unified_vendor_match"]
            
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
            
            # Track results
            improved = (not old_validation_passed and new_validation_passed) or \
                       (old_match_method == "none" and new_match_method != "none")
            
            results["success"] += 1
            if improved:
                results["improved"] += 1
            else:
                results["unchanged"] += 1
            
            results["details"].append({
                "doc_id": doc_id[:8] + "...",
                "vendor": vendor_name[:30] if vendor_name else "N/A",
                "old_match": old_match_method,
                "new_match": new_match_method,
                "improved": improved,
                "validation_passed": new_validation_passed
            })
            
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "doc_id": doc_id[:8] + "...",
                "error": str(e)[:100]
            })
            logger.error("Batch revalidate error for %s: %s", doc_id, str(e))
    
    return results


# =============================================================================
# DRY-RUN PREVIEW ENDPOINT - Validates against Production BC without writing
# =============================================================================

class DryRunPreviewRequest(BaseModel):
    """Request for dry-run preview with optional BC environment override."""
    use_production_bc: bool = True  # Default to Production for validation
    bc_tenant_id: Optional[str] = None  # Override tenant if needed
    bc_environment: Optional[str] = None  # Override environment if needed


# Moved to routers/documents.py (Domain 7)
async def preview_post_to_bc(doc_id: str, request: DryRunPreviewRequest = None):
    """
    DRY-RUN PREVIEW: Shows exactly what would be posted to BC without actually posting.
    
    - Validates document against Production BC (read-only)
    - Shows the Purchase Invoice payload that would be created
    - Validates Sales Order references
    - Returns detailed preview - NO WRITES
    
    Use this to test the flow before enabling writes to Production.
    """
    
    def _parse_amount(value):
        """Parse amount handling commas and currency symbols."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            # Remove currency symbols, commas, spaces
            cleaned = str(value).replace(",", "").replace("$", "").replace(" ", "").strip()
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None
    
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Use Production BC credentials for validation (read-only operations)
    # Credentials should be set in environment variables
    PROD_TENANT_ID = request.bc_tenant_id if request and request.bc_tenant_id else os.environ.get("BC_PROD_TENANT_ID", "")
    PROD_ENVIRONMENT = request.bc_environment if request and request.bc_environment else os.environ.get("BC_PROD_ENVIRONMENT", "Production")
    PROD_CLIENT_ID = os.environ.get("BC_PROD_CLIENT_ID", "")
    PROD_CLIENT_SECRET = os.environ.get("BC_PROD_CLIENT_SECRET", "")
    
    # Check if Production BC credentials are configured
    if not PROD_TENANT_ID or not PROD_CLIENT_ID or not PROD_CLIENT_SECRET:
        return {
            "doc_id": doc_id,
            "dry_run": True,
            "error": "Production BC credentials not configured. Set BC_PROD_TENANT_ID, BC_PROD_CLIENT_ID, BC_PROD_CLIENT_SECRET in environment.",
            "errors": ["Missing BC_PROD_* environment variables"]
        }
    
    preview_result = {
        "doc_id": doc_id,
        "file_name": doc.get("file_name"),
        "document_type": doc.get("document_type") or doc.get("suggested_job_type"),
        "dry_run": True,
        "would_write_to_bc": False,
        "bc_environment_used": f"{PROD_TENANT_ID[:8]}.../{PROD_ENVIRONMENT}",
        "validation": {
            "passed": False,
            "checks": [],
            "warnings": []
        },
        "extracted_data": {},
        "purchase_invoice_preview": None,
        "sales_order_match": None,
        "folder_routing": None,  # Will be populated with SharePoint folder routing
        "errors": []
    }
    
    try:
        # Get OAuth token for Production BC
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                f"https://login.microsoftonline.com/{PROD_TENANT_ID}/oauth2/v2.0/token",
                data={
                    "client_id": PROD_CLIENT_ID,
                    "client_secret": PROD_CLIENT_SECRET,
                    "scope": "https://api.businesscentral.dynamics.com/.default",
                    "grant_type": "client_credentials"
                }
            )
            
            if token_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC token: {token_resp.status_code}")
                return preview_result
            
            token = token_resp.json().get("access_token")
            
            # Get company ID
            companies_resp = await client.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if companies_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC companies: {companies_resp.status_code}")
                return preview_result
            
            companies = companies_resp.json().get("value", [])
            company_id = None
            for c in companies:
                if "Gamer" in c.get("name", ""):
                    company_id = c.get("id")
                    break
            if not company_id and companies:
                company_id = companies[0].get("id")
            
            if not company_id:
                preview_result["errors"].append("No BC company found")
                return preview_result
            
            # Extract data from document
            extracted_fields = doc.get("extracted_fields", {})
            normalized_fields = doc.get("normalized_fields", {})
            ai_extraction = doc.get("ai_extraction", {})
            
            # Build extracted data summary
            vendor_name = (
                doc.get("vendor_canonical") or 
                normalized_fields.get("vendor") or 
                extracted_fields.get("vendor") or
                ai_extraction.get("vendor")
            )
            
            invoice_number = (
                doc.get("invoice_number_clean") or
                normalized_fields.get("invoice_number") or
                extracted_fields.get("invoice_number") or
                ai_extraction.get("invoice_number")
            )
            
            invoice_date = (
                doc.get("invoice_date") or
                normalized_fields.get("invoice_date") or
                extracted_fields.get("invoice_date") or
                ai_extraction.get("invoice_date")
            )
            
            total_amount = (
                doc.get("amount_float") or
                normalized_fields.get("amount") or
                extracted_fields.get("amount") or
                ai_extraction.get("total_amount")
            )
            
            # Get BOL/Order reference
            order_reference = (
                doc.get("bol_number_extracted") or
                doc.get("po_number_extracted") or
                normalized_fields.get("bol_number") or
                normalized_fields.get("po_number") or
                extracted_fields.get("bol_number") or
                extracted_fields.get("po_number") or
                extracted_fields.get("order_number") or
                ai_extraction.get("bol_number") or
                ai_extraction.get("po_number")
            )
            
            preview_result["extracted_data"] = {
                "vendor": vendor_name,
                "invoice_number": invoice_number,
                "invoice_date": invoice_date,
                "total_amount": _parse_amount(total_amount),
                "order_reference": order_reference,
                "currency": doc.get("currency", "USD")
            }
            
            # Validate vendor using Unified Vendor Intelligence Service
            # This checks: Document History, Spiro CRM, Business Central, SharePoint patterns
            if vendor_name:
                unified_result = await match_vendor_unified(db, vendor_name, min_score=0.7)
                
                if unified_result.get("matched"):
                    best_match = unified_result.get("best_match", {})
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match",
                        "passed": True,
                        "details": f"Found vendor via {unified_result.get('source')}: {best_match.get('name')} (score: {unified_result.get('score', 0):.0%})",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "is_freight_carrier": unified_result.get("is_freight_carrier", False)
                    })
                    preview_result["extracted_data"]["vendor_number"] = best_match.get("vendor_number") or unified_result.get("bc_vendor_number")
                    preview_result["extracted_data"]["vendor_id"] = best_match.get("vendor_id") or unified_result.get("bc_vendor_id")
                    preview_result["extracted_data"]["vendor_display_name"] = best_match.get("name")
                    preview_result["extracted_data"]["is_freight_carrier"] = unified_result.get("is_freight_carrier", False)
                    preview_result["extracted_data"]["vendor_match_source"] = unified_result.get("source")
                else:
                    # Show what sources were checked and any candidates found
                    all_matches = unified_result.get("all_matches", [])
                    candidate_info = ""
                    if all_matches:
                        top = all_matches[0]
                        candidate_info = f" Best candidate: {top.get('name')} ({top.get('score', 0):.0%}) from {top.get('source')}"
                    
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match",
                        "passed": False,
                        "details": f"No vendor found matching '{vendor_name}' (checked: {', '.join(unified_result.get('sources_checked', []))}).{candidate_info}",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "candidates": [{"name": m.get("name"), "score": m.get("score"), "source": m.get("source")} for m in all_matches[:3]]
                    })
            
            # =============== FREIGHT DIRECTION DETECTION ===============
            # Outbound freight: BOL/Order matches a Sales Order (shipping TO customer)
            # Inbound freight: BOL/Order matches a Purchase Order (receiving FROM vendor)
            freight_direction = "unknown"
            
            if order_reference:
                order_str = str(order_reference).strip()
                
                # Step 1: Try matching against Sales Orders (OUTBOUND freight)
                order_resp = await client.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"number eq '{order_str}'"}
                )
                
                if order_resp.status_code == 200:
                    orders = order_resp.json().get("value", [])
                    if orders:
                        matched_order = orders[0]
                        freight_direction = "outbound"
                        preview_result["freight_direction"] = "outbound"
                        preview_result["freight_direction_details"] = {
                            "direction": "outbound",
                            "reason": "Order reference matches a Sales Order",
                            "description": "Freight cost for shipping TO customer"
                        }
                        preview_result["sales_order_match"] = {
                            "found": True,
                            "number": matched_order.get("number"),
                            "customer_name": matched_order.get("customerName"),
                            "customer_number": matched_order.get("customerNumber"),
                            "order_date": matched_order.get("orderDate"),
                            "status": matched_order.get("status"),
                            "total_amount": matched_order.get("totalAmountIncludingTax")
                        }
                        preview_result["validation"]["checks"].append({
                            "check": "freight_direction",
                            "passed": True,
                            "details": f"OUTBOUND freight - Order {order_str} matches Sales Order for {matched_order.get('customerName')}"
                        })
                
                # Step 2: If no Sales Order match, try Purchase Orders (INBOUND freight)
                if freight_direction == "unknown":
                    po_resp = await client.get(
                        f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"number eq '{order_str}'"}
                    )
                    
                    if po_resp.status_code == 200:
                        pos = po_resp.json().get("value", [])
                        if pos:
                            matched_po = pos[0]
                            freight_direction = "inbound"
                            preview_result["freight_direction"] = "inbound"
                            preview_result["freight_direction_details"] = {
                                "direction": "inbound",
                                "reason": "Order reference matches a Purchase Order",
                                "description": "Freight cost for receiving FROM vendor/supplier"
                            }
                            preview_result["purchase_order_match"] = {
                                "found": True,
                                "number": matched_po.get("number"),
                                "vendor_name": matched_po.get("vendorName"),
                                "vendor_number": matched_po.get("vendorNumber"),
                                "order_date": matched_po.get("orderDate"),
                                "status": matched_po.get("status"),
                                "total_amount": matched_po.get("totalAmountIncludingTax")
                            }
                            preview_result["validation"]["checks"].append({
                                "check": "freight_direction",
                                "passed": True,
                                "details": f"INBOUND freight - Order {order_str} matches Purchase Order from {matched_po.get('vendorName')}"
                            })
                
                # Step 3: If neither matched
                if freight_direction == "unknown":
                    preview_result["freight_direction"] = "unknown"
                    preview_result["freight_direction_details"] = {
                        "direction": "unknown",
                        "reason": f"Order reference '{order_str}' not found in Sales Orders or Purchase Orders",
                        "description": "Could not determine freight direction - manual review needed"
                    }
                    preview_result["validation"]["warnings"].append({
                        "check": "freight_direction",
                        "details": f"Could not determine freight direction - '{order_str}' not found as Sales Order or Purchase Order"
                    })
            else:
                preview_result["freight_direction"] = "unknown"
                preview_result["freight_direction_details"] = {
                    "direction": "unknown",
                    "reason": "No order reference extracted from document",
                    "description": "Cannot determine freight direction without BOL/Order number"
                }
                preview_result["validation"]["warnings"].append({
                    "check": "freight_direction",
                    "details": "No order reference found - cannot determine if inbound or outbound freight"
                })
            
            # Check for duplicate invoice
            if invoice_number:
                dup_resp = await client.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"}
                )
                
                if dup_resp.status_code == 200:
                    existing = dup_resp.json().get("value", [])
                    if existing:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check",
                            "passed": False,
                            "details": f"DUPLICATE: Invoice {invoice_number} already exists in BC"
                        })
                    else:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check",
                            "passed": True,
                            "details": "No duplicate invoice found"
                        })
            
            # Build the Purchase Invoice preview
            line_description = order_reference if order_reference else "Freight"
            
            preview_result["purchase_invoice_preview"] = {
                "header": {
                    "vendorNumber": preview_result["extracted_data"].get("vendor_number", "[VENDOR NOT MATCHED]"),
                    "vendorInvoiceNumber": invoice_number,
                    "invoiceDate": invoice_date,
                    "dueDate": doc.get("due_date_iso"),
                    "currencyCode": doc.get("currency", "USD")
                },
                "lines": [
                    {
                        "lineType": "Item",
                        "itemNumber": "FREIGHT",
                        "description": str(line_description)[:100],
                        "quantity": 1,
                        "unitCost": _parse_amount(total_amount) or 0
                    }
                ],
                "note": "This is what WOULD be posted. No data was written."
            }
            
            # Add folder routing preview
            folder_path, routing_reason, routing_details = determine_folder_path(
                doc,
                freight_direction=preview_result.get("freight_direction"),
                is_international=False
            )
            preview_result["folder_routing"] = {
                "folder_path": folder_path,
                "routing_reason": routing_reason,
                "routing_details": routing_details
            }
            
            # Determine overall validation status
            all_checks_passed = all(c.get("passed", False) for c in preview_result["validation"]["checks"])
            preview_result["validation"]["passed"] = all_checks_passed
            
            if all_checks_passed:
                preview_result["would_write_to_bc"] = True
                preview_result["ready_to_post"] = True
            else:
                preview_result["ready_to_post"] = False
                preview_result["blocking_issues"] = [
                    c["details"] for c in preview_result["validation"]["checks"] if not c.get("passed")
                ]
    
    except Exception as e:
        logger.error("Preview-post error for %s: %s", doc_id, str(e))
        preview_result["errors"].append(str(e))
    
    return preview_result

async def process_incoming_email(email_id: str, mailbox_address: str):
    """Process a new incoming email with attachments."""
    config = await get_email_watcher_config()
    
    if not config.get("enabled"):
        logger.info("Email watcher disabled, skipping email %s", email_id)
        return
    
    # Fetch email and attachments
    email_data = await fetch_email_with_attachments(email_id, mailbox_address)
    
    if email_data.get("status") != "ok":
        logger.error("Failed to fetch email %s: %s", email_id, email_data.get("message"))
        return
    
    email = email_data.get("email", {})
    attachments = email_data.get("attachments", [])
    
    if not attachments:
        logger.info("Email %s has no attachments, skipping", email_id)
        return
    
    # Process each attachment
    for attachment in attachments:
        try:
            # Decode attachment content
            content_bytes = base64.b64decode(attachment.get("content_bytes", ""))
            
            # Create intake request
            intake = DocumentIntake(
                source="email",
                sender=email.get("sender"),
                subject=email.get("subject"),
                attachment_name=attachment.get("name"),
                content_hash=hashlib.sha256(content_bytes).hexdigest(),
                email_id=email_id,
                email_received_utc=email.get("received_utc")
            )
            
            # Save attachment temporarily
            temp_id = str(uuid.uuid4())
            temp_path = UPLOAD_DIR / temp_id
            temp_path.write_bytes(content_bytes)
            
            # Process through intake workflow
            doc_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            # Create document record
            doc = {
                "id": doc_id,
                "source": "email",
                "file_name": attachment.get("name"),
                "sha256_hash": intake.content_hash,
                "file_size": len(content_bytes),
                "content_type": attachment.get("content_type"),
                "email_sender": intake.sender,
                "email_subject": intake.subject,
                "email_id": email_id,
                "email_received_utc": intake.email_received_utc,
                "status": "Received",
                "created_utc": now,
                "updated_utc": now,
                # Pilot metadata (added if pilot mode enabled)
                **get_pilot_metadata()
            }
            await db.hub_documents.insert_one(doc)
            
            # Move temp file to permanent location
            perm_path = UPLOAD_DIR / doc_id
            temp_path.rename(perm_path)
            
            # Run classification
            classification = await classify_document_with_ai(str(perm_path), attachment.get("name"))
            
            suggested_type = classification.get("suggested_job_type", "Unknown")
            confidence = classification.get("confidence", 0.0)
            extracted_fields = classification.get("extracted_fields", {})
            
            # Phase 8: Compute normalized fields including invoice_date and line_items
            normalized_fields = compute_ap_normalized_fields(extracted_fields)
            
            # Phase 7: Vendor alias lookup
            vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
            
            # Get job config and validate
            job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
            
            validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
            decision, reasoning = make_automation_decision(job_configs, confidence, validation_results)
            
            # Update document with ALL extracted data including invoice_date and line_items
            new_status = "NeedsReview" if decision == "needs_review" else "Classified"
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "suggested_job_type": suggested_type,
                "document_type": suggested_type,
                "ai_confidence": confidence,
                "extracted_fields": extracted_fields,
                # Phase 8: Flat normalized fields for BC posting
                "vendor_raw": normalized_fields.get("vendor_raw"),
                "vendor_normalized": normalized_fields.get("vendor_normalized"),
                "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
                "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
                "amount_raw": normalized_fields.get("amount_raw"),
                "amount_float": normalized_fields.get("amount_float"),
                "due_date_raw": normalized_fields.get("due_date_raw"),
                "due_date_iso": normalized_fields.get("due_date_iso"),
                "po_number_raw": normalized_fields.get("po_number_raw"),
                "po_number_clean": normalized_fields.get("po_number_clean"),
                # CRITICAL: Invoice date and line items for automatic BC posting
                "invoice_date": normalized_fields.get("invoice_date"),
                "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
                "line_items": normalized_fields.get("line_items", []),
                # Vendor matching
                "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
                "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
                # Validation
                "validation_results": validation_results,
                "automation_decision": decision,
                "status": new_status,
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
            
            # Move email to appropriate folder
            if decision == "needs_review":
                await move_email_to_folder(email_id, mailbox_address, config.get("needs_review_folder", "Needs Review"))
            else:
                await move_email_to_folder(email_id, mailbox_address, config.get("processed_folder", "Processed"))
            
            logger.info("Processed email attachment: doc_id=%s, type=%s, decision=%s", doc_id, suggested_type, decision)
            
        except Exception as e:
            logger.error("Failed to process attachment from email %s: %s", email_id, str(e))

# ==================== PHASE 7 C1: EMAIL POLLING (OBSERVATION INFRASTRUCTURE) ====================
# This is NOT a product feature - it is data collection plumbing for shadow mode.
# Scope: Poll → Ingest → Log → Metrics. No BC writes, no folder moves.

# Global state for polling worker
_email_polling_task = None
_email_polling_lock = asyncio.Lock()

# Skip patterns for attachments (inline images, signatures)
SKIP_CONTENT_TYPES = {'image/gif', 'image/x-icon', 'image/bmp'}
SKIP_FILENAME_PATTERNS = [
    r'^image\d+\.(png|jpg|gif)$',  # Inline images
    r'^signature',  # Email signatures
    r'^logo',  # Company logos
    r'\.vcf$',  # Contact cards
]


async def record_mail_intake_log(
    message_id: str,
    internet_message_id: str,
    attachment_id: str,
    attachment_hash: str,
    filename: str,
    status: str,
    sharepoint_doc_id: str = None,
    error: str = None
):
    """Record mail intake for idempotency and observability."""
    log_entry = {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "internet_message_id": internet_message_id,
        "attachment_id": attachment_id,
        "attachment_hash": attachment_hash,
        "filename": filename,
        "status": status,  # Processed, SkippedDuplicate, SkippedInline, Error
        "sharepoint_doc_id": sharepoint_doc_id,
        "error": error,
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
    await db.mail_intake_log.insert_one(log_entry)
    return log_entry


async def check_duplicate_mail_intake(internet_message_id: str, attachment_hash: str, message_id: str = None, attachment_id: str = None) -> bool:
    """Check if this attachment was already processed (idempotency).
    
    Primary key: internetMessageId + attachment_hash
    Fallback: message_id + attachment_id (Graph-specific IDs)
    """
    query = {"$or": [
        {"internet_message_id": internet_message_id, "attachment_hash": attachment_hash}
    ]}
    if message_id and attachment_id:
        query["$or"].append({"message_id": message_id, "attachment_id": attachment_id})
    
    existing = await db.mail_intake_log.find_one(query)
    return existing is not None


def should_skip_attachment(filename: str, content_type: str, size_bytes: int) -> tuple:
    """Determine if attachment should be skipped (inline images, signatures, too large)."""
    # Check content type
    if content_type and content_type.lower() in SKIP_CONTENT_TYPES:
        return (True, f"Skipped content type: {content_type}")
    
    # Check filename patterns
    if filename:
        for pattern in SKIP_FILENAME_PATTERNS:
            if re.match(pattern, filename.lower()):
                return (True, f"Skipped filename pattern: {filename}")
    
    # Check size limit
    max_size = EMAIL_POLLING_MAX_ATTACHMENT_MB * 1024 * 1024
    if size_bytes > max_size:
        return (True, f"Skipped size: {size_bytes / 1024 / 1024:.1f}MB > {EMAIL_POLLING_MAX_ATTACHMENT_MB}MB limit")
    
    return (False, None)


async def poll_mailbox_for_attachments():
    """
    Phase C1 (Revised): Passive Graph "Tap" - READ-ONLY.
    
    This is a shadow listener that does NOT modify the mailbox in any way.
    Zetadocs/Square9 continues to own the inbox state.
    
    Process flow:
    1. Get watermark (last seen receivedDateTime)
    2. Query messages received after watermark (with overlap buffer)
    3. For each message with attachments:
       - Check idempotency log (skip duplicates)
       - Store in SharePoint first (durability)
       - Process through intake pipeline
       - Log result
    4. Update watermark
    
    Permissions: Mail.Read only (application permission)
    
    What this does NOT do:
    - Mark messages as read
    - Add categories
    - Move messages
    - Delete anything
    """
    if not EMAIL_POLLING_ENABLED:
        return {"skipped": True, "reason": "EMAIL_POLLING_ENABLED is false"}
    
    if not EMAIL_POLLING_USER:
        return {"skipped": True, "reason": "EMAIL_POLLING_USER not configured"}
    
    if DEMO_MODE:
        return {"skipped": True, "reason": "Demo mode - no real polling"}
    
    run_id = str(uuid.uuid4())[:8]
    logger.info("[EmailPoll:%s] Starting passive tap for %s", run_id, EMAIL_POLLING_USER)
    
    stats = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages_detected": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_inline": 0,
        "attachments_failed": 0,
        "errors": []
    }
    
    try:
        # Get Email token (uses EMAIL_CLIENT_ID/SECRET if configured)
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get Email token")
            return stats
        
        # Get watermark from settings (last seen receivedDateTime)
        watermark_doc = await db.hub_settings.find_one({"type": "email_poll_watermark"}, {"_id": 0})
        
        if watermark_doc and watermark_doc.get("last_received_datetime"):
            # Use watermark with 5-minute overlap buffer for safety
            watermark_time = watermark_doc["last_received_datetime"]
            try:
                watermark_dt = datetime.fromisoformat(watermark_time.replace('Z', '+00:00'))
                buffer_time = (watermark_dt - timedelta(minutes=5)).isoformat()
            except Exception:
                buffer_time = watermark_time
        else:
            # First run: look back N minutes
            buffer_time = (datetime.now(timezone.utc) - timedelta(minutes=EMAIL_POLLING_LOOKBACK_MINUTES)).isoformat()
        
        # Query messages received after watermark
        # Note: hasAttachments filter combined with orderby can cause InefficientFilter error
        # So we filter by date only and check attachments client-side
        filter_query = f"receivedDateTime ge {buffer_time}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            messages_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments",
                    "$top": EMAIL_POLLING_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc"
                }
            )
            
            if messages_resp.status_code != 200:
                error_msg = f"Graph API error {messages_resp.status_code}: {messages_resp.text[:200]}"
                logger.error("[EmailPoll:%s] %s", run_id, error_msg)
                stats["errors"].append(error_msg)
                return stats
            
            messages = messages_resp.json().get("value", [])
            # Filter to only messages with attachments (client-side filter)
            messages_with_attachments = [m for m in messages if m.get("hasAttachments")]
            stats["messages_detected"] = len(messages_with_attachments)
            
            logger.info("[EmailPoll:%s] Detected %d messages with attachments (out of %d total)", run_id, len(messages_with_attachments), len(messages))
            
            # Process each message
            for msg in messages_with_attachments:
                msg_id = msg["id"]
                internet_msg_id = msg.get("internetMessageId", msg_id)
                subject = msg.get("subject", "No Subject")
                sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                
                try:
                    # Fetch attachments list (without contentBytes - not allowed in list query)
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size"}
                    )
                    
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed to fetch attachments for {msg_id}")
                        continue
                    
                    attachments = att_resp.json().get("value", [])
                    
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        size_bytes = att.get("size", 0)
                        
                        # Skip check
                        should_skip, skip_reason = should_skip_attachment(filename, content_type, size_bytes)
                        if should_skip:
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash="",
                                filename=filename,
                                status="SkippedInline",
                                error=skip_reason
                            )
                            stats["attachments_skipped_inline"] += 1
                            continue
                        
                        # Fetch individual attachment content
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{EMAIL_POLLING_USER}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"}
                            )
                            if att_content_resp.status_code != 200:
                                stats["attachments_failed"] += 1
                                stats["errors"].append(f"Failed to fetch content for {filename}")
                                continue
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Error fetching {filename}: {str(e)}")
                            continue
                        
                        # Decode content and hash
                        try:
                            content_bytes = base64.b64decode(content_b64)
                            att_hash = hashlib.sha256(content_bytes).hexdigest()
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Failed to decode {filename}: {str(e)}")
                            continue
                        
                        # Idempotency check
                        if await check_duplicate_mail_intake(internet_msg_id, att_hash):
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="SkippedDuplicate"
                            )
                            stats["attachments_skipped_duplicate"] += 1
                            continue
                        
                        # Process through intake pipeline
                        try:
                            intake_result = await _internal_intake_document(
                                file_content=content_bytes,
                                filename=filename,
                                content_type=content_type,
                                source="email_poll",
                                email_id=msg_id,
                                subject=subject,
                                sender=sender
                            )
                            
                            doc_id = intake_result.get("document", {}).get("id")
                            
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="Processed",
                                sharepoint_doc_id=doc_id
                            )
                            stats["attachments_ingested"] += 1
                            
                            logger.info("[EmailPoll:%s] Ingested %s → doc %s", run_id, filename, doc_id)
                            
                        except Exception as e:
                            await record_mail_intake_log(
                                message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                attachment_hash=att_hash,
                                filename=filename,
                                status="Error",
                                error=str(e)
                            )
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Intake failed for {filename}: {str(e)}")
                    
                    # NO mailbox mutations - we are read-only
                    # Idempotency log is the source of truth, not mailbox state
                
                except Exception as e:
                    stats["errors"].append(f"Failed processing message {msg_id}: {str(e)}")
            
            # Update watermark to newest receivedDateTime seen
            if messages:
                newest_received = max(msg.get("receivedDateTime", "") for msg in messages)
                if newest_received:
                    await db.hub_settings.update_one(
                        {"type": "email_poll_watermark"},
                        {"$set": {
                            "last_received_datetime": newest_received,
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }},
                        upsert=True
                    )
        
    except Exception as e:
        stats["errors"].append(f"Poll run failed: {str(e)}")
        logger.error("[EmailPoll:%s] Run failed: %s", run_id, str(e))
    
    stats["ended_at"] = datetime.now(timezone.utc).isoformat()
    
    # Store run stats (make a copy since insert_one adds _id)
    stats_to_store = stats.copy()
    await db.mail_poll_runs.insert_one(stats_to_store)
    
    logger.info(
        "[EmailPoll:%s] Complete: detected=%d, ingested=%d, skipped_dup=%d, skipped_inline=%d, failed=%d",
        run_id, stats["messages_detected"], stats["attachments_ingested"],
        stats["attachments_skipped_duplicate"], stats["attachments_skipped_inline"], stats["attachments_failed"]
    )
    
    return stats


async def email_polling_worker():
    """Background worker that polls mailbox at configured interval."""
    logger.info("Email polling worker started (interval: %d minutes)", EMAIL_POLLING_INTERVAL_MINUTES)
    
    while True:
        try:
            # Get current interval from config (allows runtime adjustment)
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
            
            # Check if polling is enabled
            async with _email_polling_lock:
                if config.get("enabled", True) and EMAIL_POLLING_ENABLED:
                    await poll_mailbox_for_attachments()
        except Exception as e:
            logger.error("Email polling worker error: %s", str(e))
        
        # Get interval again in case it changed
        try:
            config = await get_email_watcher_config()
            interval = config.get("interval_minutes", EMAIL_POLLING_INTERVAL_MINUTES)
        except:
            interval = EMAIL_POLLING_INTERVAL_MINUTES
        
        # Wait for next interval
        await asyncio.sleep(interval * 60)





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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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

# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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

# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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

# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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

# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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


# Moved to routers/workflows.py (Domain 8)
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











# ==================== WORKFLOW METRICS ====================

# Moved to routers/workflows.py (Domain 8)
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

# Mailbox source routes moved to routers/mailbox_sources.py — REMOVED (Domain 3)
# poll_mailbox_for_documents stays here (used by background worker)


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
# Routes moved to routers/aliases.py — REMOVED (Domain 2)
# Helper record_alias_usage also moved to routers/aliases.py

# Keep VendorAlias model for backward compatibility (may be referenced elsewhere)
class VendorAlias(BaseModel):
    alias_string: str
    vendor_no: str
    vendor_name: Optional[str] = None
    confidence_override: Optional[float] = None
    notes: Optional[str] = None

# ==================== AUTOMATION METRICS ENGINE ====================




class ShadowModeConfig(BaseModel):
    """Configuration for shadow mode tracking."""
    shadow_mode_started_at: Optional[str] = None
    shadow_mode_notes: Optional[str] = None








from services.bc_sandbox_service import (
    get_vendor, search_vendors_by_name, validate_vendor_exists,
    get_customer, get_purchase_order, get_purchase_invoice, get_sales_invoice,
    validate_invoice_exists, validate_ap_invoice_in_bc, validate_sales_invoice_in_bc,
    validate_purchase_order_in_bc, get_bc_sandbox_status,
    PilotModeWriteBlockedError, BCSandboxError, BCLookupResult
)
from services.workflow_engine import BCValidationHistoryEntry















from services.bc_simulation_service import (
    simulate_export_ap_invoice, simulate_create_purchase_invoice,
    simulate_attach_pdf, simulate_sales_invoice_export, simulate_po_linkage,
    run_full_export_simulation, calculate_simulation_summary,
    get_simulation_service_status, SimulationResult, SimulationType, SimulationStatus
)
from services.workflow_engine import SimulationHistoryEntry










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


# Sales file import routes moved to routers/file_import.py — REMOVED (Domain 4)

# ---------------------------------------------------------------------------
# NOTE: Router imports and app.include_router() calls that used to live here
# have been removed.  All router wiring is now in main.py (the single
# authoritative FastAPI app).  server.py is a library only.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Startup / shutdown are called explicitly by main.py, not via app events.
# ---------------------------------------------------------------------------
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
    # Initialize centralized deps module for modular routers
    from deps import set_db as set_deps_db
    set_deps_db(db)
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
    if sharepoint_migration_module:
        sharepoint_migration_module.db = db
    await db.migration_candidates.create_index("source_item_id", unique=True)
    await db.migration_candidates.create_index("status")
    await db.migration_candidates.create_index("doc_type")
    logger.info("SharePoint Migration module initialized")
    
    # Initialize Event-Driven Workflow Services (Phase 1 & 2)
    set_event_service(db)
    set_derived_state_service(db)
    await initialize_event_indexes(db)
    logger.info("Event-driven workflow services initialized")
    
    # Initialize BC Write Safety Guard
    event_service = get_event_service()
    set_write_guard(event_service)
    guard_status = get_write_guard().get_status()
    logger.info("BC Write Safety Guard initialized: %s", guard_status["message"])
    
    # Initialize Reference Intelligence Service
    bc_resolver = get_reference_resolver()
    set_reference_intelligence_service(db, bc_resolver=bc_resolver, event_service=event_service)
    logger.info("Reference Intelligence Service initialized")
    
    # Initialize BC Reference Cache Service
    cache_service = set_cache_service(db, event_service=event_service)
    await cache_service.initialize()
    bc_resolver.set_cache_service(cache_service)
    cache_service.start_background_sync()
    logger.info("BC Reference Cache Service initialized (background sync enabled)")
    
    # Initialize Auto-Resolution Service
    ref_intel_service = get_reference_intelligence_service()
    auto_resolve = set_auto_resolve_service(db, ref_intel_service, event_service)
    auto_resolve.start()
    logger.info("Auto-Resolution Service initialized (5 workers)")
    
    # Initialize Vendor Intelligence Service
    vendor_intel = set_vendor_intelligence_service(db, event_service)
    await vendor_intel.initialize()
    auto_resolve.set_vendor_intelligence(vendor_intel)
    logger.info("Vendor Intelligence Service initialized")
    
    # Initialize Automation Rules Engine
    rules_engine = set_automation_rules_service(db, event_service, vendor_intel)
    await rules_engine.initialize()
    auto_resolve.set_rules_engine(rules_engine)
    logger.info("Automation Rules Engine initialized")
    
    # Initialize Freight G/L Routing Service
    freight_gl = set_freight_gl_service(db, event_service, vendor_intel)
    await freight_gl.initialize()
    auto_resolve.set_freight_gl_service(freight_gl)
    logger.info("Freight G/L Routing Service initialized")
    
    # Initialize AP Validation Service and inject into auto-resolution
    bc_service = get_bc_service()
    ap_validation_svc = APValidationService(db, bc_service=bc_service, event_service=event_service)
    auto_resolve.set_ap_validation_service(ap_validation_svc)
    logger.info("AP Validation Service initialized and wired into auto-resolution pipeline")
    
    # Initialize Label Correction Service (feedback loop)
    label_correction_svc = set_label_correction_service(db, event_service)
    await label_correction_svc.initialize()
    auto_resolve.set_label_correction_service(label_correction_svc)
    ref_intel_service.set_label_correction_service(label_correction_svc)
    ref_intel_service.set_vendor_intelligence_service(vendor_intel)
    logger.info("Label Correction Feedback Loop initialized")
    
    # Initialize Alert Pattern Service (threshold alerts)
    alert_svc = set_alert_pattern_service(db, event_service)
    await alert_svc.initialize()
    await alert_svc.evaluate_patterns()  # Initial evaluation
    alert_svc.start_background_eval()
    logger.info("Alert Pattern Service initialized with background evaluation")
    
    # Initialize Vendor Extraction Profile Service (adaptive interpretation layer)
    vep_svc = set_vep_service(db, event_service)
    await vep_svc.initialize()
    ref_intel_service.set_vep_service(vep_svc)
    await vep_svc.generate_all_profiles()  # Initial profile generation
    vep_svc.start_background_learning()
    logger.info("Vendor Extraction Profile Service initialized with background learning")
    
    # Initialize Layout Fingerprint Service (structural document analysis)
    layout_fp_svc = set_layout_fingerprint_service(db, event_service)
    await layout_fp_svc.initialize()
    ref_intel_service.set_layout_fingerprint_service(layout_fp_svc)
    auto_resolve.set_layout_fingerprint_service(layout_fp_svc)
    logger.info("Layout Fingerprint Service initialized")
    
    # Initialize Stable Vendor Auto-Ready Service
    from services.stable_vendor_service import set_stable_vendor_service
    stable_vendor_svc = set_stable_vendor_service(
        db, event_service=event_service, vendor_intel_service=vendor_intel,
        layout_fp_service=layout_fp_svc, alert_service=alert_svc,
    )
    await stable_vendor_svc.initialize()
    auto_resolve.set_stable_vendor_service(stable_vendor_svc)
    logger.info("Stable Vendor Auto-Ready Service initialized")
    
    # Start daily pilot summary scheduler if enabled
    global _pilot_summary_task
    if PILOT_MODE_ENABLED and DAILY_PILOT_EMAIL_ENABLED:
        from routers.pilot import _daily_pilot_summary_scheduler
        _pilot_summary_task = asyncio.create_task(_daily_pilot_summary_scheduler())
        logger.info("Daily pilot summary scheduler started (cron: %d:00 UTC)", PILOT_SUMMARY_CRON_HOUR_UTC)
    
    logger.info("GPI Document Hub started. Demo mode: %s, Loaded %d vendor aliases", DEMO_MODE, len(aliases))

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
    # Stop BC cache background sync
    cache = get_cache_service()
    if cache:
        cache.stop_background_sync()
    # Stop auto-resolution workers
    auto_resolve = get_auto_resolve_service()
    if auto_resolve:
        auto_resolve.stop()
    client.close()
