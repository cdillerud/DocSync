"""
GPI Document Hub — Sales Order Rules Engine

Evaluates sales orders against documented Business Central operating
procedures and business rules.  Determines workflow stage, compliance
status, blocking issues, and recommended next actions.

This is a strict, operational rules engine — not a summarizer.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from deps import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# CANONICAL WORKFLOW STAGES
# ─────────────────────────────────────────────────────────────

STAGES = [
    "Draft / Open",
    "Pending Approval",
    "Pending Prepayment",
    "Released",
    "Confirmation Needed",
    "Pick Needed",
    "Drop Ship PO Needed",
    "Drop Ship PO Incomplete",
    "Waiting for Freight",
    "Shipped / Ready to Invoice",
    "Ready to Post Invoice",
    "Posted",
    "Exception / Needs Review",
]

COMPLIANCE_VALUES = ["Compliant", "Conditionally Compliant", "Non-Compliant", "Insufficient Evidence"]
CONFIDENCE_VALUES = ["High", "Medium", "Low"]


# ─────────────────────────────────────────────────────────────
# RULES ENGINE
# ─────────────────────────────────────────────────────────────

async def evaluate_sales_order(doc_id: str) -> Dict[str, Any]:
    """
    Evaluate a sales order document against all business rules.

    Returns the structured evaluation result with stage, compliance,
    blocking issues, controls present/missing, and recommended action.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": f"Document {doc_id} not found"}

    # Gather all available data
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    ext = doc.get("sales_pilot_extraction") or {}
    line_items = nf.get("line_items") or doc.get("line_items") or []
    bc_val = doc.get("bc_prod_validation") or {}
    spiro = doc.get("spiro_match") or {}

    # Build the order context
    ctx = _build_order_context(doc, ef, nf, ext, line_items, bc_val, spiro)

    # Run all rule checks
    blocking_issues = []
    controls_present = []
    controls_missing = []
    rules_triggered = []
    risks = []

    # Rule 1: Status Governance
    _check_status_governance(ctx, blocking_issues, controls_present, controls_missing, rules_triggered)

    # Rule 2: Customer PO Control
    _check_customer_po(ctx, blocking_issues, controls_present, controls_missing, rules_triggered)

    # Rule 3: Sales Order Line Rules
    _check_line_items(ctx, blocking_issues, controls_present, controls_missing, rules_triggered, risks)

    # Rule 4: Cost Rules
    _check_cost_rules(ctx, blocking_issues, controls_present, controls_missing, rules_triggered)

    # Rule 5: Price Change Rules
    _check_price_rules(ctx, blocking_issues, rules_triggered, risks)

    # Rule 6: Drop-Ship Rules
    _check_drop_ship_rules(ctx, blocking_issues, controls_present, controls_missing, rules_triggered)

    # Rule 7: Freight Rules
    _check_freight_rules(ctx, blocking_issues, controls_present, controls_missing, rules_triggered, risks)

    # Rule 8: Confirmation Rules
    _check_confirmation_rules(ctx, blocking_issues, rules_triggered)

    # Rule 9: Pick Rules
    _check_pick_rules(ctx, blocking_issues, rules_triggered)

    # Rule 10: Shipping and Invoicing Readiness
    _check_readiness(ctx, blocking_issues, controls_present, controls_missing, rules_triggered)

    # Determine stage
    stage = _determine_stage(ctx, blocking_issues, rules_triggered)

    # Determine compliance
    compliance = _determine_compliance(blocking_issues, controls_missing, ctx)

    # Determine confidence
    confidence = _determine_confidence(ctx, controls_present, controls_missing)

    # Determine recommended action
    action, why = _determine_next_action(stage, blocking_issues, controls_missing, ctx)

    result = {
        "document_id": doc_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "compliance_status": compliance,
        "blocking_issues": blocking_issues,
        "required_controls_present": controls_present,
        "required_controls_missing": controls_missing,
        "business_rules_triggered": rules_triggered,
        "operational_risks": risks,
        "recommended_next_action": action,
        "why": why,
        "confidence": confidence,
        "order_context": {
            "customer": ctx["customer"],
            "customer_no": ctx["customer_no"],
            "po_number": ctx["po_number"],
            "order_number": ctx["order_number"],
            "status": ctx["status"],
            "amount": ctx["amount"],
            "line_count": ctx["line_count"],
            "is_drop_ship": ctx["is_drop_ship"],
            "has_po_attachment": ctx["has_po_attachment"],
        },
    }

    # Persist on document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"so_rules_evaluation": result}},
    )

    logger.info(
        "[SORulesEngine] doc=%s stage=%s compliance=%s confidence=%s blockers=%d",
        doc_id[:8], stage, compliance, confidence, len(blocking_issues),
    )
    return result


