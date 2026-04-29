"""Contract Intelligence HTTP surface (Phase 2).

Endpoints:
    POST /api/docusign/webhook                        — DocuSign Connect receiver
                                                        (HMAC validated, idempotent)
    GET  /api/contracts/agreements                    — list agreements
    GET  /api/contracts/agreements/{agreement_id}     — detail (parties, terms,
                                                        pricing, links, exceptions)
    POST /api/contracts/agreements/{agreement_id}/links
                                                       — create manual link
    POST /api/contracts/agreements/{agreement_id}/links/{link_id}/confirm
                                                       — confirm proposed link
    POST /api/contracts/agreements/{agreement_id}/links/{link_id}/reject
                                                       — reject proposed link
    GET  /api/contracts/exceptions                     — list (filter by status/code)
    POST /api/contracts/exceptions/{exception_id}/resolve
                                                       — resolve exception

Auth posture:
    * The DocuSign webhook is intentionally UNAUTHENTICATED — DocuSign
      cannot present a bearer token. Authenticity is enforced by HMAC-SHA256
      validation against `DOCUSIGN_HMAC_SECRET[_2]`.
    * All other endpoints require `Depends(get_current_user)`.
    * No BC writes, no DocuSign writes, no live DocuSign calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field

from deps import get_db
from models.contracts import CONTRACTS_COLLECTIONS
from services.auth_deps import get_current_user
from services.contracts.contract_intelligence_service import (
    ContractIntelligenceService,
)
from services.integrations.docusign_client import get_docusign_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Contract Intelligence"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _service() -> ContractIntelligenceService:
    return ContractIntelligenceService(get_db())


def _extract_event_id(payload: Dict[str, Any]) -> str:
    """Pick the unique event id from a DocuSign Connect SIM payload.

    DocuSign SIM provides a top-level ``generatedDateTime`` and
    ``data.envelopeId`` — the canonical idempotency key is the
    ``configurationId`` + ``generatedDateTime`` + envelope id pair, but
    DocuSign also exposes a stable ``eventId`` on most modern envelope
    events. We accept any of: ``payload.eventId``, ``payload.event_id``,
    ``payload.uri``, or a synthesized key built from
    ``(generatedDateTime, envelopeId, event)``.
    """
    if isinstance(payload.get("eventId"), str) and payload["eventId"].strip():
        return payload["eventId"].strip()
    if isinstance(payload.get("event_id"), str) and payload["event_id"].strip():
        return payload["event_id"].strip()
    data = payload.get("data") or {}
    env_id = data.get("envelopeId") or payload.get("envelopeId") or "unknown"
    gen = payload.get("generatedDateTime") or data.get("envelopeSummary", {}).get(
        "statusChangedDateTime") or ""
    evt = payload.get("event") or "unknown"
    return f"{evt}:{env_id}:{gen}".strip(":") or "unknown"


def _extract_envelope_id(payload: Dict[str, Any]) -> Optional[str]:
    data = payload.get("data") or {}
    return (
        (data.get("envelopeSummary") or {}).get("envelopeId")
        or data.get("envelopeId")
        or payload.get("envelopeId")
    )


# ---------------------------------------------------------------------------
# DocuSign Connect webhook receiver
# ---------------------------------------------------------------------------

@router.post("/docusign/webhook", include_in_schema=True)
async def docusign_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_docusign_signature_1: Optional[str] = Header(None),
    x_docusign_signature_2: Optional[str] = Header(None),
):
    """Receive a DocuSign Connect SIM event.

    Flow:
        1. Read RAW body (HMAC must hash unparsed bytes).
        2. Validate HMAC against any configured secret (rotation-friendly).
        3. Parse JSON.
        4. Insert into ``agreement_events`` (idempotent via unique index).
        5. Schedule background normalization + matching.
        6. ACK 200 immediately so DocuSign doesn't retry.

    Errors before HMAC validation succeeds return 400 with a generic message.
    """
    raw_body = await request.body()
    client = get_docusign_client()

    if not client.is_webhook_ready():
        # Webhook hasn't been configured yet on this environment. Refuse
        # rather than silently accepting unsigned events.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="docusign webhook not configured",
        )

    sig = x_docusign_signature_1 or x_docusign_signature_2
    valid = client.validate_webhook_signature(raw_body, sig)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="malformed json",
        )

    event_id = _extract_event_id(payload)
    envelope_id = _extract_envelope_id(payload)
    event_type = payload.get("event") or "unknown"

    svc = _service()
    record = await svc.record_event(
        provider_event_id=event_id,
        provider_envelope_id=envelope_id,
        event_type=event_type,
        raw_payload=payload,
        hmac_valid=True,
        transport="webhook",
    )

    if record["duplicate"]:
        return {"acknowledged": True, "duplicate": True, "event_id": event_id}

    background_tasks.add_task(_run_processing, record["event_id"])
    return {"acknowledged": True, "duplicate": False, "event_id": record["event_id"]}


async def _run_processing(event_id: str) -> None:
    """Background-task wrapper that owns its own DB handle."""
    try:
        svc = _service()
        outcome = await svc.process_event(event_id)
        logger.info("[contracts] processed event %s: %s", event_id, outcome)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[contracts] background processing failed for %s: %s",
                         event_id, exc)


# ---------------------------------------------------------------------------
# Read endpoints (auth required)
# ---------------------------------------------------------------------------

@router.get("/contracts/agreements")
async def list_agreements(
    status_filter: Optional[str] = Query(None, alias="status"),
    has_unmatched: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
):
    db = get_db()
    coll = db[CONTRACTS_COLLECTIONS["agreements"]]
    q: Dict[str, Any] = {}
    if status_filter:
        q["status"] = status_filter
    if has_unmatched is not None:
        q["has_unmatched_exceptions"] = has_unmatched
    cursor = coll.find(q, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit)
    items = await cursor.to_list(length=limit)
    total = await coll.count_documents(q)
    return {"total": total, "items": items, "skip": skip, "limit": limit}


@router.get("/contracts/agreements/{agreement_id}")
async def get_agreement_detail(
    agreement_id: str,
    _user: dict = Depends(get_current_user),
):
    db = get_db()
    agr = await db[CONTRACTS_COLLECTIONS["agreements"]].find_one(
        {"id": agreement_id}, {"_id": 0},
    )
    if not agr:
        raise HTTPException(status_code=404, detail="agreement not found")

    async def _all(coll_name: str) -> List[Dict[str, Any]]:
        return await db[CONTRACTS_COLLECTIONS[coll_name]].find(
            {"agreement_id": agreement_id}, {"_id": 0},
        ).to_list(length=None)

    parties = await _all("agreement_parties")
    terms = await _all("agreement_terms")
    pricing = await _all("agreement_pricing")
    documents = await _all("agreement_documents")
    links = await _all("agreement_bc_links")
    exceptions = await _all("agreement_exceptions")

    return {
        "agreement": agr,
        "parties": parties,
        "terms": terms,
        "pricing": pricing,
        "documents": documents,
        "bc_links": links,
        "exceptions": exceptions,
    }


# ---------------------------------------------------------------------------
# Manual mapping (write paths — auth required, all audited)
# ---------------------------------------------------------------------------

class ManualLinkBody(BaseModel):
    link_type: Literal[
        "customer", "vendor", "item",
        "sales_order", "purchase_order", "contact",
    ]
    bc_entity: str = Field(..., min_length=1, max_length=64)
    bc_no: str = Field(..., min_length=1, max_length=64)
    bc_name_snapshot: Optional[str] = None
    notes: Optional[str] = None


@router.post("/contracts/agreements/{agreement_id}/links")
async def create_manual_link(
    agreement_id: str,
    body: ManualLinkBody = Body(...),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    agr = await db[CONTRACTS_COLLECTIONS["agreements"]].find_one(
        {"id": agreement_id}, {"_id": 0, "id": 1},
    )
    if not agr:
        raise HTTPException(status_code=404, detail="agreement not found")
    actor = user.get("email") or user.get("id") or "user"
    link = await _service().manual_link(
        agreement_id=agreement_id,
        link_type=body.link_type,
        bc_entity=body.bc_entity,
        bc_no=body.bc_no,
        bc_name_snapshot=body.bc_name_snapshot,
        actor=actor,
        notes=body.notes,
    )
    return {"link": link.model_dump(mode="json")}


@router.post("/contracts/agreements/{agreement_id}/links/{link_id}/confirm")
async def confirm_link_endpoint(
    agreement_id: str,
    link_id: str,
    user: dict = Depends(get_current_user),
):
    actor = user.get("email") or user.get("id") or "user"
    updated = await _service().confirm_link(
        agreement_id=agreement_id, link_id=link_id, actor=actor,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="link not found")
    return {"link": updated}


class RejectLinkBody(BaseModel):
    notes: Optional[str] = None


@router.post("/contracts/agreements/{agreement_id}/links/{link_id}/reject")
async def reject_link_endpoint(
    agreement_id: str,
    link_id: str,
    body: RejectLinkBody = Body(default=RejectLinkBody()),
    user: dict = Depends(get_current_user),
):
    actor = user.get("email") or user.get("id") or "user"
    updated = await _service().reject_link(
        agreement_id=agreement_id, link_id=link_id, actor=actor, notes=body.notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="link not found")
    return {"link": updated}


@router.get("/contracts/exceptions")
async def list_exceptions(
    status_filter: Optional[str] = Query("open", alias="status"),
    code: Optional[str] = Query(None),
    agreement_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
):
    db = get_db()
    coll = db[CONTRACTS_COLLECTIONS["agreement_exceptions"]]
    q: Dict[str, Any] = {}
    if status_filter:
        q["status"] = status_filter
    if code:
        q["code"] = code
    if agreement_id:
        q["agreement_id"] = agreement_id
    items = await coll.find(q, {"_id": 0}).sort("opened_at", -1).skip(skip).limit(limit).to_list(length=limit)
    total = await coll.count_documents(q)
    return {"total": total, "items": items, "skip": skip, "limit": limit}


class ResolveExceptionBody(BaseModel):
    note: Optional[str] = None


@router.post("/contracts/exceptions/{exception_id}/resolve")
async def resolve_exception_endpoint(
    exception_id: str,
    body: ResolveExceptionBody = Body(default=ResolveExceptionBody()),
    user: dict = Depends(get_current_user),
):
    actor = user.get("email") or user.get("id") or "user"
    updated = await _service().resolve_exception(
        exception_id=exception_id, actor=actor, note=body.note,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="exception not found")
    return {"exception": updated}


# ---------------------------------------------------------------------------
# Health / status (no auth — diagnostic surface)
# ---------------------------------------------------------------------------

@router.get("/contracts/health")
async def contracts_health():
    client = get_docusign_client()
    return {
        "module": "contract_intelligence",
        "phase": 2,
        "docusign": client.status(),
    }
