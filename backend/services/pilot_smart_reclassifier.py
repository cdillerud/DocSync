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

    # ── Certificates / Compliance ──
    ("cert_sqf", re.compile(r"(?i)\bSQF\b"), "Certificate", "SQF certification document"),
    ("cert_iso", re.compile(r"(?i)\bISO[\s\-_]\d"), "Certificate", "ISO certification document"),
    ("cert_generic", re.compile(r"(?i)\bcertificate\b"), "Certificate", "Certificate document"),
    ("cert_filename", re.compile(r"(?i)certif"), "Certificate", "Certificate (filename match)"),

    # ── Information Sheets / Vendor Docs ──
    ("info_sheet", re.compile(r"(?i)information\s*sheet|info\s*sheet"), "Vendor_Document", "Vendor information sheet"),
    ("vendor_spec", re.compile(r"(?i)spec\s*sheet|specification"), "Vendor_Document", "Specification sheet"),

    # ── Dunnage / Returns ──
    ("dunnage_return", re.compile(r"(?i)dunnage.*return"), "BOL", "Dunnage return BOL"),
    ("dunnage_request", re.compile(r"(?i)dunnage.*request"), "BOL", "Dunnage request"),
    ("dunnage_tracking", re.compile(r"(?i)dunnage.*track"), "Shipping_Document", "Dunnage tracking"),
    ("dunnage_generic", re.compile(r"(?i)\bdunnage\b"), "Shipping_Document", "Dunnage-related document"),
    ("bol_explicit", re.compile(r"(?i)\bbol\b|bill\s*of\s*lading"), "BOL", "Bill of Lading"),

    # ── Reports / Lists ──
    ("open_orders_report", re.compile(r"(?i)open.*order.*list|order.*report"), "Report", "Open orders report"),
    ("report_generic", re.compile(r"(?i)\breport\b.*\.(xlsx|xls|csv)$"), "Report", "Report spreadsheet"),

    # ── Internal Communications ──
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
            if pattern.search(combined):
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
            "sales_pilot_extraction": 1,
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
