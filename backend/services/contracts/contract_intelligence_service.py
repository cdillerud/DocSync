"""Contract Intelligence orchestrator.

Glues the normalizer + matcher + persistence + audit log together. Called
from:
    * the webhook receiver (after a fresh event is durably persisted)
    * future poll/backfill jobs (Phase 2.x)
    * the manual "reprocess" endpoint (Phase 3)

Idempotency contract:
    Webhook-level idempotency lives at the storage layer (unique index on
    (provider, provider_event_id) in agreement_events). Re-running the
    orchestrator for the SAME event id is a no-op once `processed=True`.
    Re-running for a DIFFERENT event on the same envelope updates the
    agreement state additively — auto-generated links are refreshed
    (linked_by='system' AND status in {proposed, auto_confirmed} get
    replaced); manually-confirmed/-rejected links are preserved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from models.contracts import (
    CONTRACTS_COLLECTIONS,
    AgreementBCLink,
    AgreementException,
    AgreementMatchAudit,
    ExceptionCode,
)
from services.contracts.agreement_normalizer import (
    NormalizedAgreement,
    normalize_envelope,
)
from services.contracts.bc_agreement_matcher import (
    BCAgreementMatcher,
    BCLookupRepository,
    InMemoryBCRepository,
    MatchResult,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractIntelligenceService:
    """Orchestrates persistence of normalized agreement state."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        repo: Optional[BCLookupRepository] = None,
    ) -> None:
        self.db = db
        self.matcher = BCAgreementMatcher(repo or InMemoryBCRepository())

    # --- Event ingestion -------------------------------------------------

    async def record_event(
        self,
        *,
        provider_event_id: str,
        provider_envelope_id: Optional[str],
        event_type: str,
        raw_payload: Dict[str, Any],
        hmac_valid: bool,
        transport: str = "webhook",
    ) -> Dict[str, Any]:
        """Insert the raw event row. Returns ``{duplicate: bool, event_id: str}``.

        Relies on the ``uniq_provider_event`` unique index for idempotency.
        Duplicate keys do NOT raise — they return ``duplicate=True``.
        """
        from pymongo.errors import DuplicateKeyError

        coll = self.db[CONTRACTS_COLLECTIONS["agreement_events"]]
        doc = {
            "id": _new_id(),
            "provider": "docusign",
            "provider_event_id": provider_event_id,
            "provider_envelope_id": provider_envelope_id,
            "event_type": event_type,
            "received_at": _utc_now(),
            "hmac_valid": hmac_valid,
            "transport": transport,
            "raw_payload": raw_payload,
            "processed": False,
            "processed_at": None,
            "error": None,
        }
        try:
            await coll.insert_one(doc)
        except DuplicateKeyError:
            existing = await coll.find_one(
                {"provider": "docusign", "provider_event_id": provider_event_id},
                {"_id": 0, "id": 1},
            )
            return {"duplicate": True, "event_id": (existing or {}).get("id")}
        return {"duplicate": False, "event_id": doc["id"]}

    # --- Normalization + matching + persistence --------------------------

    async def process_event(self, event_id: str) -> Dict[str, Any]:
        """Process a previously-recorded event. Idempotent."""
        events = self.db[CONTRACTS_COLLECTIONS["agreement_events"]]
        evt = await events.find_one({"id": event_id}, {"_id": 0})
        if not evt:
            return {"status": "not_found", "event_id": event_id}
        if evt.get("processed"):
            return {"status": "already_processed", "event_id": event_id}

        try:
            normalized = normalize_envelope(
                evt["raw_payload"],
                event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            await events.update_one(
                {"id": event_id},
                {"$set": {
                    "processed": True,
                    "processed_at": _utc_now(),
                    "error": f"normalizer_failed: {exc}",
                }},
            )
            await self._insert_exception(AgreementException(
                agreement_id="(unbound)",
                code="normalization_failed",
                severity="high",
                details={"error": str(exc), "event_id": event_id},
                related_event_id=event_id,
            ))
            return {"status": "normalizer_failed", "event_id": event_id, "error": str(exc)}

        agreement_id = await self._upsert_agreement(normalized, evt)
        await self._upsert_parties(normalized)
        await self._upsert_terms(normalized)
        await self._upsert_pricing(normalized)
        await self._upsert_documents(normalized)

        match_result = await self.matcher.match(
            agreement_id=agreement_id,
            parties=normalized.parties,
            pricing=normalized.pricing,
        )
        await self._persist_match_result(agreement_id, match_result)
        await self._persist_warnings(agreement_id, normalized.warnings, event_id)

        await events.update_one(
            {"id": event_id},
            {"$set": {
                "processed": True,
                "processed_at": _utc_now(),
                "agreement_id": agreement_id,
                "error": None,
            }},
        )
        return {
            "status": "ok",
            "event_id": event_id,
            "agreement_id": agreement_id,
            "links": len(match_result.links),
            "exceptions": len(match_result.exceptions),
            "warnings": len(normalized.warnings),
        }

    # --- Persistence helpers --------------------------------------------

    async def _upsert_agreement(
        self,
        normalized: NormalizedAgreement,
        event: Dict[str, Any],
    ) -> str:
        coll = self.db[CONTRACTS_COLLECTIONS["agreements"]]
        envelope_id = normalized.agreement.provider_envelope_id

        existing = await coll.find_one(
            {"provider_envelope_id": envelope_id},
            {"_id": 0, "id": 1, "created_at": 1},
        )
        agreement_doc = normalized.agreement.model_dump(mode="json")
        agreement_doc["updated_at"] = _utc_now().isoformat()

        if existing:
            agreement_doc["id"] = existing["id"]
            agreement_doc["created_at"] = existing.get("created_at",
                                                       agreement_doc["created_at"])
            await coll.update_one(
                {"provider_envelope_id": envelope_id},
                {"$set": {k: v for k, v in agreement_doc.items() if k != "id"}},
            )
            await self._audit(
                agreement_id=existing["id"],
                action="agreement_status_changed",
                after={"status": agreement_doc["status"]},
                notes=f"event={event.get('event_type')}",
            )
            return existing["id"]

        await coll.insert_one(agreement_doc)
        await self._audit(
            agreement_id=agreement_doc["id"],
            action="agreement_normalized",
            after={"status": agreement_doc["status"], "envelope": envelope_id},
            notes=f"event={event.get('event_type')}",
        )
        # Rewrite agreement_id on every child row to the persisted id
        # (already aligned via Pydantic field default, but defensive):
        for child in (
            normalized.parties + normalized.terms +
            normalized.pricing + normalized.documents
        ):
            child.agreement_id = agreement_doc["id"]
        return agreement_doc["id"]

    async def _upsert_parties(self, normalized: NormalizedAgreement) -> None:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_parties"]]
        for p in normalized.parties:
            doc = p.model_dump(mode="json")
            doc["updated_at"] = _utc_now().isoformat()
            # Stable key: (agreement_id, role, email, provider_recipient_id)
            filt = {
                "agreement_id": p.agreement_id,
                "role": p.role,
                "email": p.email,
                "provider_recipient_id": p.provider_recipient_id,
            }
            await coll.update_one(filt, {"$set": doc, "$setOnInsert": {
                "id": doc["id"],
                "created_at": doc["created_at"],
            }}, upsert=True)

    async def _upsert_terms(self, normalized: NormalizedAgreement) -> None:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_terms"]]
        for t in normalized.terms:
            doc = t.model_dump(mode="json")
            filt = {"agreement_id": t.agreement_id, "term_key": t.term_key,
                    "source": t.source}
            await coll.update_one(
                filt,
                {"$set": doc, "$setOnInsert": {"id": doc["id"]}},
                upsert=True,
            )

    async def _upsert_pricing(self, normalized: NormalizedAgreement) -> None:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_pricing"]]
        for p in normalized.pricing:
            doc = p.model_dump(mode="json")
            filt = {"agreement_id": p.agreement_id, "line_no": p.line_no}
            await coll.update_one(
                filt,
                {"$set": doc, "$setOnInsert": {"id": doc["id"], "created_at": doc["created_at"]}},
                upsert=True,
            )

    async def _upsert_documents(self, normalized: NormalizedAgreement) -> None:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_documents"]]
        for d in normalized.documents:
            doc = d.model_dump(mode="json")
            filt = {
                "agreement_id": d.agreement_id,
                "provider_document_id": d.provider_document_id,
            }
            await coll.update_one(
                filt,
                {"$set": doc, "$setOnInsert": {"id": doc["id"], "created_at": doc["created_at"]}},
                upsert=True,
            )

    async def _persist_match_result(
        self, agreement_id: str, result: MatchResult,
    ) -> None:
        links_coll = self.db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
        ex_coll = self.db[CONTRACTS_COLLECTIONS["agreement_exceptions"]]

        # Strategy: only auto-generated, NOT-yet-confirmed links are refreshed.
        # Manually-confirmed or rejected links survive replays untouched.
        await links_coll.delete_many({
            "agreement_id": agreement_id,
            "linked_by": "system",
            "status": {"$in": ["proposed", "auto_confirmed"]},
        })
        for link in result.links:
            doc = link.model_dump(mode="json")
            await links_coll.insert_one(doc)
            await self._audit(
                agreement_id=agreement_id,
                action="proposed_link" if link.status == "proposed" else "confirmed_link",
                link_id=link.id,
                after={
                    "link_type": link.link_type,
                    "bc_no": link.bc_no,
                    "confidence": link.confidence,
                    "status": link.status,
                },
                actor="system",
            )

        # Exceptions: only auto-emitted open ones are refreshed; user-resolved
        # rows survive unchanged.
        await ex_coll.delete_many({
            "agreement_id": agreement_id,
            "status": "open",
        })
        for ex in result.exceptions:
            doc = ex.model_dump(mode="json")
            await ex_coll.insert_one(doc)
            await self._audit(
                agreement_id=agreement_id,
                action="exception_opened",
                exception_id=ex.id,
                after={
                    "code": ex.code,
                    "severity": ex.severity,
                    "details": ex.details,
                },
                actor="system",
            )

        # Maintain agreement.has_unmatched_exceptions snapshot.
        agr_coll = self.db[CONTRACTS_COLLECTIONS["agreements"]]
        await agr_coll.update_one(
            {"id": agreement_id},
            {"$set": {
                "has_unmatched_exceptions": bool(result.exceptions),
                "updated_at": _utc_now().isoformat(),
            }},
        )

    async def _persist_warnings(
        self,
        agreement_id: str,
        warnings: list,
        event_id: str,
    ) -> None:
        if not warnings:
            return
        ex_coll = self.db[CONTRACTS_COLLECTIONS["agreement_exceptions"]]
        for w in warnings:
            code = w.get("code") or "other"
            mapped: ExceptionCode = code if code in {
                "party_unmatched", "item_unmatched", "term_missing",
                "pricing_unparsable", "duplicate_envelope", "missing_envelope",
                "hmac_invalid", "normalization_failed", "other",
            } else "other"  # type: ignore
            await ex_coll.insert_one(AgreementException(
                agreement_id=agreement_id,
                code=mapped,  # type: ignore[arg-type]
                severity="low",
                details=w.get("details") or {"raw": w},
                related_event_id=event_id,
            ).model_dump(mode="json"))

    # --- Manual mapping endpoints (called from router) -------------------

    async def manual_link(
        self,
        *,
        agreement_id: str,
        link_type: str,
        bc_entity: str,
        bc_no: str,
        bc_name_snapshot: Optional[str],
        actor: str,
        notes: Optional[str] = None,
    ) -> AgreementBCLink:
        link = AgreementBCLink(
            agreement_id=agreement_id,
            link_type=link_type,  # type: ignore[arg-type]
            bc_entity=bc_entity,
            bc_no=bc_no,
            bc_name_snapshot=bc_name_snapshot,
            match_method="manual",
            confidence=1.0,
            status="confirmed",
            linked_by=actor,
            confirmed_by=actor,
            confirmed_at=_utc_now(),
            notes=notes,
        )
        await self.db[CONTRACTS_COLLECTIONS["agreement_bc_links"]].insert_one(
            link.model_dump(mode="json")
        )
        await self._audit(
            agreement_id=agreement_id,
            action="confirmed_link",
            link_id=link.id,
            actor=actor,
            after={"link_type": link_type, "bc_no": bc_no, "manual": True},
            notes=notes,
        )
        return link

    async def confirm_link(
        self, *, agreement_id: str, link_id: str, actor: str,
    ) -> Optional[Dict[str, Any]]:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
        before = await coll.find_one(
            {"id": link_id, "agreement_id": agreement_id}, {"_id": 0},
        )
        if not before:
            return None
        await coll.update_one(
            {"id": link_id, "agreement_id": agreement_id},
            {"$set": {
                "status": "confirmed",
                "confirmed_by": actor,
                "confirmed_at": _utc_now().isoformat(),
            }},
        )
        await self._audit(
            agreement_id=agreement_id,
            action="confirmed_link",
            link_id=link_id,
            actor=actor,
            before={"status": before.get("status")},
            after={"status": "confirmed"},
        )
        return await coll.find_one(
            {"id": link_id, "agreement_id": agreement_id}, {"_id": 0},
        )

    async def reject_link(
        self, *, agreement_id: str, link_id: str, actor: str,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
        before = await coll.find_one(
            {"id": link_id, "agreement_id": agreement_id}, {"_id": 0},
        )
        if not before:
            return None
        await coll.update_one(
            {"id": link_id, "agreement_id": agreement_id},
            {"$set": {
                "status": "rejected",
                "confirmed_by": actor,
                "confirmed_at": _utc_now().isoformat(),
                "notes": notes,
            }},
        )
        await self._audit(
            agreement_id=agreement_id,
            action="rejected_link",
            link_id=link_id,
            actor=actor,
            before={"status": before.get("status")},
            after={"status": "rejected"},
            notes=notes,
        )
        return await coll.find_one(
            {"id": link_id, "agreement_id": agreement_id}, {"_id": 0},
        )

    async def resolve_exception(
        self, *, exception_id: str, actor: str, note: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        coll = self.db[CONTRACTS_COLLECTIONS["agreement_exceptions"]]
        before = await coll.find_one({"id": exception_id}, {"_id": 0})
        if not before:
            return None
        await coll.update_one(
            {"id": exception_id},
            {"$set": {
                "status": "resolved",
                "resolved_by": actor,
                "resolved_at": _utc_now().isoformat(),
                "resolution_note": note,
            }},
        )
        await self._audit(
            agreement_id=before["agreement_id"],
            action="exception_resolved",
            exception_id=exception_id,
            actor=actor,
            before={"status": before.get("status")},
            after={"status": "resolved"},
            notes=note,
        )
        return await coll.find_one({"id": exception_id}, {"_id": 0})

    # --- Audit -----------------------------------------------------------

    async def _audit(
        self,
        *,
        agreement_id: str,
        action: str,
        actor: str = "system",
        link_id: Optional[str] = None,
        exception_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> None:
        row = AgreementMatchAudit(
            agreement_id=agreement_id,
            action=action,  # type: ignore[arg-type]
            actor=actor,
            link_id=link_id,
            exception_id=exception_id,
            before=before or {},
            after=after or {},
            notes=notes,
        )
        await self.db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].insert_one(
            row.model_dump(mode="json")
        )

    async def _insert_exception(self, ex: AgreementException) -> None:
        await self.db[CONTRACTS_COLLECTIONS["agreement_exceptions"]].insert_one(
            ex.model_dump(mode="json")
        )


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())