# ─────────────────────────────────────────────────────────────
# CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────

def _build_order_context(
    doc: Dict, ef: Dict, nf: Dict, ext: Dict,
    line_items: List, bc_val: Dict, spiro: Dict,
) -> Dict[str, Any]:
    """Build a normalized order context from all available data sources."""

    customer = (
        ext.get("customer_name") or ef.get("customer")
        or nf.get("customer") or doc.get("vendor_canonical")
    )
    customer_no = (
        doc.get("matched_customer_no") or doc.get("customer_no")
        or nf.get("customer_no")
        or (bc_val.get("customer_match") or {}).get("bc_customer_no")
    )
    po_number = (
        ext.get("po_number") or ef.get("po_number")
        or nf.get("customer_po") or doc.get("po_resolution_number")
    )
    order_number = (
        ext.get("order_number") or ef.get("order_number")
        or nf.get("order_number") or ef.get("sales_order_number")
    )
    amount = (
        ext.get("total_amount") or nf.get("amount_float")
        or ef.get("total_amount") or doc.get("total_amount")
    )
    status = (
        ef.get("order_status") or ef.get("status")
        or nf.get("order_status") or doc.get("workflow_status")
    )
    ship_to = ext.get("ship_to") or ef.get("ship_to") or nf.get("ship_to")
    ship_date = ext.get("requested_ship_date") or ef.get("ship_date") or nf.get("requested_ship_date")

    # Detect drop ship indicators
    is_drop_ship = False
    ds_indicators = ["drop ship", "dropship", "drop-ship", "ds order", "purchasing code"]
    all_text = f"{ef} {nf} {doc.get('file_name', '')}".lower()
    for ind in ds_indicators:
        if ind in all_text:
            is_drop_ship = True
            break
    for li in line_items:
        if li.get("drop_shipment") or li.get("purchasing_code") == "DROP SHIP":
            is_drop_ship = True
            break

    # Detect freight-only lines
    freight_lines = []
    inventory_lines = []
    for li in line_items:
        desc = (li.get("description") or "").lower()
        li_type = (li.get("type") or li.get("line_type") or "").lower()
        if "freight" in desc or "shipping" in desc or li_type == "charge":
            freight_lines.append(li)
        else:
            inventory_lines.append(li)

    # Check for PO attachment evidence
    has_po_attachment = bool(
        doc.get("po_attachment") or doc.get("customer_po_attached")
        or ef.get("po_attached") or po_number
    )

    # Detect confirmation sent
    confirmation_sent = bool(
        ef.get("confirmation_sent") or doc.get("confirmation_sent")
        or doc.get("order_confirmation_sent")
    )

    # Detect pick instructions
    pick_sent = bool(
        ef.get("pick_instructions_sent") or doc.get("pick_sent")
    )

    # Detect shipment
    shipped = bool(
        ef.get("shipped") or ef.get("shipment_date")
        or doc.get("shipped") or nf.get("shipment_date")
    )

    # Detect warehouse order
    is_warehouse = bool(
        ef.get("location_code") and ef.get("location_code") != "00"
        or any(li.get("location_code", "") not in ("", "00") for li in line_items)
    )

    # Cost presence
    lines_with_cost = sum(1 for li in line_items if li.get("unit_cost") or li.get("cost"))
    lines_with_price = sum(1 for li in line_items if li.get("unit_price") or li.get("price"))

    # PO linkage for drop ship
    has_po_linkage = bool(
        ef.get("purchase_order_no") or doc.get("linked_po")
        or nf.get("purchase_order_number")
    )

    return {
        "customer": customer,
        "customer_no": customer_no,
        "po_number": po_number,
        "order_number": order_number,
        "amount": amount,
        "status": _normalize_status(status),
        "raw_status": status,
        "ship_to": ship_to,
        "ship_date": ship_date,
        "is_drop_ship": is_drop_ship,
        "has_po_attachment": has_po_attachment,
        "confirmation_sent": confirmation_sent,
        "pick_sent": pick_sent,
        "shipped": shipped,
        "is_warehouse": is_warehouse,
        "line_items": line_items,
        "freight_lines": freight_lines,
        "inventory_lines": inventory_lines,
        "line_count": len(line_items),
        "lines_with_cost": lines_with_cost,
        "lines_with_price": lines_with_price,
        "has_po_linkage": has_po_linkage,
        "has_customer_resolved": bool(customer_no),
        "has_bc_match": (bc_val.get("customer_match") or {}).get("found", False),
        "has_spiro_match": bool((spiro.get("company_match") or {}).get("spiro_id")),
        "extraction_pct": doc.get("ai_confidence", 0),
        "doc_type": doc.get("doc_type"),
        "file_name": doc.get("file_name"),
    }


