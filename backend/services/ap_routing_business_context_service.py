"""Route-neutral documented business context for V117 learned AP routing.

This module turns documented Gamer workflows and read-only BC/document facts into
business-context features. It never reads route_path/final_human_route and never
selects or substitutes an Accounting route. The learned model/authority layers
may use these facts only as similarity/corroboration evidence.

Documented sources behind the feature vocabulary include warehouse outbound,
warehouse transfer/return, Canpack drop-ship/warehouse, Ball, and assembly
procedures plus the warehouse/template tracking workbooks. The code intentionally
stores facts (order family, location, shipment method, freight/service markers)
rather than hard-coding a fact -> route mapping.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set


BUSINESS_CONTEXT_SCHEMA = "v117-business-context-v1"

# Locations documented as physical warehouse/consignment locations in the
# supplied Warehouse Documents / Template Checklist material. Exact location is
# still emitted separately; membership is only a route-neutral business fact.
DOCUMENTED_WAREHOUSE_LOCATIONS = frozenset(
    {
        "000", "001", "007", "012", "013", "017", "020", "021", "028",
        "030", "031", "034", "035", "036", "037", "038", "040", "041",
        "042", "044", "045", "046", "047", "049", "051", "051WSI", "053",
        "056", "061", "074", "075", "076", "082", "087", "090", "091",
        "093", "095", "096", "097", "098", "904", "911", "913", "914",
        "915", "921", "926",
    }
)

_ORDER_PATTERNS = (
    ("wtr", re.compile(r"(?<![A-Z0-9])WTR\s*[-_ ]?\d{2,7}[A-Z]?(?![A-Z0-9])", re.IGNORECASE)),
    ("wa", re.compile(r"(?<![A-Z0-9])WA\s*[-_ ]?\d{2,7}[A-Z]?(?![A-Z0-9])", re.IGNORECASE)),
    ("w", re.compile(r"(?<![A-Z0-9])W\s*[-_ ]?\d{4,7}[A-Z]?(?![A-Z0-9])", re.IGNORECASE)),
)

_SHIPMENT_METHOD_PATTERNS = (
    ("ppdadd_intl", re.compile(r"(?<![A-Z0-9])PPDADD[-_ ]?INTL(?![A-Z0-9])", re.IGNORECASE)),
    ("ppd_intl", re.compile(r"(?<![A-Z0-9])PPD[-_ ]?INTL(?![A-Z0-9])", re.IGNORECASE)),
    ("third_party", re.compile(r"(?<![A-Z0-9])(?:3RDPARTY|3RD\s+PARTY|THIRD\s+PARTY)(?![A-Z0-9])", re.IGNORECASE)),
    ("ppdadd", re.compile(r"(?<![A-Z0-9])PPDADD(?![A-Z0-9])", re.IGNORECASE)),
    ("collect", re.compile(r"(?<![A-Z0-9])COLLECT(?![A-Z0-9])", re.IGNORECASE)),
    ("delivered", re.compile(r"(?<![A-Z0-9])DELIVERED(?![A-Z0-9])", re.IGNORECASE)),
    ("cpu", re.compile(r"(?<![A-Z0-9])CPU(?![A-Z0-9])", re.IGNORECASE)),
    ("ppd", re.compile(r"(?<![A-Z0-9])PPD(?![A-Z0-9])", re.IGNORECASE)),
)

_FREIGHT_LINE_PATTERNS = {
    "freight_ds": re.compile(r"(?<![A-Z0-9])FREIGHT[-_ ]?DS(?![A-Z0-9])", re.IGNORECASE),
    "freight_wh": re.compile(r"(?<![A-Z0-9])FREIGHT[-_ ]?WH(?![A-Z0-9])", re.IGNORECASE),
    "whsefrt": re.compile(r"(?<![A-Z0-9])WHSEFRT(?![A-Z0-9])", re.IGNORECASE),
}

_SERVICE_PATTERNS = {
    "storage": re.compile(r"\b(?:WHSESTORAGE|warehouse\s+storage|yard\s+storage|storage\s+(?:fee|charge|cost|invoice))\b", re.IGNORECASE),
    "handling": re.compile(r"\b(?:WHSEHANDLING|warehouse\s+handling|handling\s+(?:fee|charge|cost|invoice))\b", re.IGNORECASE),
    "detention": re.compile(r"\bDETENTION\b", re.IGNORECASE),
    "dunnage": re.compile(r"\b(?:DUNNAGE|PALLET(?:S)?|TIER\s*SHEET(?:S)?|TOP\s*FRAME(?:S)?)\b", re.IGNORECASE),
    "cost_only": re.compile(r"\bcost[\s_-]+only\b", re.IGNORECASE),
}

_WORKFLOW_PATTERNS = {
    "direct_ship": re.compile(r"\b(?:direct\s+ship(?:ment)?|drop\s+ship(?:ment)?)\b", re.IGNORECASE),
    "warehouse_inbound": re.compile(r"\b(?:warehouse\s+inbound|receiving\s+paperwork|warehouse\s+receipt|receive\s+and\s+invoice)\b", re.IGNORECASE),
    "warehouse_outbound": re.compile(r"\b(?:warehouse\s+outbound|outbound\s+doc(?:ument)?s?|ship\s+only)\b", re.IGNORECASE),
    "transfer": re.compile(r"\b(?:warehouse\s+transfer|transfer\s+order|transferring\s+to)\b", re.IGNORECASE),
    "assembly": re.compile(r"\b(?:assembly\s+order|repack(?:\s+fee|\s+project)?)\b", re.IGNORECASE),
    "produce_hold": re.compile(r"\bproduce\s+and\s+hold\b", re.IGNORECASE),
    "return": re.compile(r"\b(?:dunnage\s+return|sales\s+credit\s+memo|return(?:ed|s)?)\b", re.IGNORECASE),
}

_AUTHORITY_PREFIX_PRIORITY = (
    "context_pair:",
    "freight_line:",
    "service:",
    "order_family:",
    "workflow:",
    "shipment_method:",
    "location_code:",
    "reference_evidence:",
    "vendor_fact:",
)


def _flatten(value: Any, *, limit: int = 100) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts: List[str] = []
        for key, item in list(value.items())[:limit]:
            # Explicitly ignore routing labels if a caller passes a whole example.
            if str(key).lower() in {"route_path", "final_human_route", "source_route_path"}:
                continue
            parts.append(str(key))
            parts.append(_flatten(item, limit=limit))
        return " ".join(parts)
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(item, limit=limit) for item in list(value)[:limit])
    return str(value)


def _document_text(document: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(document.get("file_name") or ""),
            str(document.get("raw_text") or document.get("raw_text_excerpt") or "")[:24000],
            _flatten(document.get("extracted_fields") or {}),
            _flatten(document.get("normalized_fields") or {}),
            _flatten(document.get("key_evidence") or {}),
            _flatten(document.get("bundle_references") or document.get("bundle_reference_evidence") or {}),
            _flatten(document.get("bc_context") or {}),
        ]
    )


def _candidate_reference_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    bc = document.get("bc_context") or {}
    live = bc.get("live_bc_context") or {}
    values = [
        fields.get("po_number"),
        fields.get("order_number"),
        fields.get("reference_number"),
        (document.get("key_evidence") or {}).get("po_number"),
        bc.get("po_number"),
        bc.get("bc_document_no"),
        bc.get("bc_order_number"),
        live.get("bc_document_no"),
        live.get("bc_order_number"),
        document.get("file_name"),
    ]
    return " ".join(str(value) for value in values if value)


def _order_family(document: Dict[str, Any]) -> str:
    text = _candidate_reference_text(document).upper()
    for name, pattern in _ORDER_PATTERNS:
        if pattern.search(text):
            return name

    # Numeric order-family evidence is accepted only from structured PO/order
    # fields or resolved BC context; raw filenames/text can contain compact dates.
    fields = document.get("extracted_fields") or {}
    bc = document.get("bc_context") or {}
    live = bc.get("live_bc_context") or {}
    for value in (
        bc.get("po_number"),
        bc.get("bc_document_no"),
        bc.get("bc_order_number"),
        live.get("bc_document_no"),
        live.get("bc_order_number"),
        fields.get("po_number"),
        fields.get("order_number"),
    ):
        token = str(value or "").strip().upper()
        if re.fullmatch(r"\d{4,7}", token):
            return "numeric"
    return ""


def _location_code(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    bc = document.get("bc_context") or {}
    live = bc.get("live_bc_context") or {}
    for value in (
        bc.get("location_code"),
        live.get("location_code"),
        fields.get("location_code"),
        fields.get("location"),
        (document.get("key_evidence") or {}).get("location_code"),
    ):
        token = str(value or "").strip().upper().replace(" ", "")
        if token and re.fullmatch(r"[A-Z0-9_-]{1,12}", token):
            return token
    return ""


def _vendor_text(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    bc = document.get("bc_context") or {}
    live = bc.get("live_bc_context") or {}
    return " ".join(
        str(value or "")
        for value in (
            document.get("vendor_name"),
            document.get("vendor_canonical"),
            fields.get("vendor"),
            fields.get("vendor_name"),
            bc.get("bc_vendor_name"),
            bc.get("bc_vendor_no"),
            live.get("bc_vendor_name"),
            live.get("bc_vendor_no"),
        )
        if value
    ).upper()


def _invoice_number(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    for value in (
        fields.get("invoice_number"),
        fields.get("vendor_invoice_number"),
        document.get("invoice_number"),
    ):
        token = str(value or "").strip().upper()
        if token:
            return token
    return ""


def _reference_evidence_features(document: Dict[str, Any]) -> Set[str]:
    bundle = document.get("bundle_references") or document.get("bundle_reference_evidence") or {}
    references = bundle.get("references") or {}
    features: Set[str] = set()
    for key, feature in {
        "bol_numbers": "reference_evidence:bol",
        "shipment_numbers": "reference_evidence:shipment",
        "order_numbers": "reference_evidence:order",
        "po_numbers": "reference_evidence:po",
    }.items():
        values = references.get(key) or []
        if values:
            features.add(feature)
    return features


def business_context_features(document: Dict[str, Any]) -> Set[str]:
    """Return route-neutral business facts present in one document/example."""
    text = _document_text(document)
    features: Set[str] = set()

    family = _order_family(document)
    if family:
        features.add(f"order_family:{family}")

    location = _location_code(document)
    if location:
        features.add(f"location_code:{location}")
        if location in DOCUMENTED_WAREHOUSE_LOCATIONS:
            features.add("location_class:documented_warehouse")
        if location == "00":
            features.add("location_class:zero")

    for name, pattern in _SHIPMENT_METHOD_PATTERNS:
        if pattern.search(text):
            features.add(f"shipment_method:{name}")
            break

    for name, pattern in _FREIGHT_LINE_PATTERNS.items():
        if pattern.search(text):
            features.add(f"freight_line:{name}")

    for name, pattern in _SERVICE_PATTERNS.items():
        if pattern.search(text):
            features.add(f"service:{name}")

    for name, pattern in _WORKFLOW_PATTERNS.items():
        if pattern.search(text):
            features.add(f"workflow:{name}")

    # The documented numbering conventions let us describe the business process
    # without naming an Accounting route.
    if family == "wtr":
        features.add("workflow:transfer")
    if family == "wa":
        features.add("workflow:assembly")
    if family == "numeric" and location == "00":
        features.add("context_pair:numeric_location_00")
    if family == "w" and location in DOCUMENTED_WAREHOUSE_LOCATIONS:
        features.add("context_pair:w_documented_warehouse_location")
    if family == "wa" and location:
        features.add("context_pair:wa_location")

    vendor = _vendor_text(document)
    invoice = _invoice_number(document)
    if ("CANPACK" in vendor.replace(" ", "") or "CANPUSA" in vendor) and invoice.startswith("110"):
        features.add("vendor_fact:canpack_invoice_110")

    features.update(_reference_evidence_features(document))
    return features


def _values_for_prefix(features: Iterable[str], prefix: str) -> Set[str]:
    return {value for value in features if value.startswith(prefix)}


def authority_business_signature(document: Dict[str, Any], *, max_features: int = 3) -> Set[str]:
    """Return a compact high-specificity signature for TRAIN corroboration.

    Generic warehouse membership and ordinary freight text are intentionally not
    sufficient by themselves. The signature favors order/location pairs, exact
    freight/service facts, then order family/workflow/method/location evidence.
    """
    features = business_context_features(document)
    filtered = {
        feature
        for feature in features
        if feature not in {
            "location_class:documented_warehouse",
            "location_class:zero",
            "service:cost_only",
        }
    }
    ordered: List[str] = []
    for prefix in _AUTHORITY_PREFIX_PRIORITY:
        for feature in sorted(_values_for_prefix(filtered, prefix)):
            if feature not in ordered:
                ordered.append(feature)
            if len(ordered) >= max(1, int(max_features)):
                return set(ordered)
    return set(ordered)


def business_context_signal_families(features: Iterable[str]) -> Set[str]:
    families = set()
    for feature in features:
        if ":" in feature:
            families.add(feature.split(":", 1)[0])
    return families


def business_context_similarity(current: Dict[str, Any], example: Dict[str, Any]) -> Dict[str, Any]:
    """Score documented business-context similarity without consulting routes."""
    current_features = business_context_features(current)
    example_features = business_context_features(example)
    shared = current_features.intersection(example_features)
    score = 0.0
    signals: List[str] = []

    weights = {
        "context_pair:": 4.0,
        "freight_line:": 4.0,
        "service:": 2.5,
        "order_family:": 3.5,
        "workflow:": 2.5,
        "shipment_method:": 2.0,
        "location_code:": 2.5,
        "location_class:": 1.0,
        "reference_evidence:": 1.0,
        "vendor_fact:": 1.5,
    }
    for feature in sorted(shared):
        weight = next((value for prefix, value in weights.items() if feature.startswith(prefix)), 0.5)
        score += weight
        signals.append(f"business:{feature}")

    # Exclusive factual families can safely carry modest mismatch penalties.
    # Location is deliberately mild because one workflow can span warehouses.
    for prefix, penalty in {
        "order_family:": 3.0,
        "context_pair:": 3.0,
        "freight_line:": 3.5,
        "shipment_method:": 1.5,
        "location_code:": 1.0,
    }.items():
        cur = _values_for_prefix(current_features, prefix)
        ex = _values_for_prefix(example_features, prefix)
        if cur and ex and cur.isdisjoint(ex):
            score -= penalty
            signals.append(f"business_mismatch:{prefix[:-1]}")

    # Specific service/workflow disagreement is useful, but absence is not a
    # contradiction because invoices often omit process wording.
    for prefix, penalty in {"service:": 1.5, "workflow:": 1.5}.items():
        cur = _values_for_prefix(current_features, prefix)
        ex = _values_for_prefix(example_features, prefix)
        if cur and ex and cur.isdisjoint(ex):
            score -= penalty
            signals.append(f"business_mismatch:{prefix[:-1]}")

    return {
        "schema": BUSINESS_CONTEXT_SCHEMA,
        "score": round(score, 4),
        "current_features": sorted(current_features),
        "example_features": sorted(example_features),
        "shared_features": sorted(shared),
        "current_authority_signature": sorted(authority_business_signature(current)),
        "example_authority_signature": sorted(authority_business_signature(example)),
        "signals": signals,
    }
