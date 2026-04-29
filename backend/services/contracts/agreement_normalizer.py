"""DocuSign envelope → Contract Intelligence row normalizer.

Pure function. No I/O, no DB, no network. Takes a DocuSign Connect "Send
Individual Messages" (SIM) JSON payload (or a poll-fetched envelope dict)
and returns the persistable Pydantic model objects + a list of warnings
that the orchestrator can promote into ``agreement_exceptions`` rows.

Why pure / why a single entry point?
    * Lets us unit-test against fixture JSON without spinning up Mongo.
    * Lets the webhook receiver stay tiny and the orchestrator focus on
      persistence + matching, not parsing.
    * Defensive: any missing field becomes a warning, never an exception.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.contracts import (
    Agreement,
    AgreementDocument,
    AgreementParty,
    AgreementPricing,
    AgreementTerm,
    AgreementStatus,
    PartyRole,
    PartySigningStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status / role mapping
# ---------------------------------------------------------------------------

_STATUS_MAP: Dict[str, AgreementStatus] = {
    "created": "drafted",
    "drafted": "drafted",
    "sent": "sent",
    "delivered": "delivered",
    "signed": "completed",
    "completed": "completed",
    "declined": "declined",
    "voided": "voided",
    "expired": "expired",
    "deleted": "voided",
}

_PARTY_SIGNING_STATUS_MAP: Dict[str, PartySigningStatus] = {
    "created": "created",
    "sent": "sent",
    "delivered": "delivered",
    "signed": "signed",
    "completed": "completed",
    "declined": "declined",
    "autoresponded": "auto_responded",
    "auto_responded": "auto_responded",
}

# DocuSign uses recipient list keys like "signers", "carbonCopies", etc.
# Map those to our PartyRole enum literals.
_RECIPIENT_LIST_KEYS: List[Tuple[str, PartyRole]] = [
    ("signers", "signer"),
    ("carbonCopies", "carbon_copy"),
    ("carbon_copies", "carbon_copy"),
    ("certifiedDeliveries", "certified_delivery"),
    ("certified_deliveries", "certified_delivery"),
    ("inPersonSigners", "in_person_signer"),
    ("in_person_signers", "in_person_signer"),
    ("agents", "agent"),
    ("editors", "editor"),
    ("intermediaries", "intermediary"),
    ("witnesses", "witness"),
]


def _norm(text: Optional[str]) -> Optional[str]:
    """Lowercase + collapse non-alphanum runs to spaces. Used for BC matching."""
    if not text:
        return None
    s = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return s or None


def _parse_dt(raw: Any) -> Optional[datetime]:
    """Parse DocuSign ISO 8601 strings, returning timezone-aware UTC datetime."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    # DocuSign emits "2026-04-29T19:00:00.0000000Z" — Python's fromisoformat
    # in 3.11+ handles the trailing Z but not the 7-digit microseconds.
    s = raw.strip().replace("Z", "+00:00")
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # truncate >6-digit micros
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _money(raw: Any) -> Optional[float]:
    """Parse a money-ish string ('1,234.50', '$25', '25 USD')."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _int(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class NormalizedAgreement:
    """Output of the normalizer. All rows already share the agreement.id link."""

    agreement: Agreement
    parties: List[AgreementParty] = field(default_factory=list)
    terms: List[AgreementTerm] = field(default_factory=list)
    pricing: List[AgreementPricing] = field(default_factory=list)
    documents: List[AgreementDocument] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_persistable_payload(self) -> Dict[str, Any]:
        """Helper for tests / logs. Not used in persistence path."""
        return {
            "agreement": self.agreement.model_dump(mode="json"),
            "parties": [p.model_dump(mode="json") for p in self.parties],
            "terms": [t.model_dump(mode="json") for t in self.terms],
            "pricing": [p.model_dump(mode="json") for p in self.pricing],
            "documents": [d.model_dump(mode="json") for d in self.documents],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalize_envelope(
    payload: Dict[str, Any],
    *,
    event_id: Optional[str] = None,
) -> NormalizedAgreement:
    """Convert a DocuSign Connect SIM payload (or polled envelope dict) into
    Contract Intelligence rows.

    Args:
        payload: One of:
          - Raw Connect SIM event ({"event": "...", "data": {"envelopeSummary": {...}}})
          - The envelope summary dict directly ({"envelopeId": "...", ...})
        event_id: Optional source event id, recorded on warnings for traceability.

    Returns:
        NormalizedAgreement with populated rows + warnings list.

    Raises:
        ValueError: only if `provider_envelope_id` cannot be resolved at all.
                    (Everything else degrades into a warning.)
    """
    if not isinstance(payload, dict):
        raise ValueError("normalizer expects a dict payload")

    envelope = _extract_envelope(payload)

    envelope_id = (
        envelope.get("envelopeId")
        or envelope.get("envelope_id")
        or payload.get("envelopeId")
    )
    if not envelope_id:
        raise ValueError("payload missing envelopeId")

    warnings: List[Dict[str, Any]] = []

    raw_status = (envelope.get("status") or envelope.get("envelopeStatus") or "").lower()
    status = _STATUS_MAP.get(raw_status, "unknown")
    if status == "unknown" and raw_status:
        warnings.append({
            "code": "unknown_envelope_status",
            "details": {"raw_status": raw_status},
            "event_id": event_id,
        })

    sender = envelope.get("sender") or {}
    sender_name = sender.get("userName") or sender.get("name")
    sender_email = sender.get("email")

    agreement = Agreement(
        provider="docusign",
        provider_envelope_id=str(envelope_id),
        provider_account_id=payload.get("data", {}).get("accountId")
            or envelope.get("accountId"),
        status=status,
        title=envelope.get("subject") or envelope.get("emailSubject"),
        subject=envelope.get("subject"),
        email_subject=envelope.get("emailSubject"),
        sender_name=sender_name,
        sender_email=sender_email if _looks_like_email(sender_email) else None,
        sent_at=_parse_dt(envelope.get("sentDateTime")),
        delivered_at=_parse_dt(envelope.get("deliveredDateTime")),
        completed_at=_parse_dt(envelope.get("completedDateTime")),
        declined_at=_parse_dt(envelope.get("declinedDateTime")),
        voided_at=_parse_dt(envelope.get("voidedDateTime")),
        expires_at=_parse_dt(
            envelope.get("expireDateTime") or envelope.get("expirationDateTime")
        ),
        last_event_id=event_id,
        last_normalized_at=datetime.now(timezone.utc),
    )

    # ---- Parties --------------------------------------------------------
    parties = _normalize_parties(agreement.id, envelope, warnings)

    # Add the sender as a synthetic party for matching purposes.
    if sender_name or sender_email:
        parties.append(
            AgreementParty(
                agreement_id=agreement.id,
                role="sender",
                name=sender_name,
                email=sender_email if _looks_like_email(sender_email) else None,
                organization=sender.get("companyName") or sender.get("company"),
                normalized_name=_norm(sender_name),
                normalized_org=_norm(sender.get("companyName") or sender.get("company")),
                signing_status="completed",  # the sender is implicitly "done"
            )
        )

    # ---- Custom fields → terms ------------------------------------------
    terms = _normalize_terms(agreement.id, envelope, warnings)

    # ---- Tab values → terms (additional) and pricing --------------------
    pricing = _normalize_pricing(agreement.id, envelope, warnings)
    terms.extend(_normalize_form_data_terms(agreement.id, envelope, warnings))

    # ---- Documents -------------------------------------------------------
    documents = _normalize_documents(agreement.id, envelope, warnings)

    # ---- Counts on the agreement row ------------------------------------
    agreement_with_counts = agreement.model_copy(update={
        "party_count": len(parties),
        "document_count": len(documents),
    })

    return NormalizedAgreement(
        agreement=agreement_with_counts,
        parties=parties,
        terms=terms,
        pricing=pricing,
        documents=documents,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _extract_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the envelope summary dict regardless of the wrapper level."""
    # Connect SIM JSON: payload['data']['envelopeSummary']
    data = payload.get("data") or {}
    if isinstance(data, dict):
        env = data.get("envelopeSummary") or data.get("envelope")
        if isinstance(env, dict):
            return env
    # Sometimes payload itself is the summary (poll path / direct fetch)
    if "envelopeId" in payload or "envelope_id" in payload:
        return payload
    # Or under top-level "envelopeSummary"
    env = payload.get("envelopeSummary") or payload.get("envelope")
    if isinstance(env, dict):
        return env
    return {}


