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

    # ── HARD GATE: Gamer is NEVER the customer on a Sales Order ──
    # If customer resolves to Gamer, this is an inbound vendor/purchase document.
    customer = (ctx.get("customer") or "").lower()
    customer_no = (ctx.get("customer_no") or "").upper()
    is_gamer_customer = (
        "gamer" in customer
        or customer_no in ("GAMER", "GAMERPA", "GAMER1")
    )
    if is_gamer_customer:
        result = {
            "document_id": doc_id,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "stage": "Not a Sales Order",
            "compliance_status": "Not Applicable",
            "blocking_issues": ["Customer is Gamer Packaging — this is an inbound vendor/purchase document, not a sales order"],
            "required_controls_present": [],
            "required_controls_missing": [],
            "business_rules_triggered": ["HARD GATE: Gamer is never the customer on a Sales Order. Gamer is the seller."],
            "operational_risks": ["Document should be reclassified as Vendor_Document or Purchase_Order"],
            "recommended_next_action": "Reclassify — this is a vendor document (PO to Gamer), not a GPI sales order",
            "why": "Gamer Packaging is the buyer on this document. Sales Orders are documents where Gamer sells TO a customer.",
            "confidence": "High",
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
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"so_rules_evaluation": result}},
        )
        logger.info("[SORulesEngine] doc=%s HARD GATE: customer is Gamer — not a sales order", doc_id[:8])
        return result

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
    """Build a normalized order context from all available data sources.

    Priority: main pipeline fields > extracted_fields > normalized_fields > pilot extraction.
    The main pipeline has 2-3 months of learned intelligence — always prefer it.

    Special handling:
    - If vendor_canonical resolves to "Gamer", skip it (Gamer is the seller, not the customer)
    - For amount, the main pipeline stores as "amount_float", not "total_amount"
    """

    # Customer: main pipeline's vendor resolution first, but skip if Gamer
    raw_vendor = doc.get("vendor_canonical") or ""
    is_gamer_vendor = "gamer" in raw_vendor.lower()

    if is_gamer_vendor:
        # Gamer resolved as vendor — wrong for sales context. Use extracted fields.
        customer = (
            ef.get("customer") or ef.get("customer_name") or ef.get("bill_to")
            or ef.get("vendor_name")
            or nf.get("customer")
            or ext.get("customer_name")
        )
    else:
        customer = (
            raw_vendor  # Main pipeline (learned)
            or ef.get("customer") or ef.get("customer_name")
            or nf.get("customer")
            or ext.get("customer_name")
        )

    customer_no = (
        doc.get("matched_customer_no") or doc.get("customer_no")  # Main pipeline
        or nf.get("customer_no")
        or (bc_val.get("customer_match") or {}).get("bc_customer_no")
    )
    # Clear Gamer customer_no — it's the seller, not the customer
    if customer_no and customer_no.upper() in ("GAMER", "GAMERPA", "GAMER1"):
        customer_no = None

    # PO: main pipeline's resolution first
    po_number = (
        doc.get("po_resolution_number")  # Main pipeline
        or ef.get("po_number") or nf.get("customer_po")
        or ext.get("po_number")
    )

    # Order number
    order_number = (
        ef.get("order_number") or ef.get("sales_order_number")
        or nf.get("order_number")
        or ext.get("order_number")
    )

    # Amount: main pipeline stores as "amount_float" (top-level), not "total_amount"
    amount = (
        doc.get("amount_float")  # Main pipeline's top-level amount
        or doc.get("total_amount")  # Fallback
        or nf.get("amount_float") or nf.get("amount")
        or ef.get("total_amount") or ef.get("amount") or ef.get("grand_total")
        or ext.get("total_amount")
    )

    status = (
        ef.get("order_status") or ef.get("status")
        or nf.get("order_status") or doc.get("workflow_status")
    )
    ship_to = ef.get("ship_to") or nf.get("ship_to") or ext.get("ship_to")
    ship_date = ef.get("ship_date") or nf.get("requested_ship_date") or ext.get("requested_ship_date")

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
# RULE CHECKS — SO-001 through SO-011
# ─────────────────────────────────────────────────────────────

def _check_status_governance(ctx, blocking, present, missing, rules):
    """SO-002/003/004: Status governance."""
    status = ctx["status"]
    if status == "Pending Approval":
        blocking.append("SO-003: Order blocked by approval workflow (Pending Approval)")
        rules.append("SO-003: Status = Pending Approval → classified as blocked by approval workflow")
    elif status == "Pending Prepayment":
        blocking.append("SO-004: Order blocked by prepayment workflow (Pending Prepayment)")
        rules.append("SO-004: Status = Pending Prepayment → classified as blocked by prepayment workflow")
    elif status in ("Open", "Draft / Open"):
        rules.append("SO-002: Status != Released → downstream completion not allowed")
    elif status == "Released":
        present.append("Order status: Released")
        rules.append("SO-002: Status = Released → downstream actions may proceed")
    elif status == "Posted":
        present.append("Order status: Posted")
    elif status == "Unknown":
        missing.append("Order status not determined")
        rules.append("SO-002: Cannot determine order status → treating as not Released")


