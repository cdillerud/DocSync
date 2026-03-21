"""
GPI Document Hub - Notification Service

Sends automated notifications when Sales Orders reach key workflow states:
  - Warehouse Receiving Notice → Logistics team (when WH SO is booked)
  - SO Confirmation → Customer (when SO is booked/confirmed)

Both functions accept ``dry_run=True`` which logs the assembled content
without actually sending. In non-dry-run mode, emails are dispatched via
the existing email_service (Mock provider in dev, MS Graph in production).
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

# hub_config _key for notification addresses
NOTIFICATION_CONFIG_KEY = "notification_config"

# Defaults (overridden by hub_config at runtime)
_DEFAULT_WAREHOUSE_EMAIL = ""
_DEFAULT_FROM_ADDRESS = "GPI Document Hub <noreply@gpi-hub.local>"


# =========================================================================
# Config Helpers
# =========================================================================

async def get_notification_config(db=None) -> Dict[str, Any]:
    """Read notification config from hub_config collection."""
    if db is None:
        db = get_db()
    cfg = await db.hub_config.find_one(
        {"_key": NOTIFICATION_CONFIG_KEY}, {"_id": 0}
    )
    if not cfg:
        cfg = {"_key": NOTIFICATION_CONFIG_KEY}
    return {
        "warehouse_receiving_email": cfg.get("warehouse_receiving_email", _DEFAULT_WAREHOUSE_EMAIL),
        "from_address": cfg.get("from_address", _DEFAULT_FROM_ADDRESS),
        "enabled": cfg.get("enabled", True),
    }


async def save_notification_config(
    db, warehouse_receiving_email: str = "", from_address: str = "", enabled: bool = True
) -> Dict[str, Any]:
    """Persist notification config to hub_config collection."""
    update_doc = {
        "_key": NOTIFICATION_CONFIG_KEY,
        "warehouse_receiving_email": warehouse_receiving_email.strip(),
        "from_address": from_address.strip() or _DEFAULT_FROM_ADDRESS,
        "enabled": enabled,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    await db.hub_config.update_one(
        {"_key": NOTIFICATION_CONFIG_KEY},
        {"$set": update_doc},
        upsert=True,
    )
    return {k: v for k, v in update_doc.items() if k != "_key"}


# =========================================================================
# Content Builders
# =========================================================================

def _build_warehouse_receiving_notice_content(
    doc: Dict[str, Any], so_data: Dict[str, Any]
) -> Dict[str, str]:
    """Build subject + HTML body for the Warehouse Receiving Notice.

    Content: SO number, customer, line items, expected delivery date,
    ship-to warehouse location.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    so_number = so_data.get("bc_record_no") or so_data.get("external_doc_no") or "N/A"
    customer = so_data.get("customer_name") or ef.get("customer") or "N/A"
    external_po = so_data.get("external_doc_no") or ef.get("po_number") or ""
    order_date = so_data.get("order_date") or ef.get("order_date") or ""
    expected_delivery = ef.get("delivery_date") or ef.get("ship_date") or nf.get("delivery_date") or "TBD"

    routing = so_data.get("so_routing") or {}
    location_code = routing.get("location_code") or ef.get("location_code") or "MAIN"

    # Line items
    lines = so_data.get("resolved_lines") or []
    if not lines:
        lines = ef.get("line_items") or nf.get("line_items") or []

    lines_html = ""
    if lines:
        rows = ""
        for i, ln in enumerate(lines, 1):
            desc = ln.get("description") or ""
            qty = ln.get("quantity", ln.get("qty", ""))
            item = ln.get("lineObjectNumber") or ln.get("item_number") or ln.get("item") or ""
            rows += f"<tr><td>{i}</td><td>{item}</td><td>{desc}</td><td>{qty}</td></tr>\n"
        lines_html = f"""
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; width:100%; margin-top:12px;">
  <thead><tr style="background:#f0f0f0;"><th>#</th><th>Item</th><th>Description</th><th>Qty</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    else:
        lines_html = "<p><em>No line items available.</em></p>"

    subject = f"Warehouse Receiving Notice - SO {so_number}"
    html_body = f"""
<h2>Warehouse Receiving Notice</h2>
<p>A new warehouse Sales Order has been booked and requires receiving preparation.</p>
<table cellpadding="4">
  <tr><td><strong>SO Number:</strong></td><td>{so_number}</td></tr>
  <tr><td><strong>Customer:</strong></td><td>{customer}</td></tr>
  <tr><td><strong>Customer PO:</strong></td><td>{external_po}</td></tr>
  <tr><td><strong>Order Date:</strong></td><td>{order_date}</td></tr>
  <tr><td><strong>Expected Delivery:</strong></td><td>{expected_delivery}</td></tr>
  <tr><td><strong>Warehouse Location:</strong></td><td>{location_code}</td></tr>
