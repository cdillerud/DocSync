"""
Draft Feedback Service — Closes the Learning Loop

When a human edits an auto-drafted Purchase Invoice in BC before posting it,
this service detects the changes and feeds them back into the posting template.

Flow:
1. System creates a Draft PI with specific lines (original_draft_lines stored on doc)
2. Human reviews in BC, possibly editing lines (items, amounts, descriptions)
3. This service fetches the current PI state from BC
4. Compares original vs current to build a diff
5. Records corrections as learning events
6. Adjusts the vendor posting template weights
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


async def sync_draft_from_bc(doc_id: str, db) -> Dict:
    """
    Fetch the current state of an auto-drafted PI from BC and compare
    with the original draft lines stored on the document.

    Returns: {success, changes_detected, diff, bc_current_lines, original_lines}
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"success": False, "error": "Document not found"}

    if not doc.get("auto_draft_created"):
        return {"success": False, "error": "Document has no auto-draft"}

    bc_pi = doc.get("bc_purchase_invoice") or {}
    bc_system_id = bc_pi.get("bc_system_id", "")
    bc_record_no = bc_pi.get("bc_record_no", "")

    if not bc_system_id:
        return {"success": False, "error": "No BC system ID — cannot fetch from BC"}

    original_lines = doc.get("original_draft_lines") or []
    if not original_lines:
        return {
            "success": True,
            "changes_detected": False,
            "note": "No original draft lines stored — cannot diff. Run sync after re-drafting.",
            "bc_record_no": bc_record_no,
        }

    # Fetch current PI state from BC
    try:
        import httpx
        import os
        from services.gpi_integration_service import _get_token, _resolve_company_id, REQUEST_TIMEOUT

        BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
        BC_TENANT_ID = os.environ.get("TENANT_ID", "")
        BC_WRITE_ENV = os.environ.get("BC_WRITE_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "Sandbox_11_3_2025")

        if not BC_TENANT_ID:
            return {"success": False, "error": "BC credentials not configured"}

        token = await _get_token()
        company_id = await _resolve_company_id()

        # Fetch PI header to check status
        header_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENV}/api/v2.0/companies({company_id})/purchaseInvoices({bc_system_id})"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(header_url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            })
            if resp.status_code != 200:
                return {"success": False, "error": f"Failed to fetch PI from BC: {resp.status_code}"}
            pi_header = resp.json()

        bc_status = pi_header.get("status", "Draft")

        # Fetch current lines
        lines_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENV}/api/v2.0/companies({company_id})/purchaseInvoices({bc_system_id})/purchaseInvoiceLines"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(lines_url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            })
            bc_current_lines = resp.json().get("value", []) if resp.status_code == 200 else []

    except Exception as e:
        return {"success": False, "error": f"BC API error: {str(e)}"}

    # Normalize BC lines for comparison
    current_normalized = _normalize_bc_lines(bc_current_lines)

    # Compare original vs current
    diff = _compute_line_diff(original_lines, current_normalized)

    now = datetime.now(timezone.utc).isoformat()
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

    # Store sync result on the document
    sync_result = {
        "synced_at": now,
        "bc_status": bc_status,
        "changes_detected": diff["has_changes"],
        "changes_summary": diff["summary"],
        "current_line_count": len(current_normalized),
        "original_line_count": len(original_lines),
    }

    update_ops = {
        "draft_bc_sync": sync_result,
        "draft_bc_current_lines": current_normalized,
    }

    if diff["has_changes"]:
        update_ops["draft_review_status"] = "bc_edited"
        update_ops["draft_bc_corrections"] = diff["corrections"]

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_ops})

    # If changes were detected, create feedback events
    if diff["has_changes"]:
        await _record_feedback_events(db, doc_id, vendor_no, diff, now)
        await _adjust_template_from_feedback(db, vendor_no, diff, now)

        logger.info(
            "[DraftFeedback] Changes detected for %s (vendor=%s): %s",
            doc_id[:8], vendor_no, diff["summary"]
        )

    return {
        "success": True,
        "bc_record_no": bc_record_no,
        "bc_status": bc_status,
        "changes_detected": diff["has_changes"],
        "summary": diff["summary"],
        "corrections": diff["corrections"],
        "original_line_count": len(original_lines),
        "current_line_count": len(current_normalized),
        "template_updated": diff["has_changes"],
    }


