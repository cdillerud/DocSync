"""
Customer Inventory Ledger Router

REST API for the customer-specific inventory ledger module.
Only the endpoints the Operations Queue page and the BC sales-order panel call
remain (Round 3a); the rest of the ledger API was removed as unused.
"""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from deps import get_db
from workflows.inventory.ledger.service import MOVEMENTS_COLL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inventory-ledger", tags=["Inventory Ledger"])


# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# CUSTOMER WORKSPACES
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# DASHBOARD SUMMARY
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# BALANCES
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# MOVEMENTS (immutable)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# MANUAL MOVEMENT ENTRY (validated, restricted types)
# ═══════════════════════════════════════════════════════════════

MANUAL_ALLOWED_TYPES = {"opening_balance", "manual_adjustment", "transfer", "writeoff", "correction"}
MANUAL_BLOCKED_TYPES = {"order_commitment", "order_release", "receipt"}


# ═══════════════════════════════════════════════════════════════
# CSV IMPORT
# ═══════════════════════════════════════════════════════════════

IMPORT_ALLOWED_MODES = {"opening_balance", "manual_adjustment"}
IMPORT_HASHES_COLL = "inv_import_hashes"


# ═══════════════════════════════════════════════════════════════
# BALANCE EXPORT (CSV)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# DEMAND SIGNALS
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# SUPPLY COVERAGE
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# ACTION CENTER
# ═══════════════════════════════════════════════════════════════

ACTION_TYPES = {"shortage", "reorder", "demand_gap", "coverage_risk", "no_incoming"}

# Priority weights: higher = more urgent
_PRIORITY_WEIGHTS = {
    "shortage": 50,
    "coverage_risk": 30,
    "demand_gap": 20,
    "reorder": 10,
    "no_incoming": 5,
}


# ═══════════════════════════════════════════════════════════════
# PO DRAFT GENERATION
# ═══════════════════════════════════════════════════════════════

PO_DRAFTS_COLL = "po_drafts"
PO_SUBMISSION_LOGS_COLL = "po_submission_logs"
PO_DUPLICATE_WINDOW_MINUTES = 5


BC_RESPONSE_STATUSES = ("created", "rejected", "pending")
BC_RESPONSE_TO_LOG_STATUS = {"created": "acknowledged", "rejected": "failed", "pending": "submitted"}


# ═══════════════════════════════════════════════════════════════
# PO SUBMISSION LOG
# ═══════════════════════════════════════════════════════════════

SUBMISSION_STATUSES = ("exported", "submitted", "acknowledged", "failed")


# ═══════════════════════════════════════════════════════════════
# ITEM DETAIL
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# INVENTORY SNAPSHOT
# ═══════════════════════════════════════════════════════════════

EXCEPTION_TYPES = {"short", "low", "reorder", "no_incoming"}


# ═══════════════════════════════════════════════════════════════
# REORDER RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════

DEFAULT_SAFETY_BUFFER = 10
DEFAULT_REORDER_THRESHOLD = 0


# ═══════════════════════════════════════════════════════════════
# HISTORY & AUDIT
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# SEED / IMPORT
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# LOOKUPS
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# ORDER RELEASE
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# SALES ORDER RECONCILIATION
# ═══════════════════════════════════════════════════════════════

class ReconcileLineReq(BaseModel):
    item: str
    qty: float


class ReconcileSOReq(BaseModel):
    sales_order_id: str
    lines: list[ReconcileLineReq] = []
    cancelled: bool = False


