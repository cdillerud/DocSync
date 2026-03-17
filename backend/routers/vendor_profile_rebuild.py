"""
Vendor Profile Rebuild — Recompute vendor intelligence profiles from actual document data.

Fixes:
  1. Duplicate vendor profiles (case/punctuation variants)
  2. Zero-value rates (automation, resolution, validation)
  3. Inaccurate doc counts

Endpoints:
  POST /api/vendor-profiles/rebuild/dry-run  — Preview what would change
  POST /api/vendor-profiles/rebuild/run      — Full rebuild from documents
"""

import logging
import re
import time
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter
from deps import get_db

logger = logging.getLogger("vendor_profile_rebuild")
router = APIRouter(prefix="/vendor-profiles", tags=["Vendor Profiles"])


def _normalize_vendor_name(name: str) -> str:
    """Normalize vendor name for dedup: lowercase, strip suffixes/punctuation, collapse whitespace."""
    if not name:
        return ""
    s = name.lower().strip()
    # Remove common business suffixes that vary
    s = re.sub(r'\b(inc\.?|llc\.?|ltd\.?|corp\.?|co\.?|company|corporation|pte\.?|int\'?l\.?|international)\b', '', s, flags=re.IGNORECASE)
    # Remove punctuation (including apostrophes, hyphens, etc.)
    s = re.sub(r'[.,;:\'\"()\-/&!@#$%^*_+=\[\]{}|\\<>?~`]', ' ', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _pick_best_display_name(names: list) -> str:
    """Pick the best display name from a list of variants."""
    if not names:
        return "Unknown"
    # Prefer the one with most mixed case (not all-caps), then longest
    scored = []
    for n in names:
        has_mixed = not n.isupper() and not n.islower()
        scored.append((has_mixed, len(n), n))
    scored.sort(reverse=True)
    return scored[0][2]


@router.post("/rebuild/dry-run")
async def rebuild_dry_run():
    """Preview vendor profile rebuild from document data."""
    db = get_db()
    start = time.time()

    groups, vendor_no_map = await _aggregate_vendor_data(db)

    current_profiles = await db.vendor_intelligence_profiles.find(
        {}, {"_id": 0, "vendor_name": 1, "vendor_no": 1}
    ).to_list(5000)

    return {
        "current_profiles": len(current_profiles),
        "new_profiles": len(groups),
        "would_merge": len(current_profiles) - len(groups) if len(current_profiles) > len(groups) else 0,
        "top_vendors": [
            {
                "name": data["display_name"],
                "vendor_no": data.get("vendor_no", ""),
                "docs": data["doc_count"],
                "auto_cleared": data["auto_cleared_count"],
                "validation_passed": data["validation_passed_count"],
                "vendor_resolved": data["vendor_resolved_count"],
                "auto_rate": round(data["auto_cleared_count"] / max(data["doc_count"], 1), 3),
                "resolution_rate": round(data["vendor_resolved_count"] / max(data["doc_count"], 1), 3),
                "variants": data["name_variants"][:5],
            }
            for _, data in sorted(groups.items(), key=lambda x: x[1]["doc_count"], reverse=True)[:20]
        ],
        "duration_ms": int((time.time() - start) * 1000),
    }


@router.post("/rebuild/run")
async def rebuild_run():
    """Full rebuild of vendor intelligence profiles from document data."""
    db = get_db()
    start = time.time()

    groups, vendor_no_map = await _aggregate_vendor_data(db)

    # Preserve manual overrides from existing profiles
    existing = {}
    async for p in db.vendor_intelligence_profiles.find({}, {"_id": 0}):
        norm = _normalize_vendor_name(p.get("vendor_name", ""))
        if norm and norm not in existing:
            existing[norm] = {
                "manual_override_status": p.get("manual_override_status"),
                "manual_override_reason": p.get("manual_override_reason"),
                "manual_override_by": p.get("manual_override_by"),
                "manual_override_at": p.get("manual_override_at"),
                "manual_override_note": p.get("manual_override_note"),
                "manual_override_expires_at": p.get("manual_override_expires_at"),
                "stable_vendor_last_evaluated": p.get("stable_vendor_last_evaluated"),
            }

    # Drop and rebuild
    await db.vendor_intelligence_profiles.delete_many({})

    now = datetime.now(timezone.utc).isoformat()
    created = 0

    for norm_name, data in groups.items():
        doc_count = data["doc_count"]
        auto_cleared = data["auto_cleared_count"]
        val_passed = data["validation_passed_count"]
        vendor_resolved = data["vendor_resolved_count"]
        ref_resolved = data["ref_resolved_count"]

        auto_rate = round(auto_cleared / max(doc_count, 1), 4)
        val_rate = round(val_passed / max(doc_count, 1), 4)
        resolution_rate = round(vendor_resolved / max(doc_count, 1), 4)
        ref_rate = round(ref_resolved / max(doc_count, 1), 4)

        # Stable vendor check — use same config as StableVendorService
        sv_cfg = await db.stable_vendor_config.find_one(
            {"config_id": "stable_vendor_defaults"}, {"_id": 0}
        ) or {}
        is_stable = (
            doc_count >= sv_cfg.get("min_documents_processed", 10)
            and auto_rate >= sv_cfg.get("min_automation_success_rate", 0.50)
            and resolution_rate >= sv_cfg.get("min_reference_resolution_rate", 0.70)
            and val_rate >= sv_cfg.get("min_validation_pass_rate", 0.05)
        )

        # Compute score (0-1)
        score = round(
            min(doc_count / 50, 1.0) * 0.15  # volume
            + auto_rate * 0.30                # automation
            + resolution_rate * 0.25          # resolution
            + val_rate * 0.20                 # validation
            + (1 - data.get("correction_rate", 0)) * 0.10  # low corrections
        , 4)

        # Restore manual overrides
        overrides = existing.get(norm_name, {})

        vendor_no = data.get("vendor_no", "") or data["display_name"]

        profile = {
            "vendor_no": vendor_no,
            "vendor_name": data["display_name"],
            "vendor_name_normalized": norm_name,
            "name_variants": data["name_variants"],
            "invoice_count": doc_count,
            "document_types_seen": list(data["doc_types"]),
            "automation_success_count": auto_cleared,
            "automation_success_rate": auto_rate,
            "validation_pass_count": val_passed,
            "validation_pass_rate": val_rate,
            "resolution_success_count": vendor_resolved,
            "reference_resolution_success_rate": resolution_rate,
            "reference_intelligence_rate": ref_rate,
            "stable_vendor_flag": is_stable,
            "stable_vendor_score": score,
            "stable_vendor_last_evaluated": now,
            "correction_rate": data.get("correction_rate", 0),
            "created_at": now,
            "updated_at": now,
            # Preserve overrides
            "manual_override_status": overrides.get("manual_override_status", "none"),
            "manual_override_reason": overrides.get("manual_override_reason", ""),
            "manual_override_by": overrides.get("manual_override_by", ""),
            "manual_override_at": overrides.get("manual_override_at"),
            "manual_override_note": overrides.get("manual_override_note", ""),
            "manual_override_expires_at": overrides.get("manual_override_expires_at"),
        }

        await db.vendor_intelligence_profiles.insert_one(profile)
        created += 1

    # Recreate indexes
    await db.vendor_intelligence_profiles.create_index("vendor_no", unique=True, sparse=True)
    await db.vendor_intelligence_profiles.create_index("vendor_name")
    await db.vendor_intelligence_profiles.create_index("vendor_name_normalized")
    await db.vendor_intelligence_profiles.create_index("stable_vendor_flag")

    duration_ms = int((time.time() - start) * 1000)

    stable_count = await db.vendor_intelligence_profiles.count_documents({"stable_vendor_flag": True})

    return {
        "status": "completed",
        "profiles_created": created,
        "stable_vendors": stable_count,
        "duration_ms": duration_ms,
        "timestamp": now,
    }


async def _aggregate_vendor_data(db):
    """Aggregate document data grouped by normalized vendor name."""
    groups = defaultdict(lambda: {
        "doc_count": 0,
        "auto_cleared_count": 0,
        "validation_passed_count": 0,
        "vendor_resolved_count": 0,
        "ref_resolved_count": 0,
        "name_variants": [],
        "display_name": "",
        "vendor_no": "",
        "doc_types": set(),
        "correction_rate": 0,
    })
    vendor_no_map = {}

    # Get all non-duplicate documents with any vendor reference
    cursor = db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "$or": [
                {"vendor_canonical": {"$exists": True, "$ne": None}},
                {"vendor_raw": {"$exists": True, "$ne": None}},
                {"matched_vendor_name": {"$exists": True, "$ne": None}},
            ],
        },
        {
            "_id": 0, "id": 1,
            "vendor_canonical": 1, "vendor_raw": 1, "matched_vendor_name": 1,
            "vendor_normalized": 1,
            "auto_cleared": 1, "status": 1, "workflow_status": 1,
            "vendor_match_method": 1, "vendor_resolution": 1,
            "validation_results": 1, "validation_state": 1,
            "reference_intelligence": 1,
            "doc_type": 1, "document_type": 1, "suggested_job_type": 1,
            "unified_vendor_match": 1,
        },
    )

    async for doc in cursor:
        # Pick the best vendor name
        raw_name = (
            doc.get("vendor_canonical")
            or doc.get("matched_vendor_name")
            or doc.get("vendor_raw")
            or doc.get("vendor_normalized")
        )
        if not raw_name or raw_name.lower() in ("unknown", "none", "n/a", ""):
            continue

        norm = _normalize_vendor_name(raw_name)
        if not norm:
            continue

        g = groups[norm]
        g["doc_count"] += 1

        # Track name variants
        if raw_name not in g["name_variants"]:
            g["name_variants"].append(raw_name)
        g["display_name"] = _pick_best_display_name(g["name_variants"])

        # Track vendor_no from BC match
        uvm = doc.get("unified_vendor_match") or {}
        vno = uvm.get("bc_vendor_no", "")
        vr = doc.get("vendor_resolution") or {}
        if not vno:
            vno = vr.get("vendor_no", "")
        if vno and not g["vendor_no"]:
            g["vendor_no"] = vno

        # Automation success: doc was processed end-to-end successfully
        # Includes auto-cleared, manually approved, or any terminal success status
        status = (doc.get("status") or "").lower()
        workflow_status = (doc.get("workflow_status") or "").lower()
        if (doc.get("auto_cleared")
            or status in ("completed", "posted", "linkedtobc", "storedinsp", "archived")
            or workflow_status in ("completed", "processed", "exported", "validation_passed")):
            g["auto_cleared_count"] += 1

        # Validation passed
        val_state = (doc.get("validation_state") or "").lower()
        val_results = doc.get("validation_results") or {}
        if (val_state == "pass"
            or val_results.get("all_passed")
            or status in ("validationpassed", "validated", "storedinsp", "readytolink", "linkedtobc", "completed", "posted")):
            g["validation_passed_count"] += 1

        # Vendor resolved (has BC match)
        match_method = doc.get("vendor_match_method") or ""
        has_vendor = bool(doc.get("vendor_canonical")) or match_method not in ("", "none", None)
        if has_vendor:
            g["vendor_resolved_count"] += 1

        # Reference intelligence resolved
        ref_intel = doc.get("reference_intelligence") or {}
        ref_outcome = ref_intel.get("match_outcome", "")
        if ref_outcome in ("exact_match", "likely_match"):
            g["ref_resolved_count"] += 1

        # Doc type
        dt = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type")
        if dt:
            g["doc_types"].add(dt)

    return dict(groups), vendor_no_map
