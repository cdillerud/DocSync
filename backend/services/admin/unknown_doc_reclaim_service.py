"""
Unknown-Doc Reclaim Service (v2.5.5 / v2.5.6 enhancements)
───────────────────────────────────────────────────────────

One-shot sweep that rescues documents which slipped through the pipeline
before the v2.5.3 auto-clear `unclassified_guard`. Those docs are currently
sitting at `status = Completed` / `workflow_status = exported` even though
their `doc_type` is None / "" / "Unknown" / "Other" — bypassing manual
review with no extracted content.

Modes:
  • basic (default)      — every candidate → NeedsReview
  • smart=True           — batch-split children whose parent IS classified
                           inherit the parent's doc_type + vendor before
                           routing to NeedsReview. Reviewers see context
                           instead of bare "Unknown".
  • skip_noise=True      — filters out garbage filenames (email sprites,
                           tiny signature PNGs, `image.png`, etc.) so they
                           DON'T come back to the review queue — they're
                           silently marked as `noise_filtered` instead.

Safety (unchanged across modes):
  • Candidates require all three type fields unclassified AND auto_cleared
  • Docs with any BC write evidence are hard-excluded
  • Idempotent via `reclaim_to_needs_review_at`
  • Dry-run by default
  • Full audit (auto_cleared_at preserved, workflow_history appended,
    per-run summary in `unknown_doc_reclaim_runs`)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from deps import get_db

logger = logging.getLogger(__name__)

UNKNOWN_DOC_TYPES = [
    None, "", "DEFAULT",
    "Unknown", "UNKNOWN", "unknown",
    "Unknown_Document", "UNKNOWN_DOCUMENT",
    "Unknown_Sales", "UNKNOWN_SALES",
    "Other", "OTHER",
]

BC_EVIDENCE_FIELDS = [
    "bc_purchase_invoice_no",
    "bc_record_no",
    "bc_document_no",
    "bc_record_id",
]

CLEARED_STATUSES = ["Completed", "Exported", "Archived", "completed", "exported", "archived"]

# Filename patterns that almost-always indicate email sprites / signatures /
# inline images that were never real documents. Matched case-insensitively
# against `file_name`. Kept narrow on purpose: we'd rather re-review a false
# positive than silently drop a real doc.
NOISE_FILENAME_PATTERNS = [
    r"^linkedin[_\-]?\d+x\d+",     # linkedin_32x32_*.png
    r"^twitter[_\-]?\d+x\d+",
    r"^facebook[_\-]?\d+x\d+",
    r"^instagram[_\-]?\d+x\d+",
    r"^cmn_[0-9a-f\-]{8,}",         # cmn_<uuid>.png email sprites
    r"^qr[0-9a-f\-]{8,}",           # QR<uuid>.png
    r"^image\.png$",
    r"^image\.jpg$",
    r"^image\.jpeg$",
    r"^image\d+\.(png|jpg|jpeg|gif)$",
    r"^signature\.(png|jpg|jpeg|gif)$",
    r"^sig[_\-]?\d*\.(png|jpg|jpeg|gif)$",
    r"^logo\.(png|jpg|jpeg|gif|svg)$",
    r"^pixel\.(gif|png)$",          # tracking pixels
    r"^spacer\.(gif|png)$",
]
_NOISE_RE = re.compile("|".join(NOISE_FILENAME_PATTERNS), re.IGNORECASE)


def _is_noise(filename: str) -> bool:
    if not filename:
        return False
    return bool(_NOISE_RE.match(filename.strip()))


def _build_filter() -> Dict[str, Any]:
    """Candidate filter. Both preview and run must see the same set."""
    bc_not_present = {
        "$and": [{f: {"$in": [None, ""]}} for f in BC_EVIDENCE_FIELDS]
    }
    return {
        "$and": [
            {"doc_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"document_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"suggested_job_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"status": {"$in": CLEARED_STATUSES}},
            {"auto_cleared": True},
            bc_not_present,
            {"reclaim_to_needs_review_at": {"$in": [None, "", False]}},
        ],
    }


async def _load_parents_map(db, parent_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-load parent docs so smart mode is O(1) round-trips."""
    if not parent_ids:
        return {}
    cursor = db.hub_documents.find(
        {"id": {"$in": list(set(parent_ids))}},
        {"_id": 0, "id": 1, "doc_type": 1, "document_type": 1,
         "suggested_job_type": 1, "vendor_canonical": 1, "vendor_id": 1,
         "vendor_name": 1, "customer_canonical": 1},
    )
    return {d["id"]: d async for d in cursor}