def _looks_like_email(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and "@" in value
        and "." in value.split("@")[-1]
    )


def _normalize_parties(
    agreement_id: str,
    envelope: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> List[AgreementParty]:
    recipients = envelope.get("recipients") or {}
    out: List[AgreementParty] = []
    for key, role in _RECIPIENT_LIST_KEYS:
        items = recipients.get(key) or []
        if not isinstance(items, list):
            continue
        for r in items:
            if not isinstance(r, dict):
                continue
            email = r.get("email")
            email = email if _looks_like_email(email) else None
            raw_signing = (r.get("status") or "").lower()
            signing = _PARTY_SIGNING_STATUS_MAP.get(raw_signing, "unknown")
            org = r.get("companyName") or r.get("company")
            name = r.get("name")
            try:
                routing_order = _int(r.get("routingOrder"))
            except Exception:
                routing_order = None
            out.append(AgreementParty(
                agreement_id=agreement_id,
                role=role,
                routing_order=routing_order,
                name=name,
                email=email,
                organization=org,
                normalized_name=_norm(name),
                normalized_org=_norm(org),
                signing_status=signing,
                sent_at=_parse_dt(r.get("sentDateTime")),
                delivered_at=_parse_dt(r.get("deliveredDateTime")),
                signed_at=_parse_dt(r.get("signedDateTime")),
                declined_reason=r.get("declinedReason"),
                provider_recipient_id=r.get("recipientId"),
            ))
            if not email and role in ("signer", "carbon_copy"):
                warnings.append({
                    "code": "party_missing_email",
                    "details": {"role": role, "name": name},
                })
    return out


def _normalize_terms(
    agreement_id: str,
    envelope: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> List[AgreementTerm]:
    out: List[AgreementTerm] = []
    cf = envelope.get("customFields") or {}
    if not isinstance(cf, dict):
        return out
    for bucket in ("textCustomFields", "listCustomFields", "text_custom_fields", "list_custom_fields"):
        for fld in cf.get(bucket) or []:
            if not isinstance(fld, dict):
                continue
            name = fld.get("name")
            value = fld.get("value")
            if not name:
                continue
            out.append(AgreementTerm(
                agreement_id=agreement_id,
                term_key=str(name).strip(),
                term_value=str(value).strip() if value is not None else None,
                raw_value=str(value) if value is not None else None,
                source="custom_field",
                source_field_name=str(name),
                confidence=0.95,  # custom fields are author-curated
            ))
    return out


def _normalize_form_data_terms(
    agreement_id: str,
    envelope: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> List[AgreementTerm]:
    """DocuSign exposes tab values via 'formData' on completed envelopes."""
    out: List[AgreementTerm] = []
    form_data = envelope.get("formData") or envelope.get("form_data") or []
    if not isinstance(form_data, list):
        return out
    for entry in form_data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        value = entry.get("value")
        if not name:
            continue
        # Skip anything that looks like a pricing tab — those go to pricing,
        # not terms. The pricing path consumes everything matching `line_N_*`.
        if _PRICING_LINE_RE.match(str(name)):
            continue
        lname = str(name).lower()
        if any(p in lname for p in ("price", "qty", "quantity", "unit_cost",
                                     "total", "line_total", "amount")):
            continue
        out.append(AgreementTerm(
            agreement_id=agreement_id,
            term_key=str(name).strip(),
            term_value=str(value).strip() if value is not None else None,
            raw_value=str(value) if value is not None else None,
            source="form_data",
            source_field_name=str(name),
            confidence=0.85,
        ))
    return out


_PRICING_LINE_RE_DEFAULT = r"^line[_\-]?(\d+)[_\-]?(.+)$"


def _get_pricing_line_re() -> "re.Pattern[str]":
    """Return the compiled pricing-tab regex, env-overridable.

    Set ``CONTRACT_PRICING_TAB_REGEX`` to override the default
    ``line_N_<attr>`` convention. The regex MUST capture two groups:
    group 1 = line number (integer-castable), group 2 = attribute name.
    """
    raw = os.environ.get("CONTRACT_PRICING_TAB_REGEX", "").strip()
    pattern = raw or _PRICING_LINE_RE_DEFAULT
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        logger.warning(
            "Invalid CONTRACT_PRICING_TAB_REGEX=%r (%s); using default.",
            pattern, exc,
        )
        compiled = re.compile(_PRICING_LINE_RE_DEFAULT, re.IGNORECASE)
    if compiled.groups < 2:
        logger.warning(
            "CONTRACT_PRICING_TAB_REGEX must have >= 2 capture groups; "
            "using default."
        )
        compiled = re.compile(_PRICING_LINE_RE_DEFAULT, re.IGNORECASE)
    return compiled


_PRICING_LINE_RE = _get_pricing_line_re()


def _normalize_pricing(
    agreement_id: str,
    envelope: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> List[AgreementPricing]:
    """Extract pricing rows from `formData` tab values.

    Convention: tabs named like ``line_1_item``, ``line_1_qty``, ``line_1_price``,
    ``line_1_uom``, ``line_1_total``, ``line_1_description`` are bucketed by the
    line number prefix. This is a Phase 2 default — if your DocuSign templates
    use different tab names, the matcher will simply emit zero pricing rows
    and a warning per unparsed line.
    """
    out: List[AgreementPricing] = []
    form_data = envelope.get("formData") or envelope.get("form_data") or []
    if not isinstance(form_data, list):
        return out

    buckets: Dict[int, Dict[str, Any]] = {}
    for entry in form_data:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        m = _PRICING_LINE_RE.match(name)
        if not m:
            continue
        line_no = int(m.group(1))
        attr = m.group(2).lower().strip("_- ")
        value = entry.get("value")
        bucket = buckets.setdefault(line_no, {})
        bucket[attr] = value

    for line_no in sorted(buckets):
        b = buckets[line_no]
        item_label = b.get("item") or b.get("item_label") or b.get("sku") or b.get("part")
        description = b.get("description") or b.get("desc")
        qty = _money(b.get("qty") or b.get("quantity"))
        unit_price = _money(b.get("price") or b.get("unit_price") or b.get("unit_cost"))
        line_total = _money(b.get("total") or b.get("line_total") or b.get("amount"))
        uom = b.get("uom") or b.get("unit") or None
        currency = b.get("currency") or None
        confidence = 0.9 if (item_label and (unit_price is not None or qty is not None)) else 0.5

        out.append(AgreementPricing(
            agreement_id=agreement_id,
            line_no=line_no,
            item_label=str(item_label).strip() if item_label else None,
            description=str(description).strip() if description else None,
            quantity=qty,
            uom=str(uom).strip() if uom else None,
            unit_price=unit_price,
            line_total=line_total,
            currency=str(currency).strip() if currency else None,
            source="tab",
            confidence=confidence,
        ))
        if not item_label:
            warnings.append({
                "code": "pricing_missing_item",
                "details": {"line_no": line_no},
            })
    return out


def _normalize_documents(
    agreement_id: str,
    envelope: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> List[AgreementDocument]:
    out: List[AgreementDocument] = []
    docs = (
        envelope.get("envelopeDocuments")
        or envelope.get("documents")
        or envelope.get("envelope_documents")
        or []
    )
    if not isinstance(docs, list):
        return out
    for d in docs:
        if not isinstance(d, dict):
            continue
        doc_id = d.get("documentId") or d.get("document_id") or d.get("id")
        if not doc_id:
            continue
        out.append(AgreementDocument(
            agreement_id=agreement_id,
            provider_document_id=str(doc_id),
            name=d.get("name") or d.get("documentName"),
            mime_type=d.get("mimeType") or d.get("type"),
            page_count=_int(d.get("pages") or d.get("pageCount")),
            size_bytes=_int(d.get("size") or d.get("sizeBytes")),
        ))
    return out
