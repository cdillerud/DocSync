"""
Auto-Approve Router — Batch auto-approve validated documents from stable vendors.

Endpoints:
  GET  /api/auto-approve/diagnose   — Analyze what's blocking approvals
  POST /api/auto-approve/dry-run    — Preview what would be approved
  POST /api/auto-approve/run        — Execute batch auto-approve
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from deps import get_db
from services.stable_vendor_service import get_stable_vendor_service

logger = logging.getLogger("auto_approve")
router = APIRouter(prefix="/auto-approve", tags=["Auto-Approve"])

TERMINAL_STATUSES = ["Completed", "Archived", "Posted", "Deleted"]


async def _get_approval_candidates(db, limit=5000):
    """Get documents in the 'Needs Approval' bucket — matches dashboard query exactly."""
    return await db.hub_documents.find(
        {
            "validation_results.all_passed": True,
            "status": {"$nin": TERMINAL_STATUSES},
            "$or": [
                {"workflow_status": "ready_for_approval"},
                {"workflow_status": "validated"},
                {"workflow_status": "ready_for_post"},
                {"$and": [
                    {"bc_record_id": {"$exists": True}},
                    {"bc_posting_status": {"$nin": ["posted", "completed"]}},
                ]},
            ],
        },
        {"_id": 0},
    ).to_list(limit)


def _get_vendor_id(doc):
    """Extract vendor identifier from document, checking all possible fields."""
    return (
        doc.get("vendor_canonical")
        or doc.get("matched_vendor_name")
        or doc.get("vendor_raw")
        or (doc.get("unified_vendor_match") or {}).get("vendor_no")
        or (doc.get("unified_vendor_match") or {}).get("vendor_name")
        or (doc.get("validation_results") or {}).get("vendor_no")
        or doc.get("vendor_no")
        or ""
    )


@router.get("/diagnose")
async def diagnose_approval_backlog():
    """Analyze the Needs Approval backlog and what's blocking auto-approval."""
    db = get_db()

    candidates = await _get_approval_candidates(db)

    # Group by vendor
    by_vendor = {}
    no_vendor = 0
    for doc in candidates:
        vendor = _get_vendor_id(doc)
        if not vendor:
            no_vendor += 1
            continue
        by_vendor.setdefault(vendor, []).append(doc)

    # Check each vendor's stability
    vendor_analysis = []
    auto_approvable = 0
    needs_stable_vendor = 0

    stable_vendors = set()
    if svc:
        profiles = await db.vendor_intelligence_profiles.find(
            {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1, "stable_vendor_flag": 1,
                 "effective_status": 1, "manual_override_status": 1}
        ).to_list(5000)
        for p in profiles:
            eff = _effective_status(p)
            if eff in ("stable", "watch"):
                stable_vendors.add(p.get("vendor_no", ""))
                stable_vendors.add(p.get("vendor_name", ""))

    for vendor, docs in sorted(by_vendor.items(), key=lambda x: -len(x[1]))[:30]:
        is_stable = vendor in stable_vendors
        doc_count = len(docs)
        if is_stable:
            auto_approvable += doc_count
        else:
            needs_stable_vendor += doc_count

        # Check what's blocking these docs
        has_vendor_match = sum(1 for d in docs if d.get("vendor_canonical") or d.get("match_method", "none") != "none")
        has_bc_link = sum(1 for d in docs if d.get("bc_record_id"))

        vendor_analysis.append({
            "vendor": vendor,
            "doc_count": doc_count,
            "is_stable": is_stable,
            "has_vendor_match": has_vendor_match,
            "has_bc_link": has_bc_link,
            "would_auto_approve": is_stable,
        })

    return {
        "total_needs_approval": len(candidates),
        "no_vendor_identified": no_vendor,
        "auto_approvable_now": auto_approvable,
        "needs_stable_vendor_first": needs_stable_vendor,
        "unique_vendors": len(by_vendor),
        "stable_vendors_matched": len([v for v in vendor_analysis if v["is_stable"]]),
        "top_vendors": vendor_analysis[:20],
        "recommendation": (
            f"Promote top vendors to stable status to unlock auto-approval for "
            f"{needs_stable_vendor} documents. Currently {auto_approvable} are auto-approvable."
        ),
    }