def _normalize_bc_lines(bc_lines: List[Dict]) -> List[Dict]:
    """Normalize BC API line format to a standard comparison format."""
    normalized = []
    for idx, l in enumerate(bc_lines):
        normalized.append({
            "line_no": l.get("sequence", l.get("lineNo", idx)),
            "type": l.get("lineObjectNumber", l.get("lineType", "")),
            "item_or_account": l.get("lineObjectNumber", ""),
            "description": l.get("description", ""),
            "quantity": l.get("quantity", 0),
            "unit_cost": l.get("unitCost", l.get("directUnitCost", 0)),
            "amount": l.get("totalAmount", l.get("lineAmount", l.get("amount", 0))),
            "tax_code": l.get("taxCode", ""),
            "uom": l.get("unitOfMeasureCode", ""),
        })
    return normalized


def _compute_line_diff(original: List[Dict], current: List[Dict]) -> Dict:
    """
    Compare original auto-drafted lines with current BC lines.
    Returns corrections for each changed field.
    """
    corrections = []
    has_changes = False

    # Line count change
    if len(original) != len(current):
        has_changes = True
        corrections.append({
            "field": "line_count",
            "original": len(original),
            "corrected": len(current),
            "type": "structural",
        })

    # Per-line comparison (greedy matching by position)
    max_lines = max(len(original), len(current))
    for i in range(max_lines):
        orig = original[i] if i < len(original) else None
        curr = current[i] if i < len(current) else None

        if orig and not curr:
            has_changes = True
            corrections.append({
                "field": "line_removed",
                "line_index": i,
                "original": orig.get("item_or_account") or orig.get("lineObjectNumber", ""),
                "corrected": "(removed)",
                "type": "line_deletion",
            })
            continue

        if curr and not orig:
            has_changes = True
            corrections.append({
                "field": "line_added",
                "line_index": i,
                "original": "(none)",
                "corrected": curr.get("item_or_account", ""),
                "type": "line_addition",
                "details": curr,
            })
            continue

        # Both exist — check fields
        orig_item = orig.get("item_or_account") or orig.get("lineObjectNumber", "")
        curr_item = curr.get("item_or_account", "")
        if orig_item != curr_item and curr_item:
            has_changes = True
            corrections.append({
                "field": "item_or_account",
                "line_index": i,
                "original": orig_item,
                "corrected": curr_item,
                "type": "item_change",
            })

        orig_desc = (orig.get("description") or "").strip()
        curr_desc = (curr.get("description") or "").strip()
        if orig_desc != curr_desc and curr_desc:
            has_changes = True
            corrections.append({
                "field": "description",
                "line_index": i,
                "original": orig_desc,
                "corrected": curr_desc,
                "type": "description_change",
            })

        orig_amount = _safe_float(orig.get("amount") or orig.get("unit_cost", 0))
        curr_amount = _safe_float(curr.get("amount") or curr.get("unit_cost", 0))
        if abs(orig_amount - curr_amount) > 0.01:
            has_changes = True
            corrections.append({
                "field": "amount",
                "line_index": i,
                "original": orig_amount,
                "corrected": curr_amount,
                "type": "amount_change",
            })

        orig_qty = _safe_float(orig.get("quantity", 0))
        curr_qty = _safe_float(curr.get("quantity", 0))
        if abs(orig_qty - curr_qty) > 0.001:
            has_changes = True
            corrections.append({
                "field": "quantity",
                "line_index": i,
                "original": orig_qty,
                "corrected": curr_qty,
                "type": "quantity_change",
            })

        orig_tax = (orig.get("tax_code") or "").strip()
        curr_tax = (curr.get("tax_code") or "").strip()
        if orig_tax != curr_tax and curr_tax:
            has_changes = True
            corrections.append({
                "field": "tax_code",
                "line_index": i,
                "original": orig_tax,
                "corrected": curr_tax,
                "type": "tax_change",
            })

    summary_parts = []
    change_types = {}
    for c in corrections:
        ct = c.get("type", "unknown")
        change_types[ct] = change_types.get(ct, 0) + 1
    for ct, count in change_types.items():
        summary_parts.append(f"{count} {ct}")

    return {
        "has_changes": has_changes,
        "corrections": corrections,
        "change_count": len(corrections),
        "summary": ", ".join(summary_parts) if summary_parts else "No changes detected",
    }


