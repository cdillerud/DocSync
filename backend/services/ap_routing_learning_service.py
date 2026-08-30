"""GPI Document Hub — AP Routing Learning Service.

Purpose
-------
Turn Accounting's existing work into supervised routing intelligence so the
system learns from documents that humans have already sorted instead of asking
Accounting to validate the same patterns repeatedly.

Authority model
---------------
* GamerAccounting/AP/Temp Folder placement is a routing LABEL.
* Explicit reviewer corrections are stronger labels than passive placement.
* DocsNAV/Zetadocs is useful for layout/vendor coverage only and is NEVER a
  routing label.
* This service stores/selects examples only. It never moves SharePoint files,
  posts to BC, or changes routing by itself.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


COLLECTION = "ap_routing_examples"
LABEL_SOURCE_ACCOUNTING_TEMP = "accounting_temp"
LABEL_SOURCE_REVIEWER_CORRECTION = "reviewer_correction"
LABEL_SOURCE_MIGRATION_GOLDEN = "migration_golden"
UNLABELED_SOURCE_NAV_ARCHIVE = "nav_archive_unlabeled"

ROUTING_LABEL_SOURCES = {
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    LABEL_SOURCE_MIGRATION_GOLDEN,
}

_SOURCE_WEIGHT = {
    LABEL_SOURCE_REVIEWER_CORRECTION: 1.00,
    LABEL_SOURCE_MIGRATION_GOLDEN: 0.98,
    LABEL_SOURCE_ACCOUNTING_TEMP: 0.94,
}

_CORP_SUFFIX = re.compile(
    r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|company|co)\b",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_vendor_name(value: Any) -> str:
    text = str(value or "").lower().replace("_", " ")
    text = _CORP_SUFFIX.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_route_path(value: Any) -> str:
    parts = [p.strip() for p in str(value or "").replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p)


def is_routing_label_source(source: str) -> bool:
    return str(source or "") in ROUTING_LABEL_SOURCES


def make_example_fingerprint(example: Dict[str, Any]) -> str:
    stable = "|".join(
        [
            str(example.get("source_item_id") or example.get("document_id") or ""),
            str(example.get("file_name") or ""),
            normalize_route_path(example.get("route_path")),
            str(example.get("label_source") or ""),
        ]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def prepare_routing_example(example: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one supervised routing example and reject false authority.

    NAV/Zetadocs examples may be stored elsewhere for layout coverage, but this
    function intentionally refuses to turn them into routing labels.
    """
    source = str(example.get("label_source") or "")
    if source == UNLABELED_SOURCE_NAV_ARCHIVE:
        raise ValueError("NAV/Zetadocs archive placement is not routing authority")
    if not is_routing_label_source(source):
        raise ValueError(f"Unsupported routing label source: {source!r}")

    route_path = normalize_route_path(example.get("route_path"))
    if not route_path:
        raise ValueError("route_path is required for a supervised routing example")

    vendor_name = (
        example.get("vendor_name")
        or example.get("vendor_canonical")
        or ((example.get("extracted_fields") or {}).get("vendor"))
        or ""
    )

    prepared = dict(example)
    prepared.update(
        {
            "route_path": route_path,
            "normalized_vendor": normalize_vendor_name(vendor_name),
            "vendor_name": str(vendor_name or "").strip(),
            "label_source": source,
            "label_weight": float(example.get("label_weight") or _SOURCE_WEIGHT[source]),
            "active": bool(example.get("active", True)),
            "updated_at": _now(),
        }
    )
    prepared.setdefault("created_at", prepared["updated_at"])
    prepared["fingerprint"] = make_example_fingerprint(prepared)
    return prepared


async def upsert_routing_example(db, example: Dict[str, Any]) -> Dict[str, Any]:
    prepared = prepare_routing_example(example)
    await db[COLLECTION].update_one(
        {"fingerprint": prepared["fingerprint"]},
        {"$set": prepared, "$setOnInsert": {"created_at": prepared["created_at"]}},
        upsert=True,
    )
    return prepared


def _bc_context_signature(context: Optional[Dict[str, Any]]) -> Dict[str, str]:
    context = context or {}
    return {
        "location_code": str(
            context.get("location_code")
            or context.get("locationCode")
            or context.get("bc_location_code")
            or ""
        ).upper(),
        "order_family": str(
            context.get("order_family")
            or context.get("order_type")
            or context.get("route_family")
            or ""
        ).lower(),
        "bc_entity_type": str(context.get("bc_entity_type") or "").lower(),
    }


