"""
Vendor Profile Helpers (v2.5.2)
───────────────────────────────

Small, self-contained helpers for maintaining the
`vendor_intelligence_profiles` collection — the running per-vendor
stability scorecard that drives the "Stable Vendor" auto-clear logic.

Extracted from `server.py` as part of the Orchestration Extraction
work so that `services/document_handlers.py` and other ingress-side
modules no longer need a late `from server import ...`.

The authoritative implementation lives here. `server.py` keeps a
thin compatibility wrapper so legacy internal callers inside that
module continue to work during the 30-day dual-path window.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _normalize_vendor_name(name: str) -> str:
    """Lower-case, strip company suffixes and punctuation — used as the
    canonical key for `vendor_intelligence_profiles`."""
    s = (name or "").lower().strip()
    s = re.sub(r'\b(inc\.?|llc\.?|ltd\.?|corp\.?|co\.?|company|corporation)\b', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[.,;:\'\"()\-/&]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


async def update_vendor_profile_incremental(
    db,
    doc_id: str,
    vendor_name: str,
    update_data: Dict[str, Any],
    final_status: str,
) -> None:
    """Incrementally update a vendor's intelligence profile after
    processing a document. Maintains running counters + recomputes
    success rates + stability score. Idempotency is best-effort —
    call once per document finalization.
    """
    norm = _normalize_vendor_name(vendor_name)
    if not norm:
        return

    now = datetime.now(timezone.utc).isoformat()
    status_lower = (final_status or "").lower()
    auto_cleared = update_data.get("auto_cleared", False)
    val_results = update_data.get("validation_results") or {}
    val_passed = (
        val_results.get("all_passed")
        or status_lower in (
            "validationpassed", "validated", "storedinsp",
            "readytolink", "linkedtobc", "completed", "posted",
        )
    )
    has_vendor = bool(update_data.get("vendor_canonical")) or bool(update_data.get("vendor_match_method"))

    inc_fields = {"invoice_count": 1}
    if auto_cleared:
        inc_fields["automation_success_count"] = 1
    if val_passed:
        inc_fields["validation_pass_count"] = 1
    if has_vendor:
        inc_fields["resolution_success_count"] = 1

    result = await db.vendor_intelligence_profiles.find_one_and_update(
        {"vendor_name_normalized": norm},
        {
            "$inc": inc_fields,
            "$set": {"updated_at": now},
            "$setOnInsert": {
                "vendor_name": vendor_name,
                "vendor_name_normalized": norm,
                "created_at": now,
                "stable_vendor_flag": False,
                "stable_vendor_score": 0,
                "manual_override_status": "none",
            },
            "$addToSet": {"name_variants": vendor_name},
        },
        upsert=True,
        return_document=True,
    )

    if not result:
        return

    doc_count = result.get("invoice_count", 1)
    auto_count = result.get("automation_success_count", 0)
    val_count = result.get("validation_pass_count", 0)
    res_count = result.get("resolution_success_count", 0)

    auto_rate = round(auto_count / max(doc_count, 1), 4)
    val_rate = round(val_count / max(doc_count, 1), 4)
    res_rate = round(res_count / max(doc_count, 1), 4)

    score = round(
        min(doc_count / 50, 1.0) * 0.15
        + auto_rate * 0.30
        + res_rate * 0.25
        + val_rate * 0.20
        + (1 - result.get("correction_rate", 0)) * 0.10
        , 4,
    )

    is_stable = (
        doc_count >= 10
        and (auto_rate >= 0.5 or res_rate >= 0.7)
        and val_rate >= 0.4
    )

    await db.vendor_intelligence_profiles.update_one(
        {"vendor_name_normalized": norm},
        {"$set": {
            "automation_success_rate": auto_rate,
            "validation_pass_rate": val_rate,
            "reference_resolution_success_rate": res_rate,
            "stable_vendor_score": score,
            "stable_vendor_flag": is_stable,
            "stable_vendor_last_evaluated": now,
        }},
    )


__all__ = ["update_vendor_profile_incremental"]
