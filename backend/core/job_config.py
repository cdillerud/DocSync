"""
Job type configuration, document intake models, and shared enums.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 9 - Ingestion/classification
engine). No logic changed. These are read by multiple groups (ingestion,
settings, metrics, migration, aliases) - hence a shared core/ module rather
than living inside any one routes/*.py file.

NOTE: DEFAULT_JOB_TYPES and VENDOR_ALIAS_MAP are read via .get()/.keys()/
item-assignment everywhere they're used - never reassigned wholesale - so a
plain import is safe here (unlike the BC_CLIENT_ID-style hot-reload trap:
mutating a dict's contents is visible to every importer of that same dict
object, only *rebinding* a name is not).
"""
from typing import List, Optional
from pydantic import BaseModel

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

class TransactionAction:
    """Track what action was taken on the BC side"""
    NONE = "NONE"                       # No BC action taken
    VALIDATED = "VALIDATED"             # Square9: Validation passed, stored in SharePoint
    LINKED_ONLY = "LINKED_ONLY"         # Document attached to existing record
    DRAFT_CREATED = "DRAFT_CREATED"     # Draft invoice header created
    DRAFT_WITH_LINES = "DRAFT_WITH_LINES"  # Future: draft with lines

# Phase 4: CREATE_DRAFT_HEADER configuration
# These are safety thresholds that must be met before creating a draft
DRAFT_CREATION_CONFIG = {
    # Match methods eligible for draft creation (high confidence methods only)
    "eligible_match_methods": ["exact_no", "exact_name", "normalized", "alias"],
    # Minimum match score for draft creation (stricter than auto-link)
    "min_match_score_for_draft": 0.92,
    # Minimum AI confidence for draft creation
    "min_confidence_for_draft": 0.92,
    # Number of days to look back for duplicate check
    "duplicate_lookback_days": 365,
}