@router.post("/reconcile-sales-order")
async def api_reconcile_sales_order(body: ReconcileSOReq):
    """Reconcile inventory commitments for an edited or cancelled Sales Order.

    When cancelled=true, releases all remaining net commitments.
    When cancelled=false, adjusts per-line: creates delta commitments or releases.
    Drop-ship orders are rejected — they have no inventory commitments.
    """
    db = get_db()
    order_type = await _get_order_type(db, body.sales_order_id)
    if order_type == "drop_ship":
        raise HTTPException(
            status_code=422,
            detail="Drop-ship orders have no inventory commitments to reconcile.",
        )
    try:
        from services.inventory_so_integration import reconcile_sales_order
        result = await reconcile_sales_order(
            db,
            sales_order_id=body.sales_order_id,
            lines=[{"item": ln.item, "qty": ln.qty} for ln in body.lines],
            cancelled=body.cancelled,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# BC SHIPMENT SYNC → INVENTORY LEDGER
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY FROM SHORTAGE (separate prefix)
# ═══════════════════════════════════════════════════════════════

incoming_supply_router = APIRouter(prefix="/incoming-supply", tags=["Incoming Supply"])


# ═══════════════════════════════════════════════════════════════
# SO ORDER TYPE
# ═══════════════════════════════════════════════════════════════

VALID_ORDER_TYPES = ("warehouse", "drop_ship")


async def _get_order_type(db, sales_order_id: str) -> str:
    """Return the order type for a sales order. Default: warehouse."""
    doc = await db[SO_ORDER_TYPES_COLL].find_one(
        {"sales_order_id": sales_order_id}, {"_id": 0, "order_type": 1}
    )
    return doc["order_type"] if doc else "warehouse"


# ═══════════════════════════════════════════════════════════════
# DROP-SHIP PO DRAFT GENERATION
# ═══════════════════════════════════════════════════════════════

DS_VENDOR_SHIPMENT_LOGS_COLL = "ds_vendor_shipment_logs"


# ═══════════════════════════════════════════════════════════════
# DROP-SHIP VENDOR SHIPMENT CAPTURE
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# BC SHIPMENT CAPTURE
# ═══════════════════════════════════════════════════════════════

BC_SHIPMENT_LOGS_COLL = "bc_shipment_logs"
BC_INVOICE_LOGS_COLL = "bc_invoice_logs"
SO_ORDER_TYPES_COLL = "so_order_types"


# ═══════════════════════════════════════════════════════════════
# BC INVOICE CAPTURE
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# DOCUMENT LINKAGE & PROCESS CHECKLIST
# ═══════════════════════════════════════════════════════════════

DOCUMENT_LINKS_COLL = "document_links"
VALID_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_DOCUMENT_TYPES = ("customer_po", "warehouse_agreement", "approval_backup", "vendor_po_support", "other")


async def _get_document_links_summary(db, entity_type: str, entity_id: str):
    """Helper: return doc link count and by-type summary."""
    cursor = db[DOCUMENT_LINKS_COLL].find(
        {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
    ).sort("uploaded_at", -1)
    docs = await cursor.to_list(length=200)
    by_type = {}
    for d in docs:
        dt = d["document_type"]
        by_type[dt] = by_type.get(dt, 0) + 1
    return len(docs), by_type, docs


async def _derive_so_checklist(db, sales_order_id: str, order_type: str, doc_count: int, docs_by_type: dict):
    """Derive process checklist for a Sales Order."""
    items = []

    # Common: customer PO attached
    has_customer_po = docs_by_type.get("customer_po", 0) > 0
    items.append({"key": "customer_po_attached", "label": "Customer PO attached", "satisfied": has_customer_po})

    if order_type == "warehouse":
        # Warehouse: approval requested + granted + warehouse agreement
        approval = await _get_latest_approval(db, "sales_order", sales_order_id)
        items.append({"key": "approval_requested", "label": "Approval requested", "satisfied": approval is not None})
        items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})
        has_agreement = docs_by_type.get("warehouse_agreement", 0) > 0
        items.append({"key": "warehouse_agreement", "label": "Warehouse agreement attached", "satisfied": has_agreement})
    else:
        # Drop-ship: DS PO draft created + approval granted
        ds_draft_count = await db[PO_DRAFTS_COLL].count_documents(
            {"sales_order_id": sales_order_id, "po_type": "drop_ship"}
        )
        items.append({"key": "ds_po_draft_created", "label": "Drop-Ship PO draft created", "satisfied": ds_draft_count > 0})
        approval = await _get_latest_approval(db, "sales_order", sales_order_id)
        items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})

    all_satisfied = all(i["satisfied"] for i in items)
    return items, all_satisfied


def _derive_po_draft_checklist(draft: dict, doc_count: int, docs_by_type: dict, approval=None):
    """Derive process checklist for a PO Draft."""
    items = []

    # Vendor assigned
    has_vendor = bool(draft.get("vendor_name") or draft.get("vendor_id"))
    items.append({"key": "vendor_assigned", "label": "Vendor assigned", "satisfied": has_vendor})

    # Export-ready for BC (has lines and vendor)
    has_lines = len(draft.get("lines", [])) > 0
    export_ready = has_vendor and has_lines
    items.append({"key": "export_ready", "label": "Export-ready for BC", "satisfied": export_ready})

    # Approval granted
    items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})

    all_satisfied = all(i["satisfied"] for i in items)
    return items, all_satisfied


# ═══════════════════════════════════════════════════════════════
# APPROVAL WORKFLOW TRACKING
# ═══════════════════════════════════════════════════════════════

APPROVAL_LOGS_COLL = "approval_logs"
VALID_APPROVAL_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_APPROVAL_TYPES = ("sales_order", "purchase_order")
VALID_APPROVAL_STATUSES = ("pending", "approved", "rejected")


async def _get_latest_approval(db, entity_type: str, entity_id: str):
    """Return the latest approval record for an entity, or None."""
    doc = await db[APPROVAL_LOGS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0},
        sort=[("requested_at", -1)],
    )
    return doc


# ═══════════════════════════════════════════════════════════════
# OPERATIONS QUEUE (UNIFIED WORKLIST)
# ═══════════════════════════════════════════════════════════════

PRIORITY_WEIGHTS = {
    "missing_approval": 50,
    "missing_documents": 40,
    "inventory_shortage": 35,
    "missing_po_draft": 30,
    "missing_vendor": 25,
    "pending_bc_export": 20,
    "pending_bc_response": 15,
    "pending_shipment": 10,
    "pending_invoice": 5,
}

ESCALATION_SCORE = {"due_soon": 10, "overdue": 20, "escalated": 30}


# ═══════════════════════════════════════════════════════════════
# ESCALATIONS & DUE DATES
# ═══════════════════════════════════════════════════════════════

ESCALATIONS_COLL = "escalations"
VALID_ESCALATION_STATUSES = ("on_track", "due_soon", "overdue", "escalated")