def score_example_similarity(
    example: Dict[str, Any],
    *,
    vendor_name: str = "",
    document_type: str = "",
    bc_context: Optional[Dict[str, Any]] = None,
) -> float:
    """Deterministic retrieval score; the LLM never chooses its own examples."""
    score = float(example.get("label_weight") or 0.0)
    wanted_vendor = normalize_vendor_name(vendor_name)
    example_vendor = normalize_vendor_name(
        example.get("vendor_name") or example.get("normalized_vendor")
    )
    if wanted_vendor and example_vendor:
        if wanted_vendor == example_vendor:
            score += 4.0
        elif wanted_vendor in example_vendor or example_vendor in wanted_vendor:
            score += 2.0

    wanted_type = str(document_type or "").lower()
    example_type = str(
        example.get("document_type") or example.get("suggested_job_type") or ""
    ).lower()
    if wanted_type and example_type and wanted_type == example_type:
        score += 1.5

    wanted_ctx = _bc_context_signature(bc_context)
    example_ctx = _bc_context_signature(example.get("bc_context"))
    if wanted_ctx["location_code"] and wanted_ctx["location_code"] == example_ctx["location_code"]:
        score += 2.5
    if wanted_ctx["order_family"] and wanted_ctx["order_family"] == example_ctx["order_family"]:
        score += 2.5
    if wanted_ctx["bc_entity_type"] and wanted_ctx["bc_entity_type"] == example_ctx["bc_entity_type"]:
        score += 0.5

    if example.get("reviewer_corrected"):
        score += 1.0
    return round(score, 4)


async def select_few_shot_examples(
    db,
    *,
    vendor_name: str = "",
    document_type: str = "",
    bc_context: Optional[Dict[str, Any]] = None,
    limit: int = 8,
    candidate_limit: int = 250,
) -> List[Dict[str, Any]]:
    """Select a small, diverse supervised context for route prediction.

    We intentionally prefer diversity across route labels so variable vendors
    such as Tumalo do not teach the model a false one-vendor/one-folder rule.
    """
    vendor_key = normalize_vendor_name(vendor_name)
    query: Dict[str, Any] = {"active": True, "label_source": {"$in": list(ROUTING_LABEL_SOURCES)}}
    if vendor_key:
        query["normalized_vendor"] = vendor_key

    rows = await db[COLLECTION].find(query, {"_id": 0}).limit(candidate_limit).to_list(candidate_limit)

    # If a vendor is new or sparse, supplement with cross-vendor examples that
    # share document/BC context instead of immediately forcing review.
    if len(rows) < max(4, limit // 2):
        generic_query = {"active": True, "label_source": {"$in": list(ROUTING_LABEL_SOURCES)}}
        generic = await db[COLLECTION].find(generic_query, {"_id": 0}).limit(candidate_limit).to_list(candidate_limit)
        by_fp = {r.get("fingerprint"): r for r in rows if r.get("fingerprint")}
        for row in generic:
            fp = row.get("fingerprint")
            if fp and fp not in by_fp:
                rows.append(row)
                by_fp[fp] = row

    ranked = sorted(
        rows,
        key=lambda r: score_example_similarity(
            r, vendor_name=vendor_name, document_type=document_type, bc_context=bc_context
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    routes_seen = Counter()

    # Pass 1: maximize route diversity.
    for row in ranked:
        route = normalize_route_path(row.get("route_path"))
        if not route or routes_seen[route] > 0:
            continue
        selected.append(row)
        routes_seen[route] += 1
        if len(selected) >= limit:
            return selected

    # Pass 2: fill remaining slots with the strongest repeated patterns.
    selected_fps = {r.get("fingerprint") for r in selected}
    for row in ranked:
        if row.get("fingerprint") in selected_fps:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


async def get_vendor_routing_profile(db, vendor_name: str) -> Dict[str, Any]:
    vendor_key = normalize_vendor_name(vendor_name)
    rows = await db[COLLECTION].find(
        {"active": True, "normalized_vendor": vendor_key}, {"_id": 0}
    ).to_list(5000)
    route_counts = Counter(normalize_route_path(r.get("route_path")) for r in rows)
    corrected = sum(1 for r in rows if r.get("label_source") == LABEL_SOURCE_REVIEWER_CORRECTION)
    total = len(rows)
    return {
        "vendor_name": vendor_name,
        "normalized_vendor": vendor_key,
        "example_count": total,
        "reviewer_corrected_count": corrected,
        "route_count": len([r for r in route_counts if r]),
        "routes": [
            {"route_path": route, "count": count, "pct": round(count / max(total, 1) * 100, 1)}
            for route, count in route_counts.most_common()
            if route
        ],
        "variable_routing": len([r for r in route_counts if r]) > 1,
    }


def learning_readiness(
    *,
    example_count: int,
    withheld_accuracy: Optional[float],
    route_count: int,
    minimum_examples: int = 12,
    minimum_accuracy: float = 0.95,
) -> Dict[str, Any]:
    """Gate vendor-specific auto-routing based on measured held-out accuracy."""
    reasons: List[str] = []
    if example_count < minimum_examples:
        reasons.append(f"only {example_count} labeled examples; need {minimum_examples}")
    if withheld_accuracy is None:
        reasons.append("no withheld accuracy measurement")
    elif withheld_accuracy < minimum_accuracy:
        reasons.append(
            f"withheld accuracy {withheld_accuracy:.1%} below {minimum_accuracy:.1%}"
        )
    if route_count <= 0:
        reasons.append("no routing labels")

    return {
        "ready_for_auto_route": not reasons,
        "reasons": reasons,
        "example_count": int(example_count),
        "route_count": int(route_count),
        "withheld_accuracy": withheld_accuracy,
        "minimum_accuracy": minimum_accuracy,
    }