def _parent_is_classified(parent: Dict[str, Any]) -> bool:
    """True if we can usefully inherit from this parent."""
    if not parent:
        return False
    t = (
        parent.get("doc_type")
        or parent.get("document_type")
        or parent.get("suggested_job_type")
    )
    return bool(t) and t not in UNKNOWN_DOC_TYPES


async def preview(
    *,
    limit: int = 50,
    smart: bool = False,
    skip_noise: bool = False,
    db=None,
) -> Dict[str, Any]:
    """Dry-run: counts + sample + mode-specific projections. No writes."""
    db = db if db is not None else get_db()
    q = _build_filter()

    total = await db.hub_documents.count_documents(q)

    projection = {
        "_id": 0, "id": 1, "doc_type": 1, "document_type": 1,
        "suggested_job_type": 1, "status": 1, "workflow_status": 1,
        "file_name": 1, "vendor_canonical": 1, "batch_parent_id": 1,
        "auto_cleared_at": 1, "created_utc": 1,
    }
    sample = await db.hub_documents.find(q, projection).limit(limit).to_list(limit)

    # Mode-aware projections (still read-only)
    noise_sample = 0
    inheritable_sample = 0
    parents_in_sample: Dict[str, Dict[str, Any]] = {}

    if skip_noise:
        noise_sample = sum(1 for d in sample if _is_noise(d.get("file_name", "")))

    if smart:
        parent_ids = [d["batch_parent_id"] for d in sample if d.get("batch_parent_id")]
        parents_in_sample = await _load_parents_map(db, parent_ids)
        inheritable_sample = sum(
            1
            for d in sample
            if d.get("batch_parent_id")
            and _parent_is_classified(parents_in_sample.get(d["batch_parent_id"], {}))
        )

    by_batch_parent = sum(1 for d in sample if d.get("batch_parent_id"))
    by_doc_type: Dict[str, int] = {}
    for d in sample:
        t = d.get("doc_type") or d.get("document_type") or d.get("suggested_job_type") or "None"
        by_doc_type[str(t)] = by_doc_type.get(str(t), 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": total,
        "sample_size": len(sample),
        "sample_breakdown": {
            "from_batch_split": by_batch_parent,
            "by_doc_type": by_doc_type,
            # Mode previews:
            "smart_inheritable": inheritable_sample if smart else None,
            "filtered_as_noise": noise_sample if skip_noise else None,
        },
        "modes": {"smart": smart, "skip_noise": skip_noise},
        "sample": sample,
    }


