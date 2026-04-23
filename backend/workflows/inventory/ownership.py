"""
Customer-Owned Ware (COW) ownership module.

Lane C Step 1 — Customer-Owned Ware (LANE_A_SIGNED_SCOPE.md §3 row 1 + §4b).

Responsibilities:
  * CRUD over the `cp_item_registry` collection (single source of truth for CP items)
  * Ownership classification of an item_no
  * The COW_ITEM_ON_PO hard-block check invoked from the canonical readiness path

Non-responsibilities (deliberately out of scope for Step 1):
  * No gate_framework coupling — that ships in Lane C Step 2.75
  * No SO-side gate (COW_SO_USES_BASE_ITEM) — deferred
  * No BC read/write — this registry is owned by Document Hub, not BC
  * No frontend UI
  * No background re-evaluator — T13/T14 flip via explicit canonical readiness re-eval
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("workflows.inventory.ownership")

# ── Constants ────────────────────────────────────────────────────────────────

CP_ITEM_REGISTRY = "cp_item_registry"

# Per signed §4b fallback: treat items matching this pattern as CP even if not
# in the registry. The enforcement rule says such items are treated as
# "unknown_cp_pattern" and still block POs — the registry check runs first.
CP_ITEM_PATTERN = re.compile(r"^.*-CP[A-Z0-9]+$")

# Doc types that trigger the CP-on-PO hard block. Lowercased for comparison.
PURCHASE_ORDER_DOC_TYPES = frozenset({
    "po",
    "purchase_order",
})

# Doc types allowed by the signed §4b adjustment-journal carve-out.
ADJUSTMENT_JOURNAL_DOC_TYPES = frozenset({
    "inventoryadjustment",
    "adjustment_journal",
    "inventory_adjustment",
    "adjustmentjournal",
})

# Env-configured actor email authorized to retire CP items (signed §4b:
# "Only items@gamerpackaging.com can set status=retired — a manual admin action").
COW_RETIREMENT_ACTOR_EMAIL = os.environ.get(
    "COW_RETIREMENT_ACTOR_EMAIL", "items@gamerpackaging.com"
).strip().lower()

# Blocking-reason code appended to readiness.blocking_reasons.
BLOCKER_CODE = "cow_item_on_po"
BLOCKER_CODE_SO_BASE = "cow_so_uses_base_item"
BLOCKER_CODE_SO_WRONG_CUSTOMER = "cow_so_wrong_customer"

# Doc types that trigger the SO-side COW gates.
SALES_DOC_TYPES = frozenset({
    "sales_invoice",
    "sales_order",
    "so_confirmation",
    "ds_sales_order",
    "wh_sales_order",
})

# Ownership classifier output type.
OwnershipState = Literal[
    "gamer",                       # not CP — Gamer-owned stock
    "customer_owned_active",       # in registry, status=active → BLOCK
    "customer_owned_retired",      # in registry, status=retired → ALLOW
    "unknown_cp_pattern",          # matches CP regex, not in registry → BLOCK
]


# ── Pydantic models ──────────────────────────────────────────────────────────

class CpItemCreate(BaseModel):
    item_no: str = Field(..., description="CP item number (uppercased on insert)")
    customer_no: str = Field(..., description="BC customer whose CP this is")
    base_item_no: str = Field(..., description="Underlying non-CP SKU billed on SO")
    canonical_location: str = Field(..., description="Warehouse where adjustment journals are allowed")
    notes: str = Field("", description="Free-form admin notes")

    @field_validator("item_no", "customer_no", "base_item_no", "canonical_location")
    @classmethod
    def _strip_and_require(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must be non-empty")
        return v


class CpItem(BaseModel):
    item_no: str
    customer_no: str
    base_item_no: str
    canonical_location: str
    linked_invoice_ids: List[str] = Field(default_factory=list)
    status: Literal["active", "retired"]
    notes: str = ""
    created_utc: str
    updated_utc: str
    created_by: str
    retired_by: Optional[str] = None
    retired_at: Optional[str] = None


# ── Index management ─────────────────────────────────────────────────────────

async def ensure_indexes(db) -> None:
    """Ensure indexes per signed §4b. Called from app startup.

    Idempotent: motor's `create_index` is a no-op if the index already exists
    with the same spec.
    """
    await db[CP_ITEM_REGISTRY].create_index("item_no", unique=True, name="cp_item_no_uniq")
    await db[CP_ITEM_REGISTRY].create_index(
        [("customer_no", 1), ("status", 1)],
        name="cp_customer_status",
    )
    logger.info("[COW] cp_item_registry indexes ensured")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_cp_item_pattern(item_no: str) -> bool:
    """Signed §4b fallback — matches `.*-CP[A-Z0-9]+$` (case-sensitive per signed spec).

    Pure function, no I/O.
    """
    if not item_no:
        return False
    return bool(CP_ITEM_PATTERN.match(item_no.strip()))


# ── Registry CRUD ────────────────────────────────────────────────────────────

async def get_cp_item(db, item_no: str) -> Optional[Dict[str, Any]]:
    """Lookup a single registry row. `_id` excluded."""
    if not item_no:
        return None
    return await db[CP_ITEM_REGISTRY].find_one(
        {"item_no": item_no.strip().upper()}, {"_id": 0}
    )


async def list_cp_items_for_customer(
    db,
    customer_no: str,
    active_only: bool = True,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"customer_no": customer_no}
    if active_only:
        q["status"] = "active"
    cursor = db[CP_ITEM_REGISTRY].find(q, {"_id": 0}).limit(limit)
    return await cursor.to_list(length=limit)


async def list_all_cp_items(
    db,
    customer_no: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if customer_no:
        q["customer_no"] = customer_no
    if status:
        q["status"] = status
    cursor = db[CP_ITEM_REGISTRY].find(q, {"_id": 0}).limit(limit)
    return await cursor.to_list(length=limit)


async def upsert_cp_item(
    db, payload: CpItemCreate, actor: str
) -> Dict[str, Any]:
    """Create or update a CP item (admin-gated at router boundary).

    Never flips `status` — this path only creates `active` rows or updates
    fields on existing active rows. Retirement is a separate, guarded action.
    """
    item_no = payload.item_no.strip().upper()
    now = _now_iso()

    existing = await db[CP_ITEM_REGISTRY].find_one(
        {"item_no": item_no}, {"_id": 0}
    )
    if existing is None:
        doc = {
            "item_no": item_no,
            "customer_no": payload.customer_no,
            "base_item_no": payload.base_item_no,
            "canonical_location": payload.canonical_location,
            "linked_invoice_ids": [],
            "status": "active",
            "notes": payload.notes,
            "created_utc": now,
            "updated_utc": now,
            "created_by": actor,
            "retired_by": None,
            "retired_at": None,
        }
        await db[CP_ITEM_REGISTRY].insert_one(dict(doc))
        logger.info("[COW] Created CP item %s by %s", item_no, actor)
        return doc

    # Update fields but never status (status flip requires retire_cp_item)
    update = {
        "customer_no": payload.customer_no,
        "base_item_no": payload.base_item_no,
        "canonical_location": payload.canonical_location,
        "notes": payload.notes,
        "updated_utc": now,
    }
    await db[CP_ITEM_REGISTRY].update_one(
        {"item_no": item_no}, {"$set": update}
    )
    logger.info("[COW] Updated CP item %s by %s", item_no, actor)
    return await db[CP_ITEM_REGISTRY].find_one({"item_no": item_no}, {"_id": 0})


async def retire_cp_item(db, item_no: str, actor: str) -> Dict[str, Any]:
    """Retire a CP item. Actor email must match COW_RETIREMENT_ACTOR_EMAIL.

    Signed §4b: programmatic retirement is explicitly forbidden — only the
    items@gamerpackaging.com admin path can set status=retired. The guard
    also applies inside this module (tests cover the bypass attempt).
    """
    actor_clean = (actor or "").strip().lower()
    if actor_clean != COW_RETIREMENT_ACTOR_EMAIL:
        raise PermissionError(
            f"Retirement actor {actor!r} is not authorized. "
            f"Only {COW_RETIREMENT_ACTOR_EMAIL} may retire CP items."
        )

    item_no_clean = item_no.strip().upper()
    now = _now_iso()
    result = await db[CP_ITEM_REGISTRY].find_one_and_update(
        {"item_no": item_no_clean},
        {"$set": {
            "status": "retired",
            "retired_by": actor,
            "retired_at": now,
            "updated_utc": now,
        }},
        projection={"_id": 0},
        return_document=True,
    )
    if result is None:
        raise ValueError(f"CP item {item_no_clean} not found")
    logger.info("[COW] Retired CP item %s by %s", item_no_clean, actor)
    return result


async def append_linked_invoice(db, item_no: str, invoice_id: str) -> None:
    """Append an invoice id to linked_invoice_ids. Idempotent via $addToSet."""
    if not item_no or not invoice_id:
        return
    await db[CP_ITEM_REGISTRY].update_one(
        {"item_no": item_no.strip().upper()},
        {
            "$addToSet": {"linked_invoice_ids": invoice_id},
            "$set": {"updated_utc": _now_iso()},
        },
    )


# ── Ownership classifier ─────────────────────────────────────────────────────

async def classify_item_ownership(db, item_no: str) -> OwnershipState:
    """Single source of truth for item ownership classification.

    Lookup order (signed §4b):
        1. Registry row exists + status=active  → customer_owned_active
        2. Registry row exists + status=retired → customer_owned_retired
        3. No registry row, matches CP regex    → unknown_cp_pattern
        4. Otherwise                            → gamer
    """
    if not item_no:
        return "gamer"
    row = await get_cp_item(db, item_no)
    if row is not None:
        if row.get("status") == "active":
            return "customer_owned_active"
        if row.get("status") == "retired":
            return "customer_owned_retired"
    if is_cp_item_pattern(item_no):
        return "unknown_cp_pattern"
    return "gamer"


# ── Hard-block check (invoked from canonical readiness path) ─────────────────

def _is_purchase_order_doc(doc: Dict[str, Any]) -> bool:
    """Detect a PO document via document_type/doc_type/suggested_job_type."""
    fields = (
        doc.get("document_type"),
        doc.get("doc_type"),
        doc.get("suggested_job_type"),
    )
    for f in fields:
        if f and str(f).strip().lower().replace(" ", "_") in PURCHASE_ORDER_DOC_TYPES:
            return True
    return False


def _is_adjustment_journal_doc(doc: Dict[str, Any]) -> bool:
    fields = (
        doc.get("document_type"),
        doc.get("doc_type"),
        doc.get("suggested_job_type"),
    )
    for f in fields:
        if f and str(f).strip().lower().replace(" ", "_") in ADJUSTMENT_JOURNAL_DOC_TYPES:
            return True
    return False


def _iter_doc_lines(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract line items from a document. Tolerant of several known shapes."""
    extracted = doc.get("extracted_fields") or doc.get("extracted") or {}
    lines = extracted.get("line_items") or doc.get("line_items") or []
    return [ln for ln in lines if isinstance(ln, dict)]


