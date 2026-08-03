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
from workflows.core.engine import (
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
# Phase 3 Step 4d.2b: `db` and `client` authoritative home migrated to
# backend/database.py. Retained here as re-exports for compatibility
# (external importers via ``from server import db`` and in-module
# shutdown hooks referencing ``client.close()``).
from database import db, client

# Config
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
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
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Shared Documents')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# LLM Vendor Ranking — feature flag + threshold
VENDOR_RANKING_CONFIDENCE_THRESHOLD = float(
    os.environ.get("VENDOR_RANKING_CONFIDENCE_THRESHOLD", "0.80")
)

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
# Authoritative implementation: routers/auth.py and services/auth_deps.py
# ==================== BUSINESS CENTRAL SERVICE ====================
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

# ==================== SPIRO INTEGRATION ====================
# Router registration is authoritative in main.py.
from services.spiro.spiro_sync import set_spiro_db

# ==================== MICROSOFT TOKEN HELPERS ====================
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
# still calls these functions directly.
# ---------------------------------------------------------------------------


# Direct canonical AP eligibility import
from services.ap_computation import is_eligible_for_draft_creation


# ==================== WORKFLOW ENGINE ====================

from services.document_orchestration_service import run_upload_and_link_workflow

# ==================== DOCUMENT ENDPOINTS ====================

# Upload storage path
# Phase 3 Step 4d.2a: UPLOAD_DIR authoritative home migrated to backend/paths.py.
# Retained here as a re-export for external importers (``from server import UPLOAD_DIR``).
from paths import UPLOAD_DIR

# Document routes moved to routers/documents.py — REMOVED (Domain 7)
# Simple routes (list, get, update, delete, events, timeline, derived-state, refresh-state,
# file, square9-status, reset-retries) are implemented directly in routers/documents.py.
# Complex routes below remain as functions (no decorator) for thin-wrapper import.

# list_documents — moved to routers/documents.py (Domain 7)


# get_document — moved to routers/documents.py (Domain 7)


# =============================================================================
# EVENT-DRIVEN WORKFLOW ENDPOINTS — moved to routers/documents.py (Domain 7)
# =============================================================================

# get_document_events — moved to routers/documents.py

# get_document_timeline — moved to routers/documents.py

# get_document_derived_state — moved to routers/documents.py

# refresh_document_state — moved to routers/documents.py
# =============================================================================
# VENDOR INTELLIGENCE ENDPOINTS
# =============================================================================


# automation-rules routes moved to routers/automation_rules.py — REMOVED (duplicate)
# vendor-extraction-profiles route moved to routers/vendor_extraction_profiles.py — REMOVED (duplicate)


# update_document — moved to routers/documents.py (Domain 7)

# delete_document — moved to routers/documents.py (Domain 7)


# get_document_file — moved to routers/documents.py (Domain 7)


# =============================================================================
# SQUARE9 WORKFLOW ENDPOINTS — status/reset moved to routers/documents.py (Domain 7)
# =============================================================================

# get_square9_status — moved to routers/documents.py (Domain 7)


# ==================== DASHBOARD ====================


# ---------------------------------------------------------------------------
# COMPATIBILITY WRAPPER: dashboard aggregation
# Authoritative source: services.dashboard_helpers.aggregate_document_types_data
# This wrapper exists because no internal server.py code calls it, but
# the function name is retained for compatibility during transition.
# ---------------------------------------------------------------------------

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
    """Load saved config from MongoDB and apply to module globals.
    Also syncs to services.config_service so downstream consumers stay in sync.
    """
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

    # Sync to config_service so routers/services that import from there stay current
    from services import config_service as _cs
    _cs.DEMO_MODE = DEMO_MODE
    _cs.TENANT_ID = TENANT_ID
    _cs.BC_ENVIRONMENT = BC_ENVIRONMENT
    _cs.BC_COMPANY_NAME = BC_COMPANY_NAME
    _cs.BC_CLIENT_ID = BC_CLIENT_ID
    _cs.BC_CLIENT_SECRET = BC_CLIENT_SECRET
    _cs.GRAPH_CLIENT_ID = GRAPH_CLIENT_ID
    _cs.GRAPH_CLIENT_SECRET = GRAPH_CLIENT_SECRET
    _cs.SHAREPOINT_SITE_HOSTNAME = SHAREPOINT_SITE_HOSTNAME
    _cs.SHAREPOINT_SITE_PATH = SHAREPOINT_SITE_PATH
    _cs.SHAREPOINT_LIBRARY_NAME = SHAREPOINT_LIBRARY_NAME

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

def _build_vendor_resolution(
    vendor_raw: str,
    match_result: dict,
) -> dict:
    """Compatibility wrapper for vendor-resolution observability."""
    from services.vendor_resolution_helpers import (
        _build_vendor_resolution as _impl,
    )
    return _impl(vendor_raw, match_result)


VENDOR_ALIAS_MAP = {
    # "Alias on Invoice": "Vendor Name in BC"
    # Add company-specific aliases here
}

# COMPATIBILITY NOTE: VENDOR_ALIAS_MAP above is server.py's local copy.
# The authoritative VENDOR_ALIAS_MAP is now in services.vendor_name_helpers.
# Both references exist because some internal server.py code still uses the local,
# while extracted modules use the authoritative one. Future passes should unify.

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
# ==================== FIELD NORMALIZATION ====================

def normalize_extracted_fields(fields: dict) -> dict:
    """Compatibility wrapper — delegates to document_intel_helpers."""
    from services.document_intel_helpers import normalize_extracted_fields as _impl
    return _impl(fields)
# Authoritative source: services.vendor_name_helpers
# These wrappers exist because internal server.py code (match_vendor_in_bc,
# lookup_vendor_alias, etc.) still calls these functions directly.
# ---------------------------------------------------------------------------
from services.vendor_name_helpers import normalize_vendor_name, calculate_fuzzy_score

# ---------------------------------------------------------------------------
# DIRECT CANONICAL IMPORTS: AP compute functions
# Phase 3 Step 2R (2026-04-23): the `compute_ap_*` shim wrappers that lived
# in this file were deleted in favor of direct imports of the authoritative
# implementations. Call sites below use these names unchanged.
# ---------------------------------------------------------------------------
from services.ap_computation import (
    compute_ap_status,
    compute_draft_candidate_flag,
)
from services.document_intel_helpers import (
    make_automation_decision as _make_automation_decision,
)

# ---------------------------------------------------------------------------
# COMPATIBILITY WRAPPER: match_vendor_in_bc
# Authoritative source: services.vendor_matching
# ---------------------------------------------------------------------------
async def match_vendor_in_bc(
    vendor_name: str,
    strategies: list,
    threshold: float,
    token: str,
    company_id: str,
) -> dict:
    from services.vendor_matching import match_vendor_in_bc as _impl
    return await _impl(vendor_name, strategies, threshold, token, company_id)

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


# ==================== AUTOMATION DECISION ENGINE ====================
async def get_email_watcher_config() -> dict:
    """COMPATIBILITY WRAPPER — authoritative source: services.email_polling_service"""
    from services.email_polling_service import get_email_watcher_config as _impl
    return await _impl()

async def subscribe_to_mailbox_notifications(mailbox_address: str, webhook_url: str) -> dict:
    """COMPATIBILITY WRAPPER — authoritative source: services.email_polling_service"""
    from services.email_polling_service import subscribe_to_mailbox_notifications as _impl
    return await _impl(mailbox_address, webhook_url)

async def fetch_email_with_attachments(email_id: str, mailbox_address: str) -> dict:
    """COMPATIBILITY WRAPPER — authoritative source: services.email_polling_service"""
    from services.email_polling_service import fetch_email_with_attachments as _impl
    return await _impl(email_id, mailbox_address)

from services.email_polling_service import move_email_to_folder

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
        extracted_fields = doc.get("extracted_fields") or {}
        
        # Get job config
        job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])
        
        # Run BC validation
        from services.bc_validation_service import validate_bc_match
        # Pass vendor_canonical from ref intel to help validation
        if doc.get("vendor_canonical"):
            extracted_fields.setdefault("_vendor_canonical", doc["vendor_canonical"])
        validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
        
        # Make automation decision
        confidence = doc.get("ai_confidence") or 0.0
        decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)
        
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

        # === PER-DOCUMENT LEARNING: Learn from EVERY ingested document ===
        try:
            from services.per_document_learning_service import learn_from_document
            await learn_from_document(db, doc_id, trigger="ingestion")
        except Exception as pdl_err:
            logger.debug("[PerDocLearn] Ingestion learning for %s: %s", doc_id[:8], pdl_err)

        # === PREDICTIVE READINESS: Predict if this doc will need human review ===
        try:
            from services.deep_learning_engine import predict_and_store
            prediction = await predict_and_store(db, doc_id)
            pred_rec = prediction.get("recommendation", "unknown")
            logger.info("[PredictiveReadiness] doc=%s recommendation=%s prob=%.2f",
                        doc_id[:8], pred_rec, prediction.get("review_probability", 0))
        except Exception as pred_err:
            logger.debug("[PredictiveReadiness] Prediction for %s: %s", doc_id[:8], pred_err)

        # Auto-file check: if this doc type + vendor pattern has been filed enough times, auto-clear it
        # SAFETY: Must still pass PO validation checks — never auto-file if PO is missing from BC
        # SAFETY: Never auto-file Inside Sales Pilot documents
        _is_pilot_for_filing = doc.get("inside_sales_pilot") or doc.get("source") == "inside_sales_pilot"
        if new_status == "NeedsReview" and not _is_pilot_for_filing:
            try:
                doc_type_for_filing = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
                vendor_for_filing = (doc.get("vendor_canonical") or doc.get("normalized_fields", {}).get("vendor") or "").lower()
                if doc_type_for_filing and vendor_for_filing:
                    filing_match = await db.filing_actions.find_one(
                        {"document_type": doc_type_for_filing, "vendor_lower": vendor_for_filing, "count": {"$gte": 3}},
                        {"_id": 0}
                    )
                    if filing_match:
                        folder_path = filing_match["folder_path"]
                        auto_now = datetime.now(timezone.utc).isoformat()

                        # Determine final status based on validation outcome:
                        # If validation has required failures, mark as "AutoFiled" (not "Completed")
                        # so reps can still see the validation issue needs resolution.
                        has_required_failures = any(
                            not c.get("passed") and c.get("required")
                            for c in validation_results.get("checks", [])
                        )

                        # CRITICAL: Block auto-file if PO not found in BC (AP invoices)
                        # PO checks are optional (required=False) but MUST still block auto-filing
                        has_po_blocker = False
                        if doc_type_for_filing in ("AP_Invoice", "AP_INVOICE", "Purchase_Invoice"):
                            val_warnings = validation_results.get("warnings", [])
                            val_checks = validation_results.get("checks", [])
                            for w in val_warnings:
                                wn = w.get("check_name", "") if isinstance(w, dict) else str(w)
                                if "po_not_found" in wn or "po_bc_api_error" in wn:
                                    has_po_blocker = True
                                    break
                            if not has_po_blocker:
                                for c in val_checks:
                                    if isinstance(c, dict) and c.get("check_name") in ("po_validation", "po_match"):
                                        if not c.get("passed", True):
                                            has_po_blocker = True
                                            break

                        if has_po_blocker:
                            logger.info("[Workflow:%s] Auto-file BLOCKED for %s: PO not found in BC — sending to review",
                                        run_id, doc_id)
                        elif not has_required_failures:
                            auto_clear_status = "Completed"
                            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                                "auto_cleared": True,
                                "auto_clear_decision": "Cleared",
                                "auto_clear_reason": f"Auto-filed (learned from {filing_match['count']} previous filings)",
                                "auto_clear_details": {"method": "ai_auto_file", "pattern_count": filing_match["count"], "validation_override": False},
                                "status": auto_clear_status,
                                "workflow_status": "completed",
                                "sharepoint_folder_suggestion": folder_path,
                                "filed_at": auto_now,
                                "filed_folder": folder_path,
                                "updated_utc": auto_now,
                            }})
                            await db.filing_actions.update_one(
                                {"_id": filing_match.get("_id", filing_match)},
                                {"$inc": {"auto_filed_count": 1}, "$set": {"last_auto_filed_at": auto_now}},
                            )
                            logger.info("[Workflow:%s] Auto-filed doc %s to '%s' (pattern count: %d)",
                                        run_id, doc_id, folder_path, filing_match["count"])
                            # Record positive classification confirmation
                            try:
                                from services.classification_feedback_service import record_confirmation, _build_doc_context
                                await record_confirmation(
                                    doc_id=doc_id,
                                    confirmed_type=doc_type_for_filing,
                                    confirmation_source="auto_clear",
                                    doc_context=_build_doc_context(doc),
                                )
                            except Exception:
                                pass
                            # === PER-DOCUMENT LEARNING: Auto-file is a strong positive signal ===
                            try:
                                from services.per_document_learning_service import learn_from_document
                                await learn_from_document(db, doc_id, trigger="auto_file")
                            except Exception:
                                pass
            except Exception as af_err:
                logger.warning("[Workflow:%s] Auto-file check failed for %s: %s", run_id, doc_id, str(af_err))
        
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
    Phase 3 Step 4d.7: COMPATIBILITY WRAPPER.

    Body moved verbatim to
    ``workflows.document_capture.rules.workflow_status.update_standard_workflow_status``.
    This shim is retained so existing imports
    (``from server import _update_standard_workflow_status``) continue to
    resolve during the remaining carve-out steps.
    """
    from workflows.document_capture.rules.workflow_status import (
        update_standard_workflow_status,
    )
    return await update_standard_workflow_status(
        doc_id, doc_type, confidence, normalized_fields,
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
    Phase 3 Step 4d.6: COMPATIBILITY WRAPPER.

    Body moved verbatim to
    ``workflows.ap_invoice.rules.workflow_status.update_ap_workflow_status``.
    This shim is retained so existing imports
    (``from server import _update_ap_workflow_status``) continue to resolve
    during the remaining carve-out steps.
    """
    from workflows.ap_invoice.rules.workflow_status import update_ap_workflow_status
    return await update_ap_workflow_status(
        doc_id, confidence, normalized_fields,
        vendor_alias_result, validation_results, ap_validation,
    )