def _normalize_status(status: Optional[str]) -> str:
    """Normalize workflow status to canonical form."""
    if not status:
        return "Unknown"
    s = str(status).lower().strip()
    mapping = {
        "open": "Open",
        "draft": "Draft / Open",
        "pending_approval": "Pending Approval",
        "pending approval": "Pending Approval",
        "pending_prepayment": "Pending Prepayment",
        "pending prepayment": "Pending Prepayment",
        "released": "Released",
        "posted": "Posted",
        "shipped": "Shipped / Ready to Invoice",
        "exported": "Released",
        "pilot_review": "Draft / Open",
        "needs_review": "Draft / Open",
        "validated": "Released",
        "ready_to_post": "Released",
    }
    for k, v in mapping.items():
        if k in s:
            return v
    return status


# ─────────────────────────────────────────────────────────────
# RULE CHECKS
# ─────────────────────────────────────────────────────────────

def _check_status_governance(ctx, blocking, present, missing, rules):
    """Rule 1: Status governance."""
    status = ctx["status"]
    if status in ("Pending Approval", "Pending Prepayment"):
        blocking.append(f"Order is {status} — blocked from downstream execution")
        rules.append(f"R1: Order status is {status}, not Released")
    elif status in ("Open", "Draft / Open"):
        rules.append("R1: Order is Open/Draft — not yet released for execution")
    elif status == "Released":
        present.append("Order status: Released")
        rules.append("R1: Order is Released — downstream actions may proceed")
    elif status == "Posted":
        present.append("Order status: Posted")
    elif status == "Unknown":
        missing.append("Order status not determined")
        rules.append("R1: Cannot determine order status — treating as Draft")


def _check_customer_po(ctx, blocking, present, missing, rules):
    """Rule 2: Customer PO control."""
    if ctx["po_number"]:
        present.append(f"Customer PO: {ctx['po_number']}")
    else:
        missing.append("Customer PO number not extracted")
        blocking.append("Customer PO missing — required control absent")
        rules.append("R2: Customer PO attachment is a required control — not present")

    if not ctx["has_po_attachment"]:
        rules.append("R2: No evidence of PO attachment in Documents fact box")


def _check_line_items(ctx, blocking, present, missing, rules, risks):
    """Rule 3: Sales order line rules."""
    lines = ctx["line_items"]
    if not lines:
        missing.append("No line items extracted")
        rules.append("R3: Cannot evaluate line rules — no lines present")
        return

    present.append(f"Line items: {len(lines)} extracted")

    missing_fields = {"item": 0, "quantity": 0, "price": 0}
    for li in lines:
        desc = li.get("description") or li.get("item_description") or ""
        qty = li.get("quantity") or li.get("ordered_qty")
        price = li.get("unit_price") or li.get("price")

        if not desc:
            missing_fields["item"] += 1
        if not qty:
            missing_fields["quantity"] += 1
        if not price and "freight" not in desc.lower():
            missing_fields["price"] += 1

    for field, count in missing_fields.items():
        if count > 0:
            risks.append(f"R3: {count} line(s) missing {field}")


