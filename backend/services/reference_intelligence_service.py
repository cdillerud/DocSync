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
    SHIPPING = "shipping"
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
    """Reference match outcome."""
    EXACT_MATCH = "exact_match"
    LIKELY_MATCH = "likely_match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NO_MATCH = "no_match"


# Reference extraction patterns
REFERENCE_PATTERNS = {
    ReferenceLabel.PO: [
        r'P\.?O\.?\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Purchase\s+Order\s*#?\s*[:.]?\s*(\d{4,10})',
        r'PO\s+Number\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.BOL: [
        r'B\.?O\.?L\.?\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Bill\s+of\s+Lading\s*#?\s*[:.]?\s*(\d{4,10})',
        r'BOL\s+Number\s*[:.]?\s*(\d{4,10})',
        r'B/L\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.ORDER: [
        r'Order\s*#?\s*[:.]?\s*([A-Z]?\d{4,10})',
        r'Sales\s+Order\s*#?\s*[:.]?\s*(\d{4,10})',
        r'SO\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.SHIPMENT: [
        r'Shipment\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Ship\s*#?\s*[:.]?\s*(\d{4,10})',
    ],
    ReferenceLabel.LOAD: [
        r'Load\s*#?\s*[:.]?\s*(\d{4,10})',
        r'Load\s+Number\s*[:.]?\s*(\d{4,10})',
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
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "BOL": [
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_SHIPMENT,
        BCEntityType.POSTED_SALES_INVOICE,
        BCEntityType.PURCHASE_ORDER,
        BCEntityType.POSTED_PURCHASE_INVOICE,
    ],
    "Shipping_Document": [
        BCEntityType.SALES_ORDER,
        BCEntityType.POSTED_SALES_SHIPMENT,
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
        return result


# =============================================================================
# REFERENCE EXTRACTION
# =============================================================================

def normalize_reference(raw_value: str) -> str:
    """
    Normalize a reference value for BC lookup.
    
    Rules:
    - Remove prefixes (BOL, REF, ORDER, PO, etc.)
    - Strip leading zeros
    - Remove spaces and punctuation
    - Convert to uppercase
    """
    if not raw_value:
        return ""
    
    # Convert to uppercase
    normalized = raw_value.upper().strip()
    
    # Remove common prefixes
    prefixes = [
        r'^BOL[\s\-#:\.]*',
        r'^B/L[\s\-#:\.]*',
        r'^P\.?O\.?[\s\-#:\.]*',
        r'^REF[\s\-#:\.]*',
        r'^ORDER[\s\-#:\.]*',
        r'^SO[\s\-#:\.]*',
        r'^SHIP[\s\-#:\.]*',
        r'^LOAD[\s\-#:\.]*',
        r'^PRO[\s\-#:\.]*',
        r'^INV[\s\-#:\.]*',
        r'^#',
    ]
    
    for prefix in prefixes:
        normalized = re.sub(prefix, '', normalized, flags=re.IGNORECASE)
    
    # Remove remaining punctuation and spaces
    normalized = re.sub(r'[\s\-\.\#\:\,]+', '', normalized)
    
    # Strip leading zeros (but keep at least one digit)
    normalized = normalized.lstrip('0') or '0'
    
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
    vendor_hints: Dict[str, Any] = None
) -> Tuple[float, str]:
    """
    Score a BC match based on multiple factors.
    
    Returns: (score, reasoning)
    """
    score = 0.0
    reasoning_parts = []
    
    bc_number = bc_record.get("number", "")
    normalized_ref = candidate.reference_value_normalized
    
    # 1. Exact reference match (0.4)
    if bc_number == normalized_ref:
        score += 0.4
        reasoning_parts.append("Exact number match")
    elif normalize_reference(bc_number) == normalized_ref:
        score += 0.35
        reasoning_parts.append("Normalized number match")
    
    # 2. Predicted entity type alignment (0.2)
    if entity_type in candidate.predicted_entity_types:
        score += 0.2
        reasoning_parts.append(f"Entity type matches prediction: {entity_type}")
    else:
        score += 0.1
        reasoning_parts.append(f"Entity type: {entity_type}")
    
    # 3. Domain alignment (0.15)
    if candidate.predicted_domain:
        if candidate.predicted_domain == ReferenceDomain.PURCHASE.value and "purchase" in entity_type.lower():
            score += 0.15
            reasoning_parts.append("Domain alignment: purchase")
        elif candidate.predicted_domain == ReferenceDomain.SALES.value and "sales" in entity_type.lower():
            score += 0.15
            reasoning_parts.append("Domain alignment: sales")
        elif candidate.predicted_domain == ReferenceDomain.SHIPPING.value and ("shipment" in entity_type.lower() or "sales" in entity_type.lower()):
            score += 0.15
            reasoning_parts.append("Domain alignment: shipping")
    
    # 4. Vendor alignment (0.15) - if document has vendor
    if document:
        doc_vendor = document.get("vendor_raw", "") or document.get("matched_vendor_name", "")
        bc_vendor = bc_record.get("vendorName") or bc_record.get("vendor_name", "")
        
        if doc_vendor and bc_vendor:
            doc_vendor_norm = doc_vendor.lower().replace(" ", "")
            bc_vendor_norm = bc_vendor.lower().replace(" ", "")
            
            if doc_vendor_norm in bc_vendor_norm or bc_vendor_norm in doc_vendor_norm:
                score += 0.15
                reasoning_parts.append(f"Vendor alignment: {bc_vendor[:20]}")
    
    # 5. Candidate confidence (0.1)
    score += candidate.confidence * 0.1
    reasoning_parts.append(f"Candidate confidence: {candidate.confidence:.2f}")
    
    # 6. Vendor behavior boost (up to 0.15) - from vendor intelligence
    if vendor_hints and vendor_hints.get("has_hints"):
        typical_types = vendor_hints.get("typical_match_types", [])
        if entity_type in typical_types:
            boost = vendor_hints.get("behavior_score_boost", 0.15)
            score += boost
            reasoning_parts.append(f"Vendor behavior: typical match type (+{boost:.0%})")
    
    reasoning = "; ".join(reasoning_parts)
    
    return min(score, 1.0), reasoning


def determine_match_outcome(best_score: float, alternate_count: int) -> str:
    """Determine the match outcome based on score and alternatives."""
    if best_score >= 0.85:
        return MatchOutcome.EXACT_MATCH.value
    elif best_score >= 0.65:
        if alternate_count > 1:
            return MatchOutcome.AMBIGUOUS_MATCH.value
        return MatchOutcome.LIKELY_MATCH.value
    elif best_score >= 0.4:
        return MatchOutcome.AMBIGUOUS_MATCH.value
    else:
        return MatchOutcome.NO_MATCH.value


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
    
    async def resolve_document_references(
        self,
        document: Dict[str, Any],
        extracted_fields: Dict[str, Any] = None,
        document_text: str = None,
        correlation_id: str = None
    ) -> ReferenceResolutionResult:
        """
        Main entry point: resolve all references for a document.
        """
        import time
        start_time = time.time()
        
        doc_id = document.get("id", "unknown")
        doc_type = document.get("document_type") or document.get("suggested_job_type") or "default"
        vendor_name = document.get("vendor_raw") or document.get("matched_vendor_name")
        
        # Initialize result
        result = ReferenceResolutionResult(
            document_id=doc_id,
            document_type=doc_type,
            resolver_strategy=doc_type,
            search_order=get_search_strategy(doc_type),
            resolved_at=datetime.now(timezone.utc).isoformat()
        )
        
        logger.info("[Reference Intelligence] Starting resolution for doc %s (type: %s)", doc_id[:8], doc_type)
        
        # 1. Extract reference candidates
        candidates = []
        
        # From extracted fields
        if extracted_fields:
            candidates.extend(extract_references_from_extracted_fields(extracted_fields))
        
        # From document fields
        doc_fields = {
            "po_number": document.get("po_number_clean"),
            "bol_number": document.get("bol_number"),
            "invoice_number": document.get("invoice_number_clean"),
        }
        candidates.extend(extract_references_from_extracted_fields(doc_fields))
        
        # From raw text
        if document_text:
            candidates.extend(extract_references_from_text(document_text))
        
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
        
        # 2. Classify each candidate
        for candidate in unique_candidates:
            domain, entity_types, reasoning = classify_reference_domain(
                candidate, doc_type, vendor_name
            )
            candidate.predicted_domain = domain
            candidate.predicted_entity_types = entity_types
            candidate.classification_reasoning = reasoning
        
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
            return result
        
        all_matches = []
        search_tables = get_search_tables(doc_type)
        bc_query_count = 0
        
        for candidate in unique_candidates:
            # Use the adaptive resolver
            bc_result = await self.bc_resolver.resolve_reference(
                candidate.reference_value_normalized,
                check_tables=search_tables
            )
            bc_query_count += len(bc_result.tables_checked) if hasattr(bc_result, 'tables_checked') else 1
            
            if bc_result.status == "found":
                score, reasoning = score_bc_match(
                    candidate,
                    bc_result.bc_record_info,
                    bc_result.reference_type,
                    document
                )
                
                match = BCMatch(
                    entity_type=bc_result.reference_type,
                    bc_record_id=bc_result.bc_record_id,
                    bc_document_no=bc_result.bc_document_no,
                    bc_record_info=bc_result.bc_record_info,
                    match_score=score,
                    match_reasoning=reasoning
                )
                all_matches.append((candidate, match))
        
        result.total_bc_queries = bc_query_count
        
        # 4. Select best match
        if all_matches:
            all_matches.sort(key=lambda x: x[1].match_score, reverse=True)
            
            best_candidate, best_match = all_matches[0]
            result.best_match = best_match
            result.match_outcome = determine_match_outcome(
                best_match.match_score,
                len(all_matches)
            )
            
            # Add alternates (excluding best)
            for _, match in all_matches[1:3]:  # Top 3 alternates
                result.alternate_matches.append(match)
            
            logger.info(
                "[Reference Intelligence] Best match for doc %s: %s (%s) score=%.2f",
                doc_id[:8], best_match.bc_document_no, best_match.entity_type, best_match.match_score
            )
        else:
            logger.info("[Reference Intelligence] No BC matches for doc %s", doc_id[:8])
        
        # Calculate processing time
        result.processing_time_ms = int((time.time() - start_time) * 1000)
        
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
                    "processing_time_ms": result.processing_time_ms
                }
            )
        
        return result
    
    async def update_document_references(
        self,
        document_id: str,
        resolution_result: ReferenceResolutionResult
    ):
        """Update document with reference resolution results."""
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