async def check_cow_item_on_po(
    db, doc: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Run the Step 1 hard-block check.

    Returns a list of per-line evidence dicts. Empty list = no blocker.
    Callers (unified_validation_service / document_readiness_service) are
    responsible for folding the evidence into readiness.blocking_reasons /
    readiness.explanations.

    Signed §4b enforcement:
      * customer_owned_active on PO → block
      * unknown_cp_pattern    on PO → block
      * customer_owned_retired on PO → allow (do not emit evidence)
      * Adjustment journal with positive qty into canonical_location → allow
      * Adjustment journal with CP item into non-canonical location → block
    """
    # Skip entirely if not a PO and not an adjustment journal — no enforcement
    is_po = _is_purchase_order_doc(doc)
    is_adj = _is_adjustment_journal_doc(doc)
    if not (is_po or is_adj):
        return []

    evidence: List[Dict[str, Any]] = []
    for line in _iter_doc_lines(doc):
        item_no = (line.get("item_no") or "").strip()
        if not item_no:
            continue
        ownership = await classify_item_ownership(db, item_no)

        if ownership == "customer_owned_retired":
            continue
        if ownership == "gamer":
            continue

        # Line has CP ownership signal. Two paths:
        if is_adj:
            # Adjustment-journal allowance: positive qty AND location matches
            # the registry's canonical_location for that item.
            try:
                qty = float(line.get("quantity") or line.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0.0
            line_loc = str(
                line.get("location")
                or line.get("location_code")
                or doc.get("location")
                or doc.get("location_code")
                or ""
            ).strip()
            row = await get_cp_item(db, item_no) if ownership == "customer_owned_active" else None
            canonical_loc = (row or {}).get("canonical_location", "")
            allowed = (
                ownership == "customer_owned_active"
                and qty > 0
                and canonical_loc
                and line_loc == canonical_loc
            )
            if allowed:
                continue  # §4b allow clause satisfied
            evidence.append({
                "item_no": item_no,
                "ownership": ownership,
                "customer_no": (row or {}).get("customer_no"),
                "reason": "adjustment_journal_not_allowed",
                "location": line_loc or None,
                "canonical_location": canonical_loc or None,
                "quantity": qty,
            })
            continue

        # PO path: always block
        row = await get_cp_item(db, item_no) if ownership == "customer_owned_active" else None
        evidence.append({
            "item_no": item_no,
            "ownership": ownership,
            "customer_no": (row or {}).get("customer_no"),
            "reason": "cp_item_on_purchase_order",
        })

    return evidence


def apply_cow_blocker_to_readiness(
    readiness: Dict[str, Any], evidence: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Fold COW evidence into the readiness dict using existing conventions.

    * Appends `"cow_item_on_po"` to `readiness.blocking_reasons` (list of str codes)
    * Appends a human-readable message to `readiness.explanations`
    * Persists the structured evidence list under `readiness.cow_items` for
      introspection, UI, and test assertions. Additive field; does not
      modify any existing schema.
    * Pure: mutates and returns the passed-in dict.
    """
    if not evidence:
        return readiness

    blockers = list(readiness.get("blocking_reasons") or [])
    if BLOCKER_CODE not in blockers:
        blockers.append(BLOCKER_CODE)
    readiness["blocking_reasons"] = blockers

    explanations = list(readiness.get("explanations") or [])
    item_list = ", ".join(sorted({e["item_no"] for e in evidence}))
    explanations.append(
        f"COW HARD BLOCK: customer-owned ware item(s) [{item_list}] cannot be "
        f"received via Purchase Order. Use the inventory adjustment-journal "
        f"path into the canonical location, or confirm these are misclassified "
        f"and update the CP item registry."
    )
    readiness["explanations"] = explanations
    readiness["cow_items"] = evidence
    return readiness


def _is_sales_doc(doc: Dict[str, Any]) -> bool:
    """Detect a sales-side doc via document_type/doc_type/suggested_job_type."""
    fields = (
        doc.get("document_type"),
        doc.get("doc_type"),
        doc.get("suggested_job_type"),
    )
    for f in fields:
        if f and str(f).strip().lower().replace(" ", "_") in SALES_DOC_TYPES:
            return True
    return False


def _doc_customer_no(doc: Dict[str, Any]) -> str:
    """Extract the customer_no from a sales document. Tolerant of several shapes."""
    return str(
        doc.get("bc_customer_number")
        or doc.get("customer_no")
        or doc.get("customer_canonical")
        or (doc.get("extracted_fields") or {}).get("customer_no")
        or (doc.get("extracted_fields") or {}).get("bc_customer_number")
        or ""
    ).strip()


# ── Reselling COW — evidence refinement (Lane C Step 7b) ────────────────────
#
# Documentary-only: reads purported resale-authorization signals from the
# document and surfaces them on ``cow_so_wrong_customer`` evidence rows so
# reviewers can see the authorization context while the HARD BLOCK stands
# firm. Does NOT downgrade severity, does NOT add an authorization store,
# does NOT touch the ownership truth surface.
_RESALE_SIGNAL_KEYS = (
    "resale_authorization_id",
    "resale_authorized_by",
    "resale_authorization_date",
)


def _extract_resale_context(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a small documentary dict of resale-authorization signals,
    or ``None`` when no signal is present on the document.

    Signals are read exclusively from ``doc.extracted_fields``. No other
    store, no normalization, no inference — strictly what the document
    itself claims.
    """
    ef = doc.get("extracted_fields") or {}
    ctx: Dict[str, Any] = {}
    for key in _RESALE_SIGNAL_KEYS:
        v = ef.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        ctx[key] = v.strip() if isinstance(v, str) else v
    return ctx or None


async def check_cow_so_uses_base_item(
    db, doc: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Step 1 follow-up — enforce signed §4b SO-side rule.

    Returns a list of per-line evidence dicts. Each dict carries a
    ``blocker_code`` of either ``BLOCKER_CODE_SO_BASE`` (base-item
    correction) or ``BLOCKER_CODE_SO_WRONG_CUSTOMER`` (ownership-integrity
    mismatch). Empty list = no blocker.

    Rules:
      * customer_owned_active + registry.customer_no == doc.customer_no
          → cow_so_uses_base_item  (recommend base_item_no)
      * customer_owned_active + registry.customer_no != doc.customer_no
          → cow_so_wrong_customer  (record both customers)
      * unknown_cp_pattern
          → cow_so_uses_base_item  (no recommended_base_item_no)
      * customer_owned_retired / gamer → allow
    """
    if not _is_sales_doc(doc):
        return []

    doc_customer = _doc_customer_no(doc)
    evidence: List[Dict[str, Any]] = []

    for line in _iter_doc_lines(doc):
        item_no = (line.get("item_no") or "").strip()
        if not item_no:
            continue
        ownership = await classify_item_ownership(db, item_no)

        if ownership in ("gamer", "customer_owned_retired"):
            continue

        if ownership == "unknown_cp_pattern":
            evidence.append({
                "blocker_code": BLOCKER_CODE_SO_BASE,
                "item_no": item_no,
                "ownership": ownership,
                "doc_customer_no": doc_customer or None,
                "registered_customer_no": None,
                "recommended_base_item_no": None,
                "reason": "unknown_cp_pattern_on_sales_doc",
            })
            continue

        # customer_owned_active path — may be base-item issue OR wrong-customer
        row = await get_cp_item(db, item_no) or {}
        registered_customer = str(row.get("customer_no") or "").strip()
        base_item_no = row.get("base_item_no")

        if (
            doc_customer
            and registered_customer
            and doc_customer != registered_customer
        ):
            wrong_customer_entry: Dict[str, Any] = {
                "blocker_code": BLOCKER_CODE_SO_WRONG_CUSTOMER,
                "item_no": item_no,
                "ownership": ownership,
                "doc_customer_no": doc_customer,
                "registered_customer_no": registered_customer,
                "recommended_base_item_no": base_item_no,
                "reason": "cp_item_wrong_customer",
            }
            # Reselling COW — documentary evidence refinement (Step 7b).
            # Attach resale_context ONLY on wrong-customer rows, ONLY when
            # the document carries at least one resale-authorization signal.
            # Severity of cow_so_wrong_customer stays at block.
            resale_context = _extract_resale_context(doc)
            if resale_context:
                wrong_customer_entry["resale_context"] = resale_context
            evidence.append(wrong_customer_entry)
        else:
            evidence.append({
                "blocker_code": BLOCKER_CODE_SO_BASE,
                "item_no": item_no,
                "ownership": ownership,
                "doc_customer_no": doc_customer or None,
                "registered_customer_no": registered_customer or None,
                "recommended_base_item_no": base_item_no,
                "reason": "cp_item_on_sales_doc",
            })

    return evidence


def apply_cow_so_blocker_to_readiness(
    readiness: Dict[str, Any], evidence: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Fold SO-side COW evidence into readiness.

    * Appends distinct blocker codes for base-item vs wrong-customer cases
    * Writes one or two explanation strings (one per code actually present)
    * Persists the structured evidence under ``readiness.cow_so_items``
      (separate field from ``cow_items`` to avoid mixing PO-side and
      SO-side audit trails)
    * Pure: mutates and returns the passed-in dict.
    """
    if not evidence:
        return readiness

    codes_present = {e["blocker_code"] for e in evidence}
    blockers = list(readiness.get("blocking_reasons") or [])
    for code in codes_present:
        if code not in blockers:
            blockers.append(code)
    readiness["blocking_reasons"] = blockers

    explanations = list(readiness.get("explanations") or [])

    base_hits = [e for e in evidence if e["blocker_code"] == BLOCKER_CODE_SO_BASE]
    if base_hits:
        item_list = ", ".join(sorted({e["item_no"] for e in base_hits}))
        explanations.append(
            f"COW HARD BLOCK (SO): customer-owned item(s) [{item_list}] cannot "
            f"be billed on a sales document. Correct the line(s) to the base "
            f"item (recommended_base_item_no in cow_so_items) or retire the CP "
            f"item if the customer has consumed the ware."
        )

    wrong_cust_hits = [
        e for e in evidence if e["blocker_code"] == BLOCKER_CODE_SO_WRONG_CUSTOMER
    ]
    if wrong_cust_hits:
        details = sorted({
            f"{e['item_no']} (registered to {e['registered_customer_no']}, "
            f"billed to {e['doc_customer_no']})"
            for e in wrong_cust_hits
        })
        explanations.append(
            "COW HARD BLOCK (SO ownership): sales document bills CP item(s) "
            "registered to a different customer: " + "; ".join(details) + "."
        )

    readiness["explanations"] = explanations
    readiness["cow_so_items"] = evidence
    return readiness


# ── HTTP-layer helper (raises HTTPException for router convenience) ──────────

def require_retirement_actor(actor: str) -> None:
    """Router-facing guard used by POST /api/cp-items/{item_no}/retire."""
    actor_clean = (actor or "").strip().lower()
    if actor_clean != COW_RETIREMENT_ACTOR_EMAIL:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Retirement requires actor email {COW_RETIREMENT_ACTOR_EMAIL}. "
                f"Actor {actor!r} is not authorized."
            ),
        )


# ═════════════════════════════════════════════════════════════════════════════
# LANE C STEP 2 — VENDOR CONSIGNMENT (LANE_A_SIGNED_SCOPE.md §3 row 2)
# ═════════════════════════════════════════════════════════════════════════════
#
# Scope locked 2026-04-22 (signed):
#   * Separate registry collection `consigned_item_registry`
#   * Vendor-only consignor (no customer-consignor in this pass)
#   * All 5 rules hard-block
#   * Terminal `consumed` and `returned` — no reopen path
#   * R3 widened: any sales doc referencing a consigned_in item blocks
# ─────────────────────────────────────────────────────────────────────────────

CONSIGNED_ITEM_REGISTRY = "consigned_item_registry"

# Env-configured actor email authorized to transition registry state.
# Default matches COW actor (items@gamerpackaging.com) but separately tunable.
CONSIGNMENT_STATE_ACTOR_EMAIL = os.environ.get(
    "CONSIGNMENT_STATE_ACTOR_EMAIL",
    os.environ.get("COW_RETIREMENT_ACTOR_EMAIL", "items@gamerpackaging.com"),
).strip().lower()

# Blocking-reason codes (names locked in signed declaration)
BLOCKER_CODE_CONS_AP = "consigned_item_on_ap_invoice"
BLOCKER_CODE_CONS_AP_WRONG_STATE = "consigned_item_wrong_state_on_ap"
BLOCKER_CODE_CONS_SO = "consigned_item_on_sales_doc"
BLOCKER_CODE_CONS_SO_POST = "consigned_item_post_lifecycle_on_so"
BLOCKER_CODE_CONS_ADJ_LOC = "consigned_item_wrong_location_on_adj"

ConsignmentState = Literal["not_consigned", "consigned_in", "consumed", "returned"]
LegalTransitionTarget = Literal["consumed", "returned"]


class ConsignedItemCreate(BaseModel):
    item_no: str = Field(..., description="Consigned item number (uppercased on insert)")
    vendor_no: str = Field(..., description="BC vendor_no of the consignor")
    physical_location: str = Field(..., description="Warehouse where the goods sit at Gamer")
    notes: str = Field("", description="Admin notes")

    @field_validator("item_no", "vendor_no", "physical_location")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must be non-empty")
        return v


# ── Index management ────────────────────────────────────────────────────────

async def ensure_consignment_indexes(db) -> None:
    """Ensure indexes for consigned_item_registry. Idempotent."""
    await db[CONSIGNED_ITEM_REGISTRY].create_index(
        "item_no", unique=True, name="consigned_item_no_uniq"
    )
    await db[CONSIGNED_ITEM_REGISTRY].create_index(
        [("vendor_no", 1), ("state", 1)],
        name="consigned_vendor_state",
    )
    logger.info("[Consignment] consigned_item_registry indexes ensured")


# ── CRUD ────────────────────────────────────────────────────────────────────

async def get_consigned_item(db, item_no: str) -> Optional[Dict[str, Any]]:
    if not item_no:
        return None
    return await db[CONSIGNED_ITEM_REGISTRY].find_one(
        {"item_no": item_no.strip().upper()}, {"_id": 0}
    )


async def list_consigned_items(
    db,
    vendor_no: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if vendor_no:
        q["vendor_no"] = vendor_no
    if state:
        q["state"] = state
    cursor = db[CONSIGNED_ITEM_REGISTRY].find(q, {"_id": 0}).limit(limit)
    return await cursor.to_list(length=limit)


async def upsert_consigned_item(
    db, payload: ConsignedItemCreate, actor: str
) -> Dict[str, Any]:
    """Create a new registry row in state=consigned_in, or update editable fields
    on an existing row. Never flips `state` — that is state-machine-gated.
    """
    item_no = payload.item_no.strip().upper()
    now = _now_iso()

    existing = await db[CONSIGNED_ITEM_REGISTRY].find_one(
        {"item_no": item_no}, {"_id": 0}
    )
    if existing is None:
        doc = {
            "item_no": item_no,
            "vendor_no": payload.vendor_no,
            "physical_location": payload.physical_location,
            "state": "consigned_in",
            "linked_receipt_ids": [],
            "linked_consumption_ids": [],
            "linked_return_ids": [],
            "notes": payload.notes,
            "created_utc": now,
            "updated_utc": now,
            "created_by": actor,
            "state_changed_by": actor,
            "state_changed_at": now,
        }
        await db[CONSIGNED_ITEM_REGISTRY].insert_one(dict(doc))
        logger.info("[Consignment] Created %s (vendor=%s) by %s", item_no, payload.vendor_no, actor)
        return doc

    await db[CONSIGNED_ITEM_REGISTRY].update_one(
        {"item_no": item_no},
        {"$set": {
            "vendor_no": payload.vendor_no,
            "physical_location": payload.physical_location,
            "notes": payload.notes,
            "updated_utc": now,
        }},
    )
    logger.info("[Consignment] Updated %s by %s", item_no, actor)
    return await db[CONSIGNED_ITEM_REGISTRY].find_one(
        {"item_no": item_no}, {"_id": 0}
    )


async def transition_consigned_item(
    db,
    item_no: str,
    new_state: str,
    actor: str,
    evidence_id: str,
) -> Dict[str, Any]:
    """State-machine-gated transition. Only two legal paths per signed §3:
          consigned_in → consumed
          consigned_in → returned
    Both target states are terminal. Actor email must match
    CONSIGNMENT_STATE_ACTOR_EMAIL. evidence_id is required and appended to the
    appropriate `linked_*_ids` array.
    """
    actor_clean = (actor or "").strip().lower()
    if actor_clean != CONSIGNMENT_STATE_ACTOR_EMAIL:
        raise PermissionError(
            f"Transition actor {actor!r} is not authorized. "
            f"Only {CONSIGNMENT_STATE_ACTOR_EMAIL} may change consignment state."
        )
    if not evidence_id:
        raise ValueError("evidence_id is required for every state transition")
    if new_state not in ("consumed", "returned"):
        raise ValueError(
            f"Illegal target state {new_state!r}. Legal targets: consumed, returned."
        )

    item_no_clean = item_no.strip().upper()
    row = await db[CONSIGNED_ITEM_REGISTRY].find_one(
        {"item_no": item_no_clean}, {"_id": 0}
    )
    if row is None:
        raise ValueError(f"Consigned item {item_no_clean} not found")

    current = row.get("state")
    if current != "consigned_in":
        raise ValueError(
            f"Illegal transition: {current!r} → {new_state!r}. "
            f"Only 'consigned_in' can transition; terminal states cannot be reopened."
        )

    now = _now_iso()
    link_field = {
        "consumed": "linked_consumption_ids",
        "returned": "linked_return_ids",
    }[new_state]

    result = await db[CONSIGNED_ITEM_REGISTRY].find_one_and_update(
        {"item_no": item_no_clean, "state": "consigned_in"},
        {
            "$set": {
                "state": new_state,
                "state_changed_by": actor,
                "state_changed_at": now,
                "updated_utc": now,
            },
            "$addToSet": {link_field: evidence_id},
        },
        projection={"_id": 0},
    )
    if result is None:
        # Lost a race against another transition; surface it as illegal
        raise ValueError(f"Transition on {item_no_clean} was raced by another actor")
    # find_one_and_update returns the pre-update document by default; fetch post.
    return await db[CONSIGNED_ITEM_REGISTRY].find_one(
        {"item_no": item_no_clean}, {"_id": 0}
    )
    logger.info(
        "[Consignment] Transitioned %s: consigned_in → %s by %s (evidence=%s)",
        item_no_clean, new_state, actor, evidence_id,
    )
    return result


# ── Classifier ──────────────────────────────────────────────────────────────

async def classify_consignment_state(db, item_no: str) -> ConsignmentState:
    if not item_no:
        return "not_consigned"
    row = await get_consigned_item(db, item_no)
    if row is None:
        return "not_consigned"
    state = row.get("state")
    if state in ("consigned_in", "consumed", "returned"):
        return state  # type: ignore[return-value]
    return "not_consigned"


# ── Rule check (single pass over lines, all 5 rules) ────────────────────────

async def check_consignment_rules(
    db, doc: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Evaluate all 5 signed consignment rules against a single document.

    Returns a list of evidence dicts, each carrying a `blocker_code`. Empty
    list = no rule fired. All 5 rules are hard blocks per signed declaration.
    """
    # Pre-compute doc context
    is_po = _is_purchase_order_doc(doc)
    is_adj = _is_adjustment_journal_doc(doc)
    is_sales = _is_sales_doc(doc)

    # Early exit: rule space only covers AP invoice / PO / Sales / adj journal
    # (AP invoice is handled as "not-PO, not-sales, not-adj" via document_type).
    doc_type = str(
        doc.get("document_type")
        or doc.get("doc_type")
        or doc.get("suggested_job_type")
        or ""
    ).strip().lower().replace(" ", "_")
    is_ap_invoice = doc_type in ("ap_invoice", "purchase_invoice", "apinvoice")

    if not (is_po or is_adj or is_sales or is_ap_invoice):
        return []

    evidence: List[Dict[str, Any]] = []

    for line in _iter_doc_lines(doc):
        item_no = (line.get("item_no") or "").strip()
        if not item_no:
            continue
        state = await classify_consignment_state(db, item_no)
        if state == "not_consigned":
            continue

        row = await get_consigned_item(db, item_no) or {}

        # ── R1 / R2: AP invoice or PO side ─────────────────────────────────
        if is_po or is_ap_invoice:
            if state == "consigned_in":
                evidence.append({
                    "blocker_code": BLOCKER_CODE_CONS_AP,
                    "item_no": item_no,
                    "state": state,
                    "vendor_no": row.get("vendor_no"),
                    "reason": "consigned_in_item_on_ap_or_po",
                })
            else:  # consumed / returned
                evidence.append({
                    "blocker_code": BLOCKER_CODE_CONS_AP_WRONG_STATE,
                    "item_no": item_no,
                    "state": state,
                    "vendor_no": row.get("vendor_no"),
                    "reason": "ap_or_po_on_terminal_consignment_state",
                })
            continue

        # ── R3 (widened) / R4: Sales side ──────────────────────────────────
        if is_sales:
            if state == "consigned_in":
                evidence.append({
                    "blocker_code": BLOCKER_CODE_CONS_SO,
                    "item_no": item_no,
                    "state": state,
                    "vendor_no": row.get("vendor_no"),
                    "reason": "consigned_in_item_on_sales_doc",
                })
            else:  # consumed / returned
                evidence.append({
                    "blocker_code": BLOCKER_CODE_CONS_SO_POST,
                    "item_no": item_no,
                    "state": state,
                    "vendor_no": row.get("vendor_no"),
                    "reason": "sales_doc_after_consignment_cycle_ended",
                })
            continue

        # ── R5: Adjustment journal, location mismatch ──────────────────────
        if is_adj:
            line_loc = str(
                line.get("location")
                or line.get("location_code")
                or doc.get("location")
                or doc.get("location_code")
                or ""
            ).strip()
            physical_loc = str(row.get("physical_location") or "").strip()
            if physical_loc and line_loc != physical_loc:
                evidence.append({
                    "blocker_code": BLOCKER_CODE_CONS_ADJ_LOC,
                    "item_no": item_no,
                    "state": state,
                    "vendor_no": row.get("vendor_no"),
                    "location": line_loc or None,
                    "physical_location": physical_loc or None,
                    "reason": "adjustment_journal_location_mismatch",
                })

    return evidence


def apply_consignment_blocker_to_readiness(
    readiness: Dict[str, Any], evidence: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Fold consignment evidence into readiness using existing conventions.

    Each distinct `blocker_code` appears once in `readiness.blocking_reasons`.
    One explanation line per code category that fired. Structured evidence
    lives in the new additive field `readiness.consigned_items`.
    """
    if not evidence:
        return readiness

    codes_present = {e["blocker_code"] for e in evidence}
    blockers = list(readiness.get("blocking_reasons") or [])
    for code in codes_present:
        if code not in blockers:
            blockers.append(code)
    readiness["blocking_reasons"] = blockers

    explanations = list(readiness.get("explanations") or [])

    msgs = {
        BLOCKER_CODE_CONS_AP: "CONSIGNMENT BLOCK: AP invoice / PO references item(s) still in consignment (state=consigned_in). Gamer does not own this stock — it must not post as a regular vendor invoice.",
        BLOCKER_CODE_CONS_AP_WRONG_STATE: "CONSIGNMENT BLOCK: AP invoice references item(s) whose consignment cycle is already consumed or returned. Likely a duplicate or misclassified invoice.",
        BLOCKER_CODE_CONS_SO: "CONSIGNMENT BLOCK: sales document references item(s) still in consignment (state=consigned_in). Gamer does not own consigned stock and cannot sell it through the standard sales flow.",
        BLOCKER_CODE_CONS_SO_POST: "CONSIGNMENT BLOCK: sales document references item(s) whose consignment cycle is already consumed or returned. If a new cycle has begun, update the registry explicitly first.",
        BLOCKER_CODE_CONS_ADJ_LOC: "CONSIGNMENT BLOCK: inventory adjustment journal is targeting a location that does not match the registered physical_location for the consigned item(s).",
    }

    for code in codes_present:
        items = ", ".join(sorted({
            e["item_no"] for e in evidence if e["blocker_code"] == code
        }))
        msg = msgs.get(code, code)
        explanations.append(f"{msg} Item(s): {items}.")

    readiness["explanations"] = explanations
    readiness["consigned_items"] = evidence
    return readiness


def require_consignment_actor(actor: str) -> None:
    """Router-facing guard used by POST .../transition."""
    actor_clean = (actor or "").strip().lower()
    if actor_clean != CONSIGNMENT_STATE_ACTOR_EMAIL:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Consignment state transitions require actor email "
                f"{CONSIGNMENT_STATE_ACTOR_EMAIL}. Actor {actor!r} is not authorized."
            ),
        )