def _safe_float(val) -> float:
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


async def _record_feedback_events(db, doc_id: str, vendor_no: str, diff: Dict, now: str):
    """Record feedback events from detected changes."""
    # Create a posting learning event for each correction
    await db.posting_learning_events.insert_one({
        "vendor_no": vendor_no,
        "doc_id": doc_id,
        "event_type": "draft_bc_feedback",
        "posted_at": now,
        "feedback": "corrective",
        "change_count": diff["change_count"],
        "corrections": diff["corrections"],
        "summary": diff["summary"],
    })

    # Dual-write to unified learning_events_v2 (U1, v2.4.1)
    try:
        from workflows.core.learning_core import record_event
        await record_event(
            domain="ap_posting",
            event_type="draft_bc_feedback",
            scope_type="vendor",
            scope_value=vendor_no,
            target={"doc_id": doc_id},
            applied={
                "change_count": diff.get("change_count"),
                "summary": diff.get("summary"),
            },
            extra={"corrections_preview": diff.get("corrections", [])[:5]},
            actor="bc_write_hook",
            source="draft_feedback_service",
            db=db,
        )
    except Exception as e:
        logger.debug("[DraftFeedback] unified event dual-write failed: %s", e)

    # Create individual classification corrections for learning dashboard visibility
    for c in diff["corrections"]:
        await db.classification_corrections.insert_one({
            "doc_id": doc_id,
            "vendor_id": vendor_no,
            "correction_type": f"bc_feedback_{c.get('type', 'unknown')}",
            "original_type": str(c.get("original", "")),
            "corrected_type": str(c.get("corrected", "")),
            "source": "bc_draft_feedback",
            "confirmed_at": now,
            "applied": True,
        })