def _check_cost_rules(ctx, blocking, present, missing, rules):
    """Rule 4: Cost rules."""
    lines = ctx["inventory_lines"]
    if not lines:
        return

    lines_needing_cost = [
        li for li in lines
        if not li.get("drop_shipment")
        and (li.get("type") or "").lower() in ("", "item", "service")
    ]

    if lines_needing_cost and ctx["lines_with_cost"] == 0:
        rules.append("R4: Service/item lines without drop ship should have cost entered")
        if ctx["status"] == "Released":
            rules.append("R4: Cost may be conditionally acceptable if documented process allows later entry")


def _check_price_rules(ctx, blocking, rules, risks):
    """Rule 5: Price change rules."""
    if ctx["status"] == "Released" and ctx["lines_with_price"] == 0:
        risks.append("R5: Released order with no prices on lines — potential price issue")
    # Note: We can't detect price changes without historical data
    # Flag as a risk if order is released and we're re-evaluating
    rules.append("R5: If price changes after release, order must be reopened and re-released")


def _check_drop_ship_rules(ctx, blocking, present, missing, rules):
    """Rule 6: Drop-ship rules."""
    if not ctx["is_drop_ship"]:
        return

    rules.append("R6: Drop-ship order detected")

    if ctx["has_po_linkage"]:
        present.append("Drop-ship PO linkage present")
    else:
        missing.append("Drop-ship PO linkage not found")
        blocking.append("Drop-ship order missing corresponding PO linkage")
        rules.append("R6: Missing PO linkage is a blocking exception for drop-ship orders")

    # Check that drop-ship lines are properly marked
    ds_lines = [li for li in ctx["line_items"] if li.get("drop_shipment") or li.get("purchasing_code") == "DROP SHIP"]
    non_freight_lines = ctx["inventory_lines"]

    if non_freight_lines and not ds_lines:
        rules.append("R6: Inventory lines found but none marked as Drop Shipment — verify purchasing code")


def _check_freight_rules(ctx, blocking, present, missing, rules, risks):
    """Rule 7: Freight rules."""
    if ctx["freight_lines"]:
        present.append(f"Freight lines: {len(ctx['freight_lines'])}")
    elif ctx["is_drop_ship"]:
        rules.append("R7: Drop-ship order with no freight lines — may be acceptable if Gamer Logistics manages freight on SO")
    elif ctx["line_count"] > 0:
        risks.append("R7: No freight lines detected — verify freight coordination")


def _check_confirmation_rules(ctx, blocking, rules):
    """Rule 8: Confirmation rules."""
    if ctx["status"] == "Released" and not ctx["confirmation_sent"]:
        rules.append("R8: Released order without confirmation sent — classify as Confirmation Needed")
    elif ctx["confirmation_sent"]:
        rules.append("R8: Order confirmation has been sent")


def _check_pick_rules(ctx, blocking, rules):
    """Rule 9: Pick rules."""
    if ctx["is_warehouse"] and ctx["status"] == "Released" and not ctx["pick_sent"]:
        rules.append("R9: Warehouse order without pick instructions — classify as Pick Needed")


def _check_readiness(ctx, blocking, present, missing, rules):
    """Rule 10: Shipping and invoicing readiness."""
    if ctx["shipped"]:
        present.append("Shipment evidence detected")
        rules.append("R10: Shipped — may still require review before invoicing")
    elif ctx["status"] == "Released":
        rules.append("R10: Released but not shipped — not ready for invoice posting")

    if not ctx["has_customer_resolved"]:
        missing.append("Customer not resolved in BC")
        if ctx["status"] in ("Released", "Posted"):
            blocking.append("Customer not resolved in BC — cannot post")


# ─────────────────────────────────────────────────────────────
# DETERMINATION LOGIC
# ─────────────────────────────────────────────────────────────

def _determine_stage(ctx, blocking, rules) -> str:
    """Determine the canonical workflow stage."""
    status = ctx["status"]

    if status == "Posted":
        return "Posted"
    if status == "Pending Approval":
        return "Pending Approval"
    if status == "Pending Prepayment":
        return "Pending Prepayment"

    if blocking:
        return "Exception / Needs Review"

    if status in ("Open", "Draft / Open", "Unknown"):
        return "Draft / Open"

    # Released path
    if status == "Released":
        if ctx["shipped"]:
            return "Shipped / Ready to Invoice"
        if ctx["is_drop_ship"] and not ctx["has_po_linkage"]:
            return "Drop Ship PO Needed"
        if not ctx["confirmation_sent"]:
            return "Confirmation Needed"
        if ctx["is_warehouse"] and not ctx["pick_sent"]:
            return "Pick Needed"
        return "Released"

    return "Exception / Needs Review"