@router.post("/dry-run")
async def dry_run_auto_approve(
    require_stable_vendor: bool = Query(True, description="Only approve docs from stable vendors"),
    require_bc_link: bool = Query(False, description="Only approve docs linked to BC"),
    min_routing_score: int = Query(0, description="Minimum routing score to approve"),
):
    """Preview what would be auto-approved."""
    db = get_db()

    candidates = await _get_approval_candidates(db)

    stable_vendors = set()
    if require_stable_vendor:
        profiles = await db.vendor_intelligence_profiles.find(
            {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1, "stable_vendor_flag": 1,
                 "manual_override_status": 1}
        ).to_list(5000)
        for p in profiles:
            eff = _effective_status(p)
            if eff in ("stable", "watch"):
                stable_vendors.add(p.get("vendor_no", ""))
                stable_vendors.add(p.get("vendor_name", ""))

    would_approve = []
    would_skip = []

    for doc in candidates:
        vendor = _get_vendor_id(doc)
        skip_reasons = []

        if require_stable_vendor and vendor not in stable_vendors:
            skip_reasons.append(f"vendor '{vendor}' not stable")

        if require_bc_link and not doc.get("bc_record_id"):
            skip_reasons.append("no BC link")

        routing_score = doc.get("routing_score", 0) or 0
        if min_routing_score > 0 and routing_score < min_routing_score:
            skip_reasons.append(f"routing_score {routing_score} < {min_routing_score}")

        entry = {
            "id": doc.get("id", ""),
            "file_name": doc.get("file_name", ""),
            "vendor": vendor,
            "doc_type": doc.get("doc_type") or doc.get("document_type", ""),
            "workflow_status": doc.get("workflow_status", ""),
            "routing_score": routing_score,
        }

        if skip_reasons:
            entry["skip_reasons"] = skip_reasons
            would_skip.append(entry)
        else:
            would_approve.append(entry)

    # Group skips by reason
    skip_reasons_summary = {}
    for s in would_skip:
        for r in s.get("skip_reasons", []):
            key = r.split("'")[0].strip() if "'" in r else r
            skip_reasons_summary.setdefault(key, 0)
            skip_reasons_summary[key] += 1

    return {
        "total_candidates": len(candidates),
        "would_approve": len(would_approve),
        "would_skip": len(would_skip),
        "skip_reasons_summary": dict(sorted(skip_reasons_summary.items(), key=lambda x: -x[1])),
        "sample_approvals": would_approve[:10],
        "require_stable_vendor": require_stable_vendor,
        "require_bc_link": require_bc_link,
        "min_routing_score": min_routing_score,
    }


@router.post("/run")
async def run_auto_approve(
    require_stable_vendor: bool = Query(True, description="Only approve docs from stable vendors"),
    require_bc_link: bool = Query(False, description="Only approve docs linked to BC"),
    min_routing_score: int = Query(0, description="Minimum routing score to approve"),
    force: bool = Query(False, description="Force approve ALL candidates regardless of vendor stability"),
):
    """Execute batch auto-approve for qualifying documents."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    candidates = await _get_approval_candidates(db)

    stable_vendors = set()
    if require_stable_vendor and not force:
        profiles = await db.vendor_intelligence_profiles.find(
            {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1, "stable_vendor_flag": 1,
                 "manual_override_status": 1}
        ).to_list(5000)
        for p in profiles:
            eff = _effective_status(p)
            if eff in ("stable", "watch"):
                stable_vendors.add(p.get("vendor_no", ""))
                stable_vendors.add(p.get("vendor_name", ""))

    approved = 0
    skipped = 0
    by_vendor = {}

    for doc in candidates:
        vendor = _get_vendor_id(doc)

        if not force:
            if require_stable_vendor and vendor not in stable_vendors:
                skipped += 1
                continue
            if require_bc_link and not doc.get("bc_record_id"):
                skipped += 1
                continue
            routing_score = doc.get("routing_score", 0) or 0
            if min_routing_score > 0 and routing_score < min_routing_score:
                skipped += 1
                continue

        await db.hub_documents.update_one(
            {"id": doc["id"]},
            {"$set": {
                "workflow_status": "approved",
                "auto_approved": True,
                "auto_approved_at": now,
                "auto_approved_reason": "force_approve" if force else "stable_vendor_auto_approve",
                "updated_utc": now,
            }},
        )
        approved += 1
        by_vendor.setdefault(vendor or "unknown", 0)
        by_vendor[vendor or "unknown"] += 1

    return {
        "total_candidates": len(candidates),
        "approved": approved,
        "skipped": skipped,
        "by_vendor": dict(sorted(by_vendor.items(), key=lambda x: -x[1])[:20]),
        "force_mode": force,
        "timestamp": now,
    }


def _effective_status(profile):
    """Compute effective status from profile."""
    override = profile.get("manual_override_status", "none") or "none"
    if override == "force_stable":
        return "stable"
    if override == "force_watch":
        return "watch"
    if override == "force_unstable":
        return "unstable"
    if profile.get("stable_vendor_flag", False):
        return "stable"
    return "unstable"