async def _adjust_template_from_feedback(db, vendor_no: str, diff: Dict, now: str):
    """
    Adjust the vendor's posting template based on human corrections.

    For each type of correction:
    - item_change: Boost the corrected item's weight, reduce the original's weight
    - description_change: Update description patterns
    - amount_change: Widen amount tolerance
    - line_addition/deletion: Adjust typical_line_count
    - tax_change: Update tax code preferences
    """
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )
    if not profile:
        logger.warning("[DraftFeedback] No profile for vendor %s — cannot adjust template", vendor_no)
        return

    inc_ops = {}
    set_ops = {
        "last_feedback_at": now,
    }

    for c in diff["corrections"]:
        ctype = c.get("type", "")

        if ctype == "item_change":
            # Human changed the item/GL account — boost the corrected one
            corrected_item = c.get("corrected", "")
            original_item = c.get("original", "")
            if corrected_item:
                # Increment the corrected item's count (makes it appear more in the template)
                inc_ops[f"line_patterns.top_items.{corrected_item}"] = \
                    inc_ops.get(f"line_patterns.top_items.{corrected_item}", 0) + 3
                inc_ops[f"line_patterns.top_gl_accounts.{corrected_item}"] = \
                    inc_ops.get(f"line_patterns.top_gl_accounts.{corrected_item}", 0) + 3
            if original_item:
                # Decrement the original (but never below 0 — handled by analysis re-run)
                inc_ops[f"feedback_penalties.items.{original_item}"] = \
                    inc_ops.get(f"feedback_penalties.items.{original_item}", 0) + 1

        elif ctype == "tax_change":
            corrected_tax = c.get("corrected", "")
            if corrected_tax:
                inc_ops[f"line_patterns.tax_code_distribution.{corrected_tax}"] = \
                    inc_ops.get(f"line_patterns.tax_code_distribution.{corrected_tax}", 0) + 3

        elif ctype == "line_addition":
            # Human added a line — record the item for future templates
            details = c.get("details") or {}
            added_item = details.get("item_or_account", "")
            if added_item:
                inc_ops[f"line_patterns.top_items.{added_item}"] = \
                    inc_ops.get(f"line_patterns.top_items.{added_item}", 0) + 2

        elif ctype == "structural" and c.get("field") == "line_count":
            # Human changed the line count — adjust typical
            corrected_count = c.get("corrected", 0)
            if corrected_count:
                set_ops["posting_template.typical_line_count"] = corrected_count

    # Track total feedback corrections
    inc_ops["feedback_correction_count"] = inc_ops.get("feedback_correction_count", 0) + len(diff["corrections"])
    inc_ops["continuous_learning_count"] = inc_ops.get("continuous_learning_count", 0) + 1

    update_query = {}
    if inc_ops:
        update_query["$inc"] = inc_ops
    if set_ops:
        update_query["$set"] = set_ops

    if update_query:
        await db.posting_pattern_analysis.update_one(
            {"vendor_no": vendor_no, "status": "analyzed"},
            update_query,
        )
        logger.info(
            "[DraftFeedback] Adjusted template for %s: %d inc ops, %d set ops",
            vendor_no, len(inc_ops), len(set_ops)
        )


async def process_feedback_batch(db, limit: int = 50) -> Dict:
    """
    Batch process: Sync all auto-drafted documents that haven't been synced recently.
    Detects changes in BC and feeds them back into templates.
    """
    # Find auto-drafted docs that need syncing
    docs = await db.hub_documents.find(
        {
            "auto_draft_created": True,
            "draft_review_status": {"$nin": ["approved", "corrected", "feedback_synced"]},
            "bc_purchase_invoice.bc_system_id": {"$exists": True, "$ne": ""},
        },
        {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "auto_draft_bc_record_no": 1}
    ).limit(limit).to_list(limit)

    results = {
        "processed": 0,
        "changes_found": 0,
        "no_changes": 0,
        "errors": 0,
        "details": [],
    }

    for doc_stub in docs:
        doc_id = doc_stub.get("id", "")
        if not doc_id:
            continue

        results["processed"] += 1
        try:
            result = await sync_draft_from_bc(doc_id, db)
            if result.get("success"):
                if result.get("changes_detected"):
                    results["changes_found"] += 1
                else:
                    results["no_changes"] += 1
                results["details"].append({
                    "doc_id": doc_id[:8],
                    "vendor_no": doc_stub.get("bc_vendor_number") or doc_stub.get("vendor_no", ""),
                    "bc_record_no": result.get("bc_record_no", ""),
                    "changes_detected": result.get("changes_detected", False),
                    "summary": result.get("summary", ""),
                })
            else:
                results["errors"] += 1
                results["details"].append({
                    "doc_id": doc_id[:8],
                    "error": result.get("error", "Unknown"),
                })
        except Exception as e:
            results["errors"] += 1
            results["details"].append({"doc_id": doc_id[:8], "error": str(e)})

    logger.info(
        "[DraftFeedback] Batch sync: processed=%d, changes=%d, no_changes=%d, errors=%d",
        results["processed"], results["changes_found"], results["no_changes"], results["errors"]
    )
    return results