def _check_customer_po(ctx, blocking, present, missing, rules):
    """SO-001: Customer PO control."""
    if ctx["po_number"]:
        present.append(f"Customer PO: {ctx['po_number']}")
    else:
        missing.append("Customer PO")
        # Only block if this appears to be a GPI-originated sales order
        # Inbound vendor docs may not have a separate PO number — the doc itself IS the PO
        is_inbound = (ctx.get("customer") or "").lower().startswith("gamer")
        file_name = (ctx.get("file_name") or "").lower()
        is_vendor_confirmation = any(ind in file_name for ind in [
            "confirmation", "order ack", "ord_ack",
            "_ack.", "_ack_", "acknowledg", "proforma",
        ])
        doc_type = ctx.get("doc_type", "")
        is_vendor_type = doc_type in ("Vendor_Document", "Purchase_Order")
        if is_inbound or is_vendor_confirmation or is_vendor_type:
            rules.append("SO-001: Customer PO not extracted — but this appears to be an inbound vendor document (PO implicit)")
        else:
            blocking.append("SO-001: Customer PO missing — required control absent, Non-Compliant unless exception evidence exists")
            rules.append("SO-001: Customer PO attachment missing → Required Controls Missing = Customer PO, Compliance = Non-Compliant")

    if not ctx["has_po_attachment"]:
        rules.append("SO-001: No evidence of PO attachment in Documents fact box")


def _check_line_items(ctx, blocking, present, missing, rules, risks):
    """Line item evaluation (supports SO-005, SO-008, SO-009)."""
    lines = ctx["line_items"]
    if not lines:
        missing.append("No line items extracted")
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
            risks.append(f"{count} line(s) missing {field}")


def _check_cost_rules(ctx, blocking, present, missing, rules):
    """SO-005: Service item cost rule.

    Only applies to GPI-created Sales Orders where cost should be present.
    Does NOT apply to inbound vendor documents (POs, order confirmations)
    where cost naturally lives on the BC Purchase Order, not the PDF.
    """
    lines = ctx["inventory_lines"]
    if not lines:
        return

    # Detect if this is an inbound vendor document vs a GPI sales order
    # Inbound vendor docs: order confirmations, vendor POs, invoices FROM vendors
    file_name = (ctx.get("file_name") or "").lower()
    is_vendor_doc = any(ind in file_name for ind in [
        "confirmation", "order ack", "ord_ack", "vendor", "supplier",
        "_ack.", "_ack_", "acknowledg", "proforma",
    ])
    doc_type = ctx.get("doc_type", "")
    is_vendor_type = doc_type in ("Vendor_Document", "Purchase_Order")
    # If the customer resolved as "GAMER" — this is a vendor sending TO us, not our SO
    is_inbound = (ctx.get("customer") or "").lower().startswith("gamer")

    if is_vendor_doc or is_inbound or is_vendor_type:
        rules.append("SO-005: Skipped — inbound vendor document (cost lives on BC PO, not vendor confirmation)")
        return

    lines_needing_cost = [
        li for li in lines
        if not li.get("drop_shipment")
        and (li.get("type") or "").lower() in ("", "item", "service")
    ]

    if lines_needing_cost and ctx["lines_with_cost"] == 0:
        blocking.append("SO-005: Service/item lines (non drop ship) with missing cost — business rule violation")
        rules.append("SO-005: Line is service item AND not drop ship AND cost missing → business rule violation")


def _check_price_rules(ctx, blocking, rules, risks):
    """SO-010: Price change on released order."""
    if ctx["status"] == "Released" and ctx["lines_with_price"] == 0:
        risks.append("SO-010: Released order with no prices on lines — potential price issue")
    rules.append("SO-010: If released order price changed → must reopen and rerelease")


