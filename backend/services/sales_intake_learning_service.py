"""
GPI Document Hub — Sales Intake Learning Orchestrator
─────────────────────────────────────────────────────

Generalises the Giovanni/Nikki blanket-PO learning pattern (C-10250) so
it runs on EVERY document we ingest — sales POs, inventory XLS
spreadsheets, freight/AP invoices, and any regular hub document.

Giovanni reference (what we're replicating for everyone):
  • C-10250 has ~15 posted invoices in BC. We mined them and learned:
      - Product-level pattern: C-9874-* trigger → OIPALLET/OITIERSHEET
      - Customer-level pattern: every order has 1× Energy Surcharge
      - Historical qty bounds: C-9874 orders always 24–99 cases (±2σ)
  • Today that learning only fires inside Sales-Order preflight.
  • This service makes it fire at INTAKE, on every doc, and stores the
    result as `intake_insights` directly on the document (or the XLS
    staging record), so reviewers see it immediately.

What's surfaced per document (`intake_insights`):
  {
    "customer_no": "C-10250",
    "customer_source": "bc_prod_validation" | "resolve" | "unknown",
    "spiro_company_id": "abc-123" | null,
    "spiro_assigned_isr": "Nikki Hannover" | null,
    "cold_start": false,              # true if no BC history yet
    "cold_start_reason": null,
    "patterns_available": 3,          # number of learned patterns for this customer
    "suggested_lines": [...],         # dunnage/surcharges auto-suggested
    "bounds_check": {"in_bounds": true/false, "violations": [...]},
    "item_validation": {              # summary — never duplicates bc_prod_validator
        "lines_total": 7,
        "lines_matched": 5,
        "lines_unmatched": 2,
        "unmatched_items": ["NEW-PART-001", ...],
    },
    "ran_at": "...",
    "stages_ran": [...],
    "errors": [],
  }

Never writes to BC. Pure learning / visibility layer.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Policy — which doc types get intake learning
# ─────────────────────────────────────────────────────────────

# Doc types for which intake learning is valuable.
# Others (random attachments) return a no-op result.
LEARNING_DOC_TYPES = {
    # Sales side (was pilot-only, now hub-wide)
    "purchase_order", "po", "purchaseorder",
    "sales_order", "so_confirmation", "sales_invoice",
    "sales order confirmation", "sales order", "sales_order_confirmation",
    "sales invoice",  # GPI ZD00010 — blanket sales orders (Giovanni pattern)
    "quote", "rfq", "rate_request",
    # AP side — invoices still benefit from historical price/qty check
    "invoice", "ap_invoice", "vendor_invoice",
    # Freight
    "freight_invoice", "bol",
    # Shipping/warehouse handoffs
    "packing_slip", "shipment_notice",
}


# ─────────────────────────────────────────────────────────────
# Helpers: extract customer + line items from a hub_documents row
# ─────────────────────────────────────────────────────────────

def _pick_customer_no(doc: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Find the BC customer_no in priority order. Returns {customer_no, source, customer_name}."""
    bv = doc.get("bc_prod_validation") or {}
    cm = bv.get("customer_match") or {}
    if cm.get("found") and cm.get("bc_customer_no"):
        return {
            "customer_no": cm.get("bc_customer_no"),
            "customer_name": cm.get("bc_customer_name"),
            "source": "bc_prod_validation",
        }
    if doc.get("matched_customer_no"):
        return {
            "customer_no": doc.get("matched_customer_no"),
            "customer_name": doc.get("matched_customer_name"),
            "source": "matched_customer_no",
        }
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    name = (
        (doc.get("sales_pilot_extraction") or {}).get("customer_name")
        or ef.get("customer")
        or nf.get("customer")
    )
    return {"customer_no": None, "customer_name": name, "source": "unresolved"}


def _pick_spiro_match(doc: Dict[str, Any]) -> Dict[str, Optional[str]]:
    sm = doc.get("spiro_match") or {}
    cm = sm.get("company_match") or {}
    return {
        "spiro_id": cm.get("spiro_id"),
        "spiro_name": cm.get("name"),
        "assigned_isr": cm.get("assigned_isr"),
        "relationship_type": cm.get("relationship_type"),
        "opportunity_count": len(sm.get("opportunities") or []),
    }


