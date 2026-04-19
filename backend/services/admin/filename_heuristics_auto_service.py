"""
Auto-Propose Filename Heuristic Rules (v2.5.10)
───────────────────────────────────────────────

Zero-manual-input rule generation. For every unmatched `(vendor, shape)`
group in the triage scan, mine that vendor's OWN already-classified
documents to derive the dominant `doc_type`. If the vote is decisive
(≥ `min_majority`% and ≥ `min_vendor_samples` samples), emit a proposal.

Proposals can then be persisted as dynamic rules into
`filename_heuristic_custom_rules` — no code change required, no
service restart. The classify_filename() function in
filename_heuristics_service consults both built-in AND custom rules.

Design decisions:
    * We intentionally IGNORE BC vendor master for doc-type inference —
      BC tells us the vendor exists, not what their files *typically* are.
      Only in-hub history reveals that.
    * We also exclude the vendor's own heuristic-classified docs from the
      vote (`filename_heuristic_applied_at IS NOT NULL`) to avoid
      feedback loops where one week's heuristic decision ratifies itself
      the next week.
    * Shape→regex conversion is deliberately permissive (`A+` → `[A-Za-z]+`,
      `#+` → `\\d+`) so forward shape-equivalent filenames match.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db
from services.admin.filename_heuristics_service import classify_filename
from services.admin.triage_tools_service import (
    filename_shape, _unmatched_filter,
)
from services.admin.unknown_doc_reclaim_service import UNKNOWN_DOC_TYPES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Shape → regex
# ─────────────────────────────────────────────────────────────

def shape_to_regex(shape: str) -> str:
    """Turn a shape signature back into an anchored regex.

    >>> shape_to_regex("A+#+_A+#+.A+")
    '^[A-Za-z]+\\\\d+_[A-Za-z]+\\\\d+\\\\.[A-Za-z]+$'
    """
    parts: List[str] = []
    i = 0
    n = len(shape)
    while i < n:
        ch = shape[i]
        if shape.startswith("A+", i):
            parts.append(r"[A-Za-z]+")
            i += 2
        elif shape.startswith("#+", i):
            parts.append(r"\d+")
            i += 2
        else:
            parts.append(re.escape(ch))
            i += 1
    return "^" + "".join(parts) + "$"


# ─────────────────────────────────────────────────────────────
# Vendor majority-type mining
# ─────────────────────────────────────────────────────────────

async def vendor_majority_doc_type(
    db,
    vendor_canonical: Optional[str],
    vendor_name: Optional[str] = None,
    *,
    min_samples: int = 5,
    min_majority_pct: float = 70.0,
) -> Optional[Dict[str, Any]]:
    """Return `{doc_type, votes, total, pct}` if one doc_type dominates
    this vendor's classified history, else None."""
    if not vendor_canonical and not vendor_name:
        return None
    or_clauses = []
    if vendor_canonical:
        or_clauses.append({"vendor_canonical": vendor_canonical})
    if vendor_name:
        or_clauses.append({"vendor_name": vendor_name})
    q = {
        "$or": or_clauses,
        "doc_type": {"$nin": list(UNKNOWN_DOC_TYPES)},
        # Exclude our own heuristic decisions so the vote is based on
        # real classifications (AI, reviewer, BC evidence).
        "filename_heuristic_applied_at": {"$in": [None, "", False]},
    }
    cursor = db.hub_documents.find(q, {"_id": 0, "doc_type": 1}).limit(2000)
    counter: Counter = Counter()
    async for d in cursor:
        dt = d.get("doc_type")
        if dt:
            counter[dt] += 1
    total = sum(counter.values())
    if total < min_samples:
        return None
    top_type, top_votes = counter.most_common(1)[0]
    pct = round((top_votes / total) * 100.0, 1)
    if pct < min_majority_pct:
        return None
    return {
        "doc_type": top_type,
        "votes": top_votes,
        "total": total,
        "pct": pct,
    }


# ─────────────────────────────────────────────────────────────
# Group collection
# ─────────────────────────────────────────────────────────────

