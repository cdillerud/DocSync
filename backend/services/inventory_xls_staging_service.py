"""
Inventory XLS Staging Service
──────────────────────────────

Phases C & D of the Inventory XLS pipeline:

  • Stage  — persist a parsed sheet + column_map for human review
  • Approve — apply staged rows to the inv_movements ledger, record learning
  • Reject  — mark as rejected, keep for audit
  • Update mapping — user corrects the column map before approving
  • Learn   — persist approved mapping keyed by (sender_domain, header_hash)

Every ledger write goes through `services.inventory_ledger_service.create_movement`,
so every row picks up:
  • source_type = "spreadsheet_import"
  • reference_type = "xls_import"
  • reference_id = <staging_id>
  • effective_date (new field — additive, never overrides created_at)
  • standard negative-balance checks

NEVER bypasses the ledger — staging is the only path for XLS → ledger.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.inventory_ledger_service import (
    CUSTOMERS_COLL, MOVEMENTS_COLL, create_movement, get_customer,
)

logger = logging.getLogger(__name__)


STAGING_COLL = "inv_import_staging"
LEARNING_COLL = "inv_xls_learned_mappings"

STAGING_STATUSES = {"pending_review", "applied", "rejected", "superseded"}

# Auto-approve threshold — a staging record created from a learned mapping
# will auto-approve if ALL of the following are true:
#   1. column_map source == "learned"
#   2. approval_count for the learned mapping >= AUTO_APPROVE_MIN_APPROVALS
#   3. learned confidence >= AUTO_APPROVE_MIN_CONFIDENCE
#   4. an assigned customer has been resolved via sender-domain auto-suggest
#   5. normalized rows exist and no missing_required fields
# This keeps the pilot's human-in-the-loop safety for new/unknown senders
# while letting repeat senders flow straight through.
AUTO_APPROVE_MIN_APPROVALS = 3
AUTO_APPROVE_MIN_CONFIDENCE = 0.95


# ─────────────────────────────────────────────────────────────
# Customer auto-suggestion from sender
# ─────────────────────────────────────────────────────────────

async def suggest_customer_workspace(
    db,
    sender_email: Optional[str],
    filename: str = "",
) -> Optional[Dict[str, Any]]:
    """Auto-suggest an inv_customers workspace based on sender domain or filename.

    Returns the matching customer record or None.
    """
    hints: List[str] = []
    if sender_email and "@" in sender_email:
        domain = sender_email.split("@", 1)[1].split(".")[0].lower()
        if domain not in ("gmail", "outlook", "hotmail", "yahoo"):
            hints.append(domain)
    fname_lower = (filename or "").lower()
    for token in ("gamer", "giovanni", "owen", "suja", "puer", "comar"):
        if token in fname_lower and token not in hints:
            hints.append(token)

    for hint in hints:
        # Try prefix match in BOTH directions: code startsWith hint, OR hint startsWith code
        # e.g. sender domain "gamerpackaging" should match customer code "gamer"
        cust = await db[CUSTOMERS_COLL].find_one(
            {"$or": [
                {"code": {"$regex": f"^{hint}", "$options": "i"}},
                {"code": {"$regex": f"^{hint[:5]}", "$options": "i"}},
                {"name": {"$regex": hint, "$options": "i"}},
            ]},
            {"_id": 0},
        )
        if cust:
            return cust
        # Also try: where hint startsWith customer code (domain is longer than code)
        all_customers = await db[CUSTOMERS_COLL].find({}, {"_id": 0, "id": 1, "code": 1, "name": 1}).to_list(500)
        for c in all_customers:
            code = (c.get("code") or "").lower()
            if code and len(code) >= 3 and hint.startswith(code):
                return c
    return None


# ─────────────────────────────────────────────────────────────
# Stage
# ─────────────────────────────────────────────────────────────

async def stage_import(
    db,
    filename: str,
    file_hash: str,
    sender_email: Optional[str],
    classification: Dict[str, Any],
    column_map: Dict[str, Any],
    normalized_rows: List[Dict[str, Any]],
    row_errors: List[Dict[str, Any]],
    headers: List[str],
    suggested_customer_id: Optional[str] = None,
    filename_effective_date: Optional[str] = None,
    source_doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a new staging record. Returns the staging doc."""
    # Dedup by file_hash + customer (if assigned)
    dedup_key = f"{file_hash}:{suggested_customer_id or 'unassigned'}"
    existing = await db[STAGING_COLL].find_one(
        {"dedup_key": dedup_key, "status": {"$ne": "rejected"}},
        {"_id": 0, "id": 1, "status": 1},
    )
    if existing:
        return {"already_staged": True, "staging_id": existing["id"], "status": existing["status"]}

    sender_domain = None
    if sender_email and "@" in sender_email:
        sender_domain = sender_email.split("@", 1)[1].lower()

    from services.inventory_xls_parser import compute_header_hash

    staging_doc = {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "file_hash": file_hash,
        "dedup_key": dedup_key,
        "sender_email": sender_email,
        "sender_domain": sender_domain,
        "source_doc_id": source_doc_id,  # link back to hub_documents
        "classification": classification,
        "column_map": column_map,
        "headers": headers,
        "header_hash": compute_header_hash(headers),
        "rows": normalized_rows,
        "row_errors": row_errors,
        "row_count": len(normalized_rows),
        "filename_effective_date": filename_effective_date,
        "suggested_customer_id": suggested_customer_id,
        "assigned_customer_id": suggested_customer_id,
        "status": "pending_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        "approved_by": None,
        "applied_movements": [],
    }
    await db[STAGING_COLL].insert_one(staging_doc)
    staging_doc.pop("_id", None)
    logger.info(
        "[XLSStaging] staged id=%s rows=%d classification=%s customer=%s",
        staging_doc["id"][:8], staging_doc["row_count"],
        classification.get("classification"), suggested_customer_id,
    )

    # Auto-approve gate — only when we have a learned mapping with history,
    # an auto-suggested customer, and healthy rows.
    auto_applied = False
    if await _should_auto_approve(db, staging_doc):
        try:
            approve_result = await approve_staging(
                db, staging_doc["id"], approved_by="auto:learned-mapping",
            )
            auto_applied = approve_result.get("status") == "applied"
            staging_doc["status"] = approve_result.get("status", staging_doc["status"])
            staging_doc["auto_approved"] = auto_applied
            logger.info(
                "[XLSStaging] auto-approved id=%s applied=%d intent=%s",
                staging_doc["id"][:8], approve_result.get("applied_count", 0),
                classification.get("movement_intent"),
            )
        except Exception as e:
            logger.warning("[XLSStaging] auto-approve failed for %s: %s", staging_doc["id"][:8], e)

    return {
        "already_staged": False,
        "staging": staging_doc,
        "auto_applied": auto_applied,
    }