# Default Job Type configurations - Production Grade
DEFAULT_JOB_TYPES = {
    # ==================== AP DOCUMENTS (Category: AP) ====================
    "AP_Invoice": {
        "job_type": "AP_Invoice",
        "display_name": "AP Invoice (Vendor Invoice)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.85,
        "min_confidence_to_auto_create_draft": 0.95,
        "po_validation_mode": "PO_IF_PRESENT",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["alias", "exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "AP_Invoices",
        "bc_entity": "purchaseInvoices",
        "required_extractions": ["vendor", "invoice_number", "amount"],
        "optional_extractions": ["po_number", "due_date", "line_items"],
        "enabled": True
    },
    "Sales_PO": {
        "job_type": "Sales_PO",
        "display_name": "Sales PO (Customer Purchase Order)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.80,
        "min_confidence_to_auto_create_draft": 0.92,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Sales_POs",
        "bc_entity": "salesOrders",
        "required_extractions": ["customer", "po_number", "order_date"],
        "optional_extractions": ["amount", "ship_to", "line_items"],
        "enabled": True
    },
    "AR_Invoice": {
        "job_type": "AR_Invoice",
        "display_name": "AR Invoice (Outgoing Invoice)",
        "category": "AP",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.90,
        "min_confidence_to_auto_create_draft": 0.98,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "AR_Invoices",
        "bc_entity": "salesInvoices",
        "required_extractions": ["customer", "invoice_number", "amount"],
        "optional_extractions": ["due_date", "line_items"],
        "enabled": True
    },
    "Remittance": {
        "job_type": "Remittance",
        "display_name": "Remittance Advice (Payment Confirmation)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.75,
        "min_confidence_to_auto_create_draft": 0.95,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.75,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Remittances",
        "bc_entity": "vendorPayments",
        "required_extractions": ["vendor", "payment_amount", "payment_date"],
        "optional_extractions": ["invoice_references", "check_number"],
        "enabled": True
    },
    "Freight_Document": {
        "job_type": "Freight_Document",
        "display_name": "Freight Document (BOL/HAWB/Shipping)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.80,
        "min_confidence_to_auto_create_draft": 0.92,
        "po_validation_mode": "PO_IF_PRESENT",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.75,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Freight",
        "bc_entity": "purchaseReceipts",
        "required_extractions": ["shipper", "tracking_number"],
        "optional_extractions": ["consignee", "ship_date", "weight", "pieces", "origin", "destination", "carrier"],
        "enabled": True
    },
    "Warehouse_Document": {
        "job_type": "Warehouse_Document",
        "display_name": "Warehouse Document (Receipt/Shipment)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.80,
        "min_confidence_to_auto_create_draft": 0.92,
        "po_validation_mode": "PO_IF_PRESENT",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.75,
        "vendor_match_strategies": ["alias", "exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Warehouse",
        "bc_entity": "warehouseReceipts",
        "required_extractions": ["document_number", "location"],
        "optional_extractions": ["item_numbers", "quantities", "bin_codes", "receipt_date"],
        "enabled": True
    },
    "Purchase_Order": {
        "job_type": "Purchase_Order",
        "display_name": "Purchase Order (Outgoing PO to Vendor)",
        "category": "AP",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.85,
        "min_confidence_to_auto_create_draft": 0.92,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["alias", "exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Purchase_Orders",
        "bc_entity": "purchaseOrders",
        "required_extractions": ["vendor", "po_number"],
        "optional_extractions": ["amount", "order_date", "ship_to", "line_items"],
        "keywords": ["purchase order", "po", "order", "vendor", "supplier"],
        "enabled": True
    },
    
    # ==================== SALES DOCUMENTS (Category: Sales) ====================
    "Sales_Order": {
        "job_type": "Sales_Order",
        "display_name": "Sales Order (Customer PO)",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.80,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": False,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.80,
        "vendor_match_strategies": ["exact_no", "exact_name", "normalized", "fuzzy"],
        "sharepoint_folder": "Sales_Orders",
        "bc_entity": "salesOrders",
        "required_extractions": ["customer", "po_number"],
        "optional_extractions": ["amount", "ship_to", "line_items", "order_date"],
        "keywords": ["purchase order", "po", "order", "buy", "quantity", "ship to", "bill to"],
        "enabled": True
    },
    "Sales_Quote": {
        "job_type": "Sales_Quote",
        "display_name": "Sales Quote (Proposal)",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.70,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.70,
        "vendor_match_strategies": ["exact_name", "normalized"],
        "sharepoint_folder": "Sales_Quotes",
        "bc_entity": "salesQuotes",
        "required_extractions": ["customer"],
        "optional_extractions": ["amount", "valid_until"],
        "keywords": ["quote", "quotation", "proposal", "estimate", "pricing", "valid until"],
        "enabled": True
    },
    "Order_Confirmation": {
        "job_type": "Order_Confirmation",
        "display_name": "Order Confirmation",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.70,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.70,
        "vendor_match_strategies": ["exact_name", "normalized"],
        "sharepoint_folder": "Sales_Confirmations",
        "bc_entity": "salesOrders",
        "required_extractions": ["order_number"],
        "optional_extractions": ["customer", "amount"],
        "keywords": ["confirmation", "confirmed", "order acknowledgment", "acknowledge"],
        "enabled": True
    },
    "Inventory_Report": {
        "job_type": "Inventory_Report",
        "display_name": "Inventory Report",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.60,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": False,
        "vendor_match_threshold": 0.60,
        "vendor_match_strategies": ["normalized"],
        "sharepoint_folder": "Inventory_Reports",
        "bc_entity": "items",
        "required_extractions": [],
        "optional_extractions": ["warehouse", "item_numbers", "quantities"],
        "keywords": ["inventory", "stock", "on hand", "available", "warehouse"],
        "enabled": True
    },
    "Shipping_Document": {
        "job_type": "Shipping_Document",
        "display_name": "Shipping Document (BOL/Shipment)",
        "category": "Warehouse",
        "automation_level": 1,
        "min_confidence_to_auto_link": 0.70,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_IF_PRESENT",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.70,
        "vendor_match_strategies": ["exact_name", "normalized"],
        "sharepoint_folder": "Shipping_Docs",
        "bc_entity": "salesShipments",
        "required_extractions": ["bol_number", "ship_date"],
        "optional_extractions": ["po_number", "tracking_number", "shipper", "consignee", "carrier", "weight", "pieces", "pro_number"],
        "keywords": ["ship", "shipping", "delivery", "dispatch", "release", "pick up", "bill of lading", "bol", "tracking", "straight bill"],
        "enabled": True
    },
    "Quality_Issue": {
        "job_type": "Quality_Issue",
        "display_name": "Quality Issue / Complaint",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.60,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.60,
        "vendor_match_strategies": ["normalized"],
        "sharepoint_folder": "Quality_Issues",
        "bc_entity": "items",
        "required_extractions": [],
        "optional_extractions": ["customer", "item", "description"],
        "keywords": ["quality", "defect", "damage", "complaint", "issue", "problem", "ncr", "claim"],
        "enabled": True
    },
    "Return_Request": {
        "job_type": "Return_Request",
        "display_name": "Return Request / RMA",
        "category": "Sales",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.70,
        "min_confidence_to_auto_create_draft": 0.90,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.70,
        "vendor_match_strategies": ["exact_name", "normalized"],
        "sharepoint_folder": "Returns",
        "bc_entity": "salesCreditMemos",
        "required_extractions": [],
        "optional_extractions": ["customer", "amount", "reason"],
        "keywords": ["return", "rma", "credit", "refund", "send back"],
        "enabled": True
    },
    "Unknown_Document": {
        "job_type": "Unknown_Document",
        "display_name": "Unknown / Unclassified",
        "category": "Unknown",
        "automation_level": 0,
        "min_confidence_to_auto_link": 0.50,
        "min_confidence_to_auto_create_draft": 0.95,
        "po_validation_mode": "PO_NOT_REQUIRED",
        "allow_duplicate_check_override": True,
        "requires_human_review_if_exception": True,
        "vendor_match_threshold": 0.50,
        "vendor_match_strategies": ["normalized"],
        "sharepoint_folder": "Unclassified",
        "bc_entity": "documents",
        "required_extractions": [],
        "optional_extractions": [],
        "keywords": [],
        "enabled": True
    }
}

# Vendor Alias Map (company-specific)
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
