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
import re
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
    db = get_db()
    # Surface vendor-side miss volume without flooding the exception queue
    # (vendor-side party misses are intentionally not emitted as exceptions).
    audit = db[CONTRACTS_COLLECTIONS["agreement_match_audit"]]
    proposed_vendor = await audit.count_documents({
        "action": "proposed_link",
        "after.link_type": "vendor",
    })
    confirmed_vendor = await audit.count_documents({
        "action": "confirmed_link",
        "after.link_type": "vendor",
    })
    return {
        "module": "contract_intelligence",
        "phase": 3,
        "docusign": client.status(),
        "vendor_link_telemetry": {
            "proposed_vendor_links_total": proposed_vendor,
            "confirmed_vendor_links_total": confirmed_vendor,
        },
    }


# ---------------------------------------------------------------------------
# Analytics endpoints (Phase 3) — read-only, advisory, no BC writes
# ---------------------------------------------------------------------------

@router.get("/contracts/summary")
async def contracts_summary(_user: dict = Depends(get_current_user)):
    """High-level counts for dashboard cards.

    Returns:
        {
          "agreements": { "total": N, "by_status": {...} },
          "exceptions": { "open": N, "by_code": {...} },
          "links":      { "total": N, "by_status": {...}, "by_type": {...} },
          "events":     { "total": N, "unprocessed": N },
        }
    """
    db = get_db()

    async def _group(coll, key: str, match: Optional[Dict[str, Any]] = None):
        pipeline: List[Dict[str, Any]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline.append({"$group": {"_id": f"${key}", "count": {"$sum": 1}}})
        out: Dict[str, int] = {}
        async for row in coll.aggregate(pipeline):
            out[str(row["_id"]) if row["_id"] is not None else "null"] = row["count"]
        return out

    agr = db[CONTRACTS_COLLECTIONS["agreements"]]
    ex = db[CONTRACTS_COLLECTIONS["agreement_exceptions"]]
    lk = db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
    ev = db[CONTRACTS_COLLECTIONS["agreement_events"]]

    return {
        "agreements": {
            "total": await agr.count_documents({}),
            "by_status": await _group(agr, "status"),
            "with_unmatched_exceptions": await agr.count_documents(
                {"has_unmatched_exceptions": True}
            ),
        },
        "exceptions": {
            "open": await ex.count_documents({"status": "open"}),
            "resolved": await ex.count_documents({"status": "resolved"}),
            "by_code": await _group(ex, "code", {"status": "open"}),
            "by_severity": await _group(ex, "severity", {"status": "open"}),
        },
        "links": {
            "total": await lk.count_documents({}),
            "by_status": await _group(lk, "status"),
            "by_type": await _group(lk, "link_type"),
        },
        "events": {
            "total": await ev.count_documents({}),
            "unprocessed": await ev.count_documents({"processed": False}),
        },
    }


@router.get("/contracts/expiring")
async def contracts_expiring(
    within_days: int = Query(60, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(get_current_user),
):
    """Agreements with `expires_at` within the next N days, soonest-first."""
    from datetime import datetime, timedelta, timezone
    db = get_db()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=within_days)
    coll = db[CONTRACTS_COLLECTIONS["agreements"]]
    q = {
        "expires_at": {
            "$ne": None,
            "$gte": now.isoformat(),
            "$lte": horizon.isoformat(),
        },
        "status": {"$nin": ["voided", "declined", "expired"]},
    }
    items = await coll.find(q, {"_id": 0}).sort("expires_at", 1).limit(limit).to_list(length=limit)
    total = await coll.count_documents(q)
    return {
        "as_of": now.isoformat(),
        "within_days": within_days,
        "total": total,
        "items": items,
    }


@router.get("/contracts/coverage")
async def contracts_coverage(_user: dict = Depends(get_current_user)):
    """Aggregate coverage: how many agreements have at least one customer
    link, vendor link, item link; how many pricing rows are matched/unmatched.
    """
    db = get_db()
    agr_coll = db[CONTRACTS_COLLECTIONS["agreements"]]
    lk_coll = db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
    pr_coll = db[CONTRACTS_COLLECTIONS["agreement_pricing"]]

    total_agreements = await agr_coll.count_documents({})

    async def _agreements_with_link(link_type: str) -> int:
        ids = set()
        cursor = lk_coll.find(
            {"link_type": link_type, "status": {"$in": ["confirmed", "auto_confirmed", "proposed"]}},
            {"_id": 0, "agreement_id": 1},
        )
        async for row in cursor:
            ids.add(row["agreement_id"])
        return len(ids)

    customer_covered = await _agreements_with_link("customer")
    vendor_covered = await _agreements_with_link("vendor")
    item_covered = await _agreements_with_link("item")

    pricing_total = await pr_coll.count_documents({})
    pricing_matched = await pr_coll.count_documents({"matched_bc_item_no": {"$ne": None}})

    # Item link rows give an alternative read of pricing match: each item link
    # is anchored to a pricing row via pricing_id.
    pricing_with_item_link = await lk_coll.count_documents(
        {"link_type": "item", "pricing_id": {"$ne": None}},
    )

    def _pct(num: int, denom: int) -> float:
        return round(num / denom, 4) if denom else 0.0

    return {
        "agreements_total": total_agreements,
        "customer_coverage": {
            "covered": customer_covered,
            "uncovered": max(0, total_agreements - customer_covered),
            "ratio": _pct(customer_covered, total_agreements),
        },
        "vendor_coverage": {
            "covered": vendor_covered,
            "uncovered": max(0, total_agreements - vendor_covered),
            "ratio": _pct(vendor_covered, total_agreements),
        },
        "item_coverage": {
            "agreements_with_item_links": item_covered,
            "agreements_total": total_agreements,
            "ratio": _pct(item_covered, total_agreements),
        },
        "pricing_lines": {
            "total": pricing_total,
            "matched": pricing_matched,
            "with_item_link": pricing_with_item_link,
            "match_ratio": _pct(pricing_matched, pricing_total),
        },
    }


@router.get("/contracts/threshold-telemetry")
async def contracts_threshold_telemetry(
    days: int = Query(30, ge=1, le=365),
    _user: dict = Depends(get_current_user),
):
    """Read-only precision@threshold over the last N days using audit rows.

    Reports:
      * total system-emitted links (action proposed_link / confirmed_link with actor=system)
      * how many of those were later rejected by a human
      * **separate** override rates for each band:
          - auto_confirm_override_rate = rejected ÷ system-emitted with confidence >= auto_confirm
          - propose_override_rate      = rejected ÷ system-emitted with confidence in [propose, auto_confirm)
      * a combined `override_rate` retained for back-compat
    """
    from datetime import datetime, timedelta, timezone
    from services.contracts.bc_agreement_matcher import (
        AUTO_CONFIRM_THRESHOLD as auto,
        MIN_PROPOSE_THRESHOLD as propose,
    )
    db = get_db()
    audit = db[CONTRACTS_COLLECTIONS["agreement_match_audit"]]
    links = db[CONTRACTS_COLLECTIONS["agreement_bc_links"]]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # System-emitted links since `since`
    system_emitted_ids: List[str] = []
    cursor = audit.find(
        {
            "actor": "system",
            "action": {"$in": ["proposed_link", "confirmed_link"]},
            "at": {"$gte": since},
            "link_id": {"$ne": None},
        },
        {"_id": 0, "link_id": 1},
    )
    async for row in cursor:
        system_emitted_ids.append(row["link_id"])
    system_emitted_ids = list(set(system_emitted_ids))

    if not system_emitted_ids:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "thresholds": {"auto_confirm": auto, "propose": propose},
            "system_emitted": 0,
            "human_overrides": 0,
            "override_rate": 0.0,
            "by_threshold_band": {
                "auto_confirm": 0, "propose": 0, "below_propose": 0,
            },
            "by_band_overrides": {
                "auto_confirm": 0, "propose": 0, "below_propose": 0,
            },
            "auto_confirm_override_rate": 0.0,
            "propose_override_rate": 0.0,
        }

    # Slice by confidence band (live state from links table)
    bands = {"auto_confirm": 0, "propose": 0, "below_propose": 0}
    band_by_id: Dict[str, str] = {}
    cursor = links.find(
        {"id": {"$in": system_emitted_ids}},
        {"_id": 0, "id": 1, "confidence": 1, "status": 1},
    )
    async for row in cursor:
        c = float(row.get("confidence") or 0)
        if c >= auto:
            bands["auto_confirm"] += 1
            band_by_id[row["id"]] = "auto_confirm"
        elif c >= propose:
            bands["propose"] += 1
            band_by_id[row["id"]] = "propose"
        else:
            bands["below_propose"] += 1
            band_by_id[row["id"]] = "below_propose"

    # Human overrides — fetch each rejected_link audit and bucket by band
    overrides_by_band = {"auto_confirm": 0, "propose": 0, "below_propose": 0}
    human_overrides = 0
    cursor = audit.find(
        {
            "action": "rejected_link",
            "actor": {"$ne": "system"},
            "link_id": {"$in": system_emitted_ids},
        },
        {"_id": 0, "link_id": 1},
    )
    async for row in cursor:
        human_overrides += 1
        band = band_by_id.get(row["link_id"], "below_propose")
        overrides_by_band[band] = overrides_by_band.get(band, 0) + 1

    def _pct(num: int, denom: int) -> float:
        return round(num / denom, 4) if denom else 0.0

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "thresholds": {"auto_confirm": auto, "propose": propose},
        "system_emitted": len(system_emitted_ids),
        "human_overrides": human_overrides,
        "override_rate": _pct(human_overrides, len(system_emitted_ids)),
        "by_threshold_band": bands,
        "by_band_overrides": overrides_by_band,
        "auto_confirm_override_rate": _pct(
            overrides_by_band["auto_confirm"], bands["auto_confirm"],
        ),
        "propose_override_rate": _pct(
            overrides_by_band["propose"], bands["propose"],
        ),
    }