async def _should_auto_approve(db, staging_doc: Dict[str, Any]) -> bool:
    """Return True iff this staging is eligible for auto-approval."""
    # We accept either suggested_customer_id OR assigned_customer_id — since
    # stage_import sets both to the same value on creation.
    customer_id = staging_doc.get("assigned_customer_id") or staging_doc.get("suggested_customer_id")
    if not customer_id:
        return False
    staging_doc["assigned_customer_id"] = customer_id
    if not staging_doc.get("rows"):
        return False
    cm = staging_doc.get("column_map") or {}
    if (cm.get("missing_required") or []):
        return False
    if cm.get("source") != "learned":
        return False
    if (cm.get("confidence") or 0) < AUTO_APPROVE_MIN_CONFIDENCE:
        return False
    # Lookup the learning record to confirm approval_count
    sender_domain = staging_doc.get("sender_domain") or "unknown"
    header_hash = staging_doc.get("header_hash")
    learned = await db[LEARNING_COLL].find_one(
        {"sender_domain": sender_domain, "header_hash": header_hash},
        {"_id": 0, "approval_count": 1},
    )
    if not learned:
        return False
    if learned.get("approval_count", 0) < AUTO_APPROVE_MIN_APPROVALS:
        return False
    return True


# ─────────────────────────────────────────────────────────────
# Update mapping / reassign customer (pre-approval)
# ─────────────────────────────────────────────────────────────