def _build_reclaim_update(
    doc: Dict[str, Any],
    parent: Optional[Dict[str, Any]],
    now: str,
    actor: str,
) -> Tuple[Dict[str, Any], str]:
    """Build the $set/$push update dict for a single doc. Returns (update,
    path_taken). path_taken ∈ {'inherited', 'plain'}."""
    path = "plain"
    set_fields: Dict[str, Any] = {
        "status": "NeedsReview",
        "workflow_status": "needs_review",
        "square9_stage": "needs_review",
        "queue_visible": True,
        "reclaim_to_needs_review_at": now,
        "reclaim_reason": (
            "v2.5.5 reclaim: doc was auto-cleared before the "
            "v2.5.3 unclassified_guard existed; restoring to "
            "NeedsReview for human review."
        ),
        "reclaim_actor": actor,
        "updated_utc": now,
    }

    if parent and _parent_is_classified(parent):
        path = "inherited"
        parent_type = (
            parent.get("doc_type")
            or parent.get("document_type")
            or parent.get("suggested_job_type")
        )
        # Audit: preserve what the old pipeline had classified the child as,
        # even though it was garbage.
        set_fields["doc_type_from_reclaim_ai"] = doc.get("doc_type")
        set_fields["doc_type"] = parent_type
        set_fields["document_type"] = parent_type
        set_fields["suggested_job_type"] = parent_type
        set_fields["parent_inheritance_applied"] = True
        set_fields["parent_inheritance_at"] = now
        set_fields["parent_inheritance_source"] = "reclaim_smart_mode"
        set_fields["reclaim_reason"] = (
            "v2.5.5 reclaim (smart): inherited parent doc_type="
            f"'{parent_type}' to replace child's unclassified value. "
            "Routed to NeedsReview with enriched context."
        )
        if parent.get("vendor_canonical") and not doc.get("vendor_canonical"):
            set_fields["vendor_canonical"] = parent["vendor_canonical"]
            set_fields["vendor_inherited_from_parent"] = True
        if parent.get("vendor_id") and not doc.get("vendor_id"):
            set_fields["vendor_id"] = parent["vendor_id"]
        if parent.get("customer_canonical") and not doc.get("customer_canonical"):
            set_fields["customer_canonical"] = parent["customer_canonical"]

    return (
        {
            "$set": set_fields,
            "$push": {
                "workflow_history": {
                    "timestamp": now,
                    "from_status": doc.get("status"),
                    "to_status": "NeedsReview",
                    "event": "reclaim_to_needs_review",
                    "actor": actor,
                    "reason": (
                        f"v2.5.5 reclaim ({path}) — unclassified auto-cleared doc"
                    ),
                },
            },
        },
        path,
    )


def _build_noise_update(doc: Dict[str, Any], now: str, actor: str) -> Dict[str, Any]:
    """Mark a noise-filtered doc so it's never treated as a real document
    while still being idempotent (future runs skip it). Does NOT go to
    NeedsReview — these are filename-noise (email sprites, signatures,
    tracking pixels)."""
    return {
        "$set": {
            "noise_filtered": True,
            "noise_filtered_at": now,
            "noise_filtered_reason": "v2.5.5 reclaim: filename matches noise pattern",
            "queue_visible": False,
            # Mark as reclaimed so we never re-pick in idempotent runs
            "reclaim_to_needs_review_at": now,
            "reclaim_actor": actor,
            "updated_utc": now,
        },
        "$push": {
            "workflow_history": {
                "timestamp": now,
                "from_status": doc.get("status"),
                "to_status": doc.get("status"),
                "event": "reclaim_noise_filtered",
                "actor": actor,
                "reason": f"v2.5.5 reclaim: filename '{doc.get('file_name')}' matched noise pattern",
            },
        },
    }