async def _collect_unmatched_groups(
    db,
    *,
    limit: int = 3000,
    min_group_size: int = 3,
) -> List[Dict[str, Any]]:
    """Walk unmatched docs, group by (vendor, shape) with examples.

    Deliberately duplicates a small part of `unmatched_sample` so we can
    keep vendor_canonical + vendor_name + example file_names together —
    information we need for vendor-history lookup that the existing
    function drops once it builds its output."""
    projection = {
        "_id": 0, "id": 1, "file_name": 1,
        "vendor_canonical": 1, "vendor_name": 1,
    }
    cursor = db.hub_documents.find(_unmatched_filter(), projection).limit(limit)
    groups: Dict[tuple, Dict[str, Any]] = {}
    async for d in cursor:
        fn = d.get("file_name") or ""
        if not fn:
            continue
        # Defensive: if an existing built-in rule matches, skip it.
        if classify_filename(fn, d.get("vendor_canonical"), d.get("vendor_name")):
            continue
        vendor_canonical = d.get("vendor_canonical") or ""
        vendor_name = d.get("vendor_name") or ""
        shape = filename_shape(fn)
        key = (vendor_canonical or vendor_name or "<no vendor>", shape)
        g = groups.setdefault(key, {
            "vendor_canonical": vendor_canonical,
            "vendor_name": vendor_name,
            "shape": shape,
            "count": 0,
            "examples": [],
            "example_ids": [],
        })
        g["count"] += 1
        if len(g["examples"]) < 5:
            g["examples"].append(fn)
            g["example_ids"].append(d.get("id"))
    return [g for g in groups.values() if g["count"] >= min_group_size]


# ─────────────────────────────────────────────────────────────
# Propose
# ─────────────────────────────────────────────────────────────