def _determine_compliance(blocking, missing, ctx) -> str:
    """Determine compliance status."""
    if blocking:
        return "Non-Compliant"
    if missing:
        if len(missing) <= 2 and ctx.get("has_customer_resolved"):
            return "Conditionally Compliant"
        return "Insufficient Evidence"
    return "Compliant"


def _determine_confidence(ctx, present, missing) -> str:
    """Determine confidence level."""
    evidence_count = len(present)
    gap_count = len(missing)

    if evidence_count >= 4 and gap_count == 0:
        return "High"
    if evidence_count >= 2 and gap_count <= 2:
        return "Medium"
    return "Low"


def _determine_next_action(stage, blocking, missing, ctx) -> Tuple[str, str]:
    """Determine the recommended next action and explanation."""
    if stage == "Posted":
        return "None — order is posted", "Order has been posted to BC"

    if stage == "Exception / Needs Review":
        top_blocker = blocking[0] if blocking else "Unknown blocking issue"
        return f"Resolve: {top_blocker}", f"Order cannot proceed — {len(blocking)} blocking issue(s) must be resolved first"

    if stage == "Draft / Open":
        if not ctx["po_number"]:
            return "Obtain customer PO", "Customer PO is a required control before the order can be released"
        if not ctx["has_customer_resolved"]:
            return "Resolve customer in BC", "Customer must be resolved in Business Central before release"
        return "Submit for approval/release", "Order is in draft — next step is approval and release"

    if stage == "Pending Approval":
        return "Await approval", "Order is pending approval — no downstream actions until approved"

    if stage == "Pending Prepayment":
        return "Collect prepayment", "Order requires prepayment before it can be released"

    if stage == "Confirmation Needed":
        return "Send order confirmation to customer", "Order is released but confirmation has not been sent"

    if stage == "Pick Needed":
        return "Generate and send pick instructions", "Warehouse order released but pick not yet created"

    if stage == "Drop Ship PO Needed":
        return "Create corresponding purchase order for drop-ship lines", "Drop-ship order requires a linked PO with matching SO data"

    if stage == "Drop Ship PO Incomplete":
        return "Complete drop-ship PO (verify line match, cost, location)", "PO exists but is missing required fields"

    if stage == "Waiting for Freight":
        return "Coordinate freight", "Freight arrangement must be completed before shipment"

    if stage == "Shipped / Ready to Invoice":
        return "Review for invoice readiness", "Shipment detected — verify hold conditions, figures, and exceptions before posting invoice"

    if stage == "Released":
        if ctx["is_drop_ship"]:
            return "Verify drop-ship PO is complete", "Released drop-ship order — ensure PO linkage and costs are correct"
        return "Proceed with fulfillment", "Order is released and compliant — execute fulfillment"

    return "Review order", "Unable to determine specific next action"


# ─────────────────────────────────────────────────────────────
# BATCH EVALUATION
# ─────────────────────────────────────────────────────────────

async def evaluate_all_pilot_sales_orders() -> Dict[str, Any]:
    """Run the rules engine on all pilot sales order documents."""
    db = get_db()
    docs = await db.hub_documents.find(
        {
            "inside_sales_pilot": True,
            "doc_type": {"$in": ["SALES_INVOICE", "Sales_Order", "Order_Confirmation"]},
        },
        {"_id": 0, "id": 1},
    ).to_list(500)

    results = {
        "total": len(docs),
        "evaluated": 0,
        "errors": 0,
        "stages": {},
        "compliance": {},
    }
    for doc in docs:
        try:
            r = await evaluate_sales_order(doc["id"])
            results["evaluated"] += 1
            stage = r.get("stage", "Unknown")
            comp = r.get("compliance_status", "Unknown")
            results["stages"][stage] = results["stages"].get(stage, 0) + 1
            results["compliance"][comp] = results["compliance"].get(comp, 0) + 1
        except Exception as e:
            results["errors"] += 1
            logger.error("[SORulesEngine] Error on %s: %s", doc["id"][:8], e)

    return results
