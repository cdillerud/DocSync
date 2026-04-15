"""
GPI Document Hub — Pilot Smart Reclassifier

Automatically reclassifies pilot documents that were incorrectly
tagged as SALES_INVOICE by analyzing filename, email context,
extraction quality, and content signals.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from deps import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# CLASSIFICATION RULES (ordered by specificity)
# ─────────────────────────────────────────────────────────────

_RULES: List[Tuple[str, Any, str, str]] = [
    # (rule_name, pattern_or_callable, new_doc_type, reason)
    #
    # ORDER MATTERS: most specific / noise rules first, broad rules last.
    # Filename-anchored rules ($) are also checked against filename alone.

    # ── 1. Logos / Images / Signatures (noise — highest priority) ──
    ("logo_file", re.compile(r"(?i)logo.*\.(png|jpg|jpeg|gif|bmp|svg|webp)$"), "Miscellaneous", "Logo image — not a document"),
    ("image_noise", re.compile(r"(?i)^(image|img|photo|pic|banner|icon)[_\s\-]?\d*\.(png|jpg|jpeg|gif|bmp|svg|webp)$"), "Miscellaneous", "Image file — not a document"),
    ("signature_file", re.compile(r"(?i)(signature|sig)[_\s\-]?\d*\.(png|jpg|jpeg|gif)$"), "Miscellaneous", "Email signature image"),
    ("small_jpg", re.compile(r"(?i)^[^/]{0,30}\.(png|jpg|jpeg|gif)$"), "Miscellaneous", "Small image file — likely not a sales document"),

    # ── 2. Certificates / Compliance ──
    ("cert_sqf", re.compile(r"(?i)\bSQF\b"), "Certificate", "SQF certification document"),
    ("cert_iso", re.compile(r"(?i)\bISO[\s\-_]\d"), "Certificate", "ISO certification document"),
    ("cert_generic", re.compile(r"(?i)\bcertificate\b"), "Certificate", "Certificate document"),
    ("cert_filename", re.compile(r"(?i)certif"), "Certificate", "Certificate (filename match)"),

    # ── 3. Order Confirmations / Vendor Acknowledgments ──
    # These are INBOUND vendor documents (vendor confirming THEIR order to Gamer),
    # NOT customer purchase orders. Must be caught before generic rules.
    ("order_confirmation", re.compile(r"(?i)\border\s*confirm"), "Vendor_Document", "Order confirmation from vendor — not a customer PO"),
    ("order_acknowledgment", re.compile(r"(?i)\border\s*ack"), "Vendor_Document", "Order acknowledgment from vendor — not a customer PO"),
    ("vendor_confirmation", re.compile(r"(?i)\bconfirmation\b(?!.*\bcertif)"), "Vendor_Document", "Vendor confirmation document — not a customer PO"),
    ("acknowledgment_file", re.compile(r"(?i)\back(?:nowledg(?:e?ment)?)?[_\s\-]"), "Vendor_Document", "Vendor acknowledgment document"),
    ("ack_suffix", re.compile(r"(?i)_ack\b|_ack\."), "Vendor_Document", "Vendor acknowledgment (filename suffix _ack)"),
    ("proforma_invoice", re.compile(r"(?i)\bproforma"), "Vendor_Document", "Proforma invoice from vendor"),

    # ── 4. Information Sheets / Vendor Docs ──
    ("info_sheet", re.compile(r"(?i)information\s*sheet|info\s*sheet"), "Vendor_Document", "Vendor information sheet"),
    ("vendor_spec", re.compile(r"(?i)spec\s*sheet|specification"), "Vendor_Document", "Specification sheet"),
    ("terms_doc", re.compile(r"(?i)\bterms\s*of\s*acceptance\b"), "Vendor_Document", "Terms of acceptance document"),
    ("graphics_policy", re.compile(r"(?i)graphics?\s*art\s*policy"), "Vendor_Document", "Graphics/art policy document"),

    # ── 5. Dunnage / Returns ──
    ("dunnage_return", re.compile(r"(?i)dunnage.*return"), "BOL", "Dunnage return BOL"),
    ("dunnage_request", re.compile(r"(?i)dunnage.*request"), "BOL", "Dunnage request"),
    ("dunnage_tracking", re.compile(r"(?i)dunnage.*track"), "Shipping_Document", "Dunnage tracking"),
    ("dunnage_commercial_inv", re.compile(r"(?i)dunnage.*(?:commercial|invoice)"), "Shipping_Document", "Dunnage commercial invoice"),
    ("dunnage_generic", re.compile(r"(?i)\bdunnage\b"), "Shipping_Document", "Dunnage-related document"),
    ("bol_explicit", re.compile(r"(?i)\bbol\b|bill\s*of\s*lading"), "BOL", "Bill of Lading"),
    ("rma_bol", re.compile(r"(?i)\brma\b.*\bbol\b"), "BOL", "RMA Bill of Lading"),

    # ── 6. Quotes / RFQs (before reports — "quote" is specific) ──
    ("quote_filename", re.compile(r"(?i)\bquote\b"), "Quote", "Quote document — not a sales order"),
    ("rfq_filename", re.compile(r"(?i)\brfq\b"), "Quote", "RFQ document"),
    ("pricing_doc", re.compile(r"(?i)\bpricing\b.*\.(xlsx|xls|docx|pdf)$"), "Quote", "Pricing document"),

    # ── 7. Reports / Lists ──
    ("open_orders_report", re.compile(r"(?i)open\s*order"), "Report", "Open orders report"),
    ("orders_report_file", re.compile(r"(?i)open_?orders_?report"), "Report", "Open orders report file"),
    ("report_generic", re.compile(r"(?i)\breport\b.*\.(xlsx|xls|csv)$"), "Report", "Report spreadsheet"),

    # ── 8. Forecasts / Consignment ──
    ("forecast", re.compile(r"(?i)\bforecast\b"), "Forecast", "Forecast document"),
    ("consignment_invoice", re.compile(r"(?i)consignment.*invoic"), "AR_Invoice", "Consignment invoicing spreadsheet"),

    # ── 9. Scanned misc ──
    ("scan_generic", re.compile(r"(?i)^scan[-_\s]"), "Miscellaneous", "Scanned document — no order indicators"),
    ("lexmark_scan", re.compile(r"(?i)scanned.*lexmark"), "Miscellaneous", "Lexmark scanned document"),
    ("packing_slip", re.compile(r"(?i)packing\s*slip.*sample"), "Miscellaneous", "Sample packing slip — not an order"),

    # ── 10. Internal Communications ──
    ("csr_realignment", re.compile(r"(?i)CSR.*realign|communication.*realign"), "Miscellaneous", "Internal CSR communication"),
    ("access_issues", re.compile(r"(?i)access\s*issue|password\s*reset|login\s*issue"), "Miscellaneous", "IT access communication"),
]


def _classify_document(filename: str, email_subject: str, email_body: str) -> Optional[Tuple[str, str, str]]:
    """
    Attempt to reclassify a document based on filename and email context.
    Returns (new_doc_type, rule_name, reason) or None if it looks like a real sales doc.
    """
    combined = f"{filename} {email_subject} {email_body}"

    for rule_name, pattern, new_type, reason in _RULES:
        if isinstance(pattern, re.Pattern):
            # Check against combined text AND filename separately
            # ($ anchors only work on filename, not combined string)
            if pattern.search(combined) or pattern.search(filename or ""):
                return new_type, rule_name, reason

    return None


# ─────────────────────────────────────────────────────────────
# SMART RECLASSIFIER
# ─────────────────────────────────────────────────────────────

async def smart_reclassify_pilot_docs(
    quality_threshold: int = 25,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Automatically reclassify pilot documents that are clearly not sales orders.

    Logic:
      1. Pattern match — filename/subject/body against known non-sales patterns
      2. Quality gate — docs with extraction_quality_pct <= threshold AND no
         pattern match get flagged for review (not auto-reclassified)
      3. Real sales docs (quality > threshold, no noise patterns) are left alone

    Args:
        quality_threshold: docs below this % with no rule match get flagged
        dry_run: if True, don't actually change anything — just report what would happen
    """
    db = get_db()
    docs = await db.hub_documents.find(
        {"inside_sales_pilot": True},
        {
            "_id": 0, "id": 1, "file_name": 1, "doc_type": 1,
            "email_subject": 1, "email_sender": 1,
            "sales_pilot_extraction": 1, "reclassified_from": 1,
        },
    ).to_list(500)

    results = {
        "total": len(docs),
        "reclassified": 0,
        "flagged_for_review": 0,
        "kept_as_sales": 0,
        "dry_run": dry_run,
        "actions": [],
    }

    now = datetime.now(timezone.utc).isoformat()

    for doc in docs:
        doc_id = doc["id"]
        filename = doc.get("file_name", "")
        subject = doc.get("email_subject", "")
        ext = doc.get("sales_pilot_extraction") or {}
        quality_pct = ext.get("extraction_quality_pct", 0)
        customer_name = ext.get("customer_name") or ""

        # ── Skip already-reclassified docs ──
        if doc.get("reclassified_from"):
            results["kept_as_sales"] += 1
            continue

        # ── HARD GATE: Gamer is never the customer on a Sales Order ──
        if "gamer" in customer_name.lower() and doc.get("doc_type") in (
            "SALES_INVOICE", "Sales_Order", "Order_Confirmation",
        ):
            action = {
                "doc_id": doc_id,
                "file_name": filename,
                "action": "reclassified",
                "old_type": doc.get("doc_type"),
                "new_type": "Vendor_Document",
                "rule": "gamer_is_buyer",
                "reason": f"Customer is '{customer_name}' (Gamer) — this is an inbound vendor document, not a sales order",
                "quality_pct": quality_pct,
            }
            if not dry_run:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "doc_type": "Vendor_Document",
                        "reclassified_from": doc.get("doc_type"),
                        "reclassified_by": "pilot_smart_reclassifier",
                        "reclassified_rule": "gamer_is_buyer",
                        "reclassified_reason": action["reason"],
                        "reclassified_at": now,
                    }},
                )
            results["reclassified"] += 1
            results["actions"].append(action)
            continue

        # Try pattern-based reclassification
        match = _classify_document(filename, subject, "")

        if match:
            new_type, rule_name, reason = match
            action = {
                "doc_id": doc_id,
                "file_name": filename,
                "action": "reclassified",
                "old_type": doc.get("doc_type"),
                "new_type": new_type,
                "rule": rule_name,
                "reason": reason,
                "quality_pct": quality_pct,
            }

            if not dry_run:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "doc_type": new_type,
                        "reclassified_from": doc.get("doc_type"),
                        "reclassified_by": "pilot_smart_reclassifier",
                        "reclassified_rule": rule_name,
                        "reclassified_reason": reason,
                        "reclassified_at": now,
                    }},
                )

            results["reclassified"] += 1
            results["actions"].append(action)

        elif quality_pct <= quality_threshold:
            # Low quality + no pattern = flag for manual review
            action = {
                "doc_id": doc_id,
                "file_name": filename,
                "action": "flagged_for_review",
                "old_type": doc.get("doc_type"),
                "reason": f"Low extraction quality ({quality_pct}%) but no matching reclassification rule",
                "quality_pct": quality_pct,
            }

            if not dry_run:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "pilot_needs_manual_review": True,
                        "pilot_review_reason": action["reason"],
                    }},
                )

            results["flagged_for_review"] += 1
            results["actions"].append(action)

        else:
            # Good quality, no noise pattern — keep as sales
            results["kept_as_sales"] += 1
            results["actions"].append({
                "doc_id": doc_id,
                "file_name": filename,
                "action": "kept",
                "doc_type": doc.get("doc_type"),
                "quality_pct": quality_pct,
            })

    logger.info(
        "[SmartReclassify] %s: reclassified=%d, flagged=%d, kept=%d (dry_run=%s)",
        "DRY RUN" if dry_run else "APPLIED",
        results["reclassified"],
        results["flagged_for_review"],
        results["kept_as_sales"],
        dry_run,
    )
    return results
