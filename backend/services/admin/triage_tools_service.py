"""
Unmatched-Sample + Duplicate-Doc Scan Service (v2.5.9)
───────────────────────────────────────────────────────

Two admin tools that share a common goal: make the 361 unmatched heuristic
candidates actionable.

1. `unmatched_sample` — for every unclassified doc that DIDN'T match any
   existing filename rule, collapse the filename into a "shape signature"
   (digits → `#+`, letters → `A+`, punctuation preserved) and group by
   (vendor, shape, extension). This surfaces new rule candidates like:
       vendor=ROTONDO  shape=A+#+_A+#+.A+    count=40  → probably AP_Invoice
       vendor=FEDEX    shape=#+_A+.A+        count=12  → probably BOL/Tracking

2. `duplicate_scan` — finds groups of docs with the same
   (file_name + vendor_canonical + ingestion_day) where count > 1. This
   catches the email-poller dedup miss we saw in prod
   (`GAMMIN_AR_20260316.xls` ingested 12 times on the same day).
   `duplicate_resolve` lets an operator mark all-but-one per group as
   `duplicate_of=<keeper_id>` and removes them from the queue.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from deps import get_db
from services.admin.filename_heuristics_service import classify_filename
from services.admin.unknown_doc_reclaim_service import (
    BC_EVIDENCE_FIELDS, UNKNOWN_DOC_TYPES,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 1. Unmatched sample / shape grouping
# ─────────────────────────────────────────────────────────────

def filename_shape(name: str) -> str:
    """Collapse a filename into a shape signature using non-overlapping
    tokens (`A+` for letter runs, `#+` for digit runs). Single-pass
    tokenization avoids the self-consumption bug where replacing digits
    with `\\d+` would then get letter-replaced into `\\A+`.

    >>> filename_shape("ROT12345_p1.pdf")
    'A+#+_A+#+.A+'
    >>> filename_shape("Invoice-0000042_doc1.pdf")
    'A+-#+_A+#+.A+'
    """
    if not name:
        return ""
    out = []
    i = 0
    n = len(name)
    while i < n:
        c = name[i]
        if c.isalpha():
            while i < n and name[i].isalpha():
                i += 1
            out.append("A+")
        elif c.isdigit():
            while i < n and name[i].isdigit():
                i += 1
            out.append("#+")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _unmatched_filter() -> Dict[str, Any]:
    """Docs the heuristic classifier didn't (or couldn't) label."""
    bc_not_present = {
        "$and": [{f: {"$in": [None, ""]}} for f in BC_EVIDENCE_FIELDS]
    }
    return {
        "$and": [
            {"doc_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"document_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"suggested_job_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"filename_heuristic_applied_at": {"$in": [None, "", False]}},
            bc_not_present,
        ],
    }


async def unmatched_sample(
    *,
    limit: int = 1000,
    top_n: int = 40,
    min_group_size: int = 2,
    db=None,
) -> Dict[str, Any]:
    """Group unmatched doc filenames by (vendor, shape) to surface rule
    candidates.

    Only returns groups with at least `min_group_size` docs (single-off
    oddballs aren't worth writing a rule for).
    """
    db = db if db is not None else get_db()
    projection = {"_id": 0, "id": 1, "file_name": 1,
                  "vendor_canonical": 1, "vendor_name": 1}
    cursor = db.hub_documents.find(_unmatched_filter(), projection).limit(limit)

    groups: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {
        "count": 0, "examples": [], "example_ids": [],
    })
    total_scanned = 0
    still_matched = 0  # sanity: re-run classify to confirm it really is unmatched

    async for d in cursor:
        total_scanned += 1
        vendor = d.get("vendor_canonical") or d.get("vendor_name") or "<no vendor>"
        fn = d.get("file_name") or "<no filename>"
        # Defensive re-check: skip if a rule actually does match now.
        if classify_filename(fn, vendor):
            still_matched += 1
            continue
        shape = filename_shape(fn)
        key = (vendor, shape)
        g = groups[key]
        g["count"] += 1
        if len(g["examples"]) < 3:
            g["examples"].append(fn)
            g["example_ids"].append(d.get("id"))

    rows = [
        {
            "vendor": k[0],
            "shape": k[1],
            "count": v["count"],
            "examples": v["examples"],
            "example_ids": v["example_ids"],
        }
        for k, v in groups.items()
        if v["count"] >= min_group_size
    ]
    rows.sort(key=lambda r: (-r["count"], r["vendor"]))
    top = rows[:top_n]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": total_scanned,
        "groups_total": len(rows),
        "groups_shown": len(top),
        "min_group_size": min_group_size,
        "rule_candidates": top,
        "still_matched_after_rescan": still_matched,
    }


# ─────────────────────────────────────────────────────────────
# 2. Duplicate-doc scan + resolve
# ─────────────────────────────────────────────────────────────

DUPLICATE_KEY_FIELDS = ("file_name", "vendor_canonical")


def _ingestion_day_from_doc(d: Dict[str, Any]) -> str:
    """YYYY-MM-DD day key derived from created_utc (first 10 chars)."""
    v = d.get("created_utc") or d.get("uploaded_at") or ""
    return str(v)[:10] if v else ""


async def duplicate_scan(
    *,
    same_day: bool = True,
    limit: int = 2000,
    min_count: int = 2,
    db=None,
) -> Dict[str, Any]:
    """Return groups of docs with the same (filename, vendor[, ingestion day])
    where `count >= min_count`.

    Args:
        same_day: If True (default), group also by YYYY-MM-DD of created_utc.
                  Catches repeated email-poll duplicates without flagging
                  legit recurring filings (e.g. a monthly statement that
                  comes in with the same name each month).
    """
    db = db if db is not None else get_db()
    projection = {
        "_id": 0, "id": 1, "file_name": 1,
        "vendor_canonical": 1, "vendor_name": 1,
        "status": 1, "created_utc": 1, "duplicate_of": 1,
        "duplicate_resolved_at": 1, "queue_visible": 1,
    }
    # Only look at docs that haven't already been deduped
    q = {"duplicate_resolved_at": {"$in": [None, "", False]}}
    docs = await db.hub_documents.find(q, projection).limit(limit).to_list(limit)

    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for d in docs:
        fn = d.get("file_name")
        vc = d.get("vendor_canonical") or d.get("vendor_name")
        if not fn or not vc:
            continue
        key = (fn, vc, _ingestion_day_from_doc(d) if same_day else "")
        groups[key].append(d)

    dup_groups = []
    total_dup_docs = 0
    for key, rows in groups.items():
        if len(rows) < min_count:
            continue
        # Sort oldest → newest so keeper selection is deterministic
        rows.sort(key=lambda r: r.get("created_utc") or "")
        total_dup_docs += len(rows)
        dup_groups.append({
            "file_name": key[0],
            "vendor_canonical": key[1],
            "ingestion_day": key[2] or None,
            "count": len(rows),
            "docs": [
                {
                    "id": r["id"],
                    "created_utc": r.get("created_utc"),
                    "status": r.get("status"),
                }
                for r in rows
            ],
        })
    dup_groups.sort(key=lambda g: -g["count"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "same_day": same_day,
        "min_count": min_count,
        "groups_total": len(dup_groups),
        "duplicate_docs_total": total_dup_docs,
        "wasted_docs_estimate": sum(g["count"] - 1 for g in dup_groups),
        "groups": dup_groups[:100],
    }


KeepStrategy = Literal["oldest", "newest"]


async def duplicate_resolve(
    *,
    execute: bool = False,
    keep: KeepStrategy = "oldest",
    same_day: bool = True,
    actor: str = "admin",
    limit: int = 2000,
    db=None,
) -> Dict[str, Any]:
    """For every dup group, keep one doc (oldest or newest) and flag the
    rest with `duplicate_of=<keeper_id>`, `queue_visible=false`,
    `status='Completed'`. Dry-run by default."""
    db = db if db is not None else get_db()
    scan = await duplicate_scan(same_day=same_day, limit=limit, db=db)

    # Decide winners / losers per group
    now = datetime.now(timezone.utc).isoformat()
    planned: List[Dict[str, Any]] = []
    for group in scan["groups"]:
        docs = sorted(group["docs"], key=lambda r: r.get("created_utc") or "")
        if keep == "oldest":
            winner = docs[0]
            losers = docs[1:]
        else:
            winner = docs[-1]
            losers = docs[:-1]
        planned.append({
            "file_name": group["file_name"],
            "vendor_canonical": group["vendor_canonical"],
            "keeper_id": winner["id"],
            "loser_ids": [d["id"] for d in losers],
        })

    if not execute:
        return {
            "execute": False,
            "keep_strategy": keep,
            "same_day": same_day,
            "groups_to_resolve": len(planned),
            "would_mark_duplicate": sum(len(p["loser_ids"]) for p in planned),
            "plan_sample": planned[:20],
            "hint": "Dry-run. Pass execute=true to apply.",
        }

    resolved: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for plan in planned:
        for loser in plan["loser_ids"]:
            try:
                r = await db.hub_documents.update_one(
                    {"id": loser},
                    {
                        "$set": {
                            "duplicate_of": plan["keeper_id"],
                            "duplicate_resolved_at": now,
                            "duplicate_resolved_actor": actor,
                            "duplicate_resolved_strategy": keep,
                            "queue_visible": False,
                            "status": "Completed",
                            "workflow_status": "completed",
                            "square9_stage": "completed",
                            "updated_utc": now,
                        },
                        "$push": {
                            "workflow_history": {
                                "timestamp": now,
                                "from_status": None,
                                "to_status": "Completed",
                                "event": "duplicate_resolved",
                                "actor": actor,
                                "reason": (
                                    f"Duplicate of {plan['keeper_id']} "
                                    f"(same file_name + vendor"
                                    f"{' + same day' if same_day else ''}); "
                                    f"keeper strategy={keep}"
                                ),
                            },
                        },
                    },
                )
                if r.modified_count:
                    resolved.append({
                        "id": loser, "keeper_id": plan["keeper_id"],
                    })
            except Exception as e:  # noqa: BLE001
                logger.warning("[DupResolve] %s failed: %s", loser, e)
                errors.append({"doc_id": loser, "error": str(e)})

    result = {
        "generated_at": now,
        "execute": True,
        "actor": actor,
        "keep_strategy": keep,
        "same_day": same_day,
        "groups_resolved": len(planned),
        "docs_marked_duplicate": len(resolved),
        "errors_count": len(errors),
        "errors": errors[:20],
        "resolved_sample": resolved[:50],
    }
    try:
        await db.duplicate_resolve_runs.insert_one({**result, "ran_at": now})
    except Exception as e:  # noqa: BLE001
        logger.debug("[DupResolve] audit insert failed: %s", e)

    logger.info(
        "[DupResolve] actor=%s groups=%d marked=%d errors=%d keep=%s",
        actor, len(planned), len(resolved), len(errors), keep,
    )
    return result


async def recent_duplicate_runs(limit: int = 20, db=None) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    return await db.duplicate_resolve_runs.find(
        {}, {"_id": 0},
    ).sort("ran_at", -1).limit(limit).to_list(limit)


__all__ = [
    "filename_shape", "unmatched_sample",
    "duplicate_scan", "duplicate_resolve", "recent_duplicate_runs",
]