def _derive_workflow_status(final_status: str, doc_type: str, decision: str) -> str:
    """COMPATIBILITY WRAPPER — authoritative source: services.classification_helpers"""
    from services.classification_helpers import derive_workflow_status as _impl
    return _impl(final_status, doc_type, decision)


async def _update_vendor_profile_incremental(db, doc_id: str, vendor_name: str, update_data: dict, final_status: str):
    """COMPATIBILITY WRAPPER — authoritative source:
    workflows.ap_invoice.rules.vendor_profile.update_vendor_profile_incremental

    Moved out of server.py during Orchestration Extraction so
    `services/document_handlers.py` no longer needs a late
    `from server import ...`.
    """
    from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental as _impl
    return await _impl(db, doc_id, vendor_name, update_data, final_status)


async def _attempt_llm_vendor_ranking(
    doc_id: str,
    vendor_alias_result: dict,
    vendor_raw: str,
    normalized_fields: dict,
) -> tuple:
    """Compatibility wrapper for LLM-assisted vendor ranking."""
    from services.vendor_resolution_helpers import (
        _attempt_llm_vendor_ranking as _impl,
    )
    return await _impl(
        doc_id,
        vendor_alias_result,
        vendor_raw,
        normalized_fields,
    )


async def _run_pilot_enrichment(pid: str):
    """Phase 3 Step 4d.8: COMPATIBILITY WRAPPER.

    Body moved verbatim to
    ``workflows.document_capture.rules.pilot_enrichment.run_pilot_enrichment``.
    This shim is retained so existing references (`server._run_pilot_enrichment`)
    continue to resolve during the remaining carve-out steps.
    """
    from workflows.document_capture.rules.pilot_enrichment import run_pilot_enrichment
    return await run_pilot_enrichment(pid)