def _pick_line_items(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a normalized list of {item_no, description, quantity, unit_price, uom}
    from the various shapes line items can take across the hub."""
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    extr = doc.get("sales_pilot_extraction") or {}
    raw = (
        extr.get("line_items")
        or nf.get("line_items")
        or ef.get("line_items")
        or []
    )
    out: List[Dict[str, Any]] = []
    for r in raw or []:
        if not isinstance(r, dict):
            continue
        item_no = (
            r.get("item_no") or r.get("itemNumber") or r.get("sku")
            or r.get("part_number") or r.get("lineObjectNumber")
            or r.get("code") or ""
        )
        desc = r.get("description") or r.get("item_description") or r.get("name") or ""
        qty_raw = r.get("quantity") or r.get("qty") or r.get("ordered_qty") or 0
        price_raw = r.get("unit_price") or r.get("unitPrice") or r.get("price") or 0
        try:
            qty = float(qty_raw or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            price = float(price_raw or 0)
        except (TypeError, ValueError):
            price = 0.0
        out.append({
            "item_no": str(item_no).strip(),
            "description": str(desc).strip(),
            "quantity": qty,
            "unit_price": price,
            "uom": r.get("uom") or r.get("unit_of_measure") or "",
        })
    return out


# ─────────────────────────────────────────────────────────────
# Core orchestrator
# ─────────────────────────────────────────────────────────────

async def run_intake_learning(
    doc_id: str,
    *,
    force: bool = False,
    db=None,
) -> Dict[str, Any]:
    """Run the Giovanni-style BC learning pipeline on a single hub document.

    Idempotent. Safe to call repeatedly. Persists the result on the
    document under `intake_insights`.
    """
    db = db if db is not None else get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "document not found", "doc_id": doc_id}

    doc_type = (doc.get("doc_type") or "").strip().lower().replace(" ", "_")
    insights: Dict[str, Any] = {
        "doc_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "stages_ran": [],
        "errors": [],
        "scope": "hub_document",
    }

    # Skip doc types where learning does not apply.
    if doc_type and doc_type not in {t.lower().replace(" ", "_") for t in LEARNING_DOC_TYPES}:
        insights["skipped"] = True
        insights["skip_reason"] = f"doc_type '{doc.get('doc_type')}' not in learning scope"
        await db.hub_documents.update_one(
            {"id": doc_id}, {"$set": {"intake_insights": insights}},
        )
        return insights

    # ── Customer resolution ─────────────────────────────────
    cust = _pick_customer_no(doc)
    customer_no = cust["customer_no"]
    customer_name = cust.get("customer_name")
    insights["customer_no"] = customer_no
    insights["customer_name"] = customer_name
    insights["customer_source"] = cust["source"]

    # ── Spiro match (if available, read-only) ───────────────
    spiro = _pick_spiro_match(doc)
    insights["spiro_company_id"] = spiro.get("spiro_id")
    insights["spiro_company_name"] = spiro.get("spiro_name")
    insights["spiro_assigned_isr"] = spiro.get("assigned_isr")
    insights["spiro_opportunities"] = spiro.get("opportunity_count", 0)

    # ── Line items (normalized) ─────────────────────────────
    line_items = _pick_line_items(doc)
    insights["line_count"] = len(line_items)

    # ── Cold-start detection ────────────────────────────────
    # If no customer_no at all, we can still record "cold_start" with the name
    # so reviewers see "no BC learning yet".
    if not customer_no:
        insights["cold_start"] = True
        insights["cold_start_reason"] = (
            "no BC customer_no resolved — "
            + ("customer name extracted but not matched" if customer_name else "no customer extracted")
        )
        insights["patterns_available"] = 0
        insights["suggested_lines"] = []
        insights["bounds_check"] = {"in_bounds": True, "violations": [], "skipped": True}
        insights["item_validation"] = {"lines_total": len(line_items), "skipped": True}
        # Still try cold-start peer matching — we have line items even without a customer_no
        await _attach_cold_start_peer_suggestions(db, insights, line_items, exclude=None)
        await db.hub_documents.update_one(
            {"id": doc_id}, {"$set": {"intake_insights": insights}},
        )
        return insights

    # ── Lazy seed: if no customer pattern exists, learn from BC history ──
    try:
        from services.order_line_patterns import (
            learn_from_bc_posted_orders,
            get_suggested_lines,
            check_quantity_bounds,
        )
        existing_patterns = await db.order_line_patterns.count_documents(
            {"customer_no": customer_no}
        )
        if existing_patterns == 0 or force:
            try:
                seed = await learn_from_bc_posted_orders(
                    db, customer_no, order_limit=10, threshold=0.75,
                )
                insights["stages_ran"].append("bc_learning_seed")
                insights["seed_result"] = {
                    "patterns_learned": seed.get("patterns_learned", 0),
                }
            except Exception as seed_err:
                insights["errors"].append(f"bc_learning_seed: {type(seed_err).__name__}: {seed_err}")

        # Recount after potential seed
        pattern_count = await db.order_line_patterns.count_documents(
            {"customer_no": customer_no}
        )
        insights["patterns_available"] = pattern_count
        insights["cold_start"] = pattern_count == 0
        if pattern_count == 0:
            insights["cold_start_reason"] = (
                "customer resolved but no BC posted history available yet"
            )
            # Try peer-based cold-start suggestions from similar known customers
            await _attach_cold_start_peer_suggestions(
                db, insights, line_items, exclude=customer_no,
            )

        # ── Suggested lines ──
        if pattern_count > 0 and line_items:
            try:
                main_items = [
                    {"item_no": li["item_no"], "quantity": li["quantity"]}
                    for li in line_items
                    if li["item_no"] and li["quantity"] > 0
                ]
                suggestions = await get_suggested_lines(db, customer_no, main_items)
                insights["suggested_lines"] = suggestions
                insights["stages_ran"].append("suggested_lines")
            except Exception as sl_err:
                insights["errors"].append(f"suggested_lines: {type(sl_err).__name__}: {sl_err}")
                insights["suggested_lines"] = []
        else:
            insights["suggested_lines"] = []

        # ── Quantity bounds check ──
        if pattern_count > 0 and line_items:
            try:
                bounds = await check_quantity_bounds(db, customer_no, line_items)
                insights["bounds_check"] = bounds
                insights["stages_ran"].append("bounds_check")
            except Exception as bc_err:
                insights["errors"].append(f"bounds_check: {type(bc_err).__name__}: {bc_err}")
                insights["bounds_check"] = {"in_bounds": True, "violations": [], "error": True}
        else:
            insights["bounds_check"] = {"in_bounds": True, "violations": [], "skipped": True}
    except Exception as top_err:
        insights["errors"].append(f"orchestrator: {type(top_err).__name__}: {top_err}")

    # ── Item-level catalog validation (reuse bc_reference_cache) ──
    try:
        iv = await _validate_items_against_catalog(db, customer_no, line_items)
        insights["item_validation"] = iv
        insights["stages_ran"].append("item_catalog")
    except Exception as iv_err:
        insights["errors"].append(f"item_catalog: {type(iv_err).__name__}: {iv_err}")
        insights["item_validation"] = {"lines_total": len(line_items), "error": True}

    # ── Flag the doc if any actionable finding ──
    actionable = (
        not insights.get("bounds_check", {}).get("in_bounds", True)
        or (insights.get("suggested_lines") or [])
        or (insights.get("item_validation", {}).get("lines_unmatched", 0) > 0)
    )
    insights["has_actionable_findings"] = bool(actionable)

    await db.hub_documents.update_one(
        {"id": doc_id}, {"$set": {"intake_insights": insights}},
    )
    logger.info(
        "[IntakeLearning] doc=%s cust=%s patterns=%d suggested=%d bounds_violations=%d unmatched=%d actionable=%s",
        doc_id[:8], customer_no,
        insights.get("patterns_available", 0),
        len(insights.get("suggested_lines") or []),
        len((insights.get("bounds_check") or {}).get("violations") or []),
        (insights.get("item_validation") or {}).get("lines_unmatched", 0),
        insights.get("has_actionable_findings"),
    )
    return insights


async def _attach_cold_start_peer_suggestions(
    db,
    insights: Dict[str, Any],
    line_items: List[Dict[str, Any]],
    *,
    exclude: Optional[str] = None,
) -> None:
    """Side-effect: populate `insights.peer_matches` with the top
    similar known customers + their inherited suggestions, so cold-start
    docs have something actionable to review instead of an empty panel."""
    if not line_items:
        return
    try:
        from services.cold_start_matcher_service import find_similar_customers
        matches = await find_similar_customers(
            line_items, top_k=3, exclude_customer_no=exclude, db=db,
        )
        if matches:
            insights["peer_matches"] = matches
            insights["stages_ran"].append("cold_start_peer_match")
    except Exception as e:
        insights["errors"].append(f"cold_start_peer_match: {type(e).__name__}: {e}")


async def _validate_items_against_catalog(
    db, customer_no: str, line_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Per-line BC item-catalog lookup using bc_reference_cache.

    Returns matched/unmatched counts plus unmatched item numbers so the
    reviewer can see which parts are brand-new vs known.
    """
    if not line_items:
        return {"lines_total": 0, "lines_matched": 0, "lines_unmatched": 0}

    import re
    matched = 0
    unmatched: List[Dict[str, str]] = []
    for li in line_items:
        item_no = (li.get("item_no") or "").strip()
        desc = (li.get("description") or "").strip()
        key_ref = item_no or desc
        if not key_ref:
            continue
        safe_ref = re.escape(key_ref[:40])
        hit = None
        try:
            hit = await db.bc_reference_cache.find_one(
                {
                    "bc_entity_type": "item",
                    "$or": [
                        {"bc_document_no": item_no},
                        {"displayName": {"$regex": safe_ref, "$options": "i"}},
                        {"description": {"$regex": safe_ref, "$options": "i"}},
                    ],
                },
                {"_id": 0, "bc_document_no": 1, "displayName": 1},
            )
        except Exception:
            hit = None
        if hit:
            matched += 1
        else:
            unmatched.append({"item_no": item_no, "description": desc[:80]})

    return {
        "lines_total": len(line_items),
        "lines_matched": matched,
        "lines_unmatched": len(unmatched),
        "unmatched_items": unmatched[:15],
        "match_rate": round(matched / max(len(line_items), 1) * 100),
    }


# ─────────────────────────────────────────────────────────────
# Inventory XLS adapter — runs the same learning on a staging record
# ─────────────────────────────────────────────────────────────

async def run_intake_learning_for_xls_staging(
    staging_id: str,
    *,
    force: bool = False,
    db=None,
) -> Dict[str, Any]:
    """Run intake learning on an inventory XLS staging record.

    Resolves: XLS customer workspace → BC customer_no (via inv_customers),
    then treats each parsed row as a line item. Persists `intake_insights`
    back on the staging doc.
    """
    db = db if db is not None else get_db()
    from services.inventory_xls_staging_service import STAGING_COLL
    from services.inventory_ledger_service import CUSTOMERS_COLL

    staging = await db[STAGING_COLL].find_one({"id": staging_id}, {"_id": 0})
    if not staging:
        return {"error": "staging not found", "staging_id": staging_id}

    insights: Dict[str, Any] = {
        "staging_id": staging_id,
        "scope": "inventory_xls_staging",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "stages_ran": [],
        "errors": [],
    }

    customer_workspace_id = staging.get("assigned_customer_id") or staging.get("suggested_customer_id")
    bc_customer_no = None
    customer_name = None
    if customer_workspace_id:
        cust = await db[CUSTOMERS_COLL].find_one(
            {"id": customer_workspace_id},
            {"_id": 0, "code": 1, "name": 1, "bc_customer_no": 1},
        )
        if cust:
            bc_customer_no = cust.get("bc_customer_no") or cust.get("code")
            customer_name = cust.get("name")
    insights["customer_workspace_id"] = customer_workspace_id
    insights["customer_no"] = bc_customer_no
    insights["customer_name"] = customer_name

    rows = staging.get("rows") or []
    line_items = [
        {
            "item_no": (r.get("item") or "").strip(),
            "description": (r.get("item_description") or "").strip(),
            "quantity": float(r.get("qty") or 0),
            "unit_price": 0,
            "uom": r.get("uom") or "",
        }
        for r in rows
        if r.get("item")
    ]
    insights["line_count"] = len(line_items)

    # Cold-start short-circuit
    if not bc_customer_no:
        insights["cold_start"] = True
        insights["cold_start_reason"] = (
            "XLS staging not assigned to a BC-linked customer workspace yet"
        )
        insights["patterns_available"] = 0
        insights["suggested_lines"] = []
        insights["bounds_check"] = {"in_bounds": True, "violations": [], "skipped": True}
        insights["item_validation"] = {"lines_total": len(line_items), "skipped": True}
        await _attach_cold_start_peer_suggestions(db, insights, line_items, exclude=None)
        await db[STAGING_COLL].update_one(
            {"id": staging_id}, {"$set": {"intake_insights": insights}},
        )
        return insights

    try:
        from services.order_line_patterns import (
            learn_from_bc_posted_orders, get_suggested_lines, check_quantity_bounds,
        )
        pattern_count = await db.order_line_patterns.count_documents(
            {"customer_no": bc_customer_no}
        )
        if pattern_count == 0 or force:
            try:
                seed = await learn_from_bc_posted_orders(
                    db, bc_customer_no, order_limit=10, threshold=0.75,
                )
                insights["stages_ran"].append("bc_learning_seed")
                insights["seed_result"] = {"patterns_learned": seed.get("patterns_learned", 0)}
            except Exception as seed_err:
                insights["errors"].append(
                    f"bc_learning_seed: {type(seed_err).__name__}: {seed_err}"
                )
        pattern_count = await db.order_line_patterns.count_documents(
            {"customer_no": bc_customer_no}
        )
        insights["patterns_available"] = pattern_count
        insights["cold_start"] = pattern_count == 0
        if pattern_count == 0:
            insights["cold_start_reason"] = (
                "BC customer resolved but no posted orders available yet"
            )
            await _attach_cold_start_peer_suggestions(
                db, insights, line_items, exclude=bc_customer_no,
            )

        if pattern_count > 0 and line_items:
            try:
                bounds = await check_quantity_bounds(db, bc_customer_no, line_items)
                insights["bounds_check"] = bounds
                insights["stages_ran"].append("bounds_check")
            except Exception as bc_err:
                insights["errors"].append(f"bounds_check: {type(bc_err).__name__}: {bc_err}")
                insights["bounds_check"] = {"in_bounds": True, "violations": []}
            try:
                main_items = [
                    {"item_no": li["item_no"], "quantity": li["quantity"]}
                    for li in line_items if li["item_no"] and li["quantity"] > 0
                ]
                suggestions = await get_suggested_lines(db, bc_customer_no, main_items)
                insights["suggested_lines"] = suggestions
                insights["stages_ran"].append("suggested_lines")
            except Exception as sl_err:
                insights["errors"].append(f"suggested_lines: {type(sl_err).__name__}: {sl_err}")
                insights["suggested_lines"] = []
        else:
            insights["bounds_check"] = {"in_bounds": True, "violations": [], "skipped": True}
            insights["suggested_lines"] = []
    except Exception as top_err:
        insights["errors"].append(f"orchestrator: {type(top_err).__name__}: {top_err}")

    try:
        iv = await _validate_items_against_catalog(db, bc_customer_no, line_items)
        insights["item_validation"] = iv
        insights["stages_ran"].append("item_catalog")
    except Exception as iv_err:
        insights["errors"].append(f"item_catalog: {type(iv_err).__name__}: {iv_err}")
        insights["item_validation"] = {"lines_total": len(line_items), "error": True}

    actionable = (
        not insights.get("bounds_check", {}).get("in_bounds", True)
        or (insights.get("suggested_lines") or [])
        or (insights.get("item_validation", {}).get("lines_unmatched", 0) > 0)
    )
    insights["has_actionable_findings"] = bool(actionable)

    await db[STAGING_COLL].update_one(
        {"id": staging_id}, {"$set": {"intake_insights": insights}},
    )
    return insights


# ─────────────────────────────────────────────────────────────
# Backfill + summary
# ─────────────────────────────────────────────────────────────

async def backfill_intake_learning(
    limit: int = 500,
    only_missing: bool = True,
    db=None,
) -> Dict[str, Any]:
    """Run intake learning across hub_documents + inv_import_staging.

    Pass `only_missing=False` to force re-learning of every eligible doc.
    """
    db = db if db is not None else get_db()
    from services.inventory_xls_staging_service import STAGING_COLL

    # Hub docs — restrict to doc_types in scope
    hub_q: Dict[str, Any] = {
        "doc_type": {"$regex": "purchase|sales|invoice|freight|bol|packing|quote", "$options": "i"},
    }
    if only_missing:
        hub_q["intake_insights"] = {"$exists": False}

    hub_docs = await db.hub_documents.find(
        hub_q, {"_id": 0, "id": 1},
    ).limit(limit).to_list(limit)

    xls_q: Dict[str, Any] = {"status": {"$in": ["pending_review", "applied"]}}
    if only_missing:
        xls_q["intake_insights"] = {"$exists": False}
    xls_docs = await db[STAGING_COLL].find(
        xls_q, {"_id": 0, "id": 1},
    ).limit(limit).to_list(limit)

    hub_ran = 0
    hub_errors = 0
    hub_actionable = 0
    for d in hub_docs:
        try:
            res = await run_intake_learning(d["id"], db=db)
            hub_ran += 1
            if res.get("has_actionable_findings"):
                hub_actionable += 1
        except Exception as e:
            hub_errors += 1
            logger.warning("[IntakeLearning.backfill] hub doc %s failed: %s", d["id"][:8], e)

    xls_ran = 0
    xls_errors = 0
    xls_actionable = 0
    for s in xls_docs:
        try:
            res = await run_intake_learning_for_xls_staging(s["id"], db=db)
            xls_ran += 1
            if res.get("has_actionable_findings"):
                xls_actionable += 1
        except Exception as e:
            xls_errors += 1
            logger.warning("[IntakeLearning.backfill] xls %s failed: %s", s["id"][:8], e)

    return {
        "hub_documents": {
            "processed": hub_ran,
            "errors": hub_errors,
            "actionable": hub_actionable,
        },
        "xls_staging": {
            "processed": xls_ran,
            "errors": xls_errors,
            "actionable": xls_actionable,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def refresh_customer_after_bc_write(
    customer_no: str,
    db=None,
) -> Dict[str, Any]:
    """Post-BC-write hook — re-learn patterns for a single customer.

    Called the instant a sales order or AP invoice is successfully
    posted to BC, so the very next ingested doc for that customer
    picks up the fresh pattern. Read-only against BC, runs in-process.

    Safe to fire-and-forget via asyncio.create_task — never raises.
    """
    if not customer_no:
        return {"skipped": True, "reason": "no customer_no"}
    try:
        from services.order_line_patterns import learn_from_bc_posted_orders
        db = db if db is not None else get_db()
        seed = await learn_from_bc_posted_orders(
            db, customer_no, order_limit=10, threshold=0.75,
        )
        logger.info(
            "[IntakeLearning.bc-write-hook] customer=%s patterns=%d",
            customer_no, seed.get("patterns_learned", 0),
        )
        return {
            "customer_no": customer_no,
            "patterns_learned": seed.get("patterns_learned", 0),
            "triggered_by": "bc_write",
        }
    except Exception as e:
        logger.warning(
            "[IntakeLearning.bc-write-hook] customer=%s failed: %s",
            customer_no, e,
        )
        return {"customer_no": customer_no, "error": str(e)}


async def refresh_active_customers(
    lookback_hours: int = 24,
    max_customers: int = 100,
    refresh_docs: bool = True,
    db=None,
) -> Dict[str, Any]:
    """Refresh learned patterns for customers with new BC posted-order activity.

    For every customer whose BC posted orders changed inside the last
    `lookback_hours`, we:
      1. Re-run `learn_from_bc_posted_orders` to pick up new patterns
      2. Optionally (if `refresh_docs=True`) re-run `run_intake_learning`
         on any open hub docs + pending XLS staging tied to that customer,
         so their `intake_insights` pick up the fresh patterns immediately.

    Intended for a daily scheduler so Giovanni-style learning stays current
    without manual backfills. Read-only w.r.t. BC.
    """
    from datetime import timedelta
    from services.order_line_patterns import learn_from_bc_posted_orders
    from services.inventory_xls_staging_service import STAGING_COLL

    db = db if db is not None else get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # ── Discover "active" customers from bc_reference_cache ──
    # bc_reference_cache tracks posted sales orders / invoices. We look
    # for entries whose modifiedDateTime (or created_at) crossed the
    # cutoff. Falls back to customerNumber aggregation if timestamps are
    # missing.
    active_customers: List[str] = []
    try:
        pipeline = [
            {"$match": {
                "bc_entity_type": {"$in": ["sales_order", "sales_invoice", "posted_sales_invoice"]},
                "$or": [
                    {"modifiedDateTime": {"$gte": cutoff.isoformat()}},
                    {"lastModifiedDateTime": {"$gte": cutoff.isoformat()}},
                    {"created_at": {"$gte": cutoff}},
                    {"updated_at": {"$gte": cutoff}},
                ],
            }},
            {"$group": {"_id": "$bc_customer_no"}},
            {"$match": {"_id": {"$ne": None}}},
            {"$limit": max_customers},
        ]
        async for r in db.bc_reference_cache.aggregate(pipeline):
            if r.get("_id"):
                active_customers.append(r["_id"])
    except Exception as e:
        logger.warning("[IntakeLearning.refresh] discovery failed: %s", e)

    # Fallback: if no timestamp-based results, pull customers from any
    # doc whose intake_insights is older than the cutoff so we still
    # make useful progress.
    if not active_customers:
        try:
            pipeline = [
                {"$match": {
                    "intake_insights.customer_no": {"$ne": None},
                    "intake_insights.ran_at": {"$lt": cutoff.isoformat()},
                }},
                {"$group": {"_id": "$intake_insights.customer_no"}},
                {"$limit": max_customers},
            ]
            async for r in db.hub_documents.aggregate(pipeline):
                if r.get("_id"):
                    active_customers.append(r["_id"])
        except Exception as e:
            logger.warning("[IntakeLearning.refresh] fallback discovery failed: %s", e)

    refreshed_customers: List[Dict[str, Any]] = []
    docs_refreshed = 0
    xls_refreshed = 0

    for customer_no in active_customers:
        learned_count = 0
        try:
            seed = await learn_from_bc_posted_orders(
                db, customer_no, order_limit=10, threshold=0.75,
            )
            learned_count = seed.get("patterns_learned", 0)
        except Exception as e:
            logger.warning(
                "[IntakeLearning.refresh] learn failed for %s: %s", customer_no, e,
            )
            continue

        # Re-run intake learning on open docs + pending XLS for this customer
        doc_count = 0
        xls_count = 0
        if refresh_docs:
            try:
                async for d in db.hub_documents.find(
                    {"intake_insights.customer_no": customer_no,
                     "status": {"$nin": ["Completed", "Archived", "Posted"]}},
                    {"_id": 0, "id": 1},
                ).limit(50):
                    try:
                        await run_intake_learning(d["id"], force=True, db=db)
                        doc_count += 1
                    except Exception as e:
                        logger.debug("[refresh] doc %s fail: %s", d["id"][:8], e)
                docs_refreshed += doc_count

                # XLS staging — customer workspace may map to this BC customer
                from services.inventory_ledger_service import CUSTOMERS_COLL
                cust_hits = await db[CUSTOMERS_COLL].find(
                    {"$or": [{"bc_customer_no": customer_no}, {"code": customer_no}]},
                    {"_id": 0, "id": 1},
                ).to_list(10)
                workspace_ids = [c["id"] for c in cust_hits]
                if workspace_ids:
                    async for s in db[STAGING_COLL].find(
                        {"assigned_customer_id": {"$in": workspace_ids},
                         "status": "pending_review"},
                        {"_id": 0, "id": 1},
                    ).limit(50):
                        try:
                            await run_intake_learning_for_xls_staging(
                                s["id"], force=True, db=db,
                            )
                            xls_count += 1
                        except Exception as e:
                            logger.debug("[refresh] xls %s fail: %s", s["id"][:8], e)
                    xls_refreshed += xls_count
            except Exception as e:
                logger.warning("[IntakeLearning.refresh] doc loop fail for %s: %s", customer_no, e)

        refreshed_customers.append({
            "customer_no": customer_no,
            "patterns_learned": learned_count,
            "docs_refreshed": doc_count,
            "xls_refreshed": xls_count,
        })

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "active_customers": len(active_customers),
        "refreshed_customers": refreshed_customers,
        "docs_refreshed": docs_refreshed,
        "xls_refreshed": xls_refreshed,
    }
    logger.info(
        "[IntakeLearning.refresh] lookback=%dh customers=%d docs=%d xls=%d",
        lookback_hours, len(active_customers), docs_refreshed, xls_refreshed,
    )
    return result


async def get_intake_learning_summary(db=None) -> Dict[str, Any]:
    """Dashboard aggregation of intake-learning coverage across the hub."""
    db = db if db is not None else get_db()
    from services.inventory_xls_staging_service import STAGING_COLL

    total_hub = await db.hub_documents.count_documents(
        {"doc_type": {"$regex": "purchase|sales|invoice|freight|bol|packing|quote", "$options": "i"}}
    )
    hub_with_insights = await db.hub_documents.count_documents(
        {"intake_insights": {"$exists": True}}
    )
    hub_cold_start = await db.hub_documents.count_documents(
        {"intake_insights.cold_start": True}
    )
    hub_actionable = await db.hub_documents.count_documents(
        {"intake_insights.has_actionable_findings": True}
    )
    hub_bounds_violations = await db.hub_documents.count_documents(
        {"intake_insights.bounds_check.in_bounds": False}
    )

    # Top customers by learned-pattern coverage
    pipeline = [
        {"$match": {"intake_insights.customer_no": {"$ne": None}}},
        {"$group": {
            "_id": "$intake_insights.customer_no",
            "customer_name": {"$first": "$intake_insights.customer_name"},
            "doc_count": {"$sum": 1},
            "patterns": {"$max": "$intake_insights.patterns_available"},
            "actionable": {"$sum": {"$cond": ["$intake_insights.has_actionable_findings", 1, 0]}},
            "cold_start": {"$sum": {"$cond": ["$intake_insights.cold_start", 1, 0]}},
        }},
        {"$sort": {"doc_count": -1}},
        {"$limit": 25},
    ]
    top_customers_raw = [r async for r in db.hub_documents.aggregate(pipeline)]
    top_customers = [
        {
            "customer_no": r["_id"],
            "customer_name": r.get("customer_name"),
            "doc_count": r["doc_count"],
            "patterns_available": r.get("patterns") or 0,
            "actionable_docs": r.get("actionable", 0),
            "cold_start_docs": r.get("cold_start", 0),
        }
        for r in top_customers_raw
    ]

    # XLS coverage
    xls_total = await db[STAGING_COLL].count_documents({})
    xls_with_insights = await db[STAGING_COLL].count_documents(
        {"intake_insights": {"$exists": True}}
    )
    xls_cold_start = await db[STAGING_COLL].count_documents(
        {"intake_insights.cold_start": True}
    )
    xls_actionable = await db[STAGING_COLL].count_documents(
        {"intake_insights.has_actionable_findings": True}
    )

    coverage_pct = round(hub_with_insights / max(total_hub, 1) * 100)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hub": {
            "eligible_docs": total_hub,
            "with_insights": hub_with_insights,
            "cold_start": hub_cold_start,
            "actionable_findings": hub_actionable,
            "bounds_violations": hub_bounds_violations,
            "coverage_pct": coverage_pct,
        },
        "xls_staging": {
            "total": xls_total,
            "with_insights": xls_with_insights,
            "cold_start": xls_cold_start,
            "actionable": xls_actionable,
        },
        "top_customers": top_customers,
    }


__all__ = [
    "run_intake_learning",
    "run_intake_learning_for_xls_staging",
    "backfill_intake_learning",
    "refresh_active_customers",
    "refresh_customer_after_bc_write",
    "get_intake_learning_summary",
    "LEARNING_DOC_TYPES",
]
