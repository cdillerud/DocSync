"""DocuSign Navigator AI Metadata Export → Contract Intelligence normalizer.

The Navigator export is a flat, spreadsheet-style row (one agreement per
row, ~54 human-readable columns such as ``"Envelope Id"``, ``"Agreement
Type"``, ``"Parties"``, ``"Payment Term"``). It is *not* a DocuSign
Connect SIM event payload, and the existing
``agreement_normalizer.normalize_envelope`` function was written against
the Connect shape.

This adapter bridges the two shapes:
  1. Accept a Navigator row dict (optionally wrapped in an
     ``{"__source__": "...", "row": {...}}`` envelope as shipped in
     fixture JSON).
  2. Translate each Navigator column into the equivalent Connect SIM
     field (recipients, customFields, envelopeSummary timestamps, etc.).
  3. Hand the synthesized Connect-shape payload back to the existing
     ``normalize_envelope`` pipeline — so Navigator imports and live
     Connect webhooks produce the same canonical
     ``NormalizedAgreement`` output.

Phase 4A scope:
  * Pure transformation — no I/O, no DB, no network.
  * No DocuSign writes; read-only historical backfill.
  * Every field that maps cleanly becomes a term / party / document.
  * Fields the schema cannot hold today are recorded on the returned
    ``warnings`` list (e.g. ``"schema_gap"`` codes) so operators can see
    what was dropped without the import silently swallowing data.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.contracts import AgreementStatus

# ---------------------------------------------------------------------------
# Column → canonical mappings
# ---------------------------------------------------------------------------

# Navigator column → Connect SIM custom-field name (goes to AgreementTerm).
# Every value here is rendered as a textCustomField so the downstream
# normalizer treats it with source="custom_field" / confidence=0.95.
_NAVIGATOR_TERM_COLUMNS: Dict[str, str] = {
    "Agreement Type": "agreement_type",
    "Agreement ID": "agreement_id_number",        # internal QUO-... number
    "Governing Law": "governing_law",
    "Jurisdiction": "jurisdiction",
    "Languages": "languages",
    "Payment Term": "payment_term",
    "Price Cap Increase %": "price_cap_increase_pct",
    "Renewal Type": "renewal_type",
    "Renewal Notice Date": "renewal_notice_date",
    "Renewal Owner": "renewal_owner",
    "Assignment (Change of Control)": "assignment_change_of_control",
    "Assignment (General)": "assignment_general",
    "Assignment (Termination Rights)": "assignment_termination_rights",
    "NDA Type": "nda_type",
    "Sets": "sets",
    "Shortfall": "shortfall",
    "Effective Date": "effective_date",
    "Execution Date": "execution_date",
    "Expiration Date": "expiration_date",
}

# Columns that pair a numeric value with a unit column ("3" + "Years").
# Rendered as a single concatenated term ("3 Years").
_NAVIGATOR_QUANTITY_UNIT_PAIRS: List[Dict[str, str]] = [
    {"value": "Initial Term Length", "unit": "Initial Term Length Unit",
     "term": "initial_term_length"},
    {"value": "Renewal Term", "unit": "Renewal Term Unit",
     "term": "renewal_term"},
    {"value": "Extension Period", "unit": "Extension Period Unit",
     "term": "extension_period"},
    {"value": "Renewal Notice Period", "unit": "Renewal Notice Period Unit",
     "term": "renewal_notice_period"},
    {"value": "Confidentiality Duration", "unit": "Confidentiality Duration Unit",
     "term": "confidentiality_duration"},
    {"value": "Liability Cap Amount", "unit": "Liability Cap Amount Unit",
     "term": "liability_cap_amount"},
    {"value": "Liability Cap Duration", "unit": "Liability Cap Duration Unit",
     "term": "liability_cap_duration"},
    {"value": "Liability Cap Multiplier", "unit": "Liability Cap Multiplier Unit",
     "term": "liability_cap_multiplier"},
    {"value": "Annual Contract Value", "unit": "Annual Contract Value Unit",
     "term": "annual_contract_value"},
    {"value": "Total Contract Value", "unit": "Total Contract Value Unit",
     "term": "total_contract_value"},
    {"value": "Termination for Cause - Notice Period",
     "unit": "Termination for Cause - Notice Period Unit",
     "term": "termination_for_cause_notice_period"},
    {"value": "Termination for Convenience - Notice Period",
     "unit": "Termination for Convenience - Notice Period Unit",
     "term": "termination_for_convenience_notice_period"},
    {"value": "Late Fee %", "unit": "Late Fees Apply",
     "term": "late_fee_pct"},
]

# Navigator "Status" string → our AgreementStatus literal.
_NAVIGATOR_STATUS_MAP: Dict[str, AgreementStatus] = {
    "active": "completed",
    "completed": "completed",
    "signed": "completed",
    "executed": "completed",
    "in progress": "sent",
    "sent": "sent",
    "pending": "sent",
    "delivered": "delivered",
    "draft": "drafted",
    "drafted": "drafted",
    "declined": "declined",
    "voided": "voided",
    "expired": "expired",
}

# Navigator DOES NOT emit timestamps, only dates. Treat dates as UTC
# midnight for scheduling/filter math — this matches what the existing
# Connect path does when only a date is available.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date_to_utc_iso(raw: Any) -> Optional[str]:
    """Turn a 'YYYY-MM-DD' (or ISO-like) into a Connect-SIM ISO string."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    s = str(raw).strip()
    if not s:
        return None
    if _DATE_RE.match(s):
        return f"{s}T00:00:00Z"
    # Pass through anything already ISO-ish — normalize_envelope will parse it.
    return s


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _unwrap_row(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Accept either a raw row dict or a fixture-style wrapper with 'row'."""
    if isinstance(payload.get("row"), dict):
        return payload["row"]
    return payload


def _split_parties(raw: Any) -> List[str]:
    """Split the ``Parties`` column on ``;`` / ``|``, trimming whitespace."""
    if not raw:
        return []
    parts = re.split(r"[;|]+", str(raw))
    return [p.strip() for p in parts if p and p.strip()]


# ---------------------------------------------------------------------------
# Connect-SIM synthesis
# ---------------------------------------------------------------------------

def build_connect_sim_payload(
    row: Dict[str, Any],
    *,
    event_id: Optional[str] = None,
    warnings_sink: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Translate a Navigator row into a Connect-SIM envelope payload.

    The returned dict is shaped like a DocuSign Connect
    ``envelope-completed`` event so it can be handed to the existing
    ``agreement_normalizer.normalize_envelope``.
    """
    row = _unwrap_row(row)
    warnings_sink = warnings_sink if warnings_sink is not None else []

    envelope_id = _clean(row.get("Envelope Id") or row.get("envelopeId"))
    if not envelope_id:
        raise ValueError(
            "Navigator row missing 'Envelope Id' — cannot synthesize envelope"
        )

    agreement_uuid = _clean(row.get("Agreement Id") or row.get("agreementId"))
    title = _clean(row.get("Title") or row.get("File Name"))
    raw_status = (row.get("Status") or "").strip().lower()
    mapped_status = _NAVIGATOR_STATUS_MAP.get(raw_status)
    if raw_status and not mapped_status:
        warnings_sink.append({
            "code": "navigator_unknown_status",
            "details": {"raw_status": raw_status},
            "event_id": event_id,
        })
        mapped_status = "unknown"

    exec_dt = _parse_date_to_utc_iso(row.get("Execution Date"))
    effective_dt = _parse_date_to_utc_iso(row.get("Effective Date"))
    expiration_dt = _parse_date_to_utc_iso(row.get("Expiration Date"))

    # ---- Parties --------------------------------------------------------
    # Navigator only reliably carries the Customer Name column and the
    # concatenated "Parties" column. Convert each party-org into a signer
    # stub so the BC matcher has something to work against. We do not
    # synthesize emails — the adapter leaves those null so the Connect
    # normalizer's "party_missing_email" warning fires honestly for
    # Navigator-only ingests.
    orgs_ordered: List[str] = []
    seen_orgs: Dict[str, None] = {}
    for name in _split_parties(row.get("Parties")):
        if name.lower() not in seen_orgs:
            seen_orgs[name.lower()] = None
            orgs_ordered.append(name)
    customer_name = _clean(row.get("Customer Name"))
    if customer_name and customer_name.lower() not in seen_orgs:
        seen_orgs[customer_name.lower()] = None
        orgs_ordered.append(customer_name)

    signers = []
    for idx, org in enumerate(orgs_ordered, start=1):
        signers.append({
            "recipientId": str(idx),
            "name": None,
            "email": None,
            "companyName": org,
            "status": "completed" if mapped_status == "completed" else "sent",
            "routingOrder": str(idx),
            # Best-effort: the execution date is the only signing timestamp
            # Navigator surfaces. Use it for every signer; tests that rely
            # on per-signer timestamps should use the Connect path.
            "signedDateTime": exec_dt if mapped_status == "completed" else None,
        })

    # Sender is NOT exposed by Navigator. The Connect-path helpers that
    # synthesize a sender party gracefully skip when both name + email are
    # missing, so we simply omit the sender block.
    sender_block: Dict[str, Any] = {}

    # ---- Custom fields --------------------------------------------------
    text_custom_fields: List[Dict[str, Any]] = []

    def _add_term(term_key: str, value: Any) -> None:
        v = _clean(value)
        if not v:
            return
        text_custom_fields.append({"name": term_key, "value": v})

    # 1:1 column → term mappings.
    for col, term_key in _NAVIGATOR_TERM_COLUMNS.items():
        _add_term(term_key, row.get(col))

    # Paired value + unit columns render as "value unit".
    for pair in _NAVIGATOR_QUANTITY_UNIT_PAIRS:
        value = _clean(row.get(pair["value"]))
        if not value:
            continue
        unit = _clean(row.get(pair["unit"]))
        if unit:
            _add_term(pair["term"], f"{value} {unit}")
        else:
            _add_term(pair["term"], value)

    # Navigator UUID is a first-class Agreement field post-Phase-4A.
    # Emit it both as an envelope summary hint and as a custom field so
    # whichever side the downstream reader checks first sees it.
    envelope_extras: Dict[str, Any] = {}
    if agreement_uuid:
        envelope_extras["providerAgreementId"] = agreement_uuid
        _add_term("provider_agreement_id", agreement_uuid)

    # ---- Documents ------------------------------------------------------
    file_name = _clean(row.get("File Name"))
    documents: List[Dict[str, Any]] = []
    if file_name:
        documents.append({
            "documentId": "1",
            "name": file_name,
            "type": "content",
            # Navigator does not expose page count / size — omitted.
        })

    # ---- Flag any Navigator-only schema gaps discovered at row level ----
    # Pricing is never in Navigator; no line-level data to emit.
    if any(row.get(k) for k in (
        "Line 1 Item", "Line 1 Price", "Pricing", "SKU",
    )):
        warnings_sink.append({
            "code": "schema_gap",
            "details": {
                "reason": "Navigator row contained pricing-like columns but "
                          "the adapter does not map them — Navigator AI "
                          "export does not carry line-level pricing.",
            },
            "event_id": event_id,
        })

    summary = {
        "envelopeId": envelope_id,
        "status": mapped_status or "unknown",
        "subject": title,
        "emailSubject": title,
        "completedDateTime": exec_dt if mapped_status == "completed" else None,
        "sentDateTime": None,
        "deliveredDateTime": None,
        "expireDateTime": expiration_dt,
        "createdDateTime": effective_dt,
        "sender": sender_block,
        "recipients": {"signers": signers, "carbonCopies": []},
        "envelopeDocuments": documents,
        "customFields": {"textCustomFields": text_custom_fields},
        "formData": [],
    }
    summary.update(envelope_extras)

    return {
        "event": "envelope-completed" if mapped_status == "completed"
                 else "envelope-synced-from-navigator",
        "eventId": event_id or f"navigator::{envelope_id}",
        "data": {
            "accountId": None,
            "userId": None,
            "envelopeId": envelope_id,
            "envelopeSummary": summary,
        },
        "__navigator_source__": True,
    }


def normalize_navigator_row(
    payload: Dict[str, Any],
    *,
    event_id: Optional[str] = None,
):
    """Entry point: Navigator row → ``NormalizedAgreement``.

    Imports :func:`normalize_envelope` lazily so this module stays
    import-cycle-safe (``agreement_normalizer`` imports us, too, when it
    detects a Navigator-shaped payload).
    """
    # Local import breaks the cycle: agreement_normalizer → this module → back.
    from services.contracts.agreement_normalizer import normalize_envelope

    extra_warnings: List[Dict[str, Any]] = []
    sim_payload = build_connect_sim_payload(
        payload, event_id=event_id, warnings_sink=extra_warnings,
    )
    result = normalize_envelope(sim_payload, event_id=event_id)
    # Tag warnings surfaced purely by the adapter so downstream tooling
    # can distinguish "Navigator couldn't carry this" from Connect-path
    # warnings.
    for w in extra_warnings:
        w.setdefault("source", "navigator_adapter")
        result.warnings.append(w)
    # Annotate the agreement with its ingest provenance. The field does
    # not exist on the model — we stash it on last_event_id prefix only
    # when the caller didn't provide one, keeping the schema untouched.
    if result.agreement.last_event_id is None:
        envelope_id = sim_payload["data"]["envelopeId"]
        result = _with_event_id(result, f"navigator::{envelope_id}")
    return result


def _with_event_id(result, event_id: str):
    """Return a copy of ``result`` with ``agreement.last_event_id`` set."""
    agreement = result.agreement.model_copy(update={"last_event_id": event_id})
    # NormalizedAgreement is a dataclass; rebuild with the updated agreement.
    from services.contracts.agreement_normalizer import NormalizedAgreement
    return NormalizedAgreement(
        agreement=agreement,
        parties=result.parties,
        terms=result.terms,
        pricing=result.pricing,
        documents=result.documents,
        warnings=result.warnings,
    )
