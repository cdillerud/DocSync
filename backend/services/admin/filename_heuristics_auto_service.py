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

async def vendor_doc_type_distribution(
    db,
    vendor_canonical: Optional[str],
    vendor_name: Optional[str] = None,
    *,
    include_heuristic_applied: bool = False,
    limit: int = 2000,
) -> Dict[str, Any]:
    """Return the raw vendor history. Diagnostic-friendly:
        {
            total: int, by_doc_type: {<type>: <n>}, top: [ (type,n,pct), ... ],
            query_used: dict, included_heuristic_applied: bool
        }
    """
    if not vendor_canonical and not vendor_name:
        return {"total": 0, "by_doc_type": {}, "top": [],
                "query_used": None, "reason": "no vendor provided"}
    or_clauses = []
    if vendor_canonical:
        or_clauses.append({"vendor_canonical": vendor_canonical})
    if vendor_name:
        or_clauses.append({"vendor_name": vendor_name})
    q: Dict[str, Any] = {
        "$or": or_clauses,
        "doc_type": {"$nin": list(UNKNOWN_DOC_TYPES)},
    }
    if not include_heuristic_applied:
        q["filename_heuristic_applied_at"] = {"$in": [None, "", False]}

    counter: Counter = Counter()
    cursor = db.hub_documents.find(q, {"_id": 0, "doc_type": 1}).limit(limit)
    async for d in cursor:
        dt = d.get("doc_type")
        if dt:
            counter[dt] += 1
    total = sum(counter.values())
    top = [
        {"doc_type": t, "votes": n,
         "pct": round((n / total) * 100.0, 1) if total else 0.0}
        for t, n in counter.most_common(10)
    ]
    return {
        "vendor_canonical": vendor_canonical,
        "vendor_name": vendor_name,
        "total": total,
        "by_doc_type": dict(counter),
        "top": top,
        "query_used": q,
        "included_heuristic_applied": include_heuristic_applied,
    }


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
    dist = await vendor_doc_type_distribution(
        db, vendor_canonical, vendor_name,
    )
    total = dist["total"]
    if total < min_samples or not dist["top"]:
        return None
    top = dist["top"][0]
    if top["pct"] < min_majority_pct:
        return None
    return {
        "doc_type": top["doc_type"],
        "votes": top["votes"],
        "total": total,
        "pct": top["pct"],
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
        # Pull the full distribution once — we use it for both the
        # majority decision AND the deferred diagnostic.
        dist = await vendor_doc_type_distribution(db, vendor_c, vendor_n)
        decision = _decide(
            dist,
            unmatched_count=g["count"],
            min_vendor_samples=min_vendor_samples,
            min_majority_pct=min_majority_pct,
        )

        if decision is None:
            # Explain exactly why we couldn't decide.
            if not (vendor_c or vendor_n):
                reason = "no vendor on the unmatched docs (vendor_canonical + vendor_name both empty)"
            elif dist["total"] == 0:
                reason = (
                    "vendor has 0 non-Unknown, non-heuristic-classified docs "
                    "in hub_documents — can't infer doc_type from history"
                )
            elif dist["total"] < 2:
                reason = (
                    f"only {dist['total']} classified doc for this vendor "
                    f"(need ≥2 at 100% or ≥{min_vendor_samples} to vote)"
                )
            else:
                top = dist["top"][0]
                second = dist["top"][1] if len(dist["top"]) > 1 else None
                margin_note = (
                    f" (margin {round(top['pct'] / second['pct'], 1)}× over 2nd "
                    f"at {second['pct']}%)"
                    if second and second["pct"] > 0 else ""
                )
                reason = (
                    f"top doc_type is {top['doc_type']} at {top['pct']}%{margin_note} — "
                    f"no tier qualified "
                    f"(A: ≥{min_majority_pct}% + ≥{min_vendor_samples} samples | "
                    f"B: 100%% + ≥2 samples | "
                    f"C: ≥60%% + ≥2× margin + ≥20 samples)"
                )
            deferred.append({
                "vendor_canonical": vendor_c,
                "vendor_name": vendor_n,
                "shape": g["shape"],
                "unmatched_count": g["count"],
                "examples": g["examples"],
                "example_ids": g["example_ids"][:5],
                "vendor_history_total": dist["total"],
                "vendor_history_top": dist["top"][:5],
                "reason": reason,
            })
            continue

        majority, tier, confidence = decision
        rule_id = _rule_id_from(vendor_c or vendor_n, g["shape"])
        vendor_regex = _vendor_regex_from(vendor_c, vendor_n)
        filename_regex = shape_to_regex(g["shape"])

        proposals.append({
            "rule_id": rule_id,
            "vendor_canonical": vendor_c,
            "vendor_name": vendor_n,
            "vendor_regex": vendor_regex,
            "shape": g["shape"],
            "filename_regex": filename_regex,
            "doc_type": majority["doc_type"],
            "confidence": confidence,
            "tier": tier,
            "unmatched_count": g["count"],
            "vendor_history": majority,
            "examples": g["examples"],
            "example_ids": g["example_ids"],
            "note": (
                f"[Tier {tier}] Auto-derived from {majority['votes']}/{majority['total']} "
                f"({majority['pct']}%) of this vendor's classified history."
            ),
        })

    proposals.sort(key=lambda p: -p["unmatched_count"])
    deferred.sort(key=lambda p: -p["unmatched_count"])

    by_tier: Dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for p in proposals:
        by_tier[p["tier"]] = by_tier.get(p["tier"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "min_group_size": min_group_size,
        "min_vendor_samples": min_vendor_samples,
        "min_majority_pct": min_majority_pct,
        "groups_total": len(raw_groups),
        "proposals_count": len(proposals),
        "deferred_count": len(deferred),
        "proposals_by_tier": by_tier,
        "projected_coverage": sum(p["unmatched_count"] for p in proposals),
        "proposals": proposals[:200],
        "deferred": deferred[:100],
    }


# ─────────────────────────────────────────────────────────────
# Tiered decision
# ─────────────────────────────────────────────────────────────

# Tier C thresholds — catches "strong but not overwhelming" majorities
# when there's a lot of unmatched volume AND a wide margin over 2nd.
_TIER_C_MIN_PCT = 60.0
_TIER_C_MIN_SAMPLES = 20
_TIER_C_MIN_MARGIN = 2.0  # top_pct / second_pct


def _decide(
    dist: Dict[str, Any],
    *,
    unmatched_count: int,  # noqa: ARG001 — reserved for future per-group tuning
    min_vendor_samples: int,
    min_majority_pct: float,
) -> Optional[tuple]:
    """Return `(majority_dict, tier, confidence)` or None.

    Three tiers, first match wins:
        Tier A — High-volume, high-agreement (the original contract).
                 ≥ min_majority_pct AND ≥ min_vendor_samples.
                 confidence = top_pct/100, capped 0.95.
        Tier B — Small sample, perfect agreement.
                 100% majority AND total ≥ 2.
                 confidence = 0.75 (strong signal but worth a human pass).
        Tier C — Wide margin, strong (not perfect) majority, large sample.
                 top_pct ≥ 60 AND margin ≥ 2× over 2nd AND total ≥ 20.
                 confidence = 0.70. Deliberately below tier-A confidence
                 so reviewers notice these before auto-close logic trusts them.
    """
    if not dist.get("top"):
        return None
    top = dist["top"][0]
    total = dist["total"]
    top_pct = top["pct"]
    second_pct = dist["top"][1]["pct"] if len(dist["top"]) > 1 else 0.0

    majority = {
        "doc_type": top["doc_type"],
        "votes": top["votes"],
        "total": total,
        "pct": top_pct,
    }

    # Tier A: original contract
    if top_pct >= min_majority_pct and total >= min_vendor_samples:
        return majority, "A", min(0.95, round(top_pct / 100.0, 2))

    # Tier B: few samples but unanimous
    if top_pct >= 100.0 and total >= 2:
        return majority, "B", 0.75

    # Tier C: wide margin with decent sample
    if (top_pct >= _TIER_C_MIN_PCT
            and total >= _TIER_C_MIN_SAMPLES
            and second_pct > 0
            and (top_pct / second_pct) >= _TIER_C_MIN_MARGIN):
        return majority, "C", 0.70

    return None


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
