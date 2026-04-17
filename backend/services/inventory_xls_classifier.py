"""
Inventory XLS Classifier
─────────────────────────

Given an ingested .xlsx / .xls file, classify whether it is inventory-relevant
and what kind of ledger treatment it should receive.

This is step 1 of the Inventory XLS pipeline:
  Classify → Parse → Stage → Approve → Apply → Learn

This module does NOT read file contents — it only consumes the header list
(extracted by file_ingestion_service.parse_excel) plus the filename and an
optional sender email domain. This keeps it fast and synchronous-friendly.

No writes to any ledger.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# Canonical inventory classifications — map 1:1 to ledger intent.
CLASSIFICATIONS = {
    "inventory_open_orders",     # active sales commitments
    "inventory_forecast",        # planned incoming supply
    "inventory_dunnage",         # returnable / reusable ownership
    "inventory_snapshot",        # opening_balance
    "inventory_receipt",         # receipts / ASN / shipment confirmation
    "inventory_outbound",        # BOL / outbound shipment
    "not_inventory",             # skip
}


@dataclass
class XlsClassification:
    classification: str
    confidence: float            # 0.0 – 1.0
    movement_intent: Optional[str]       # opening_balance | receipt | order_commitment | outbound_shipment | incoming_supply | None
    ownership_hint: Optional[str]        # customer_owned | gamer_reserved | mixed | None
    signals: List[str] = field(default_factory=list)  # debugging — what matched
    suggested_customer_hint: Optional[str] = None     # e.g. 'gamer' from @gamerpackaging.com


# ─────────────────────────────────────────────────────────────
# Rule pack — ordered; first match wins.
# ─────────────────────────────────────────────────────────────

# Each rule: (pattern on filename, classification, movement_intent,
#             ownership_hint, confidence)
_FILENAME_RULES = [
    # Highest-specificity patterns first
    (re.compile(r"(?i)open\s*order", re.I), "inventory_open_orders", "order_commitment", None, 0.90),
    (re.compile(r"(?i)dunnage", re.I), "inventory_dunnage", "receipt", "gamer_reserved", 0.88),
    (re.compile(r"(?i)forecast|HRML", re.I), "inventory_forecast", "incoming_supply", None, 0.82),
    (re.compile(r"(?i)inventory.*(count|snapshot|balance|stock|on.?hand)", re.I),
        "inventory_snapshot", "opening_balance", None, 0.92),
    (re.compile(r"(?i)^(asn|receipt|whse.*receipt|shipment.?notification)", re.I),
        "inventory_receipt", "receipt", None, 0.85),
    (re.compile(r"(?i)^(bol|bill.?of.?lading|outbound)", re.I),
        "inventory_outbound", "outbound_shipment", None, 0.80),
]

# Header-based signals — each is a set of canonical column names that, if at
# least 2 appear together in the sheet, indicate the given classification.
_HEADER_SIGNALS = [
    # (classification, required_any_two_of, confidence_if_matched)
    ("inventory_open_orders",
        {"po", "po_number", "customer_po", "order_number", "ship_date", "qty",
         "quantity", "item", "sku", "so", "so_number"}, 0.85),
    ("inventory_forecast",
        {"week", "month", "forecast", "planned", "qty", "quantity",
         "delivery_date", "expected_date"}, 0.80),
    ("inventory_dunnage",
        {"returnable", "dunnage", "pallet", "tier_sheet", "top_frame", "qty"}, 0.85),
    ("inventory_snapshot",
        {"on_hand", "available", "balance", "stock", "inventory",
         "quantity", "item", "sku", "warehouse"}, 0.78),
    ("inventory_receipt",
        {"received", "receipt_date", "asn", "carrier", "tracking_number",
         "qty_received", "actual_qty"}, 0.80),
    ("inventory_outbound",
        {"bol_number", "ship_date", "carrier", "tracking_number", "shipped_qty",
         "delivery_address"}, 0.75),
]


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", (h or "").strip().lower()).strip("_")


def _header_signal_match(headers: List[str]) -> Optional[tuple]:
    """Return (classification, confidence, matched_signals) for the best matching signal."""
    norm = {_normalize_header(h) for h in headers if h}
    # Variants that should count as the same canonical signal
    norm |= {h.replace("number", "no") for h in list(norm)}
    best = None
    for cls, sig_set, conf in _HEADER_SIGNALS:
        hits = sig_set & norm
        if len(hits) >= 2:
            if best is None or conf > best[1]:
                best = (cls, conf, sorted(hits))
    return best


def _movement_intent_for(classification: str) -> Optional[str]:
    return {
        "inventory_open_orders": "order_commitment",
        "inventory_forecast": "incoming_supply",
        "inventory_dunnage": "receipt",
        "inventory_snapshot": "opening_balance",
        "inventory_receipt": "receipt",
        "inventory_outbound": "outbound_shipment",
    }.get(classification)


def _ownership_hint_for(classification: str) -> Optional[str]:
    if classification == "inventory_dunnage":
        # Default hint; overridden by customer profile downstream if configured.
        return "gamer_reserved"
    return None


def _sender_hint(sender_email: Optional[str]) -> Optional[str]:
    if not sender_email or "@" not in sender_email:
        return None
    domain = sender_email.split("@", 1)[1].split(".")[0].lower()
    if domain in ("gmail", "outlook", "hotmail", "yahoo"):
        return None
    return domain


def classify_xls(
    filename: str,
    headers: Optional[List[str]] = None,
    sender_email: Optional[str] = None,
) -> XlsClassification:
    """Classify an XLS file. Returns `XlsClassification`.

    Rule order (highest confidence wins):
      1. Filename + header signal both match same classification → highest conf.
      2. Filename rule matches but no header signal → filename confidence.
      3. Header signal matches but filename doesn't → header confidence.
      4. Neither matches → not_inventory, confidence 0.0.
    """
    signals = []
    filename_match = None
    for rx, cls, intent, own, conf in _FILENAME_RULES:
        if rx.search(filename or ""):
            filename_match = (cls, conf)
            signals.append(f"filename:{rx.pattern}")
            break

    header_match = _header_signal_match(headers or [])
    if header_match:
        signals.append(f"headers:{','.join(header_match[2])}")

    # Decision
    if filename_match and header_match and filename_match[0] == header_match[0]:
        cls = filename_match[0]
        conf = min(1.0, filename_match[1] + 0.05)  # agreement bonus
    elif filename_match:
        cls, conf = filename_match
    elif header_match:
        cls, conf, _ = header_match
    else:
        return XlsClassification(
            classification="not_inventory",
            confidence=0.0,
            movement_intent=None,
            ownership_hint=None,
            signals=signals or ["no_match"],
            suggested_customer_hint=_sender_hint(sender_email),
        )

    return XlsClassification(
        classification=cls,
        confidence=round(conf, 2),
        movement_intent=_movement_intent_for(cls),
        ownership_hint=_ownership_hint_for(cls),
        signals=signals,
        suggested_customer_hint=_sender_hint(sender_email),
    )