async def auto_propose(
    *,
    limit: int = 3000,
    min_group_size: int = 3,
    min_vendor_samples: int = 5,
    min_majority_pct: float = 70.0,
    db=None,
) -> Dict[str, Any]:
    """Auto-derive rule proposals for every high-confidence vendor group.

    Returns a report with two lists:
        * `proposals` — groups where vendor history decided the doc_type.
        * `deferred`  — groups we couldn't confidently type (low sample
          count or no majority). These need a human eye.
    """
    db = db if db is not None else get_db()
    raw_groups = await _collect_unmatched_groups(
        db, limit=limit, min_group_size=min_group_size,
    )
    proposals: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []

    for g in raw_groups:
        vendor_c = g["vendor_canonical"]
        vendor_n = g["vendor_name"]
        majority = await vendor_majority_doc_type(
            db, vendor_c, vendor_n,
            min_samples=min_vendor_samples,
            min_majority_pct=min_majority_pct,
        )
        if not majority:
            deferred.append({
                "vendor_canonical": vendor_c,
                "vendor_name": vendor_n,
                "shape": g["shape"],
                "unmatched_count": g["count"],
                "examples": g["examples"],
                "reason": "no decisive vendor majority",
            })
            continue

        rule_id = _rule_id_from(vendor_c or vendor_n, g["shape"])
        vendor_regex = _vendor_regex_from(vendor_c, vendor_n)
        filename_regex = shape_to_regex(g["shape"])
        # Confidence is a scaled majority: 70% majority → 0.70,
        # 100% majority → 0.95. Capped to preserve human review signal.
        confidence = min(0.95, round(majority["pct"] / 100.0, 2))

        proposals.append({
            "rule_id": rule_id,
            "vendor_canonical": vendor_c,
            "vendor_name": vendor_n,
            "vendor_regex": vendor_regex,
            "shape": g["shape"],
            "filename_regex": filename_regex,
            "doc_type": majority["doc_type"],
            "confidence": confidence,
            "unmatched_count": g["count"],
            "vendor_history": majority,
            "examples": g["examples"],
            "example_ids": g["example_ids"],
            "note": (
                f"Auto-derived from {majority['votes']}/{majority['total']} "
                f"({majority['pct']}%) of this vendor's classified history."
            ),
        })

    proposals.sort(key=lambda p: -p["unmatched_count"])
    deferred.sort(key=lambda p: -p["unmatched_count"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "min_group_size": min_group_size,
        "min_vendor_samples": min_vendor_samples,
        "min_majority_pct": min_majority_pct,
        "groups_total": len(raw_groups),
        "proposals_count": len(proposals),
        "deferred_count": len(deferred),
        "projected_coverage": sum(p["unmatched_count"] for p in proposals),
        "proposals": proposals[:200],
        "deferred": deferred[:100],
    }


def _rule_id_from(vendor: str, shape: str) -> str:
    v = re.sub(r"[^a-z0-9]+", "_", (vendor or "unk").lower()).strip("_")[:40]
    s = re.sub(r"[^a-z0-9]+", "_", shape.lower()).strip("_")[:30]
    return f"auto_{v}__{s}" if v else f"auto__{s}"


def _vendor_regex_from(canonical: str, name: str) -> Optional[str]:
    """Build a loose vendor regex from whichever label is present."""
    v = (canonical or name or "").strip()
    if not v:
        return None
    # Take the first identifying word (letters only, 3+ chars).
    m = re.match(r"[^A-Za-z]*([A-Za-z]{3,})", v)
    token = m.group(1) if m else v[:8]
    return rf"(?i)^{re.escape(token)}"


# ─────────────────────────────────────────────────────────────
# Apply — persist as custom rules
# ─────────────────────────────────────────────────────────────

async def apply_auto_proposed(
    *,
    execute: bool = False,
    actor: str = "admin",
    min_unmatched_count: int = 3,
    min_confidence: float = 0.70,
    limit: int = 3000,
    db=None,
) -> Dict[str, Any]:
    """Persist auto-proposed rules into `filename_heuristic_custom_rules`.
    Dry-run by default. Safe to re-run — uses rule_id as upsert key."""
    db = db if db is not None else get_db()
    report = await auto_propose(limit=limit, db=db)

    eligible = [
        p for p in report["proposals"]
        if p["unmatched_count"] >= min_unmatched_count
        and p["confidence"] >= min_confidence
    ]

    if not execute:
        return {
            "execute": False,
            "min_unmatched_count": min_unmatched_count,
            "min_confidence": min_confidence,
            "eligible_count": len(eligible),
            "projected_coverage": sum(p["unmatched_count"] for p in eligible),
            "eligible_sample": eligible[:30],
            "hint": "Dry-run. Pass execute=true to persist into filename_heuristic_custom_rules.",
        }

    now = datetime.now(timezone.utc).isoformat()
    inserted: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for p in eligible:
        try:
            r = await db.filename_heuristic_custom_rules.update_one(
                {"rule_id": p["rule_id"]},
                {"$set": {
                    "rule_id": p["rule_id"],
                    "vendor_canonical": p["vendor_canonical"],
                    "vendor_name": p["vendor_name"],
                    "vendor_regex": p["vendor_regex"],
                    "filename_regex": p["filename_regex"],
                    "doc_type": p["doc_type"],
                    "confidence": p["confidence"],
                    "note": p["note"],
                    "origin": "auto_proposed",
                    "actor": actor,
                    "enabled": True,
                    "last_updated_utc": now,
                },
                 "$setOnInsert": {"created_utc": now}},
                upsert=True,
            )
            if r.upserted_id is not None:
                inserted.append({"rule_id": p["rule_id"], "doc_type": p["doc_type"]})
            elif r.modified_count:
                inserted.append({"rule_id": p["rule_id"], "doc_type": p["doc_type"],
                                 "updated": True})
            else:
                skipped.append({"rule_id": p["rule_id"], "reason": "no-op"})
        except Exception as e:  # noqa: BLE001
            logger.warning("[auto_apply] %s failed: %s", p["rule_id"], e)
            errors.append({"rule_id": p["rule_id"], "error": str(e)})

    result = {
        "generated_at": now,
        "execute": True,
        "actor": actor,
        "min_unmatched_count": min_unmatched_count,
        "min_confidence": min_confidence,
        "inserted_or_updated_count": len(inserted),
        "skipped_count": len(skipped),
        "errors_count": len(errors),
        "projected_coverage": sum(p["unmatched_count"] for p in eligible),
        "inserted_sample": inserted[:50],
        "errors": errors[:20],
    }
    try:
        await db.filename_heuristic_auto_runs.insert_one({**result, "ran_at": now})
    except Exception as e:  # noqa: BLE001
        logger.debug("[auto_apply] audit insert failed: %s", e)
    # Kick the in-memory cache so new rules are visible immediately.
    try:
        from services.admin.filename_heuristics_service import (
            _invalidate_custom_rule_cache,
        )
        _invalidate_custom_rule_cache()
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "[FilenameHeuristics.auto] actor=%s eligible=%d persisted=%d errors=%d",
        actor, len(eligible), len(inserted), len(errors),
    )
    return result


# ─────────────────────────────────────────────────────────────
# Custom rules listing + delete
# ─────────────────────────────────────────────────────────────

async def list_custom_rules(db=None, only_enabled: bool = False) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    q = {"enabled": True} if only_enabled else {}
    return await db.filename_heuristic_custom_rules.find(
        q, {"_id": 0},
    ).sort("last_updated_utc", -1).to_list(500)


async def set_custom_rule_enabled(rule_id: str, enabled: bool, db=None) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    r = await db.filename_heuristic_custom_rules.update_one(
        {"rule_id": rule_id},
        {"$set": {"enabled": bool(enabled),
                  "last_updated_utc": datetime.now(timezone.utc).isoformat()}},
    )
    return {"rule_id": rule_id, "enabled": enabled, "modified": r.modified_count}


__all__ = [
    "shape_to_regex", "vendor_majority_doc_type",
    "auto_propose", "apply_auto_proposed",
    "list_custom_rules", "set_custom_rule_enabled",
]