async def _maybe_stage_inventory_xls(doc_id: str) -> None:
    """Phase 3 Step 4d.8: COMPATIBILITY WRAPPER.

    Body moved verbatim to the same canonical home as
    ``run_pilot_enrichment`` (its only caller); kept module-private there.
    This shim is retained so existing references
    (`server._maybe_stage_inventory_xls`) continue to resolve.
    """
    from workflows.document_capture.rules.pilot_enrichment import (
        _maybe_stage_inventory_xls as _impl,
    )
    return await _impl(doc_id)


# _internal_intake_document moved to services/document_handlers.py::intake_document_from_bytes (Phase 3 Step 4b, 2026-04-23)


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
    Phase 3 Step 4d.5: COMPATIBILITY WRAPPER.

    Body moved verbatim to
    ``services.event_service.emit_intake_events``. This shim is retained
    so existing imports (``from server import _emit_intake_events``)
    continue to resolve during the remaining carve-out steps.
    """
    from services.event_service import emit_intake_events
    return await emit_intake_events(
        doc_id, correlation_id, classification, validation_results,
        sp_result, decision, auto_clear_result,
    )


# ==================== PHASE 7 C1: EMAIL POLLING (OBSERVATION INFRASTRUCTURE) ====================
# Authoritative source: services/email_polling_service.py

_email_polling_task = None
# ==================== LEGACY MIGRATION ENDPOINTS ====================

class MigrationRequest(BaseModel):
    """Request model for starting a migration job."""
    source_file: Optional[str] = None
    source_filter: Optional[str] = None  # "SQUARE9" or "ZETADOCS"
    doc_type_filter: Optional[str] = None
    limit: Optional[int] = None
    mode: str = "dry_run"  # "dry_run" or "real"


# ==================== MAILBOX SOURCES CRUD ====================

# Mailbox source routes moved to routers/mailbox_sources.py — REMOVED (Domain 3)
# poll_mailbox_for_documents authoritative source: services.email_polling_service
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
    get_vendor, validate_vendor_exists,
    get_customer, get_purchase_order, get_purchase_invoice, get_sales_invoice,
    validate_invoice_exists, validate_ap_invoice_in_bc, validate_sales_invoice_in_bc,
    validate_purchase_order_in_bc, get_bc_sandbox_status,
    PilotModeWriteBlockedError, BCSandboxError, BCLookupResult
)
from workflows.core.engine import BCValidationHistoryEntry


from services.bc_simulation_service import (
    simulate_export_ap_invoice, simulate_create_purchase_invoice,
    simulate_attach_pdf, simulate_sales_invoice_export, simulate_po_linkage,
    run_full_export_simulation, calculate_simulation_summary,
    get_simulation_service_status, SimulationResult, SimulationType, SimulationStatus
)
from workflows.core.engine import SimulationHistoryEntry


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
    from workflows.core.engine import DocType, WorkflowStatus
    
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
# Authoritative source: services/email_polling_service.py

_dynamic_mailbox_polling_task = None
_mailbox_last_poll_times = {}  # Legacy — real state is in email_polling_svc


# ---------------------------------------------------------------------------
# Startup / shutdown are called explicitly by main.py, not via app events.
# ---------------------------------------------------------------------------
async def startup():
    global _dynamic_mailbox_polling_task
    global _email_polling_task
    global _sales_polling_task
    from services.lifecycle_service import register_background_task
    from services.lifecycle_startup_service import initialize_core_indexes
    await initialize_core_indexes(db=db, logger=logger)
    from services.lifecycle_startup_service import initialize_pre_scheduler_services
    aliases = await initialize_pre_scheduler_services(
        db=db,
        logger=logger,
        sales_email_polling_enabled=SALES_EMAIL_POLLING_ENABLED,
        sales_email_polling_user=SALES_EMAIL_POLLING_USER,
        sales_email_polling_interval_minutes=SALES_EMAIL_POLLING_INTERVAL_MINUTES,
        load_config_from_db=_load_config_from_db,
        default_job_types=DEFAULT_JOB_TYPES,
        vendor_alias_map=VENDOR_ALIAS_MAP,
    )
    
    # Start dynamic mailbox polling worker (polls mailboxes configured via UI)
    import services.email_polling_service as email_polling_svc
    # Ensure idempotency indexes on mail_intake_log before any worker runs.
    try:
        await email_polling_svc.ensure_mail_intake_indexes()
        logger.info("mail_intake_log indexes ensured")
    except Exception as _e:
        logger.warning("ensure_mail_intake_indexes failed (non-fatal): %s", _e)
    from services.lifecycle_scheduler_service import start_email_polling_tasks
    polling_tasks = start_email_polling_tasks(
        logger=logger, register_background_task=register_background_task,
        email_polling_svc=email_polling_svc,
        email_polling_enabled=EMAIL_POLLING_ENABLED,
        email_polling_interval_minutes=EMAIL_POLLING_INTERVAL_MINUTES,
        email_polling_user=EMAIL_POLLING_USER,
        sales_email_polling_enabled=SALES_EMAIL_POLLING_ENABLED,
        sales_email_polling_interval_minutes=SALES_EMAIL_POLLING_INTERVAL_MINUTES,
        sales_email_polling_user=SALES_EMAIL_POLLING_USER,
    )
    _dynamic_mailbox_polling_task = polling_tasks["dynamic"]
    if polling_tasks["email"] is not None: _email_polling_task = polling_tasks["email"]
    if polling_tasks["sales"] is not None: _sales_polling_task = polling_tasks["sales"]

    # Start Inside Sales Pilot worker (controlled ingestion for mkoch/nhannover)
    from services.inside_sales_pilot_service import (
        INSIDE_SALES_PILOT_ENABLED as _ISP_ENABLED,
        INSIDE_SALES_PILOT_MAILBOXES as _ISP_MAILBOXES,
        INSIDE_SALES_PILOT_INTERVAL_MINUTES as _ISP_INTERVAL,
        inside_sales_pilot_worker,
        ensure_pilot_indexes,
    )
    await ensure_pilot_indexes(db)
    from services.lifecycle_scheduler_service import start_inside_sales_pilot_tasks
    inside_sales_pilot_task = start_inside_sales_pilot_tasks(
        logger=logger, register_background_task=register_background_task,
        inside_sales_pilot_enabled=_ISP_ENABLED,
        inside_sales_pilot_worker=inside_sales_pilot_worker,
        inside_sales_pilot_mailboxes=_ISP_MAILBOXES,
        inside_sales_pilot_interval_minutes=_ISP_INTERVAL,
    )
    if inside_sales_pilot_task is not None:
        _inside_sales_pilot_task = inside_sales_pilot_task

    # Initialize email service
    email_service = EmailService(db=db)
    set_email_service(email_service)
    await db.email_logs.create_index("message_id")
    await db.email_logs.create_index("sent_at")
    logger.info("Email service initialized (provider: mock)")
    
    # Initialize migration candidate indexes
    await db.migration_candidates.create_index("source_item_id", unique=True)
    await db.migration_candidates.create_index("status")
    await db.migration_candidates.create_index("doc_type")
    logger.info("Migration candidate indexes initialized")
    
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
    
    # Start BC Catalog Sync scheduler (every 24h)
    from services.lifecycle_scheduler_service import start_catalog_sync_tasks
    start_catalog_sync_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("BC Catalog Sync scheduler started (interval: 24h)")

    # ── Intake Learning Refresh scheduler (daily) ──
    # Keeps the Giovanni-style intake_insights current by re-learning
    # for any customer whose BC posted orders changed in the last 24h
    # and re-running intake learning on their open docs + pending XLS
    # staging. Read-only — never writes to BC.
    from services.lifecycle_scheduler_service import start_intake_learning_tasks
    start_intake_learning_tasks(
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Intake Learning Refresh scheduler started (interval: 24h)")

    # ── Intake Pattern Hygiene scheduler (nightly) ──
    # Calls the unified pattern-health service which runs hygiene across
    # BOTH intake (`order_line_patterns`) and AP (`posting_pattern_analysis`)
    # adapters. Consolidates two previously-separate schedulers into one.
    logger.info("Unified Pattern Hygiene scheduler started (interval: 24h, domains: sales_intake + ap_posting)")

    # ── Drift Alert scheduler (nightly, v2.5.0) ──
    # Scans the unified learning_events_v2 log for anomalies (trusted-pattern
    # rejections, bounds drift, AP template drift, catalog explosions) and
    # writes structured alerts to `learning_drift_alerts`.
    from services.lifecycle_scheduler_service import start_learning_reporting_tasks
    start_learning_reporting_tasks(
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Drift Alert scheduler started (interval: 24h)")

    # ── Weekly Digest scheduler (v2.5.2) ──
    # Rebuilds the current-week digest every 24h so `/api/learning/digest/latest`
    # always reflects the in-progress week. Idempotent by week_key.
    logger.info("Weekly Digest scheduler started (interval: 24h, rebuilds current-week digest)")

    # ── Drift Watchlist scheduler (v2.5.4) ───────────────────────
    # Dispatches the weekly vendor Drift Watchlist to the channels
    # configured in DRIFT_WATCHLIST_CHANNELS (teams_webhook / graph_channel /
    # email). Fires once every 24h; each tick checks whether "now" matches
    # the configured day-of-week (0=Mon..6=Sun) and hour window. Defaults to
    # Monday 07:00 local server time.
    from services.lifecycle_scheduler_service import start_monitoring_tasks
    start_monitoring_tasks(
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Drift Watchlist scheduler started (check: hourly; fires once per target day/hour)")

    # Start BC Shipment Sync scheduler (every 1h)
    from services.lifecycle_scheduler_service import start_bc_maintenance_tasks
    start_bc_maintenance_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("BC Shipment Sync scheduler started (interval: 1h)")

    # Start Knowledge Base auto-seed scheduler (on startup + every 6h)
    logger.info("Knowledge Seed scheduler started (on startup + every 6h)")

    # ── Daily Trace scheduler — runs random PROD BC invoice traces ──
    logger.info("Daily Trace scheduler started (interval: 24h)")

    # Initialize Auto-Resolution Service
    ref_intel_service = get_reference_intelligence_service()
    auto_resolve = set_auto_resolve_service(db, ref_intel_service, event_service)
    auto_resolve.start()
    logger.info("Auto-Resolution Service initialized (5 workers)")

    # ── Startup: Re-queue any "not_run" docs that were lost from in-memory queue ──
    from services.lifecycle_scheduler_service import start_startup_requeue_tasks

    start_startup_requeue_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
        get_auto_resolve_service=get_auto_resolve_service,
    )

    # ── Startup + periodic readiness status-sync tasks ──
    from services.lifecycle_scheduler_service import start_status_sync_tasks

    start_status_sync_tasks(
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Periodic sync-readiness-to-status scheduler started (interval: 30min)")

    # ── Startup: Clean up noise events from posting_learning_events ──
    from services.lifecycle_scheduler_service import start_startup_repair_tasks

    start_startup_repair_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )

    # ── Startup: Fix shipping docs incorrectly parked/escalated by PO retry ──


    # ── Startup: Backfill bc_purchase_invoice_no from bc_purchase_invoice.bc_record_no ──
    from services.lifecycle_scheduler_service import start_pi_backfill_tasks

    start_pi_backfill_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )

    
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
        from services.lifecycle_scheduler_service import start_pilot_summary_tasks
        _pilot_summary_task = start_pilot_summary_tasks(register_background_task=register_background_task, _daily_pilot_summary_scheduler=_daily_pilot_summary_scheduler)
        logger.info("Daily pilot summary scheduler started (cron: %d:00 UTC)", PILOT_SUMMARY_CRON_HOUR_UTC)
    
    logger.info("GPI Document Hub started. Demo mode: %s, Loaded %d vendor aliases", DEMO_MODE, len(aliases))

    # Start Draft Feedback Sync scheduler (every 2h)
    from services.lifecycle_scheduler_service import start_draft_feedback_tasks
    start_draft_feedback_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Draft Feedback Sync + Continuous Learning scheduler started (interval: 2h)")

    # === Deep Learning: Self-Correction + Vendor Maturity (every 4 hours) ===
    from services.lifecycle_scheduler_service import start_intelligence_tasks
    start_intelligence_tasks(
        db=db,
        logger=logger,
        register_background_task=register_background_task,
    )
    logger.info("Deep Learning scheduler started (self-correction + vendor maturity, interval: 4h)")

    # === Intelligence Maintenance: Duplicate Clearing + Escalation Backfill (every 2 hours) ===
    logger.info("Intelligence Maintenance scheduler started (dup clear + escalation + dup backfill, interval: 2h)")

    # === PO Auto-Retry Queue (every 4 hours) ===
    PO_RETRY_INTERVAL_HOURS = 4
    PO_MAX_WAIT_DAYS = 3
    PO_MAX_RETRIES = PO_MAX_WAIT_DAYS * 24 // PO_RETRY_INTERVAL_HOURS  # = 18

    # === Captured Doc Auto-Retry (every 5 minutes) ===
    CAPTURED_RETRY_INTERVAL_SECONDS = 300   # 5 min
    CAPTURED_STALE_THRESHOLD_SECONDS = 300  # Docs stuck >5 min
    CAPTURED_MAX_RETRIES = 4

    from services.lifecycle_scheduler_service import start_captured_retry_tasks
    from services.document_reprocess_service import reprocess_document_inner
    start_captured_retry_tasks(db=db, logger=logger, register_background_task=register_background_task, _reprocess_document_inner=reprocess_document_inner, CAPTURED_RETRY_INTERVAL_SECONDS=CAPTURED_RETRY_INTERVAL_SECONDS, CAPTURED_STALE_THRESHOLD_SECONDS=CAPTURED_STALE_THRESHOLD_SECONDS, CAPTURED_MAX_RETRIES=CAPTURED_MAX_RETRIES)
    logger.info("Captured Doc Auto-Retry scheduler started (interval: %ds, max retries: %d)", CAPTURED_RETRY_INTERVAL_SECONDS, CAPTURED_MAX_RETRIES)

    from services.lifecycle_scheduler_service import start_po_retry_tasks
    start_po_retry_tasks(db=db, logger=logger, register_background_task=register_background_task, PO_RETRY_INTERVAL_HOURS=PO_RETRY_INTERVAL_HOURS, PO_MAX_WAIT_DAYS=PO_MAX_WAIT_DAYS, PO_MAX_RETRIES=PO_MAX_RETRIES)
    logger.info("PO Auto-Retry scheduler started (interval: %dh, max wait: %d days)", PO_RETRY_INTERVAL_HOURS, PO_MAX_WAIT_DAYS)

    # === ReadyForPost Auto-Post Scheduler (every 5 minutes) ===
    READY_POST_INTERVAL_SECONDS = 300   # 5 min
    READY_POST_MAX_RETRIES = 5          # Max BC post attempts before giving up

    from services.lifecycle_scheduler_service import start_ready_to_post_tasks
    start_ready_to_post_tasks(db=db, logger=logger, register_background_task=register_background_task, READY_POST_INTERVAL_SECONDS=READY_POST_INTERVAL_SECONDS, READY_POST_MAX_RETRIES=READY_POST_MAX_RETRIES)
    logger.info("ReadyToPost Auto-Post scheduler started (interval: %ds, max retries: %d)",
                READY_POST_INTERVAL_SECONDS, READY_POST_MAX_RETRIES)

async def shutdown_db_client():
    """Delegate application cleanup to the canonical lifecycle service."""
    from services.alert_pattern_service import get_alert_pattern_service
    from services.lifecycle_service import shutdown_application
    from services.vendor_extraction_profile_service import get_vep_service

    await shutdown_application(
        dynamic_mailbox_task=_dynamic_mailbox_polling_task,
        email_polling_task=_email_polling_task,
        sales_polling_task=_sales_polling_task,
        pilot_summary_task=_pilot_summary_task,
        get_cache_service=get_cache_service,
        get_auto_resolve_service=get_auto_resolve_service,
        get_alert_pattern_service=get_alert_pattern_service,
        get_vep_service=get_vep_service,
        client=client,
        logger=logger,
    )