</table>
<h3>Line Items</h3>
{lines_html}
<p style="margin-top:16px; color:#666;">This notice was generated automatically by GPI Document Hub.</p>
"""
    text_body = (
        f"Warehouse Receiving Notice\n"
        f"SO Number: {so_number}\n"
        f"Customer: {customer}\n"
        f"Customer PO: {external_po}\n"
        f"Order Date: {order_date}\n"
        f"Expected Delivery: {expected_delivery}\n"
        f"Warehouse Location: {location_code}\n"
    )
    return {"subject": subject, "html_body": html_body, "text_body": text_body}


def _build_so_confirmation_content(
    doc: Dict[str, Any], so_data: Dict[str, Any]
) -> Dict[str, str]:
    """Build subject + HTML body for the SO Confirmation sent to the customer.

    Content: SO number, external PO number, line items, confirmed ship date.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    so_number = so_data.get("bc_record_no") or "N/A"
    customer = so_data.get("customer_name") or ef.get("customer") or "N/A"
    external_po = so_data.get("external_doc_no") or ef.get("po_number") or ""
    confirmed_ship_date = ef.get("ship_date") or ef.get("delivery_date") or nf.get("ship_date") or "TBD"

    lines = so_data.get("resolved_lines") or []
    if not lines:
        lines = ef.get("line_items") or nf.get("line_items") or []

    lines_html = ""
    if lines:
        rows = ""
        for i, ln in enumerate(lines, 1):
            desc = ln.get("description") or ""
            qty = ln.get("quantity", ln.get("qty", ""))
            price = ln.get("unitPrice", ln.get("unit_price", ""))
            rows += f"<tr><td>{i}</td><td>{desc}</td><td>{qty}</td><td>{price}</td></tr>\n"
        lines_html = f"""
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse; width:100%; margin-top:12px;">
  <thead><tr style="background:#f0f0f0;"><th>#</th><th>Description</th><th>Qty</th><th>Unit Price</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    else:
        lines_html = "<p><em>Line item details will follow.</em></p>"

    subject = f"Sales Order Confirmation - SO {so_number} (PO {external_po})" if external_po else f"Sales Order Confirmation - SO {so_number}"
    html_body = f"""
<h2>Sales Order Confirmation</h2>
<p>Thank you for your order. This confirms that your Sales Order has been booked.</p>
<table cellpadding="4">
  <tr><td><strong>SO Number:</strong></td><td>{so_number}</td></tr>
  <tr><td><strong>Your PO Number:</strong></td><td>{external_po or 'N/A'}</td></tr>
  <tr><td><strong>Customer:</strong></td><td>{customer}</td></tr>
  <tr><td><strong>Confirmed Ship Date:</strong></td><td>{confirmed_ship_date}</td></tr>