async def update_staging(
    db,
    staging_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """Update column_map, assigned_customer_id, or row-level overrides.

    Only permitted while status == pending_review.
    """
    allowed = {"column_map", "assigned_customer_id", "rows", "classification"}
    safe = {k: v for k, v in (updates or {}).items() if k in allowed}
    if not safe:
        return {"updated": False, "reason": "no allowed fields to update"}
    doc = await db[STAGING_COLL].find_one({"id": staging_id}, {"_id": 0, "status": 1})
    if not doc:
        return {"updated": False, "reason": "not found"}
    if doc.get("status") != "pending_review":
        return {"updated": False, "reason": f"status is {doc.get('status')}"}
    safe["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db[STAGING_COLL].update_one({"id": staging_id}, {"$set": safe})
    return {"updated": True, "staging_id": staging_id}


# ─────────────────────────────────────────────────────────────
# Approve — apply to ledger
# ─────────────────────────────────────────────────────────────

async def approve_staging(
    db,
    staging_id: str,
    approved_by: str = "user",
) -> Dict[str, Any]:
    """Apply a staged XLS to the inv_movements ledger."""
    staging = await db[STAGING_COLL].find_one({"id": staging_id}, {"_id": 0})
    if not staging:
        raise ValueError(f"Staging {staging_id} not found")
    if staging.get("status") != "pending_review":
        raise ValueError(f"Staging status is {staging.get('status')}")

    customer_id = staging.get("assigned_customer_id")
    if not customer_id:
        raise ValueError("Staging has no assigned_customer_id — assign first")
    cust = await get_customer(db, customer_id)
    if not cust:
        raise ValueError(f"Customer workspace {customer_id} not found")

    cls = staging.get("classification") or {}
    movement_intent = cls.get("movement_intent") or "manual_adjustment"
    if movement_intent == "incoming_supply":
        # Forecast → incoming_supply table, NOT movements
        return await _apply_forecast_rows(db, staging, approved_by)

    # Resolve ownership — customer_profile override → staging hint → row override → default
    default_ownership = (
        cust.get("default_dunnage_ownership")
        if cls.get("classification") == "inventory_dunnage"
        else None
    ) or cls.get("ownership_hint") or "customer_owned"

    applied_ids: List[str] = []
    errors: List[Dict[str, Any]] = []

    for row in staging.get("rows") or []:
        try:
            ownership = row.get("ownership_type") or default_ownership
            result = await create_movement(
                db,
                customer_id=customer_id,
                item=row["item"],
                item_description=row.get("item_description", ""),
                warehouse=row.get("warehouse", "MAIN"),
                ownership_type=ownership,
                movement_type=movement_intent,
                quantity_delta=float(row["qty"]),
                unit_of_measure=row.get("uom", "units"),
                source_type="spreadsheet_import",
                reference_type="xls_import",
                reference_id=staging_id,
                notes=row.get("notes") or f"XLS: {staging.get('filename', '')}",
                created_by=approved_by,
                skip_balance_check=(movement_intent in ("opening_balance", "manual_adjustment")),
            )
            movement = result["movement"]
            # Attach effective_date as an additive field (never overrides created_at)
            eff = row.get("effective_date") or staging.get("filename_effective_date")
            if eff:
                await db[MOVEMENTS_COLL].update_one(
                    {"id": movement["id"]},
                    {"$set": {"effective_date": eff}},
                )
            applied_ids.append(movement["id"])
        except Exception as e:
            errors.append({"row": row.get("_raw_row_index"), "item": row.get("item"), "error": str(e)})

    # Persist learning (Phase D)
    if applied_ids:
        await _persist_learning(db, staging, approved_by)

    final_status = "applied" if applied_ids else "rejected"
    await db[STAGING_COLL].update_one(
        {"id": staging_id},
        {"$set": {
            "status": final_status,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": approved_by,
            "applied_movements": applied_ids,
            "apply_errors": errors,
        }},
    )
    logger.info(
        "[XLSStaging] approved id=%s customer=%s applied=%d errors=%d intent=%s",
        staging_id[:8], customer_id, len(applied_ids), len(errors), movement_intent,
    )
    return {
        "staging_id": staging_id,
        "status": final_status,
        "applied_count": len(applied_ids),
        "error_count": len(errors),
        "errors": errors,
    }


async def _apply_forecast_rows(db, staging: Dict[str, Any], approved_by: str) -> Dict[str, Any]:
    """Forecast rows → inv_incoming_supply planned records."""
    from services.inventory_ledger_service import INCOMING_COLL
    customer_id = staging["assigned_customer_id"]
    staging_id = staging["id"]
    applied_ids: List[str] = []
    errors: List[Dict[str, Any]] = []
    for row in staging.get("rows") or []:
        try:
            doc = {
                "id": str(uuid.uuid4()),
                "customer_id": customer_id,
                "item": row["item"],
                "item_description": row.get("item_description", ""),
                "warehouse": row.get("warehouse", "MAIN"),
                "ownership_type": row.get("ownership_type", "customer_owned"),
                "quantity": float(row["qty"]),
                "unit_of_measure": row.get("uom", "units"),
                "status": "planned",
                "expected_date": row.get("effective_date") or staging.get("filename_effective_date"),
                "reference_type": "xls_forecast_import",
                "reference_id": staging_id,
                "source_type": "spreadsheet_import",
                "notes": row.get("notes") or f"XLS forecast: {staging.get('filename','')}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": approved_by,
            }
            await db[INCOMING_COLL].insert_one(doc)
            applied_ids.append(doc["id"])
        except Exception as e:
            errors.append({"row": row.get("_raw_row_index"), "error": str(e)})

    if applied_ids:
        await _persist_learning(db, staging, approved_by)

    await db[STAGING_COLL].update_one(
        {"id": staging_id},
        {"$set": {
            "status": "applied" if applied_ids else "rejected",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": approved_by,
            "applied_movements": applied_ids,
            "apply_errors": errors,
            "applied_to": "inv_incoming_supply",
        }},
    )
    return {
        "staging_id": staging_id,
        "status": "applied" if applied_ids else "rejected",
        "applied_to": "inv_incoming_supply",
        "applied_count": len(applied_ids),
        "error_count": len(errors),
    }


async def reject_staging(db, staging_id: str, rejected_by: str, reason: str = "") -> Dict[str, Any]:
    doc = await db[STAGING_COLL].find_one({"id": staging_id}, {"_id": 0, "status": 1})
    if not doc:
        raise ValueError(f"Staging {staging_id} not found")
    if doc.get("status") != "pending_review":
        return {"rejected": False, "status": doc.get("status")}
    await db[STAGING_COLL].update_one(
        {"id": staging_id},
        {"$set": {
            "status": "rejected",
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "rejected_by": rejected_by,
            "rejection_reason": reason,
        }},
    )
    return {"rejected": True, "status": "rejected"}


# ─────────────────────────────────────────────────────────────
# Phase D — Learning
# ─────────────────────────────────────────────────────────────

async def _persist_learning(db, staging: Dict[str, Any], approved_by: str) -> None:
    """Upsert a learned mapping keyed by (sender_domain, header_hash)."""
    sender_domain = staging.get("sender_domain") or "unknown"
    header_hash = staging.get("header_hash")
    if not header_hash:
        return
    column_map = (staging.get("column_map") or {}).get("mapping") or staging.get("column_map") or {}
    if not column_map:
        return
    doc_filter = {"sender_domain": sender_domain, "header_hash": header_hash}
    existing = await db[LEARNING_COLL].find_one(doc_filter, {"_id": 0})
    if existing:
        await db[LEARNING_COLL].update_one(
            doc_filter,
            {"$set": {
                "column_map": column_map,
                "last_approved_at": datetime.now(timezone.utc).isoformat(),
                "last_approved_by": approved_by,
                "classification": (staging.get("classification") or {}).get("classification"),
            }, "$inc": {"approval_count": 1}},
        )
    else:
        await db[LEARNING_COLL].insert_one({
            "id": str(uuid.uuid4()),
            "sender_domain": sender_domain,
            "header_hash": header_hash,
            "column_map": column_map,
            "classification": (staging.get("classification") or {}).get("classification"),
            "approval_count": 1,
            "last_approved_at": datetime.now(timezone.utc).isoformat(),
            "last_approved_by": approved_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })


async def get_learning_summary(db) -> Dict[str, Any]:
    """Return stats for the AI Learning Intelligence dashboard."""
    total = await db[LEARNING_COLL].count_documents({})
    by_classification_cursor = db[LEARNING_COLL].aggregate([
        {"$group": {"_id": "$classification", "count": {"$sum": 1},
                     "total_approvals": {"$sum": "$approval_count"}}},
        {"$sort": {"count": -1}},
    ])
    by_classification = [r async for r in by_classification_cursor]
    top_senders_cursor = db[LEARNING_COLL].aggregate([
        {"$group": {"_id": "$sender_domain", "mappings": {"$sum": 1},
                     "approvals": {"$sum": "$approval_count"}}},
        {"$sort": {"approvals": -1}},
        {"$limit": 10},
    ])
    top_senders = [r async for r in top_senders_cursor]
    return {
        "total_learned_mappings": total,
        "by_classification": [
            {"classification": r["_id"], "unique_mappings": r["count"], "total_approvals": r["total_approvals"]}
            for r in by_classification
        ],
        "top_senders": [
            {"sender_domain": r["_id"], "mappings": r["mappings"], "approvals": r["approvals"]}
            for r in top_senders
        ],
    }


# ─────────────────────────────────────────────────────────────
# Listing
# ─────────────────────────────────────────────────────────────

async def list_staging(
    db,
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if customer_id:
        q["assigned_customer_id"] = customer_id
    total = await db[STAGING_COLL].count_documents(q)
    docs = await db[STAGING_COLL].find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "staging": docs}


async def get_staging(db, staging_id: str) -> Optional[Dict[str, Any]]:
    return await db[STAGING_COLL].find_one({"id": staging_id}, {"_id": 0})


async def ensure_indexes(db) -> None:
    await db[STAGING_COLL].create_index("id", unique=True)
    await db[STAGING_COLL].create_index("dedup_key")
    await db[STAGING_COLL].create_index([("status", 1), ("created_at", -1)])
    await db[STAGING_COLL].create_index("assigned_customer_id")
    await db[LEARNING_COLL].create_index([("sender_domain", 1), ("header_hash", 1)], unique=True)
