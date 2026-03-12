"""
GPI Document Hub - Reference Intelligence Service

AI-Assisted Reference Resolution Engine that:
1. Extracts multiple candidate references from documents
2. Classifies what those references likely represent
3. Normalizes references for BC lookup
4. Selects appropriate BC search strategy based on document type
5. Scores candidate matches
6. Returns the best match with reasoning

Supports: AP invoices, freight invoices, shipping documents, BOLs, carrier docs
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class ReferenceLabel(str, Enum):
    """Detected reference type labels."""
    PO = "PO"
    BOL = "BOL"
    ORDER = "ORDER"
    SHIPMENT = "SHIPMENT"
    INVOICE = "INVOICE"
    LOAD = "LOAD"
    PRO = "PRO"
    REF = "REF"
    CUSTOMER_REF = "CUSTOMER_REF"
    UNKNOWN = "UNKNOWN"


class ReferenceDomain(str, Enum):
    """Predicted reference domain."""
    PURCHASE = "purchase"
    SALES = "sales"
    VENDOR = "vendor"
    CUSTOMER = "customer"
    FINANCE = "finance"
    SHIPPING = "shipping"
    UNKNOWN = "unknown"


class SourceDocumentType(str, Enum):
    """Source document type — drives context gate and scoring bias."""
    AP_INVOICE = "ap_invoice"
    AR_INVOICE = "ar_invoice"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    PACKING_SLIP = "packing_slip"
    SHIPMENT = "shipment"
    BOL = "bol"
    ORDER_CONFIRMATION = "order_confirmation"
    FREIGHT = "freight"
    CUSTOMS = "customs"
    GENERIC_DOCUMENT = "generic_document"


class ReferenceSemanticType(str, Enum):
    """Semantic type of the extracted reference value."""
    PO_NUMBER = "po_number"
    INVOICE_NUMBER = "invoice_number"
    SHIPMENT_NUMBER = "shipment_number"
    CUSTOMER_PO = "customer_po"
    ORDER_NUMBER = "order_number"
    GENERIC_REFERENCE = "generic_reference"


class CandidateState(str, Enum):
    """Evaluation state of a BC match candidate."""
    SURFACED = "surfaced"
    SUPPRESSED = "suppressed"
    REJECTED = "rejected"


class CandidateDomain(str, Enum):
    """Domain classification for a BC candidate record."""
    PURCHASE = "purchase"
    SALES = "sales"
    VENDOR = "vendor"
    CUSTOMER = "customer"
    FINANCE = "finance"
    UNKNOWN = "unknown"


class BCEntityType(str, Enum):
    """BC entity types for reference resolution."""
    PURCHASE_ORDER = "purchase_order"
    PURCHASE_INVOICE = "purchase_invoice"
    POSTED_PURCHASE_INVOICE = "posted_purchase_invoice"
    SALES_ORDER = "sales_order"
    SALES_INVOICE = "sales_invoice"
    POSTED_SALES_INVOICE = "posted_sales_invoice"
    SALES_SHIPMENT = "sales_shipment"
    POSTED_SALES_SHIPMENT = "posted_sales_shipment"


class MatchOutcome(str, Enum):
    """Reference match outcome labels — safe interpretation."""
    STRONG_MATCH = "strong_match"
    LIKELY_MATCH = "likely_match"
    NEEDS_REVIEW = "needs_review"
    SUPPRESSED_CROSS_DOMAIN = "suppressed_cross_domain"
    COUNTERPARTY_MISMATCH = "counterparty_mismatch"
    REJECTED = "rejected"
    NO_MATCH = "no_match"
    # Legacy compat
    EXACT_MATCH = "exact_match"
    AMBIGUOUS_MATCH = "ambiguous_match"


# =============================================================================
# CONTEXT GATE — domain pool rules per source doc type
# =============================================================================

# For AP_INVOICE: purchase/vendor/finance primary, sales/customer excluded unless override
CONTEXT_GATE = {
    SourceDocumentType.AP_INVOICE: {
        "primary": {CandidateDomain.PURCHASE, CandidateDomain.VENDOR, CandidateDomain.FINANCE},
        "secondary": {CandidateDomain.UNKNOWN},
        "excluded": {CandidateDomain.SALES, CandidateDomain.CUSTOMER},
    },
    SourceDocumentType.AR_INVOICE: {
        "primary": {CandidateDomain.SALES, CandidateDomain.CUSTOMER, CandidateDomain.FINANCE},
        "secondary": {CandidateDomain.UNKNOWN},
        "excluded": {CandidateDomain.PURCHASE, CandidateDomain.VENDOR},
    },
    SourceDocumentType.PURCHASE_ORDER: {
        "primary": {CandidateDomain.PURCHASE, CandidateDomain.VENDOR},
        "secondary": {CandidateDomain.FINANCE, CandidateDomain.UNKNOWN},
        "excluded": {CandidateDomain.SALES, CandidateDomain.CUSTOMER},
    },
    SourceDocumentType.SALES_ORDER: {
        "primary": {CandidateDomain.SALES, CandidateDomain.CUSTOMER},
        "secondary": {CandidateDomain.FINANCE, CandidateDomain.UNKNOWN},
        "excluded": {CandidateDomain.PURCHASE, CandidateDomain.VENDOR},
    },
}

# Map raw doc_type strings to SourceDocumentType
DOC_TYPE_TO_SOURCE_TYPE = {
    "AP_Invoice": SourceDocumentType.AP_INVOICE,
    "ap_invoice": SourceDocumentType.AP_INVOICE,
    "AR_Invoice": SourceDocumentType.AR_INVOICE,
    "ar_invoice": SourceDocumentType.AR_INVOICE,
    "Freight_Invoice": SourceDocumentType.FREIGHT,
    "Freight": SourceDocumentType.FREIGHT,
    "Carrier_Invoice": SourceDocumentType.FREIGHT,
    "BOL": SourceDocumentType.BOL,
    "Shipping_Document": SourceDocumentType.SHIPMENT,
    "Packing_List": SourceDocumentType.PACKING_SLIP,
    "Sales_Order": SourceDocumentType.SALES_ORDER,
    "Purchase_Order": SourceDocumentType.PURCHASE_ORDER,
}

# Map ReferenceLabel to ReferenceSemanticType
LABEL_TO_SEMANTIC_TYPE = {
    ReferenceLabel.PO: ReferenceSemanticType.PO_NUMBER,
    ReferenceLabel.ORDER: ReferenceSemanticType.ORDER_NUMBER,
    ReferenceLabel.INVOICE: ReferenceSemanticType.INVOICE_NUMBER,
    ReferenceLabel.SHIPMENT: ReferenceSemanticType.SHIPMENT_NUMBER,
    ReferenceLabel.CUSTOMER_REF: ReferenceSemanticType.CUSTOMER_PO,
    ReferenceLabel.BOL: ReferenceSemanticType.SHIPMENT_NUMBER,
    ReferenceLabel.LOAD: ReferenceSemanticType.SHIPMENT_NUMBER,
    ReferenceLabel.PRO: ReferenceSemanticType.SHIPMENT_NUMBER,
    ReferenceLabel.REF: ReferenceSemanticType.GENERIC_REFERENCE,
    ReferenceLabel.UNKNOWN: ReferenceSemanticType.GENERIC_REFERENCE,
}

# Map BCEntityType to CandidateDomain
ENTITY_TO_CANDIDATE_DOMAIN = {
    BCEntityType.PURCHASE_ORDER: CandidateDomain.PURCHASE,
    BCEntityType.PURCHASE_INVOICE: CandidateDomain.PURCHASE,
    BCEntityType.POSTED_PURCHASE_INVOICE: CandidateDomain.PURCHASE,
    BCEntityType.SALES_ORDER: CandidateDomain.SALES,
    BCEntityType.SALES_INVOICE: CandidateDomain.SALES,
    BCEntityType.POSTED_SALES_INVOICE: CandidateDomain.SALES,
    BCEntityType.SALES_SHIPMENT: CandidateDomain.SALES,
    BCEntityType.POSTED_SALES_SHIPMENT: CandidateDomain.SALES,
}


# Reference extraction patterns — with improved BOL/Shipment detection
REFERENCE_PATTERNS = {
    ReferenceLabel.BOL: [
        r'B\.?O\.?L\.?\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Bill\s+of\s+Lading\s*#?\s*[:.]?\s*(\d{4,10})',
        r'BOL\s+Number\s*[:.]?\s*(\d{4,10})',
        r'B/L\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.SHIPMENT: [
        r'Shipment\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Ship\s*#?\s*[:.]?\s*(\d{4,10})',
        r'PU\s*#?\s*[:.]?\s*(\d{4,15})',
        r'Pickup\s*#?\s*[:.]?\s*(\d{4,15})',
        r'Delivery\s*#?\s*[:.]?\s*(\d{4,15})',
    ],
    ReferenceLabel.LOAD: [
        r'Load\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Load\s+Number\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.PO: [
        r'P\.?O\.?\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Purchase\s+Order\s*#?\s*[:.]?\s*(\d{4,10})',
        r'PO\s+Number\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.ORDER: [
        r'Order\s*#?\s*[:.]?\s*([A-Z]?\d{4,10})',
        r'Sales\s+Order\s*#?\s*[:.]?\s*(\d{4,10})',
        r'SO\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.PRO: [
        r'PRO\s*#?\s*[:.]?\s*(\d{4,15})',
        r'Pro\s+Number\s*[:.]?\s*(\d{4,15})',
    ],
    ReferenceLabel.REF: [
        r'Ref\.?\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Reference\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.INVOICE: [
        r'Invoice\s*#?\s*[:.]?\s*([A-Z0-9\-]{4,20})',
        r'Inv\.?\s*#?\s*[:.]?\s*([A-Z0-9\-]{4,20})',
    ],
}

# Keywords that indicate shipping/BOL context — should NOT be classified as PO
SHIPPING_CONTEXT_KEYWORDS = {
    "bill of lading", "bol", "b/l", "shipment", "ship", "pickup", "pu",
    "delivery", "load", "freight", "carrier", "trucking", "consignee",
    "shipper", "pro number", "tracking",
}

# Document type to search strategy mapping
SEARCH_STRATEGIES = {
    "AP_Invoice": [
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.PURCHASE_INVOICE,
        BCEntityType.POSTED_PURCHASE_INVOICE,
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_SALES_SHIPMENT,
    ],
    "Freight_Invoice": [
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.SALES_ORDER,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "Freight": [
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.SALES_ORDER,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "Carrier_Invoice": [
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.SALES_ORDER,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "BOL": [
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "Shipping_Document": [
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "Packing_List": [
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.PURCHASE_ORDER,
    ],
    "Sales_Order": [
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_SALES_SHIPMENT,
    ],
    "default": [
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_PURCHASE_INVOICE,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_SALES_SHIPMENT,
    ],
}

# Freight resolver trigger conditions
FREIGHT_DOC_TYPES = {"Freight_Invoice", "Freight", "Carrier_Invoice", "Freight_Document"}
FREIGHT_STRATEGY_KEY = "Freight_Invoice"

# BC entity to API table mapping
ENTITY_TO_TABLE = {
    BCEntityType.PURCHASE_ORDER: "purchaseOrders",
    BCEntityType.PURCHASE_INVOICE: "purchaseInvoices",
    BCEntityType.POSTED_PURCHASE_INVOICE: "purchaseInvoices",
    BCEntityType.SALES_ORDER: "salesOrders",
    BCEntityType.SALES_INVOICE: "salesInvoices",
    BCEntityType.POSTED_SALES_INVOICE: "salesInvoices",
    BCEntityType.SALES_SHIPMENT: "salesShipments",
    BCEntityType.POSTED_SALES_SHIPMENT: "salesShipments",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ReferenceCandidate:
    """A candidate reference extracted from a document."""
    reference_value_raw: str
    reference_value_normalized: str
    detected_label: str
    source_text: str
    confidence: float
    page_number: int = 1
    # AI classification results
    predicted_domain: str = None
    predicted_entity_types: List[str] = field(default_factory=list)
    classification_reasoning: str = None
    # Semantic type (Requirement 4)
    semantic_type: str = ReferenceSemanticType.GENERIC_REFERENCE.value
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BCMatch:
    """A match result from BC lookup."""
    entity_type: str
    bc_record_id: str
    bc_document_no: str
    bc_record_info: Dict[str, Any]
    match_score: float
    match_reasoning: str
    # New fields (Requirements 1, 6, 8, 9)
    candidate_domain: str = CandidateDomain.UNKNOWN.value
    counterparty_name: str = ""
    candidate_state: str = CandidateState.SURFACED.value
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    positive_signals: List[str] = field(default_factory=list)
    negative_signals: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceResolutionResult:
    """Complete result of reference intelligence resolution."""
    document_id: str
    document_type: str
    resolver_strategy: str
    search_order: List[str]
    
    # Extracted candidates
    reference_candidates: List[ReferenceCandidate] = field(default_factory=list)
    
    # Best match
    best_match: BCMatch = None
    match_outcome: str = MatchOutcome.NO_MATCH.value
    
    # Alternate matches
    alternate_matches: List[BCMatch] = field(default_factory=list)
    
    # Metadata
    resolved_at: str = None
    total_bc_queries: int = 0
    processing_time_ms: int = 0
    matching_diagnostics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "resolver_strategy": self.resolver_strategy,
            "search_order": self.search_order,
            "reference_candidates": [c.to_dict() for c in self.reference_candidates],
            "match_outcome": self.match_outcome,
            "alternate_matches": [m.to_dict() for m in self.alternate_matches],
            "resolved_at": self.resolved_at,
            "total_bc_queries": self.total_bc_queries,
            "processing_time_ms": self.processing_time_ms,
        }
        if self.best_match:
            result["best_match"] = self.best_match.to_dict()
        if self.matching_diagnostics:
            result["matching_diagnostics"] = self.matching_diagnostics
        return result


# =============================================================================
# REFERENCE EXTRACTION
# =============================================================================

def normalize_reference(raw_value: str, return_trace: bool = False):
    """
    Normalize a reference value for BC lookup.
    
    If return_trace=True, returns (normalized, trace_steps[]).
    """
    if not raw_value:
        return ("", []) if return_trace else ""
    
    trace = []
    normalized = raw_value.strip()
    trace.append({"step": "input", "value": normalized})
    
    # Convert to uppercase
    upper = normalized.upper()
    if upper != normalized:
        trace.append({"step": "uppercase", "value": upper})
    normalized = upper
    
    # Remove common prefixes
    prefixes = [
        (r'^BOL[\s\-#:\.]*', 'strip_bol_prefix'),
        (r'^B/L[\s\-#:\.]*', 'strip_bl_prefix'),
        (r'^P\.?O\.?[\s\-#:\.]*', 'strip_po_prefix'),
        (r'^REF[\s\-#:\.]*', 'strip_ref_prefix'),
        (r'^ORDER[\s\-#:\.]*', 'strip_order_prefix'),
        (r'^SO[\s\-#:\.]*', 'strip_so_prefix'),
        (r'^SHIP[\s\-#:\.]*', 'strip_ship_prefix'),
        (r'^LOAD[\s\-#:\.]*', 'strip_load_prefix'),
        (r'^PRO[\s\-#:\.]*', 'strip_pro_prefix'),
        (r'^INV[\s\-#:\.]*', 'strip_inv_prefix'),
        (r'^PU[\s\-#:\.]*', 'strip_pu_prefix'),
        (r'^#', 'strip_hash_prefix'),
    ]
    
    for prefix_re, step_name in prefixes:
        before = normalized
        normalized = re.sub(prefix_re, '', normalized, flags=re.IGNORECASE)
        if normalized != before:
            trace.append({"step": step_name, "value": normalized})
    
    # Remove remaining punctuation and spaces
    clean = re.sub(r'[\s\-\.\#\:\,]+', '', normalized)
    if clean != normalized:
        trace.append({"step": "strip_punctuation", "value": clean})
    normalized = clean
    
    # Strip leading zeros (but keep at least one digit)
    stripped = normalized.lstrip('0') or '0'
    if stripped != normalized:
        trace.append({"step": "strip_leading_zeros", "value": stripped})
    normalized = stripped
    
    if return_trace:
        return normalized, trace
    return normalized


def extract_references_from_text(text: str) -> List[ReferenceCandidate]:
    """
    Extract all reference candidates from document text using patterns.
    
    Returns up to 10 highest-confidence candidates.
    """
    if not text:
        return []
    
    candidates = []
    seen_normalized = set()
    
    for label, patterns in REFERENCE_PATTERNS.items():
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                raw_value = match.group(1) if match.groups() else match.group(0)
                normalized = normalize_reference(raw_value)
                
                # Skip if we've already seen this normalized value
                if normalized in seen_normalized:
                    continue
                seen_normalized.add(normalized)
                
                # Calculate confidence based on pattern specificity
                confidence = 0.8
                if label in [ReferenceLabel.PO, ReferenceLabel.BOL]:
                    confidence = 0.9
                if len(normalized) >= 5:
                    confidence += 0.05
                
                # Get surrounding context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                source_text = text[start:end].strip()
                
                candidates.append(ReferenceCandidate(
                    reference_value_raw=raw_value,
                    reference_value_normalized=normalized,
                    detected_label=label.value,
                    source_text=source_text,
                    confidence=min(confidence, 1.0),
                    page_number=1
                ))
    
    # Sort by confidence and limit to top 10
    candidates.sort(key=lambda x: x.confidence, reverse=True)
    return candidates[:10]


def extract_references_from_extracted_fields(extracted_fields: Dict[str, Any]) -> List[ReferenceCandidate]:
    """
    Extract reference candidates from already-extracted fields.
    """
    candidates = []
    seen_normalized = set()
    
    field_mappings = [
        ("po_number", ReferenceLabel.PO, 0.95),
        ("bol_number", ReferenceLabel.BOL, 0.95),
        ("invoice_number", ReferenceLabel.INVOICE, 0.9),
        ("order_number", ReferenceLabel.ORDER, 0.85),
        ("shipment_number", ReferenceLabel.SHIPMENT, 0.85),
        ("reference_number", ReferenceLabel.REF, 0.8),
        ("load_number", ReferenceLabel.LOAD, 0.8),
        ("pro_number", ReferenceLabel.PRO, 0.8),
    ]
    
    for field_name, label, confidence in field_mappings:
        value = extracted_fields.get(field_name)
        if value and str(value).strip():
            raw_value = str(value).strip()
            normalized = normalize_reference(raw_value)
            
            if normalized and normalized not in seen_normalized:
                seen_normalized.add(normalized)
                candidates.append(ReferenceCandidate(
                    reference_value_raw=raw_value,
                    reference_value_normalized=normalized,
                    detected_label=label.value,
                    source_text=f"Extracted field: {field_name}",
                    confidence=confidence,
                    page_number=1
                ))
    
    return candidates


# =============================================================================
# AI REFERENCE CLASSIFICATION
# =============================================================================

def classify_reference_domain(
    candidate: ReferenceCandidate,
    document_type: str,
    vendor_name: str = None
) -> Tuple[str, List[str], str]:
    """
    Classify the predicted domain and entity types for a reference.
    
    Returns: (domain, entity_types, reasoning)
    """
    label = candidate.detected_label
    
    # Label-based domain prediction
    domain = ReferenceDomain.UNKNOWN.value
    entity_types = []
    reasoning_parts = []
    
    if label == ReferenceLabel.PO.value:
        domain = ReferenceDomain.PURCHASE.value
        entity_types = [BCEntityType.PURCHASE_ORDER.value]
        reasoning_parts.append("PO label indicates purchase domain")
    
    elif label == ReferenceLabel.BOL.value:
        domain = ReferenceDomain.SHIPPING.value
        entity_types = [
            BCEntityType.SALES_ORDER.value,
            BCEntityType.POSTED_SALES_SHIPMENT.value
        ]
        reasoning_parts.append("BOL typically references sales/shipping")
    
    elif label == ReferenceLabel.ORDER.value:
        # Could be sales or purchase order
        if document_type in ["AP_Invoice", "Freight_Invoice"]:
            domain = ReferenceDomain.PURCHASE.value
            entity_types = [BCEntityType.PURCHASE_ORDER.value, BCEntityType.SALES_ORDER.value]
        else:
            domain = ReferenceDomain.SALES.value
            entity_types = [BCEntityType.SALES_ORDER.value, BCEntityType.PURCHASE_ORDER.value]
        reasoning_parts.append(f"Order reference, document type: {document_type}")
    
    elif label == ReferenceLabel.SHIPMENT.value:
        domain = ReferenceDomain.SHIPPING.value
        entity_types = [
            BCEntityType.POSTED_SALES_SHIPMENT.value,
            BCEntityType.SALES_ORDER.value
        ]
        reasoning_parts.append("Shipment label indicates shipping domain")
    
    elif label == ReferenceLabel.INVOICE.value:
        if document_type in ["AP_Invoice", "Freight_Invoice"]:
            domain = ReferenceDomain.PURCHASE.value
            entity_types = [BCEntityType.POSTED_PURCHASE_INVOICE.value]
        else:
            domain = ReferenceDomain.SALES.value
            entity_types = [BCEntityType.POSTED_SALES_INVOICE.value]
        reasoning_parts.append(f"Invoice reference, document type: {document_type}")
    
    elif label in [ReferenceLabel.REF.value, ReferenceLabel.UNKNOWN.value]:
        # Generic reference - use document type to infer
        if document_type in ["BOL", "Shipping_Document", "Packing_List"]:
            domain = ReferenceDomain.SHIPPING.value
            entity_types = [BCEntityType.SALES_ORDER.value, BCEntityType.POSTED_SALES_SHIPMENT.value]
        elif document_type in ["AP_Invoice", "Freight_Invoice"]:
            domain = ReferenceDomain.PURCHASE.value
            entity_types = [BCEntityType.PURCHASE_ORDER.value, BCEntityType.SALES_ORDER.value]
        else:
            entity_types = [BCEntityType.PURCHASE_ORDER.value, BCEntityType.SALES_ORDER.value]
        reasoning_parts.append(f"Generic reference, inferring from document type: {document_type}")
    
    # Add vendor context if available
    if vendor_name:
        reasoning_parts.append(f"Vendor context: {vendor_name[:30]}")
    
    reasoning = "; ".join(reasoning_parts)
    
    return domain, entity_types, reasoning


# =============================================================================
# SEARCH STRATEGY
# =============================================================================

def get_search_strategy(document_type: str) -> List[str]:
    """
    Get the BC entity search order based on document type.
    """
    strategy_key = document_type if document_type in SEARCH_STRATEGIES else "default"
    strategy = SEARCH_STRATEGIES[strategy_key]
    return [e.value for e in strategy]


def get_search_tables(document_type: str) -> List[str]:
    """
    Get BC API tables to search based on document type.
    """
    strategy_key = document_type if document_type in SEARCH_STRATEGIES else "default"
    strategy = SEARCH_STRATEGIES[strategy_key]
    
    tables = []
    for entity in strategy:
        table = ENTITY_TO_TABLE.get(entity)
        if table and table not in tables:
            tables.append(table)
    
    return tables


# =============================================================================
# MATCH SCORING
# =============================================================================

def score_bc_match(
    candidate: ReferenceCandidate,
    bc_record: Dict[str, Any],
    entity_type: str,
    document: Dict[str, Any] = None,
    vendor_hints: Dict[str, Any] = None,
    label_correction_hints: Dict[str, Any] = None,
    extraction_profile: Dict[str, Any] = None,
    layout_family_bias: Dict[str, Any] = None,
    source_doc_type: SourceDocumentType = None
) -> Tuple[float, str, Dict[str, float], str, str, List[str], List[str]]:
    """
    Score a BC match with domain-aware, multi-signal scoring.
    
    Returns: (score, reasoning, score_breakdown, candidate_domain, counterparty_name,
              positive_signals, negative_signals)
    """
    breakdown = {}
    reasoning_parts = []
    positive_signals = []
    negative_signals = []
    
    bc_number = bc_record.get("number", "")
    normalized_ref = candidate.reference_value_normalized
    
    # --- Classify candidate domain (Requirement 1) ---
    candidate_domain = ENTITY_TO_CANDIDATE_DOMAIN.get(
        entity_type, CandidateDomain.UNKNOWN
    ).value if isinstance(entity_type, str) else CandidateDomain.UNKNOWN.value
    # Try enum lookup by value
    for et in BCEntityType:
        if et.value == entity_type:
            candidate_domain = ENTITY_TO_CANDIDATE_DOMAIN.get(et, CandidateDomain.UNKNOWN).value
            break
    
    # --- Get counterparty name ---
    bc_vendor = bc_record.get("vendorName") or bc_record.get("vendor_name", "")
    bc_customer = bc_record.get("customerName") or bc_record.get("customer_name", "")
    counterparty_name = bc_vendor if candidate_domain == CandidateDomain.PURCHASE.value else bc_customer
    if not counterparty_name:
        counterparty_name = bc_vendor or bc_customer or ""
    
    # --- 1. Exact document number match (0.35 max — reduced from 0.40, Requirement 5) ---
    if bc_number == normalized_ref:
        breakdown["exact_doc_no_match"] = 0.35
        reasoning_parts.append("Exact number match")
        positive_signals.append("exact_doc_no_match")
    elif normalize_reference(bc_number) == normalized_ref:
        breakdown["exact_doc_no_match"] = 0.30
        reasoning_parts.append("Normalized number match")
        positive_signals.append("exact_doc_no_match")
    else:
        breakdown["exact_doc_no_match"] = 0.0
    
    # --- 2. Domain alignment (Requirement 2, 3) ---
    breakdown["domain_alignment"] = 0.0
    if source_doc_type and candidate_domain != CandidateDomain.UNKNOWN.value:
        gate = CONTEXT_GATE.get(source_doc_type)
        if gate:
            cd_enum = CandidateDomain(candidate_domain)
            if cd_enum in gate.get("primary", set()):
                breakdown["domain_alignment"] = 0.20
                reasoning_parts.append(f"Domain alignment: {candidate_domain} matches {source_doc_type.value} primary pool")
                positive_signals.append("domain_alignment")
            elif cd_enum in gate.get("secondary", set()):
                breakdown["domain_alignment"] = 0.05
                reasoning_parts.append(f"Domain: {candidate_domain} in secondary pool")
            elif cd_enum in gate.get("excluded", set()):
                breakdown["domain_alignment"] = -0.40
                reasoning_parts.append(f"Domain MISMATCH: {candidate_domain} excluded for {source_doc_type.value}")
                negative_signals.append(f"domain_mismatch_{candidate_domain}_vs_{source_doc_type.value}")
        else:
            # No gate defined — use heuristic
            if candidate.predicted_domain:
                if candidate.predicted_domain == ReferenceDomain.PURCHASE.value and "purchase" in entity_type.lower():
                    breakdown["domain_alignment"] = 0.15
                    positive_signals.append("domain_alignment")
                elif candidate.predicted_domain == ReferenceDomain.SALES.value and "sales" in entity_type.lower():
                    breakdown["domain_alignment"] = 0.15
                    positive_signals.append("domain_alignment")
                elif candidate.predicted_domain == ReferenceDomain.SHIPPING.value and ("shipment" in entity_type.lower() or "sales" in entity_type.lower()):
                    breakdown["domain_alignment"] = 0.15
                    positive_signals.append("domain_alignment")
    elif candidate.predicted_domain:
        if candidate.predicted_domain == ReferenceDomain.PURCHASE.value and "purchase" in entity_type.lower():
            breakdown["domain_alignment"] = 0.15
            positive_signals.append("domain_alignment")
        elif candidate.predicted_domain == ReferenceDomain.SALES.value and "sales" in entity_type.lower():
            breakdown["domain_alignment"] = 0.15
            positive_signals.append("domain_alignment")
    
    # --- 3. Counterparty alignment (Requirement 6) ---
    breakdown["counterparty_alignment"] = 0.0
    if document:
        doc_vendor = document.get("vendor_raw", "") or document.get("matched_vendor_name", "")
        
        if doc_vendor:
            doc_vendor_norm = doc_vendor.lower().replace(" ", "").replace(",", "").replace(".", "")
            
            # Check vendor match
            if bc_vendor:
                bc_vendor_norm = bc_vendor.lower().replace(" ", "").replace(",", "").replace(".", "")
                if doc_vendor_norm in bc_vendor_norm or bc_vendor_norm in doc_vendor_norm:
                    breakdown["counterparty_alignment"] = 0.20
                    reasoning_parts.append(f"Counterparty alignment: vendor '{bc_vendor[:25]}' matches doc vendor")
                    positive_signals.append("counterparty_alignment")
                elif _fuzzy_vendor_match(doc_vendor_norm, bc_vendor_norm):
                    breakdown["counterparty_alignment"] = 0.15
                    reasoning_parts.append(f"Counterparty alignment: fuzzy vendor match '{bc_vendor[:25]}'")
                    positive_signals.append("counterparty_alignment")
            
            # Customer mismatch penalty — if candidate belongs to a different entity
            if breakdown["counterparty_alignment"] == 0 and bc_customer:
                bc_customer_norm = bc_customer.lower().replace(" ", "").replace(",", "").replace(".", "")
                if candidate_domain in (CandidateDomain.SALES.value, CandidateDomain.CUSTOMER.value):
                    # Sales/customer record but vendor doesn't match — penalty
                    if doc_vendor_norm not in bc_customer_norm and bc_customer_norm not in doc_vendor_norm:
                        breakdown["counterparty_alignment"] = -0.30
                        reasoning_parts.append(f"Counterparty MISMATCH: sales record for '{bc_customer[:25]}' vs doc vendor '{doc_vendor[:25]}'")
                        negative_signals.append("counterparty_mismatch")
                    else:
                        # Vendor appears as customer — weak signal
                        breakdown["counterparty_alignment"] = 0.05
                        reasoning_parts.append(f"Weak: doc vendor in customer field '{bc_customer[:25]}'")
    
    # --- 4. Reference semantic alignment (Requirement 4) ---
    breakdown["semantic_alignment"] = 0.0
    semantic_type = candidate.semantic_type
    if semantic_type == ReferenceSemanticType.PO_NUMBER.value:
        if "purchase" in entity_type.lower():
            breakdown["semantic_alignment"] = 0.10
            reasoning_parts.append("Semantic: PO number → purchase entity (boost)")
            positive_signals.append("semantic_po_alignment")
        elif "sales" in entity_type.lower() or "shipment" in entity_type.lower():
            breakdown["semantic_alignment"] = -0.15
            reasoning_parts.append("Semantic MISMATCH: PO number → sales/shipment entity")
            negative_signals.append("semantic_mismatch")
    elif semantic_type == ReferenceSemanticType.INVOICE_NUMBER.value:
        if "invoice" in entity_type.lower():
            breakdown["semantic_alignment"] = 0.10
            positive_signals.append("semantic_invoice_alignment")
    elif semantic_type == ReferenceSemanticType.SHIPMENT_NUMBER.value:
        if "shipment" in entity_type.lower():
            breakdown["semantic_alignment"] = 0.10
            positive_signals.append("semantic_shipment_alignment")
    
    # --- 5. Date proximity (0.05) ---
    breakdown["date_proximity"] = 0.0
    if document:
        doc_date_str = (
            document.get("invoice_date")
            or document.get("document_date")
            or document.get("received_at")
        )
        bc_date_str = (
            bc_record.get("postingDate")
            or bc_record.get("orderDate")
            or bc_record.get("documentDate")
            or bc_record.get("posting_date")
        )
        if doc_date_str and bc_date_str:
            try:
                from datetime import datetime as dt
                doc_date = dt.fromisoformat(str(doc_date_str).replace("Z", "+00:00").split("T")[0])
                bc_date = dt.fromisoformat(str(bc_date_str).replace("Z", "+00:00").split("T")[0])
                days_diff = abs((doc_date - bc_date).days)
                if days_diff <= 7:
                    breakdown["date_proximity"] = 0.05
                    positive_signals.append("date_proximity")
                    reasoning_parts.append(f"Date proximity: {days_diff}d apart")
                elif days_diff <= 30:
                    breakdown["date_proximity"] = 0.03
                    reasoning_parts.append(f"Date proximity: {days_diff}d apart (moderate)")
                elif days_diff <= 90:
                    breakdown["date_proximity"] = 0.01
            except (ValueError, TypeError):
                pass
    
    # --- 6. Amount plausibility (0.05) ---
    breakdown["amount_plausibility"] = 0.0
    if document:
        doc_amount = document.get("amount_float") or document.get("extracted_fields", {}).get("total_amount")
        bc_amount = bc_record.get("totalAmountIncludingVAT") or bc_record.get("amount") or bc_record.get("totalAmount")
        if doc_amount and bc_amount:
            try:
                ratio = float(doc_amount) / float(bc_amount) if float(bc_amount) != 0 else 0
                if 0.9 <= ratio <= 1.1:
                    breakdown["amount_plausibility"] = 0.05
                    positive_signals.append("amount_plausibility")
                    reasoning_parts.append(f"Amount match: doc={doc_amount}, bc={bc_amount}")
            except (ValueError, TypeError):
                pass
    
    # --- 7. Entity type alignment (reduced) ---
    if entity_type in candidate.predicted_entity_types:
        breakdown["entity_type_alignment"] = 0.05
    else:
        breakdown["entity_type_alignment"] = 0.0
    
    # --- 8. Candidate confidence ---
    breakdown["candidate_confidence"] = candidate.confidence * 0.05
    
    # --- 9. Vendor behavior / label correction / profile / layout boosts ---
    breakdown["vendor_behavior_bonus"] = 0.0
    if vendor_hints and vendor_hints.get("has_hints"):
        typical_types = vendor_hints.get("typical_match_types", [])
        if entity_type in typical_types:
            boost = vendor_hints.get("behavior_score_boost", 0.10)
            breakdown["vendor_behavior_bonus"] = boost
    
    breakdown["freight_vendor_boost"] = 0.0
    if document:
        doc_type = document.get("document_type") or document.get("suggested_job_type") or ""
        is_freight_doc = doc_type in FREIGHT_DOC_TYPES
        uvm = document.get("unified_vendor_match") or {}
        is_freight_carrier = uvm.get("is_freight_carrier", False)
        if not is_freight_carrier:
            doc_vendor_lower = (document.get("vendor_raw") or "").lower()
            freight_kws = ["freight", "trucking", "logistics", "transport", "carrier", "shipping", "ltl"]
            is_freight_carrier = any(kw in doc_vendor_lower for kw in freight_kws)
        if (is_freight_doc or is_freight_carrier) and "shipment" in entity_type.lower():
            breakdown["freight_vendor_boost"] = 0.10
    
    breakdown["label_correction_boost"] = 0.0
    if label_correction_hints and label_correction_hints.get("has_hints"):
        entity_boosts = label_correction_hints.get("entity_boosts", {})
        if entity_type in entity_boosts:
            breakdown["label_correction_boost"] = entity_boosts[entity_type].get("boost", 0)
    
    breakdown["extraction_profile_bias"] = 0.0
    if extraction_profile and extraction_profile.get("has_profile"):
        label_bias = extraction_profile.get("reference_label_bias", {})
        if candidate.detected_label in label_bias:
            bias_info = label_bias[candidate.detected_label]
            if entity_type == bias_info.get("target_entity", ""):
                breakdown["extraction_profile_bias"] = round(min(bias_info.get("boost", 0), 0.10), 4)
    
    breakdown["layout_family_bias"] = 0.0
    if layout_family_bias and layout_family_bias.get("has_layout_bias"):
        entity_biases = layout_family_bias.get("entity_biases", {})
        if entity_type in entity_biases:
            breakdown["layout_family_bias"] = round(min(entity_biases[entity_type], 0.10), 4)
    
    # --- Vendor influence cap: max 0.20 ---
    vendor_components = (
        breakdown.get("vendor_behavior_bonus", 0)
        + breakdown.get("label_correction_boost", 0)
        + max(breakdown.get("extraction_profile_bias", 0), 0)
    )
    if vendor_components > 0.20:
        scale = 0.20 / vendor_components
        for k in ["vendor_behavior_bonus", "label_correction_boost", "extraction_profile_bias"]:
            if breakdown.get(k, 0) > 0:
                breakdown[k] = round(breakdown[k] * scale, 4)
    
    score = sum(breakdown.values())
    reasoning = "; ".join(reasoning_parts)
    
    return (
        min(max(score, 0.0), 1.0),
        reasoning,
        breakdown,
        candidate_domain,
        counterparty_name,
        positive_signals,
        negative_signals
    )


def _fuzzy_vendor_match(a: str, b: str) -> bool:
    """Simple fuzzy vendor match — checks if significant portions overlap."""
    if not a or not b:
        return False
    # Check if first N chars match (handles abbreviations)
    min_len = min(len(a), len(b))
    if min_len >= 6 and a[:6] == b[:6]:
        return True
    # Check token overlap
    tokens_a = set(a.replace(",", " ").split())
    tokens_b = set(b.replace(",", " ").split())
    if tokens_a and tokens_b:
        overlap = len(tokens_a & tokens_b)
        if overlap >= 2 or (overlap >= 1 and min(len(tokens_a), len(tokens_b)) <= 2):
            return True
    return False


def determine_match_outcome(
    best_score: float, 
    alternate_count: int,
    all_scores: List[float] = None,
    best_match: BCMatch = None,
    source_doc_type: SourceDocumentType = None
) -> str:
    """
    Determine the match outcome using domain-aware, multi-signal logic.
    
    Requirements 7, 8, 10:
    - At least two positive signals for "Likely Match"
    - At least one must be contextual (domain, counterparty, semantic, date)
    - Cross-domain numeric-only matches → suppressed
    - Updated labels for safe interpretation
    """
    if not all_scores:
        all_scores = []
    
    second_best = all_scores[1] if len(all_scores) > 1 else 0.0
    
    if not best_match:
        return MatchOutcome.NO_MATCH.value
    
    positive_signals = best_match.positive_signals or []
    negative_signals = best_match.negative_signals or []
    candidate_domain = best_match.candidate_domain
    
    # Contextual signals (not just numeric equality)
    contextual_signals = {"domain_alignment", "counterparty_alignment", "semantic_po_alignment",
                          "semantic_invoice_alignment", "semantic_shipment_alignment",
                          "date_proximity", "amount_plausibility"}
    positive_contextual = [s for s in positive_signals if s in contextual_signals]
    
    # Check for domain mismatch (cross-domain)
    has_domain_mismatch = any("domain_mismatch" in s for s in negative_signals)
    has_counterparty_mismatch = any("counterparty_mismatch" in s for s in negative_signals)
    has_semantic_mismatch = any("semantic_mismatch" in s for s in negative_signals)
    
    # Rejected: major negative signals
    if has_domain_mismatch and has_counterparty_mismatch:
        return MatchOutcome.REJECTED.value
    
    # Suppressed: cross-domain with only numeric match
    if has_domain_mismatch and len(positive_signals) <= 1:
        return MatchOutcome.SUPPRESSED_CROSS_DOMAIN.value
    
    # Counterparty mismatch label
    if has_counterparty_mismatch and not positive_contextual:
        return MatchOutcome.COUNTERPARTY_MISMATCH.value
    
    # Strong Match: high score + two signals + at least one contextual
    if best_score >= 0.80 and len(positive_signals) >= 2 and len(positive_contextual) >= 1:
        if second_best < 0.60:
            return MatchOutcome.STRONG_MATCH.value
    
    # Likely Match (Requirement 7): at least two positive signals, at least one contextual
    if best_score >= 0.50 and len(positive_signals) >= 2 and len(positive_contextual) >= 1:
        strong_competitors = sum(1 for s in all_scores[1:] if s >= 0.50)
        if strong_competitors == 0:
            return MatchOutcome.LIKELY_MATCH.value
        return MatchOutcome.NEEDS_REVIEW.value
    
    # Single signal only → Needs Review (never Likely Match from one signal)
    if len(positive_signals) <= 1:
        if has_domain_mismatch:
            return MatchOutcome.SUPPRESSED_CROSS_DOMAIN.value
        return MatchOutcome.NEEDS_REVIEW.value
    
    # Multiple candidates competing
    if alternate_count > 1 and second_best >= 0.50:
        return MatchOutcome.NEEDS_REVIEW.value
    
    return MatchOutcome.NEEDS_REVIEW.value


def determine_candidate_state(
    match: BCMatch,
    source_doc_type: SourceDocumentType = None,
    match_outcome: str = None
) -> str:
    """
    Determine if a candidate should be surfaced, suppressed, or rejected.
    (Requirement 8)
    """
    if match_outcome in (MatchOutcome.REJECTED.value,):
        return CandidateState.REJECTED.value
    
    if match_outcome in (MatchOutcome.SUPPRESSED_CROSS_DOMAIN.value,):
        return CandidateState.SUPPRESSED.value
    
    # Cross-domain numeric-only matches should be suppressed
    has_domain_mismatch = any("domain_mismatch" in s for s in (match.negative_signals or []))
    has_only_numeric = (
        len(match.positive_signals or []) == 1 and
        "exact_doc_no_match" in (match.positive_signals or [])
    )
    if has_domain_mismatch and has_only_numeric:
        return CandidateState.SUPPRESSED.value
    
    if has_domain_mismatch and match.match_score < 0.30:
        return CandidateState.REJECTED.value
    
    return CandidateState.SURFACED.value


# =============================================================================
# MAIN SERVICE CLASS
# =============================================================================

class ReferenceIntelligenceService:
    """
    AI-Assisted Reference Resolution Engine.
    
    Orchestrates reference extraction, classification, BC lookup, and scoring.
    """
    
    def __init__(self, db, bc_resolver=None, event_service=None):
        self.db = db
        self.bc_resolver = bc_resolver
        self.event_service = event_service
        self._label_correction_service = None
        self._vendor_intel_service = None
        self._vep_service = None
        self._layout_fingerprint_service = None
    
    def set_label_correction_service(self, svc):
        self._label_correction_service = svc
    
    def set_vendor_intelligence_service(self, svc):
        self._vendor_intel_service = svc
    
    def set_vep_service(self, svc):
        self._vep_service = svc
    
    def set_layout_fingerprint_service(self, svc):
        self._layout_fingerprint_service = svc
    
    async def resolve_document_references(
        self,
        document: Dict[str, Any],
        extracted_fields: Dict[str, Any] = None,
        document_text: str = None,
        correlation_id: str = None,
        capture_diagnostics: bool = False
    ) -> ReferenceResolutionResult:
        """
        Main entry point: resolve all references for a document.
        
        If capture_diagnostics=True, attach full diagnostic trace to result.
        """
        import time
        start_time = time.time()
        
        doc_id = document.get("id", "unknown")
        doc_type = document.get("document_type") or document.get("suggested_job_type") or "default"
        vendor_name = document.get("vendor_raw") or document.get("matched_vendor_name")
        
        # Derive source document type for context gate (Requirement 2)
        source_doc_type = DOC_TYPE_TO_SOURCE_TYPE.get(doc_type)
        if not source_doc_type:
            # Try category fallback
            category = document.get("category", "").upper()
            if category == "AP":
                source_doc_type = SourceDocumentType.AP_INVOICE
            elif category == "AR":
                source_doc_type = SourceDocumentType.AR_INVOICE
        
        # Determine effective strategy — use freight strategy when appropriate
        effective_strategy = doc_type
        uvm = document.get("unified_vendor_match") or {}
        is_freight_carrier = uvm.get("is_freight_carrier", False)
        has_bol = bool(document.get("bol_number") or (extracted_fields or {}).get("bol_number"))
        
        # Also check vendor name for freight indicators
        if not is_freight_carrier:
            vendor_lower = (vendor_name or "").lower()
            freight_kws = ["freight", "trucking", "logistics", "transport", "carrier",
                          "shipping", "ltl", "truckload", "drayage", "express"]
            is_freight_carrier = any(kw in vendor_lower for kw in freight_kws)
        
        if doc_type in FREIGHT_DOC_TYPES or is_freight_carrier or has_bol:
            effective_strategy = FREIGHT_STRATEGY_KEY
        
        # Initialize result
        result = ReferenceResolutionResult(
            document_id=doc_id,
            document_type=doc_type,
            resolver_strategy=effective_strategy,
            search_order=get_search_strategy(effective_strategy),
            resolved_at=datetime.now(timezone.utc).isoformat()
        )
        
        # Diagnostics collector
        diag = {
            "document_id": doc_id,
            "document_type": doc_type,
            "source_doc_type": source_doc_type.value if source_doc_type else None,
            "effective_strategy": effective_strategy,
            "strategy_reason": [],
            "vendor_name": vendor_name,
            "is_freight_carrier": is_freight_carrier,
            "has_bol": has_bol,
            "extraction": {},
            "normalization": {},
            "candidates": [],
            "cache_results": [],
            "bc_fallback_results": [],
            "candidate_scores": [],
            "decision": {},
        }
        
        if doc_type in FREIGHT_DOC_TYPES:
            diag["strategy_reason"].append(f"Freight doc type: {doc_type}")
        if is_freight_carrier:
            diag["strategy_reason"].append(f"Freight carrier: {vendor_name}")
        if has_bol:
            diag["strategy_reason"].append("BOL reference extracted")
        if not diag["strategy_reason"]:
            diag["strategy_reason"].append(f"Default for doc type: {doc_type}")
        
        logger.info(
            "[Reference Intelligence] Starting resolution for doc %s (type: %s, strategy: %s)",
            doc_id[:8], doc_type, effective_strategy
        )
        
        # 1. Extract reference candidates
        candidates = []
        
        # From extracted fields
        if extracted_fields:
            field_candidates = extract_references_from_extracted_fields(extracted_fields)
            candidates.extend(field_candidates)
            diag["extraction"]["from_fields"] = len(field_candidates)
        
        # From document fields
        doc_fields = {
            "po_number": document.get("po_number_clean"),
            "bol_number": document.get("bol_number"),
            "invoice_number": document.get("invoice_number_clean"),
            "shipment_number": document.get("shipment_number"),
        }
        doc_candidates = extract_references_from_extracted_fields(doc_fields)
        candidates.extend(doc_candidates)
        diag["extraction"]["from_document"] = len(doc_candidates)
        
        # From raw text
        if document_text:
            text_candidates = extract_references_from_text(document_text)
            candidates.extend(text_candidates)
            diag["extraction"]["from_text"] = len(text_candidates)
        
        diag["extraction"]["total_raw"] = len(candidates)
        
        # Deduplicate by normalized value
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c.reference_value_normalized not in seen:
                seen.add(c.reference_value_normalized)
                unique_candidates.append(c)
        
        # Limit to top 10
        unique_candidates.sort(key=lambda x: x.confidence, reverse=True)
        unique_candidates = unique_candidates[:10]
        
        diag["extraction"]["unique_count"] = len(unique_candidates)
        
        # Build normalization trace for each candidate
        for c in unique_candidates:
            _, trace = normalize_reference(c.reference_value_raw, return_trace=True)
            diag["normalization"][c.reference_value_raw] = {
                "raw": c.reference_value_raw,
                "normalized": c.reference_value_normalized,
                "steps": trace,
                "label": c.detected_label,
            }
        
        # 2. Classify each candidate with context-aware classification
        for candidate in unique_candidates:
            # Apply shipping context fix: if source text contains BOL/shipment keywords,
            # don't force classification to PO
            source_lower = (candidate.source_text or "").lower()
            if candidate.detected_label == ReferenceLabel.PO.value:
                for kw in SHIPPING_CONTEXT_KEYWORDS:
                    if kw in source_lower:
                        candidate.detected_label = ReferenceLabel.SHIPMENT.value
                        candidate.classification_reasoning = f"Reclassified: '{kw}' in context → shipment"
                        break
            
            domain, entity_types, reasoning = classify_reference_domain(
                candidate, doc_type, vendor_name
            )
            candidate.predicted_domain = domain
            candidate.predicted_entity_types = entity_types
            if not candidate.classification_reasoning:
                candidate.classification_reasoning = reasoning
            
            # Set semantic type (Requirement 4)
            label_enum = None
            for rl in ReferenceLabel:
                if rl.value == candidate.detected_label:
                    label_enum = rl
                    break
            candidate.semantic_type = LABEL_TO_SEMANTIC_TYPE.get(
                label_enum, ReferenceSemanticType.GENERIC_REFERENCE
            ).value
            
            diag["candidates"].append({
                "raw": candidate.reference_value_raw,
                "normalized": candidate.reference_value_normalized,
                "label": candidate.detected_label,
                "domain": candidate.predicted_domain,
                "entity_types": candidate.predicted_entity_types,
                "confidence": candidate.confidence,
                "reasoning": candidate.classification_reasoning,
            })
        
        result.reference_candidates = unique_candidates
        
        # Emit extraction event
        if self.event_service:
            await self.event_service.emit(
                event_type="reference.extraction.completed",
                document_id=doc_id,
                source_service="reference_intelligence",
                correlation_id=correlation_id,
                payload={
                    "candidate_count": len(unique_candidates),
                    "candidates": [c.to_dict() for c in unique_candidates[:5]]
                }
            )
        
        # 3. Resolve against BC
        if not self.bc_resolver:
            logger.warning("[Reference Intelligence] No BC resolver configured")
            diag["decision"] = {"outcome": "no_resolver", "reason": "BC resolver not configured"}
            result.matching_diagnostics = diag
            return result
        
        # Fetch vendor-aware hints and label correction hints
        vendor_hints = None
        if self._vendor_intel_service and vendor_name:
            try:
                vendor_hints = await self._vendor_intel_service.get_resolver_hints(vendor_name)
            except Exception:
                pass
        
        diag["vendor_hints"] = {
            "has_hints": vendor_hints.get("has_hints", False) if vendor_hints else False,
            "preferred_domain": vendor_hints.get("preferred_domain") if vendor_hints else None,
            "typical_match_types": vendor_hints.get("typical_match_types", []) if vendor_hints else [],
            "label_correction_patterns": vendor_hints.get("label_correction_patterns", {}) if vendor_hints else {},
        }
        
        all_matches = []
        search_tables = get_search_tables(effective_strategy)
        bc_query_count = 0
        
        # --- Part 5: Dynamic search strategy based on vendor correction patterns ---
        # If vendor patterns indicate label→entity bias, reorder search tables
        vendor_correction_patterns = {}
        if vendor_hints and vendor_hints.get("has_hints"):
            vendor_correction_patterns = vendor_hints.get("label_correction_patterns", {})
        
        dynamic_strategy_applied = False
        if vendor_correction_patterns:
            # Check if the dominant correction is toward shipments
            shipment_count = 0
            total_count = 0
            for key, pattern in vendor_correction_patterns.items():
                count = pattern.get("count", 0)
                total_count += count
                if pattern.get("actual_entity_type", "") in ("posted_sales_shipment", "sales_shipment"):
                    shipment_count += count
            
            if total_count >= 2 and shipment_count / max(total_count, 1) > 0.5:
                # Vendor has strong shipment bias — reorder to prioritize shipments
                shipment_first = ["salesShipments", "salesOrders", "purchaseOrders", "purchaseInvoices", "salesInvoices"]
                search_tables = [t for t in shipment_first if t in search_tables] + [t for t in search_tables if t not in shipment_first]
                dynamic_strategy_applied = True
                diag["dynamic_strategy"] = {
                    "applied": True,
                    "reason": f"Vendor shipment correction rate: {shipment_count}/{total_count}",
                    "reordered_tables": search_tables,
                }
        
        if not dynamic_strategy_applied:
            diag["dynamic_strategy"] = {"applied": False}
        
        # Pre-fetch label correction hints for each candidate's label
        label_correction_cache = {}
        if self._label_correction_service and vendor_name:
            for candidate in unique_candidates:
                label = candidate.detected_label
                if label not in label_correction_cache:
                    try:
                        hints = await self._label_correction_service.get_scoring_hints(vendor_name, label)
                        label_correction_cache[label] = hints
                    except Exception:
                        label_correction_cache[label] = {"has_hints": False}
        
        diag["label_correction_hints"] = {
            k: v for k, v in label_correction_cache.items() if v.get("has_hints")
        }
        
        # Fetch Vendor Extraction Profile (adaptive interpretation layer)
        extraction_profile = None
        if self._vep_service and vendor_name:
            try:
                extraction_profile = await self._vep_service.get_resolver_adjustments(vendor_name)
            except Exception:
                extraction_profile = {"has_profile": False}
        
        diag["extraction_profile"] = {
            "has_profile": extraction_profile.get("has_profile", False) if extraction_profile else False,
            "document_type_bias": extraction_profile.get("document_type_bias") if extraction_profile else None,
            "reference_priority_order": extraction_profile.get("reference_priority_order", []) if extraction_profile else [],
            "label_bias_count": len(extraction_profile.get("reference_label_bias", {})) if extraction_profile else 0,
            "learning_source": extraction_profile.get("learning_source", []) if extraction_profile else [],
        }
        
        # Fetch Layout Family Bias (structural signal, NOT a template)
        layout_family_bias = None
        if self._layout_fingerprint_service:
            try:
                layout_family_bias = await self._layout_fingerprint_service.get_resolver_bias(doc_id)
            except Exception:
                layout_family_bias = {"has_layout_bias": False}
        
        diag["layout_family"] = {
            "has_bias": layout_family_bias.get("has_layout_bias", False) if layout_family_bias else False,
            "family_id": layout_family_bias.get("layout_family_id") if layout_family_bias else None,
            "fingerprint": layout_family_bias.get("layout_fingerprint") if layout_family_bias else None,
            "similarity_score": layout_family_bias.get("layout_similarity_score") if layout_family_bias else None,
            "new_layout_detected": layout_family_bias.get("new_layout_detected", False) if layout_family_bias else False,
            "entity_biases": layout_family_bias.get("entity_biases", {}) if layout_family_bias else {},
            "documents_count": layout_family_bias.get("documents_count", 0) if layout_family_bias else 0,
        }
        
        for candidate in unique_candidates:
            # Use the adaptive resolver
            bc_result = await self.bc_resolver.resolve_reference(
                candidate.reference_value_normalized,
                check_tables=search_tables
            )
            bc_query_count += len(bc_result.tables_checked) if hasattr(bc_result, 'tables_checked') else 1
            
            # Track cache vs API results
            source = bc_result.bc_record_info.get("source", "api") if bc_result.bc_record_info else "miss"
            if source == "cache":
                diag["cache_results"].append({
                    "reference": candidate.reference_value_normalized,
                    "entity": bc_result.reference_type,
                    "doc_no": bc_result.bc_document_no,
                    "status": bc_result.status,
                })
            elif bc_result.status == "found":
                diag["bc_fallback_results"].append({
                    "reference": candidate.reference_value_normalized,
                    "entity": bc_result.reference_type,
                    "doc_no": bc_result.bc_document_no,
                    "tables_checked": bc_result.tables_checked,
                })
            
            if bc_result.status == "found":
                lc_hints = label_correction_cache.get(candidate.detected_label, {"has_hints": False})
                score, reasoning, breakdown, cand_domain, counterparty, pos_signals, neg_signals = score_bc_match(
                    candidate,
                    bc_result.bc_record_info,
                    bc_result.reference_type,
                    document,
                    vendor_hints=vendor_hints,
                    label_correction_hints=lc_hints,
                    extraction_profile=extraction_profile,
                    layout_family_bias=layout_family_bias,
                    source_doc_type=source_doc_type
                )
                
                match = BCMatch(
                    entity_type=bc_result.reference_type,
                    bc_record_id=bc_result.bc_record_id,
                    bc_document_no=bc_result.bc_document_no,
                    bc_record_info=bc_result.bc_record_info,
                    match_score=score,
                    match_reasoning=reasoning,
                    candidate_domain=cand_domain,
                    counterparty_name=counterparty,
                    score_breakdown=breakdown,
                    positive_signals=pos_signals,
                    negative_signals=neg_signals
                )
                all_matches.append((candidate, match))
                
                diag["candidate_scores"].append({
                    "reference": candidate.reference_value_normalized,
                    "entity_type": bc_result.reference_type,
                    "bc_document_no": bc_result.bc_document_no,
                    "final_score": round(score, 4),
                    "score_breakdown": {k: round(v, 4) for k, v in breakdown.items()},
                    "reasoning": reasoning,
                    "candidate_domain": cand_domain,
                    "counterparty": counterparty,
                    "positive_signals": pos_signals,
                    "negative_signals": neg_signals,
                    "semantic_type": candidate.semantic_type,
                })
        
        result.total_bc_queries = bc_query_count
        
        # --- Part 4: Shipment Reference Clustering ---
        # For freight/BOL docs, try cluster search for additional shipment-related matches
        cluster_matches_added = 0
        if (effective_strategy == FREIGHT_STRATEGY_KEY and
                self.bc_resolver and hasattr(self.bc_resolver, '_cache_service') and
                self.bc_resolver._cache_service and
                hasattr(self.bc_resolver._cache_service, 'search_shipment_cluster')):
            try:
                for candidate in unique_candidates:
                    # Only cluster-search if primary didn't find a shipment match
                    primary_has_shipment = any(
                        "shipment" in m.entity_type.lower()
                        for _, m in all_matches
                        if m.bc_document_no
                    )
                    if primary_has_shipment:
                        break
                    
                    cluster_results = await self.bc_resolver._cache_service.search_shipment_cluster(
                        candidate.reference_value_normalized
                    )
                    for cr in cluster_results:
                        # Score clustered results with a cluster bonus
                        cluster_entity_type = cr.get("bc_entity_type", "unknown")
                        cluster_info = {
                            "number": cr.get("bc_document_no", ""),
                            "id": cr.get("bc_record_id"),
                            "table": "cache",
                            "source": "cluster",
                            "vendor_name": cr.get("bc_vendor_name", ""),
                            "customer_name": cr.get("bc_customer_name", ""),
                            "posting_date": cr.get("bc_posting_date"),
                            "orderNumber": cr.get("bc_order_number", ""),
                            "order_number": cr.get("bc_order_number", ""),
                            "_cluster_reason": cr.get("_cluster_reason", ""),
                        }
                        lc_hints = label_correction_cache.get(candidate.detected_label, {"has_hints": False})
                        score, reasoning, breakdown, cand_domain, counterparty, pos_signals, neg_signals = score_bc_match(
                            candidate, cluster_info, cluster_entity_type,
                            document, vendor_hints=vendor_hints,
                            label_correction_hints=lc_hints,
                            extraction_profile=extraction_profile,
                            layout_family_bias=layout_family_bias,
                            source_doc_type=source_doc_type
                        )
                        # Add cluster bonus (0.03) for relationship-based discovery
                        cluster_bonus = 0.03 if cr.get("_cluster_reason", "").startswith("linked_via") else 0
                        breakdown["cluster_match_bonus"] = cluster_bonus
                        score = min(sum(breakdown.values()), 1.0)
                        
                        match = BCMatch(
                            entity_type=cluster_entity_type,
                            bc_record_id=cr.get("bc_record_id"),
                            bc_document_no=cr.get("bc_document_no", ""),
                            bc_record_info=cluster_info,
                            match_score=score,
                            match_reasoning=reasoning + "; Cluster: " + cr.get("_cluster_reason", ""),
                            candidate_domain=cand_domain,
                            counterparty_name=counterparty,
                            score_breakdown=breakdown,
                            positive_signals=pos_signals,
                            negative_signals=neg_signals
                        )
                        # Avoid duplicates
                        existing_doc_nos = {m.bc_document_no for _, m in all_matches}
                        if match.bc_document_no not in existing_doc_nos:
                            all_matches.append((candidate, match))
                            cluster_matches_added += 1
                            diag["candidate_scores"].append({
                                "reference": candidate.reference_value_normalized,
                                "entity_type": cluster_entity_type,
                                "bc_document_no": cr.get("bc_document_no", ""),
                                "final_score": round(score, 4),
                                "score_breakdown": {k: round(v, 4) for k, v in breakdown.items()},
                                "reasoning": reasoning,
                                "source": "shipment_cluster",
                                "cluster_reason": cr.get("_cluster_reason", ""),
                            })
            except Exception as ce:
                logger.warning("[Reference Intelligence] Shipment clustering error: %s", str(ce))
        
        diag["shipment_clustering"] = {
            "attempted": effective_strategy == FREIGHT_STRATEGY_KEY,
            "cluster_matches_added": cluster_matches_added,
        }
        
        # 4. Select best match with domain-aware, multi-signal logic
        if all_matches:
            all_matches.sort(key=lambda x: x[1].match_score, reverse=True)
            all_scores = [m.match_score for _, m in all_matches]
            
            best_candidate, best_match = all_matches[0]
            result.best_match = best_match
            result.match_outcome = determine_match_outcome(
                best_match.match_score,
                len(all_matches),
                all_scores=all_scores,
                best_match=best_match,
                source_doc_type=source_doc_type
            )
            
            # Apply candidate state to best match
            best_match.candidate_state = determine_candidate_state(
                best_match, source_doc_type, result.match_outcome
            )
            
            # Add alternates (excluding best) with their states
            for _, match in all_matches[1:3]:
                alt_outcome = determine_match_outcome(
                    match.match_score, 1, [match.match_score],
                    best_match=match, source_doc_type=source_doc_type
                )
                match.candidate_state = determine_candidate_state(
                    match, source_doc_type, alt_outcome
                )
                result.alternate_matches.append(match)
            
            diag["decision"] = {
                "outcome": result.match_outcome,
                "best_score": round(best_match.match_score, 4),
                "second_best_score": round(all_scores[1], 4) if len(all_scores) > 1 else 0,
                "best_entity": best_match.entity_type,
                "best_doc_no": best_match.bc_document_no,
                "total_candidates": len(all_matches),
                # Part 8: feedback loop diagnostics
                "label_correction_applied": any(
                    s.get("score_breakdown", {}).get("label_correction_boost", 0) > 0
                    for s in diag.get("candidate_scores", [])
                ),
                "vendor_pattern_weight": round(sum(
                    s.get("score_breakdown", {}).get("vendor_behavior_bonus", 0)
                    + s.get("score_breakdown", {}).get("label_correction_boost", 0)
                    for s in diag.get("candidate_scores", [])
                    if s.get("bc_document_no") == best_match.bc_document_no
                ), 4),
                "cluster_match_bonus": round(sum(
                    s.get("score_breakdown", {}).get("cluster_match_bonus", 0)
                    for s in diag.get("candidate_scores", [])
                    if s.get("bc_document_no") == best_match.bc_document_no
                ), 4),
                "extraction_profile_applied": any(
                    s.get("score_breakdown", {}).get("extraction_profile_bias", 0) != 0
                    for s in diag.get("candidate_scores", [])
                ),
                "layout_family_bias_applied": any(
                    s.get("score_breakdown", {}).get("layout_family_bias", 0) != 0
                    for s in diag.get("candidate_scores", [])
                ),
                "layout_family_id": (layout_family_bias or {}).get("layout_family_id"),
                "new_layout_detected": (layout_family_bias or {}).get("new_layout_detected", False),
            }
            
            logger.info(
                "[Reference Intelligence] Best match for doc %s: %s (%s) score=%.2f outcome=%s",
                doc_id[:8], best_match.bc_document_no, best_match.entity_type,
                best_match.match_score, result.match_outcome
            )
        else:
            # Determine failure reason
            failure_reason = "no_reference_extracted" if not unique_candidates else "reference_not_found"
            diag["decision"] = {
                "outcome": MatchOutcome.NO_MATCH.value,
                "failure_reason": failure_reason,
                "candidates_searched": len(unique_candidates),
                "tables_checked": search_tables,
            }
            logger.info("[Reference Intelligence] No BC matches for doc %s (%s)", doc_id[:8], failure_reason)
        
        # Calculate processing time
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        diag["processing_time_ms"] = result.processing_time_ms
        
        # Attach diagnostics to result
        result.matching_diagnostics = diag
        
        # Emit resolution event
        if self.event_service:
            event_type = "reference.resolve.completed"
            if result.match_outcome == MatchOutcome.AMBIGUOUS_MATCH.value:
                event_type = "reference.resolve.ambiguous"
            
            await self.event_service.emit(
                event_type=event_type,
                document_id=doc_id,
                status="completed" if result.best_match else "warning",
                source_service="reference_intelligence",
                correlation_id=correlation_id,
                payload={
                    "match_outcome": result.match_outcome,
                    "best_match_type": result.best_match.entity_type if result.best_match else None,
                    "best_match_score": result.best_match.match_score if result.best_match else None,
                    "candidate_count": len(result.reference_candidates),
                    "bc_queries": result.total_bc_queries,
                    "processing_time_ms": result.processing_time_ms,
                    "strategy": effective_strategy,
                }
            )
        
        return result
    
    async def update_document_references(
        self,
        document_id: str,
        resolution_result: ReferenceResolutionResult
    ):
        """Update document with reference resolution results and persist diagnostics."""
        update_data = {
            "reference_intelligence": resolution_result.to_dict(),
            "reference_candidates": [c.to_dict() for c in resolution_result.reference_candidates],
            "reference_match_outcome": resolution_result.match_outcome,
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }
        
        if resolution_result.best_match:
            update_data["reference_best_match"] = resolution_result.best_match.to_dict()
            update_data["reference_bc_type"] = resolution_result.best_match.entity_type
            update_data["reference_bc_document_no"] = resolution_result.best_match.bc_document_no
            update_data["reference_bc_record_id"] = resolution_result.best_match.bc_record_id
        
        await self.db.hub_documents.update_one(
            {"id": document_id},
            {"$set": update_data}
        )
        
        # Persist matching diagnostics for ambiguous/no_match/all results
        diag = resolution_result.matching_diagnostics
        if diag:
            diag["document_id"] = document_id
            diag["resolved_at"] = resolution_result.resolved_at
            await self.db.matching_diagnostics.replace_one(
                {"document_id": document_id},
                diag,
                upsert=True
            )


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_reference_intelligence_service: Optional[ReferenceIntelligenceService] = None


def get_reference_intelligence_service() -> Optional[ReferenceIntelligenceService]:
    """Get the global reference intelligence service."""
    return _reference_intelligence_service


def set_reference_intelligence_service(db, bc_resolver=None, event_service=None) -> ReferenceIntelligenceService:
    """Initialize the reference intelligence service."""
    global _reference_intelligence_service
    _reference_intelligence_service = ReferenceIntelligenceService(db, bc_resolver, event_service)
    return _reference_intelligence_service