</table>
<h3>Order Details</h3>
{lines_html}
<p style="margin-top:16px; color:#666;">If you have questions about this order, please contact Gamer Packaging, Inc.</p>
"""
    text_body = (
        f"Sales Order Confirmation\n"
        f"SO Number: {so_number}\n"
        f"Your PO Number: {external_po or 'N/A'}\n"
        f"Customer: {customer}\n"
        f"Confirmed Ship Date: {confirmed_ship_date}\n"
    )
    return {"subject": subject, "html_body": html_body, "text_body": text_body}


# =========================================================================
# Send Functions
# =========================================================================

async def send_warehouse_receiving_notice(
    doc: Dict[str, Any],
    so_data: Dict[str, Any],
    dry_run: bool = True,
    db=None,
) -> Dict[str, Any]:
    """Send Warehouse Receiving Notice to Logistics.

    Args:
        doc: The hub_documents record.
        so_data: The bc_sales_order sub-document (or preflight result).
        dry_run: If True, assemble and log but do NOT send.
        db: Optional MongoDB handle (uses get_db() if None).

    Returns:
        Dict with keys: sent, dry_run, subject, to, content, result.
    """
    if db is None:
        db = get_db()

    config = await get_notification_config(db)
    recipient = config.get("warehouse_receiving_email", "")
    from_addr = config.get("from_address", _DEFAULT_FROM_ADDRESS)
    enabled = config.get("enabled", True)

    content = _build_warehouse_receiving_notice_content(doc, so_data)

    outcome = {
        "type": "warehouse_receiving_notice",
        "dry_run": dry_run,
        "subject": content["subject"],
        "to": recipient,
        "from_address": from_addr,
        "content": content,
        "doc_id": doc.get("id", ""),
        "so_number": so_data.get("bc_record_no", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        logger.info(
            "[DRY-RUN] Warehouse Receiving Notice: to=%s subject='%s'",
            recipient or "(not configured)", content["subject"],
        )
        outcome["sent"] = False
        outcome["reason"] = "dry_run"
        return outcome

    if not enabled:
        logger.info("[NOTIFICATION] Notifications disabled — skipping warehouse receiving notice")
        outcome["sent"] = False
        outcome["reason"] = "disabled"
        return outcome

    if not recipient:
        logger.warning("[NOTIFICATION] No warehouse_receiving_email configured — skipping")
        outcome["sent"] = False
        outcome["reason"] = "no_recipient"
        return outcome

    # Send via email_service
    from services.email_service import get_email_service
    svc = get_email_service()
    result = await svc.send_email(
        to=[recipient],
        subject=content["subject"],
        html_body=content["html_body"],
        text_body=content["text_body"],
        from_address=from_addr,
    )
    outcome["sent"] = result.success
    outcome["result"] = result.to_dict()
    logger.info(
        "[NOTIFICATION] Warehouse Receiving Notice sent=%s to=%s msg_id=%s",
        result.success, recipient, result.message_id,
    )
    return outcome


async def send_so_confirmation_to_customer(
    doc: Dict[str, Any],
    so_data: Dict[str, Any],
    customer_email: str = "",
    dry_run: bool = True,
    db=None,
) -> Dict[str, Any]:
    """Send SO Confirmation to the customer.

    Args:
        doc: The hub_documents record.
        so_data: The bc_sales_order sub-document.
        customer_email: Explicit customer email. Falls back to doc fields.
        dry_run: If True, assemble and log but do NOT send.
        db: Optional MongoDB handle.

    Returns:
        Dict with keys: sent, dry_run, subject, to, content, result.
    """
    if db is None:
        db = get_db()

    config = await get_notification_config(db)
    from_addr = config.get("from_address", _DEFAULT_FROM_ADDRESS)
    enabled = config.get("enabled", True)

    # Resolve customer email from doc, extracted fields, or Spiro CRM
    ef = doc.get("extracted_fields") or {}
    recipient = customer_email or ef.get("customer_email") or ef.get("email") or ""

    # Fallback: check spiro_data on the document
    if not recipient:
        spiro = doc.get("spiro_data") or {}
        recipient = spiro.get("email") or spiro.get("contact_email") or ""

    content = _build_so_confirmation_content(doc, so_data)

    outcome = {
        "type": "so_confirmation",
        "dry_run": dry_run,
        "subject": content["subject"],
        "to": recipient,
        "from_address": from_addr,
        "content": content,
        "doc_id": doc.get("id", ""),
        "so_number": so_data.get("bc_record_no", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        logger.info(
            "[DRY-RUN] SO Confirmation: to=%s subject='%s'",
            recipient or "(no customer email)", content["subject"],
        )
        outcome["sent"] = False
        outcome["reason"] = "dry_run"
        return outcome

    if not enabled:
        logger.info("[NOTIFICATION] Notifications disabled — skipping SO confirmation")
        outcome["sent"] = False
        outcome["reason"] = "disabled"
        return outcome

    if not recipient:
        logger.warning("[NOTIFICATION] No customer email found — skipping SO confirmation")
        outcome["sent"] = False
        outcome["reason"] = "no_recipient"
        return outcome

    from services.email_service import get_email_service
    svc = get_email_service()
    result = await svc.send_email(
        to=[recipient],
        subject=content["subject"],
        html_body=content["html_body"],
        text_body=content["text_body"],
        from_address=from_addr,
    )
    outcome["sent"] = result.success
    outcome["result"] = result.to_dict()
    logger.info(
        "[NOTIFICATION] SO Confirmation sent=%s to=%s msg_id=%s",
        result.success, recipient, result.message_id,
    )
    return outcome


# =========================================================================
# Orchestrator — called from workflow engine or SO creation
# =========================================================================

async def on_warehouse_so_booked(
    doc: Dict[str, Any],
    so_data: Dict[str, Any],
    dry_run: bool = False,
    db=None,
) -> Dict[str, Any]:
    """Orchestrate all notifications when a Warehouse SO reaches Booked state.

    Sends:
      1. Warehouse Receiving Notice → Logistics
      2. SO Confirmation → Customer

    Returns a summary dict with results for each notification.
    """
    results = {}
    results["warehouse_notice"] = await send_warehouse_receiving_notice(
        doc, so_data, dry_run=dry_run, db=db
    )
    results["so_confirmation"] = await send_so_confirmation_to_customer(
        doc, so_data, dry_run=dry_run, db=db
    )
    return results
