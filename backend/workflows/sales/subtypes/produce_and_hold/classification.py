"""
GPI Hub — Produce & Hold classifier (Lane C Step 4)

Pure, rule-based classifier that inspects a sales-document's extracted
fields for structural evidence of a Produce & Hold workflow. Orthogonal
to the DS vs WH classifier in services/document_intel_helpers.py — a
document can be WH *and* PH, or neither.

This module is UNWIRED. Nothing in the ingestion pipeline calls
``classify_produce_and_hold`` in this PR. It is exercised only by its
own pytest.

Signal weights and thresholds are constants at module scope so they can
be tightened later without changing the public surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple

# Threshold at which we declare the doc is PH. Tuned against the signal
# weights below so that any single strong positive signal clears it.
PH_CONFIDENCE_THRESHOLD: float = 0.5

# Blanket-match divergence tolerance (signed declaration §5: 5%).
PH_BLANKET_DIVERGENCE_FRACTION: float = 0.05

# Aging threshold for held inventory in days (signed declaration §5: 90).
PH_AGING_THRESHOLD_DAYS: int = 90

# Known PH customers — INTENTIONALLY EMPTY per user sign-off. The hook
# is preserved so canonical reference data can be added later without
# redesigning the classifier. When populated, each entry is a customer_no
# string (exact match, case-insensitive).
KNOWN_PH_CUSTOMERS: Tuple[str, ...] = ()

# Signal weights. Positive signals push toward PH; negative subtract.
_W_ORDER_TYPE_BLANKET: float = 0.6
_W_HOLD_FIELD_PRESENT: float = 0.5
_W_BLANKET_KEYWORD: float = 0.4
_W_PRODUCE_AND_HOLD_KEYWORD: float = 0.7
_W_KNOWN_CUSTOMER: float = 0.5
_W_DROP_SHIP_KEYWORD: float = -0.8
_W_DROP_SHIP_LOCATION: float = -0.7
_W_SHORT_LEAD_TIME: float = -0.3

# Textual markers (lowercase comparisons).
_HOLD_FIELDS: Tuple[str, ...] = (
    "hold_until", "release_schedule", "call_off_date", "call_off_schedule",
    "scheduled_release", "release_dates",
)
_BLANKET_KEYWORDS: Tuple[str, ...] = (
    "blanket order", "blanket po", "blanket sales order", "blanket-order",
)
_PH_KEYWORDS: Tuple[str, ...] = (
    "produce and hold", "produce & hold", "produce-and-hold", "p&h",
    "produce to stock", "hold until called", "hold for release",
)
_DROP_SHIP_KEYWORDS: Tuple[str, ...] = (
    "drop ship", "dropship", "drop-ship", "direct ship", "ship direct",
)
# Location codes that unambiguously indicate drop-ship (not held in Gamer inventory).
_DROP_SHIP_LOCATION_CODES: Tuple[str, ...] = ("00", "001")


@dataclass(frozen=True)
class PHClassification:
    """Classifier output.

    ``confidence`` is a clamped [0, 1] value. ``signals`` enumerates the
    positive and negative signals that fired, in declaration order. When
    no signal fires, returns the sentinel below.
    """
    is_produce_and_hold: bool
    confidence: float
    signals: Tuple[str, ...]
    reasons: Tuple[str, ...]


_EMPTY = PHClassification(
    is_produce_and_hold=False,
    confidence=0.0,
    signals=(),
    reasons=("no signals found",),
)


def _collect_text(doc: Mapping[str, Any], ef: Mapping[str, Any]) -> str:
    parts = [
        doc.get("raw_text") or "",
        doc.get("ocr_text") or "",
        ef.get("description") or "",
        ef.get("notes") or "",
        ef.get("special_instructions") or "",
        ef.get("remarks") or "",
    ]
    return " ".join(str(p) for p in parts).lower()


def _extract_customer_no(doc: Mapping[str, Any], ef: Mapping[str, Any]) -> str:
    for key in ("customer_no", "customer_number", "bill_to_customer_no"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip().upper()
    return ""


def _lead_time_days(ef: Mapping[str, Any]) -> int | None:
    """Best-effort lead-time in days, if a ship-date-requested field is set.

    Returns None when no usable date is present. We intentionally avoid
    pulling in dateutil or implementing calendar math here — the negative
    signal's value is only to nudge away from PH when lead time is very
    short. If parsing fails we return None (signal does not fire).
    """
    from datetime import date, datetime, timezone as _tz

    raw = ef.get("ship_date_requested") or ef.get("requested_ship_date")
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s[: len(fmt) + 8], fmt)
            today = datetime.now(_tz.utc).date()
            return (dt.date() - today).days
        except ValueError:
            continue
    try:
        # ISO fallback.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        today = datetime.now(_tz.utc).date()
        d = dt.date() if isinstance(dt, datetime) else dt
        return (d - today).days if isinstance(d, date) else None
    except (ValueError, TypeError):
        return None


def classify_produce_and_hold(
    doc: Mapping[str, Any], extracted_fields: Mapping[str, Any],
) -> PHClassification:
    """Classify a sales document. Pure; no I/O; no DB; no mutation.

    Returns the ``_EMPTY`` sentinel when nothing triggers. Otherwise
    returns a ``PHClassification`` where ``is_produce_and_hold`` reflects
    ``confidence >= PH_CONFIDENCE_THRESHOLD``.
    """
    doc = doc or {}
    ef = extracted_fields or {}

    signals: list[str] = []
    reasons: list[str] = []
    score = 0.0

    text = _collect_text(doc, ef)

    # --- Positive signals -----------------------------------------------
    order_type = (ef.get("order_type") or doc.get("order_type") or "").strip().lower()
    if order_type == "blanket":
        score += _W_ORDER_TYPE_BLANKET
        signals.append("order_type_blanket")
        reasons.append("order_type field == 'blanket'")

    present_hold_fields = [k for k in _HOLD_FIELDS if ef.get(k) or doc.get(k)]
    if present_hold_fields:
        score += _W_HOLD_FIELD_PRESENT
        signals.append("hold_field_present")
        reasons.append(f"hold-scheduling field present: {present_hold_fields[0]}")

    matched_blanket = next((kw for kw in _BLANKET_KEYWORDS if kw in text), None)
    if matched_blanket:
        score += _W_BLANKET_KEYWORD
        signals.append("blanket_keyword")
        reasons.append(f"blanket-order keyword in text: '{matched_blanket}'")

    matched_ph = next((kw for kw in _PH_KEYWORDS if kw in text), None)
    if matched_ph:
        score += _W_PRODUCE_AND_HOLD_KEYWORD
        signals.append("produce_and_hold_keyword")
        reasons.append(f"PH keyword in text: '{matched_ph}'")

    customer_no = _extract_customer_no(doc, ef)
    if customer_no and any(customer_no == c.upper() for c in KNOWN_PH_CUSTOMERS):
        score += _W_KNOWN_CUSTOMER
        signals.append("known_ph_customer")
        reasons.append(f"customer {customer_no} is on the KNOWN_PH_CUSTOMERS seed")

    # --- Negative signals -----------------------------------------------
    matched_ds = next((kw for kw in _DROP_SHIP_KEYWORDS if kw in text), None)
    if matched_ds:
        score += _W_DROP_SHIP_KEYWORD
        signals.append("drop_ship_keyword")
        reasons.append(f"drop-ship keyword in text: '{matched_ds}'")

    loc = (ef.get("ship_to_location_code") or ef.get("location_code") or "").strip()
    if loc and loc in _DROP_SHIP_LOCATION_CODES:
        score += _W_DROP_SHIP_LOCATION
        signals.append("drop_ship_location")
        reasons.append(f"location_code '{loc}' is a drop-ship code")

    lead = _lead_time_days(ef)
    if lead is not None and 0 <= lead < 7:
        score += _W_SHORT_LEAD_TIME
        signals.append("short_lead_time")
        reasons.append(f"requested ship in {lead} day(s) — too short to produce")

    if not signals:
        return _EMPTY

    confidence = max(0.0, min(1.0, score))
    return PHClassification(
        is_produce_and_hold=confidence >= PH_CONFIDENCE_THRESHOLD,
        confidence=confidence,
        signals=tuple(signals),
        reasons=tuple(reasons),
    )


__all__ = [
    "PHClassification",
    "PH_CONFIDENCE_THRESHOLD",
    "PH_BLANKET_DIVERGENCE_FRACTION",
    "PH_AGING_THRESHOLD_DAYS",
    "KNOWN_PH_CUSTOMERS",
    "classify_produce_and_hold",
]