def _derive_escalation_status(due_date_str: str, current_status: str = ""):
    """Derive escalation status from due_date vs current date."""
    if current_status == "escalated":
        return "escalated"
    try:
        due = datetime.fromisoformat(due_date_str[:10]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "on_track"
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (due - now).days
    if delta < 0:
        return "overdue"
    if delta <= 3:
        return "due_soon"
    return "on_track"


def _calc_days(due_date_str: str):
    """Return (days_to_due, days_overdue) from due_date string."""
    try:
        due = datetime.fromisoformat(due_date_str[:10]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None, None
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (due - now).days
    if delta >= 0:
        return delta, 0
    return 0, abs(delta)


async def _get_escalation(db, entity_type: str, entity_id: str):
    """Return latest escalation for an entity, or None."""
    doc = await db[ESCALATIONS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


# ═══════════════════════════════════════════════════════════════
# ASSIGNMENTS & OWNERSHIP
# ═══════════════════════════════════════════════════════════════

ASSIGNMENTS_COLL = "assignments"
VALID_ASSIGNMENT_STATUSES = ("assigned", "in_progress", "waiting", "completed")


async def _get_active_assignment(db, entity_type: str, entity_id: str):
    """Return the latest active (non-completed) assignment for an entity, or None."""
    doc = await db[ASSIGNMENTS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id, "assignment_status": {"$ne": "completed"}},
        {"_id": 0},
        sort=[("assigned_at", -1)],
    )
    return doc


async def _get_assignment_enrichment(db, entity_type: str, entity_id: str):
    """Return assignment enrichment fields for summary/detail/queue."""
    asgn = await _get_active_assignment(db, entity_type, entity_id)
    if not asgn:
        return {"current_owner": None, "assignment_status": "unassigned", "assignment_updated_at": None}
    return {
        "current_owner": asgn.get("assigned_to", ""),
        "assignment_status": asgn.get("assignment_status", "assigned"),
        "assignment_updated_at": asgn.get("updated_at", asgn.get("assigned_at", "")),
    }


# ═══════════════════════════════════════════════════════════════
# ACTIVITIES & NOTES TIMELINE
# ═══════════════════════════════════════════════════════════════

ACTIVITIES_COLL = "activities"
VALID_ACTIVITY_TYPES = (
    "note", "assignment", "approval", "document", "bc_export",
    "bc_response", "shipment", "invoice", "receipt", "escalation", "system",
)


async def _create_activity(db, entity_type: str, entity_id: str, activity_type: str,
                           title: str, body_text: str = "", created_by: str = "system", metadata: dict = None):
    """Internal helper to create an activity record."""
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body_text,
        "created_by": created_by,
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLL].insert_one(record.copy())
    record.pop("_id", None)
    return record


async def _get_activity_enrichment(db, entity_type: str, entity_id: str):
    """Return activity enrichment fields for summary/detail."""
    latest = await db[ACTIVITIES_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0, "created_at": 1, "activity_type": 1},
        sort=[("created_at", -1)],
    )
    count = await db[ACTIVITIES_COLL].count_documents(
        {"entity_type": entity_type, "entity_id": entity_id}
    )
    if latest:
        return {
            "latest_activity_at": latest.get("created_at", ""),
            "latest_activity_type": latest.get("activity_type", ""),
            "activity_count": count,
        }
    return {"latest_activity_at": "", "latest_activity_type": "", "activity_count": 0}


# ═══════════════════════════════════════════════════════════════
# SAVED VIEWS & PERSONAL QUEUE PRESETS
# ═══════════════════════════════════════════════════════════════

SAVED_VIEWS_COLL = "saved_views"
VALID_VIEW_TYPES = ("operations_queue", "sales_orders", "po_drafts")


class SavedViewIn(BaseModel):
    view_type: str = Field(...)
    name: str = Field(..., min_length=1)
    is_default: bool = Field(default=False)
    created_by: str = Field(default="user")
    filters: dict = Field(default_factory=dict)
    sort: dict = Field(default_factory=dict)
    notes: str = Field(default="")


class SavedViewUpdateIn(BaseModel):
    name: str = Field(default="")
    is_default: bool = Field(default=None)
    filters: dict = Field(default=None)
    sort: dict = Field(default=None)
    notes: str = Field(default=None)


@router.post("/saved-views")
async def api_create_saved_view(body: SavedViewIn):
    """Create a saved view."""
    import uuid as _uuid

    if body.view_type not in VALID_VIEW_TYPES:
        raise HTTPException(status_code=422, detail=f"view_type must be one of: {VALID_VIEW_TYPES}")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # If setting as default, unset previous default for same view_type + created_by
    if body.is_default:
        await db[SAVED_VIEWS_COLL].update_many(
            {"view_type": body.view_type, "created_by": body.created_by.strip(), "is_default": True},
            {"$set": {"is_default": False, "updated_at": now}},
        )

    record = {
        "saved_view_id": f"SV-{_uuid.uuid4().hex[:8].upper()}",
        "view_type": body.view_type,
        "name": body.name.strip(),
        "is_default": body.is_default,
        "created_by": body.created_by.strip(),
        "created_at": now,
        "updated_at": now,
        "filters": body.filters,
        "sort": body.sort,
        "notes": body.notes.strip(),
    }
    await db[SAVED_VIEWS_COLL].insert_one(record.copy())
    record.pop("_id", None)
    return record