def _check_drop_ship_rules(ctx, blocking, present, missing, rules):
    """SO-008/009: Drop-ship PO rules."""
    if not ctx["is_drop_ship"]:
        return

    if ctx["has_po_linkage"]:
        present.append("Drop-ship PO linkage present")
        # SO-009: Check if PO cost is present
        # We can't directly check PO cost from the SO doc, flag as risk
        rules.append("SO-009: Drop ship PO exists — verify PO cost is entered (cannot confirm from SO data alone)")
    else:
        missing.append("Drop-ship PO linkage")
        blocking.append("SO-008: Drop ship order AND PO missing → stage = Drop Ship PO Needed")
        rules.append("SO-008: Drop ship order AND PO missing → Drop Ship PO Needed, blocking")

    ds_lines = [li for li in ctx["line_items"] if li.get("drop_shipment") or li.get("purchasing_code") == "DROP SHIP"]
    non_freight_lines = ctx["inventory_lines"]

    if non_freight_lines and not ds_lines:
        rules.append("SO-008: Inventory lines found but none marked as Drop Shipment — verify purchasing code")


def _check_freight_rules(ctx, blocking, present, missing, rules, risks):
    """Freight evaluation (supports operational assessment)."""
    if ctx["freight_lines"]:
        present.append(f"Freight lines: {len(ctx['freight_lines'])}")
    elif ctx["is_drop_ship"]:
        rules.append("Freight: Drop-ship order with no freight lines — acceptable if Gamer Logistics manages freight on SO")
    elif ctx["line_count"] > 0:
        risks.append("No freight lines detected — verify freight coordination")


def _check_confirmation_rules(ctx, blocking, rules):
    """SO-006: Confirmation on released order."""
    if ctx["status"] == "Released" and not ctx["confirmation_sent"]:
        rules.append("SO-006: Released order has unsent confirmation → stage = Confirmation Needed")
    elif ctx["confirmation_sent"]:
        rules.append("SO-006: Order confirmation has been sent")


def _check_pick_rules(ctx, blocking, rules):
    """SO-007: Pick instructions on warehouse order."""
    if ctx["is_warehouse"] and ctx["status"] == "Released" and not ctx["pick_sent"]:
        rules.append("SO-007: Warehouse order AND pick instructions unsent → stage = Pick Needed")


def _check_readiness(ctx, blocking, present, missing, rules):
    """SO-011: Shipping and invoicing readiness."""
    if ctx["shipped"]:
        present.append("Shipment evidence detected")
        rules.append("SO-011: Shipped but final readiness controls not fully evidenced → stage = Shipped / Ready to Invoice, NOT Ready to Post Invoice")
    elif ctx["status"] == "Released":
        rules.append("SO-011: Released but not shipped — not ready for invoice posting")

    if not ctx["has_customer_resolved"]:
        missing.append("Customer not resolved in BC")
        if ctx["status"] in ("Released", "Posted"):
            blocking.append("Customer not resolved in BC — cannot post")


# ─────────────────────────────────────────────────────────────
# DETERMINATION LOGIC
# ─────────────────────────────────────────────────────────────

def _determine_stage(ctx, blocking, rules) -> str:
    """Determine the canonical workflow stage using SO rule precedence."""
    status = ctx["status"]

    if status == "Posted":
        return "Posted"

    # SO-003: Pending Approval = blocked
    if status == "Pending Approval":
        return "Pending Approval"

    # SO-004: Pending Prepayment = blocked
    if status == "Pending Prepayment":
        return "Pending Prepayment"

    # SO-002: If not Released, treat as Draft unless blocking
    if status in ("Open", "Draft / Open", "Unknown"):
        if blocking:
            return "Exception / Needs Review"
        return "Draft / Open"

    # Released path — apply downstream rules in order
    if status == "Released":
        # Check blocking issues first
        if blocking:
            # SO-008: Drop ship PO missing
            if ctx["is_drop_ship"] and not ctx["has_po_linkage"]:
                return "Drop Ship PO Needed"
            return "Exception / Needs Review"

        # SO-011: Shipped but readiness not fully evidenced
        if ctx["shipped"]:
            return "Shipped / Ready to Invoice"

        # SO-008: Drop ship PO needed
        if ctx["is_drop_ship"] and not ctx["has_po_linkage"]:
            return "Drop Ship PO Needed"

        # SO-006: Confirmation needed
        if not ctx["confirmation_sent"]:
            return "Confirmation Needed"

        # SO-007: Pick needed
        if ctx["is_warehouse"] and not ctx["pick_sent"]:
            return "Pick Needed"

        return "Released"

    if blocking:
        return "Exception / Needs Review"

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
    """Run the rules engine on all pilot sales order documents.

    Skips docs that have been reclassified (e.g., Vendor_Document) since
    they are not genuine customer purchase orders.
    """
    db = get_db()
    docs = await db.hub_documents.find(
        {
            "inside_sales_pilot": True,
            "doc_type": {"$in": ["SALES_INVOICE", "Sales_Order", "Order_Confirmation"]},
            "reclassified_from": {"$exists": False},  # Skip reclassified docs
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