async def run(
    *,
    execute: bool = False,
    limit: Optional[int] = None,
    actor: str = "admin",
    smart: bool = False,
    skip_noise: bool = False,
    db=None,
) -> Dict[str, Any]:
    """Execute (or dry-run) the reclaim sweep.

    Args:
        execute:     Must be True to mutate (default False = dry-run report).
        limit:       Optional cap on docs processed this run.
        actor:       Audit label.
        smart:       If True, batch-split children whose parent is
                     classified inherit the parent's doc_type + vendor
                     before routing to NeedsReview (ghost-review prevention).
        skip_noise:  If True, filename-noise candidates are marked
                     `noise_filtered` and kept OUT of NeedsReview.
    """
    db = db if db is not None else get_db()

    if not execute:
        p = await preview(db=db, limit=50, smart=smart, skip_noise=skip_noise)
        return {
            **p,
            "execute": False,
            "hint": "Dry-run. Pass execute=true to actually reclaim.",
        }

    q = _build_filter()
    now = datetime.now(timezone.utc).isoformat()

    projection = {"_id": 0, "id": 1, "doc_type": 1, "status": 1,
                  "workflow_status": 1, "batch_parent_id": 1,
                  "vendor_canonical": 1, "vendor_id": 1,
                  "customer_canonical": 1, "file_name": 1}
    cursor = db.hub_documents.find(q, projection)
    if limit:
        cursor = cursor.limit(int(limit))

    # Materialize so we can do a batched parent lookup for smart mode
    batch: List[Dict[str, Any]] = []
    async for doc in cursor:
        batch.append(doc)

    parents_map: Dict[str, Dict[str, Any]] = {}
    if smart:
        parent_ids = [d["batch_parent_id"] for d in batch if d.get("batch_parent_id")]
        parents_map = await _load_parents_map(db, parent_ids)

    reclaimed_plain: List[str] = []
    reclaimed_inherited: List[str] = []
    filtered_noise: List[str] = []
    errors: List[Dict[str, Any]] = []

    for doc in batch:
        doc_id = doc.get("id")
        if not doc_id:
            continue
        try:
            # Noise filter first — shortest path
            if skip_noise and _is_noise(doc.get("file_name", "")):
                update = _build_noise_update(doc, now, actor)
                r = await db.hub_documents.update_one({"id": doc_id}, update)
                if r.modified_count:
                    filtered_noise.append(doc_id)
                continue

            parent = None
            if smart and doc.get("batch_parent_id"):
                parent = parents_map.get(doc["batch_parent_id"])

            update, path = _build_reclaim_update(doc, parent, now, actor)
            r = await db.hub_documents.update_one({"id": doc_id}, update)
            if r.modified_count:
                if path == "inherited":
                    reclaimed_inherited.append(doc_id)
                else:
                    reclaimed_plain.append(doc_id)
        except Exception as e:  # noqa: BLE001 — one failure must not abort run
            logger.warning("[UnknownDocReclaim] doc %s failed: %s", doc_id, e)
            errors.append({"doc_id": doc_id, "error": str(e)})

    total_mutated = len(reclaimed_plain) + len(reclaimed_inherited) + len(filtered_noise)
    result = {
        "generated_at": now,
        "execute": True,
        "actor": actor,
        "modes": {"smart": smart, "skip_noise": skip_noise},
        "limit_applied": limit,
        # Legacy field kept for backward-compat with earlier /runs rows
        "reclaimed_count": len(reclaimed_plain) + len(reclaimed_inherited),
        "reclaimed_ids": (reclaimed_plain + reclaimed_inherited)[:50],
        "reclaimed_plain_count": len(reclaimed_plain),
        "reclaimed_inherited_count": len(reclaimed_inherited),
        "filtered_noise_count": len(filtered_noise),
        "filtered_noise_ids": filtered_noise[:50],
        "total_mutated": total_mutated,
        "errors_count": len(errors),
        "errors": errors[:20],
    }

    try:
        await db.unknown_doc_reclaim_runs.insert_one({**result, "ran_at": now})
    except Exception as e:  # noqa: BLE001
        logger.debug("[UnknownDocReclaim] audit insert failed: %s", e)

    logger.info(
        "[UnknownDocReclaim] actor=%s plain=%d inherited=%d noise=%d errors=%d smart=%s skip_noise=%s",
        actor, len(reclaimed_plain), len(reclaimed_inherited),
        len(filtered_noise), len(errors), smart, skip_noise,
    )
    return result


async def recent_runs(limit: int = 20, db=None) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    return await db.unknown_doc_reclaim_runs.find(
        {}, {"_id": 0},
    ).sort("ran_at", -1).limit(limit).to_list(limit)


__all__ = [
    "preview", "run", "recent_runs",
    "UNKNOWN_DOC_TYPES", "NOISE_FILENAME_PATTERNS",
]