# ---------------------------------------------------------------------------
# BC search (scoped to Contract Intelligence) — Phase 3.1
# ---------------------------------------------------------------------------

@router.get("/contracts/bc-search")
async def contracts_bc_search(
    q: str = Query(..., min_length=1, max_length=128),
    link_type: str = Query(..., pattern="^(customer|vendor|item)$"),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(get_current_user),
):
    """Search the existing BC reference cache for candidates to attach as a
    Contract Intelligence link. Read-only: no BC writes, no cache mutation.

    Behavior:
      * `customer` → searches `bc_reference_cache` by `bc_customer_name` regex
        (case-insensitive) AND by exact `bc_customer_no`. Dedupes by customer no.
      * `vendor`   → same against `bc_vendor_name` / `bc_vendor_no`.
      * `item`     → the BC reference cache does NOT index items by display
        name in this codebase; returns an empty result with a `hint` field so
        the UI can prompt the operator to enter the BC item no manually.
        (Item search is on the Phase 4 backlog if/when item indexing lands.)

    Returns:
        { "link_type", "query", "matches": [ {bc_no, bc_name, source} ], "hint"? }
    """
    db = get_db()
    coll = db["bc_reference_cache"]
    raw = q.strip()
    if not raw:
        return {"link_type": link_type, "query": q, "matches": []}

    # Escape regex special chars to keep this purely a substring search.
    escaped = re.escape(raw)
    name_field = {
        "customer": "bc_customer_name",
        "vendor": "bc_vendor_name",
    }.get(link_type)

    if link_type == "item":
        return {
            "link_type": "item",
            "query": q,
            "matches": [],
            "hint": (
                "BC reference cache does not index items by display name. "
                "Enter the BC item number directly via the manual link form."
            ),
        }

    no_field = {
        "customer": "bc_customer_no",
        "vendor": "bc_vendor_no",
    }[link_type]

    query = {
        "$or": [
            {name_field: {"$regex": escaped, "$options": "i"}},
            {no_field: raw},
        ],
        no_field: {"$nin": [None, ""]},  # require entity number
    }

    cursor = coll.find(query, {"_id": 0, no_field: 1, name_field: 1, "bc_entity_type": 1}).limit(limit * 4)
    seen: set[str] = set()
    matches: List[Dict[str, Any]] = []
    async for row in cursor:
        bc_no = row.get(no_field)
        if not bc_no or bc_no in seen:
            continue
        seen.add(bc_no)
        matches.append({
            "bc_no": bc_no,
            "bc_name": row.get(name_field) or "",
            "source": row.get("bc_entity_type") or link_type,
        })
        if len(matches) >= limit:
            break

    return {"link_type": link_type, "query": q, "matches": matches}


@router.get("/contracts/audit/{agreement_id}")
async def contracts_audit_for_agreement(
    agreement_id: str,
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(get_current_user),
):
    """Audit trail for a single agreement, newest-first."""
    db = get_db()
    items = await db[CONTRACTS_COLLECTIONS["agreement_match_audit"]].find(
        {"agreement_id": agreement_id}, {"_id": 0},
    ).sort("at", -1).limit(limit).to_list(length=limit)
    return {"agreement_id": agreement_id, "total": len(items), "items": items}