@router.get("/saved-views")
async def api_list_saved_views(view_type: str = "", created_by: str = ""):
    """List saved views, optionally filtered."""
    db = get_db()
    query = {}
    if view_type:
        query["view_type"] = view_type
    if created_by:
        query["created_by"] = created_by
    cursor = db[SAVED_VIEWS_COLL].find(query, {"_id": 0}).sort("updated_at", -1)
    entries = await cursor.to_list(length=100)
    return {"total": len(entries), "entries": entries}


@router.patch("/saved-views/{saved_view_id}")
async def api_update_saved_view(saved_view_id: str, body: SavedViewUpdateIn):
    """Update a saved view."""
    db = get_db()
    existing = await db[SAVED_VIEWS_COLL].find_one({"saved_view_id": saved_view_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Saved view '{saved_view_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if body.name and body.name.strip():
        update["name"] = body.name.strip()
    if body.is_default is not None:
        update["is_default"] = body.is_default
        if body.is_default:
            await db[SAVED_VIEWS_COLL].update_many(
                {"view_type": existing["view_type"], "created_by": existing.get("created_by", "user"),
                 "is_default": True, "saved_view_id": {"$ne": saved_view_id}},
                {"$set": {"is_default": False, "updated_at": now}},
            )
    if body.filters is not None:
        update["filters"] = body.filters
    if body.sort is not None:
        update["sort"] = body.sort
    if body.notes is not None:
        update["notes"] = body.notes.strip() if body.notes else ""

    await db[SAVED_VIEWS_COLL].update_one({"saved_view_id": saved_view_id}, {"$set": update})
    result = {**existing, **update}
    return result


@router.delete("/saved-views/{saved_view_id}")
async def api_delete_saved_view(saved_view_id: str):
    """Delete a saved view."""
    db = get_db()
    result = await db[SAVED_VIEWS_COLL].delete_one({"saved_view_id": saved_view_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Saved view '{saved_view_id}' not found")
    return {"deleted": saved_view_id}


async def _build_so_queue_items(db, limit: int = 200):
    """Build queue items for Sales Orders that need attention."""
    items = []

    # Gather all known SOs from order_commitment movements + so_order_types + shipment/invoice logs
    so_ids = set()
    async for doc in db[SO_ORDER_TYPES_COLL].find({}, {"_id": 0, "sales_order_id": 1}):
        so_ids.add(doc["sales_order_id"])
    async for doc in db[MOVEMENTS_COLL].find(
        {"movement_type": "order_commitment"}, {"_id": 0, "reference_id": 1}
    ).limit(500):
        so_ids.add(doc["reference_id"])
    async for doc in db[BC_SHIPMENT_LOGS_COLL].find({}, {"_id": 0, "sales_order_id": 1}).limit(500):
        so_ids.add(doc["sales_order_id"])
    async for doc in db[DS_VENDOR_SHIPMENT_LOGS_COLL].find({}, {"_id": 0, "sales_order_id": 1}).limit(500):
        so_ids.add(doc["sales_order_id"])

    for so_id in so_ids:
        order_type = await _get_order_type(db, so_id)
        approval = await _get_latest_approval(db, "sales_order", so_id)
        doc_count, docs_by_type, _ = await _get_document_links_summary(db, "sales_order", so_id)

        score = 0
        actions = []

        # Approval missing
        approval_status = approval["approval_status"] if approval else "not_requested"
        if approval_status != "approved":
            score += PRIORITY_WEIGHTS["missing_approval"]
            actions.append("Approval missing" if approval_status == "not_requested" else f"Approval {approval_status}")

        # Customer PO document missing
        if docs_by_type.get("customer_po", 0) == 0:
            score += PRIORITY_WEIGHTS["missing_documents"]
            actions.append("Customer PO document missing")

        if order_type == "warehouse":
            # Inventory shortage: check if remaining committed > 0 and no shipment yet
            has_shipment = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_invoice = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0

            if not has_shipment:
                score += PRIORITY_WEIGHTS["pending_shipment"]
                actions.append("Shipment not yet recorded")
            if not has_invoice:
                score += PRIORITY_WEIGHTS["pending_invoice"]
                actions.append("Invoice not yet captured")
        else:
            # Drop-ship
            ds_draft_count = await db[PO_DRAFTS_COLL].count_documents(
                {"sales_order_id": so_id, "po_type": "drop_ship"}
            )
            if ds_draft_count == 0:
                score += PRIORITY_WEIGHTS["missing_po_draft"]
                actions.append("Drop-Ship PO draft not yet created")

            has_vendor_ship = await db[DS_VENDOR_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_bc_ship = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_invoice = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0

            if not has_vendor_ship and not has_bc_ship:
                score += PRIORITY_WEIGHTS["pending_shipment"]
                actions.append("Vendor shipment not recorded")
            if not has_invoice:
                score += PRIORITY_WEIGHTS["pending_invoice"]
                actions.append("Invoice not yet captured")

        if score == 0:
            continue  # Fully complete, no action needed

        # Determine next action
        next_action = actions[0] if actions else "Review"

        # Get created_at from the type record or first movement
        type_rec = await db[SO_ORDER_TYPES_COLL].find_one({"sales_order_id": so_id}, {"_id": 0, "set_at": 1})
        created_at = (type_rec or {}).get("set_at", "")

        checklist_items, checklist_complete = await _derive_so_checklist(db, so_id, order_type, doc_count, docs_by_type)

        items.append({
            "entity_type": "sales_order",
            "entity_id": so_id,
            "order_type": order_type,
            "vendor_name": "",
            "approval_status": approval_status,
            "checklist_complete": checklist_complete,
            "priority_score": score,
            "action_required": actions,
            "next_action": next_action,
            "created_at": created_at,
            "due_date": "",
            "escalation_status": "",
            "days_to_due": None,
            "days_overdue": None,
        })

    # Enrich with escalation data
    for item in items:
        esc = await _get_escalation(db, "sales_order", item["entity_id"])
        if esc:
            due = esc.get("due_date", "")
            esc_status = _derive_escalation_status(due, esc.get("escalation_status", ""))
            days_to, days_over = _calc_days(due)
            item["due_date"] = due
            item["escalation_status"] = esc_status
            item["days_to_due"] = days_to
            item["days_overdue"] = days_over
            item["priority_score"] += ESCALATION_SCORE.get(esc_status, 0)
            if esc_status in ("due_soon", "overdue", "escalated"):
                item["action_required"].append(f"{esc_status.replace('_', ' ').title()}: due {due}")

    return items


async def _build_po_draft_queue_items(db, limit: int = 200):
    """Build queue items for PO Drafts that need attention."""
    items = []
    cursor = db[PO_DRAFTS_COLL].find(
        {"status": {"$nin": ["archived"]}}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)

    async for draft in cursor:
        draft_id = draft["po_draft_id"]
        score = 0
        actions = []

        # Vendor missing
        has_vendor = bool(draft.get("vendor_name") or draft.get("vendor_id"))
        if not has_vendor:
            score += PRIORITY_WEIGHTS["missing_vendor"]
            actions.append("Vendor not assigned")

        # Approval not granted
        approval = await _get_latest_approval(db, "po_draft", draft_id)
        approval_status = approval["approval_status"] if approval else "not_requested"
        if approval_status != "approved":
            score += PRIORITY_WEIGHTS["missing_approval"]
            actions.append("Approval not granted")

        # BC export not yet performed
        bc_payload = draft.get("bc_payload_snapshot")
        if not bc_payload:
            score += PRIORITY_WEIGHTS["pending_bc_export"]
            actions.append("BC export not yet performed")

        # BC response not yet captured
        bc_response = draft.get("bc_response_status")
        if not bc_response:
            score += PRIORITY_WEIGHTS["pending_bc_response"]
            actions.append("BC response not yet captured")

        if score == 0:
            continue

        next_action = actions[0] if actions else "Review"
        doc_count, docs_by_type, _ = await _get_document_links_summary(db, "po_draft", draft_id)
        checklist_items, checklist_complete = _derive_po_draft_checklist(draft, doc_count, docs_by_type, approval=approval)

        items.append({
            "entity_type": "po_draft",
            "entity_id": draft_id,
            "order_type": draft.get("po_type", "warehouse_supply"),
            "vendor_name": draft.get("vendor_name", ""),
            "approval_status": approval_status,
            "checklist_complete": checklist_complete,
            "priority_score": score,
            "action_required": actions,
            "next_action": next_action,
            "created_at": draft.get("created_at", ""),
            "due_date": "",
            "escalation_status": "",
            "days_to_due": None,
            "days_overdue": None,
        })

    # Enrich with escalation data
    for item in items:
        esc = await _get_escalation(db, "po_draft", item["entity_id"])
        if esc:
            due = esc.get("due_date", "")
            esc_status = _derive_escalation_status(due, esc.get("escalation_status", ""))
            days_to, days_over = _calc_days(due)
            item["due_date"] = due
            item["escalation_status"] = esc_status
            item["days_to_due"] = days_to
            item["days_overdue"] = days_over
            item["priority_score"] += ESCALATION_SCORE.get(esc_status, 0)
            if esc_status in ("due_soon", "overdue", "escalated"):
                item["action_required"].append(f"{esc_status.replace('_', ' ').title()}: due {due}")

    return items


@router.get("/operations-queue")
async def api_operations_queue(
    entity_type: str = "",
    status: str = "",
    escalation: str = "",
    assigned_to: str = "",
    assignment_status: str = "",
    unassigned_only: str = "",
    stale_days: int = 0,
    sort_by: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """Return a prioritized list of entities requiring operational attention."""
    db = get_db()

    all_items = []
    if not entity_type or entity_type == "sales_order":
        all_items.extend(await _build_so_queue_items(db))
    if not entity_type or entity_type == "po_draft":
        all_items.extend(await _build_po_draft_queue_items(db))

    # Enrich with assignment + activity data
    for item in all_items:
        asgn = await _get_assignment_enrichment(db, item["entity_type"], item["entity_id"])
        item.update(asgn)
        act = await _get_activity_enrichment(db, item["entity_type"], item["entity_id"])
        item.update(act)
        # +10 priority for unassigned high-priority items
        if not item.get("current_owner") and item["priority_score"] >= 40:
            item["priority_score"] += 10

    # Filter by approval status if provided
    if status:
        all_items = [i for i in all_items if i["approval_status"] == status]

    # Filter by escalation status if provided
    if escalation:
        all_items = [i for i in all_items if i.get("escalation_status") == escalation]

    # Filter by assignment
    if assigned_to:
        all_items = [i for i in all_items if (i.get("current_owner") or "").lower() == assigned_to.lower()]
    if assignment_status:
        all_items = [i for i in all_items if i.get("assignment_status") == assignment_status]
    if unassigned_only.lower() in ("true", "1", "yes"):
        all_items = [i for i in all_items if not i.get("current_owner")]

    # Filter for stale items (no activity in N days)
    if stale_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        all_items = [i for i in all_items if not i.get("latest_activity_at") or i["latest_activity_at"] < cutoff]

    # Sort
    if sort_by == "latest_activity":
        all_items.sort(key=lambda x: (x.get("latest_activity_at") or ""), reverse=True)
    else:
        all_items.sort(key=lambda x: (-x["priority_score"], x["created_at"] or ""))

    total = len(all_items)
    page = all_items[offset: offset + limit]
    high_priority = sum(1 for i in all_items if i["priority_score"] >= 40)
    due_soon_count = sum(1 for i in all_items if i.get("escalation_status") == "due_soon")
    overdue_count = sum(1 for i in all_items if i.get("escalation_status") == "overdue")
    escalated_count = sum(1 for i in all_items if i.get("escalation_status") == "escalated")

    # Assignment counts
    unassigned_count = sum(1 for i in all_items if not i.get("current_owner"))
    in_progress_count = sum(1 for i in all_items if i.get("assignment_status") == "in_progress")
    waiting_count = sum(1 for i in all_items if i.get("assignment_status") == "waiting")

    # Activity counts
    now_iso = datetime.now(timezone.utc)
    today_start = now_iso.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    stale_cutoff = (now_iso - timedelta(days=7)).isoformat()
    recent_activity_today = sum(1 for i in all_items if i.get("latest_activity_at", "") >= today_start)
    no_recent_activity_7d = sum(1 for i in all_items if not i.get("latest_activity_at") or i["latest_activity_at"] < stale_cutoff)

    # Saved views counts
    sv_total = await db[SAVED_VIEWS_COLL].count_documents({"view_type": "operations_queue"})
    sv_default = await db[SAVED_VIEWS_COLL].find_one(
        {"view_type": "operations_queue", "is_default": True}, {"_id": 0, "name": 1}
    )

    return {
        "total": total,
        "high_priority_count": high_priority,
        "due_soon_count": due_soon_count,
        "overdue_count": overdue_count,
        "escalated_count": escalated_count,
        "unassigned_count": unassigned_count,
        "in_progress_count": in_progress_count,
        "waiting_count": waiting_count,
        "recent_activity_today": recent_activity_today,
        "no_recent_activity_7d": no_recent_activity_7d,
        "saved_views_count": sv_total,
        "default_view_name": sv_default["name"] if sv_default else "",
        "offset": offset,
        "limit": limit,
        "items": page,
    }


# ═══════════════════════════════════════════════════════════════
# BULK ACTIONS
# ═══════════════════════════════════════════════════════════════

VALID_BULK_ACTIONS = ("assign_owner", "update_assignment_status", "set_due_date", "set_escalation_status", "request_approval", "apply_template")


class BulkActionIn(BaseModel):
    entity_type: str = Field(...)
    entity_ids: list = Field(..., min_length=1)
    action: str = Field(...)
    payload: dict = Field(default_factory=dict)


@router.post("/operations-queue/bulk-action")
async def api_bulk_action(body: BulkActionIn):
    """Apply a bulk action to multiple entities."""
    import uuid as _uuid

    if body.entity_type not in ("sales_order", "po_draft"):
        raise HTTPException(status_code=422, detail="entity_type must be sales_order or po_draft")
    if body.action not in VALID_BULK_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid action. Must be one of: {VALID_BULK_ACTIONS}")
    if not body.entity_ids:
        raise HTTPException(status_code=422, detail="entity_ids must not be empty")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    results = []

    for eid in body.entity_ids:
        eid = str(eid).strip()
        try:
            # Validate entity exists
            if body.entity_type == "po_draft":
                draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": eid}, {"_id": 0, "po_draft_id": 1})
                if not draft:
                    results.append({"entity_id": eid, "status": "failed", "message": f"PO Draft '{eid}' not found"})
                    continue

            if body.action == "assign_owner":
                assigned_to = body.payload.get("assigned_to", "").strip()
                notes = body.payload.get("notes", "").strip()
                if not assigned_to:
                    results.append({"entity_id": eid, "status": "failed", "message": "assigned_to is required"})
                    continue
                existing = await db[ASSIGNMENTS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
                )
                if existing:
                    await db[ASSIGNMENTS_COLL].update_one(
                        {"assignment_id": existing["assignment_id"]},
                        {"$set": {"assigned_to": assigned_to, "assignment_status": "assigned", "notes": notes, "updated_at": now}},
                    )
                else:
                    await db[ASSIGNMENTS_COLL].insert_one({
                        "assignment_id": f"ASGN-{_uuid.uuid4().hex[:8].upper()}",
                        "entity_type": body.entity_type, "entity_id": eid,
                        "assigned_to": assigned_to, "assigned_by": "bulk_action",
                        "assigned_at": now, "assignment_status": "assigned",
                        "notes": notes, "updated_at": now,
                    })
                await _create_activity(db, body.entity_type, eid, "assignment",
                                       f"Bulk assigned to {assigned_to}", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Assigned to {assigned_to}"})

            elif body.action == "update_assignment_status":
                new_status = body.payload.get("assignment_status", "").strip()
                if new_status not in VALID_ASSIGNMENT_STATUSES:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Invalid status: {new_status}"})
                    continue
                existing = await db[ASSIGNMENTS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
                )
                if not existing:
                    results.append({"entity_id": eid, "status": "failed", "message": "No active assignment found"})
                    continue
                await db[ASSIGNMENTS_COLL].update_one(
                    {"assignment_id": existing["assignment_id"]},
                    {"$set": {"assignment_status": new_status, "updated_at": now}},
                )
                await _create_activity(db, body.entity_type, eid, "assignment",
                                       f"Bulk status update: {new_status}", "", "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Status updated to {new_status}"})

            elif body.action == "set_due_date":
                due_date = body.payload.get("due_date", "").strip()
                notes = body.payload.get("notes", "").strip()
                if not due_date:
                    results.append({"entity_id": eid, "status": "failed", "message": "due_date is required"})
                    continue
                derived_status = _derive_escalation_status(due_date)
                existing = await db[ESCALATIONS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid}, {"_id": 0}
                )
                if existing:
                    await db[ESCALATIONS_COLL].update_one(
                        {"entity_type": body.entity_type, "entity_id": eid},
                        {"$set": {"due_date": due_date, "escalation_status": derived_status, "notes": notes, "updated_at": now}},
                    )
                else:
                    await db[ESCALATIONS_COLL].insert_one({
                        "escalation_id": f"ESC-{_uuid.uuid4().hex[:8].upper()}",
                        "entity_type": body.entity_type, "entity_id": eid,
                        "due_date": due_date, "escalation_status": derived_status,
                        "notes": notes, "created_at": now, "updated_at": now,
                    })
                await _create_activity(db, body.entity_type, eid, "escalation",
                                       f"Bulk due date set: {due_date}", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Due date set to {due_date} ({derived_status})"})

            elif body.action == "set_escalation_status":
                esc_status = body.payload.get("escalation_status", "").strip()
                if esc_status not in ("on_track", "due_soon", "overdue", "escalated"):
                    results.append({"entity_id": eid, "status": "failed", "message": f"Invalid escalation_status: {esc_status}"})
                    continue
                existing = await db[ESCALATIONS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid}, {"_id": 0}
                )
                if not existing:
                    results.append({"entity_id": eid, "status": "failed", "message": "No escalation record found. Set a due date first."})
                    continue
                await db[ESCALATIONS_COLL].update_one(
                    {"entity_type": body.entity_type, "entity_id": eid},
                    {"$set": {"escalation_status": esc_status, "updated_at": now}},
                )
                await _create_activity(db, body.entity_type, eid, "escalation",
                                       f"Bulk escalation: {esc_status}", "", "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Escalation set to {esc_status}"})

            elif body.action == "request_approval":
                approval_type = body.payload.get("approval_type", "manager_review")
                notes = body.payload.get("notes", "").strip()
                requested_by = body.payload.get("requested_by", "bulk_action").strip()
                record = {
                    "approval_id": f"APR-{_uuid.uuid4().hex[:8].upper()}",
                    "entity_type": body.entity_type, "entity_id": eid,
                    "approval_type": approval_type,
                    "approval_status": "pending",
                    "requested_by": requested_by,
                    "requested_at": now,
                    "decided_by": "", "decided_at": "", "notes": notes,
                }
                await db[APPROVAL_LOGS_COLL].insert_one(record.copy())
                await _create_activity(db, body.entity_type, eid, "approval",
                                       f"Bulk approval requested ({approval_type})", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Approval requested ({approval_type})"})

            elif body.action == "apply_template":
                tmpl_id = body.payload.get("template_id", "").strip()
                if not tmpl_id:
                    results.append({"entity_id": eid, "status": "failed", "message": "template_id is required"})
                    continue
                tmpl = await db[TEMPLATES_COLL].find_one({"template_id": tmpl_id, "is_active": True}, {"_id": 0})
                if not tmpl:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Template '{tmpl_id}' not found or inactive"})
                    continue
                if tmpl["entity_type"] != body.entity_type:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Template entity_type mismatch"})
                    continue
                apply_res = await _apply_template_to_entity(db, tmpl, body.entity_type, eid)
                results.append({"entity_id": eid, "status": "success", "message": f"Template applied: {', '.join(apply_res['actions_applied'])} | skipped: {', '.join(apply_res['actions_skipped'])}"})

        except Exception as e:
            results.append({"entity_id": eid, "status": "failed", "message": str(e)})

    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")

    return {
        "action": body.action,
        "entity_type": body.entity_type,
        "processed_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════
# OPERATIONAL TEMPLATES
# ═══════════════════════════════════════════════════════════════

TEMPLATES_COLL = "operational_templates"
VALID_TEMPLATE_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_ORDER_TYPES = ("warehouse", "drop_ship")


@router.get("/templates")
async def api_list_templates(entity_type: str = "", applies_to_order_type: str = "", is_active: str = ""):
    """List templates, optionally filtered."""
    db = get_db()
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if applies_to_order_type:
        query["applies_to_order_type"] = applies_to_order_type
    if is_active.lower() in ("true", "1"):
        query["is_active"] = True
    elif is_active.lower() in ("false", "0"):
        query["is_active"] = False
    cursor = db[TEMPLATES_COLL].find(query, {"_id": 0}).sort("updated_at", -1)
    entries = await cursor.to_list(length=100)
    return {"total": len(entries), "entries": entries}


async def _apply_template_to_entity(db, tmpl: dict, entity_type: str, entity_id: str):
    """Apply a template to an entity. Returns actions_applied, actions_skipped, messages."""
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    applied = []
    skipped = []
    messages = []

    # Assignment
    if tmpl.get("default_assignment_to"):
        existing_asgn = await db[ASSIGNMENTS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
        )
        if existing_asgn:
            skipped.append("assignment")
            messages.append(f"Assignment already exists ({existing_asgn.get('assigned_to', '')})")
        else:
            await db[ASSIGNMENTS_COLL].insert_one({
                "assignment_id": f"ASGN-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "assigned_to": tmpl["default_assignment_to"],
                "assigned_by": "template", "assigned_at": now,
                "assignment_status": "assigned", "notes": f"From template: {tmpl['name']}",
                "updated_at": now,
            })
            await _create_activity(db, entity_type, entity_id, "assignment",
                                   f"Template assigned to {tmpl['default_assignment_to']}", f"Template: {tmpl['name']}", "template")
            applied.append("assignment")
            messages.append(f"Assigned to {tmpl['default_assignment_to']}")

    # Due date / escalation
    if tmpl.get("default_due_days", 0) > 0:
        existing_esc = await db[ESCALATIONS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
        )
        if existing_esc:
            skipped.append("due_date")
            messages.append(f"Due date already set ({existing_esc.get('due_date', '')})")
        else:
            due_date = (datetime.now(timezone.utc) + timedelta(days=tmpl["default_due_days"])).isoformat()
            esc_status = tmpl.get("default_escalation_status", "") or _derive_escalation_status(due_date)
            await db[ESCALATIONS_COLL].insert_one({
                "escalation_id": f"ESC-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "due_date": due_date, "escalation_status": esc_status,
                "notes": f"From template: {tmpl['name']}", "created_at": now, "updated_at": now,
            })
            await _create_activity(db, entity_type, entity_id, "escalation",
                                   f"Template due date: +{tmpl['default_due_days']} days", f"Template: {tmpl['name']}", "template")
            applied.append("due_date")
            messages.append(f"Due date set to +{tmpl['default_due_days']} days")

    # Approval
    if tmpl.get("auto_request_approval"):
        existing_apr = await db[APPROVAL_LOGS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id, "approval_status": "pending"}, {"_id": 0}
        )
        if existing_apr:
            skipped.append("approval")
            messages.append("Pending approval already exists")
        else:
            await db[APPROVAL_LOGS_COLL].insert_one({
                "approval_id": f"APR-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "approval_type": "manager_review", "approval_status": "pending",
                "requested_by": "template", "requested_at": now,
                "decided_by": "", "decided_at": "",
                "notes": f"From template: {tmpl['name']}",
            })
            await _create_activity(db, entity_type, entity_id, "approval",
                                   f"Template approval requested (manager_review)", f"Template: {tmpl['name']}", "template")
            applied.append("approval")
            messages.append("Approval requested (manager_review)")

    # Activity for template applied
    await _create_activity(db, entity_type, entity_id, "system",
                           f"Template applied: {tmpl['name']}", f"Applied: {', '.join(applied) or 'none'}, Skipped: {', '.join(skipped) or 'none'}", "template")

    return {"template_id": tmpl["template_id"], "entity_type": entity_type, "entity_id": entity_id,
            "actions_applied": applied, "actions_skipped": skipped, "messages": messages}


class ShortageLineReq(BaseModel):
    item: str
    qty_needed: float
    qty_available: float


class ShortageReq(BaseModel):
    sales_order_id: str
    lines: list[ShortageLineReq]


@incoming_supply_router.post("/from-shortage")
async def api_create_from_shortage(body: ShortageReq):
    """Create incoming supply records for SHORT items on a Sales Order.

    Returns 409 if a duplicate supply record already exists for the same
    item + order reference. Returns 422 if shortage <= 0.
    """
    db = get_db()
    try:
        from services.inventory_so_integration import create_shortage_supply
        result = await create_shortage_supply(
            db,
            sales_order_id=body.sales_order_id,
            lines=[{"item": ln.item, "qty_needed": ln.qty_needed, "qty_available": ln.qty_available} for ln in body.lines],
            created_by="gpi_hub",
        )
        # If ALL lines were duplicates and nothing was created, return 409
        if result["created"] == 0 and len(result["duplicates"]) > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"Duplicate incoming supply already exists for: {', '.join(result['duplicates'])}",
                    "duplicates": result["duplicates"],
                },
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


