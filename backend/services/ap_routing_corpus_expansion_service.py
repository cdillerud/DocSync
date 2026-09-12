"""Targeted expansion of the live Accounting AP routing corpus.

The broad corpus builder is intentionally route-balanced. That prevents large
queues from dominating evaluation, but it can leave high-value/variable vendors
with too few examples to learn their legitimate workflow variations. This module
adds a second read-only sampling pass using vendor identity to admit candidate
Accounting documents, balances those already-admitted candidates across their
human Accounting placements, and adds a bounded route-neutral workflow-semantic
pass for discriminating document purposes. Human route labels are training truth,
never deterministic routing rules.

No SharePoint writes, Mongo writes, Business Central writes, or runtime changes
are performed here.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import httpx

from services.ap_routing_corpus_service import (
    _canonicalize_discovered_labels,
    discover_accounting_temp_labels,
    hydrate_accounting_label,
)
from services.ap_routing_learned_features_service import semantic_features
from services.ap_routing_learning_service import normalize_vendor_name

ProgressCallback = Callable[[int, int, Dict[str, Any]], None]

# These are the same route-neutral workflow signals that the autonomy layer
# treats as discriminating. Expansion may use them only to choose which live
# human-labeled documents to hydrate. The Accounting folder is still the label.
SEMANTIC_EXPANSION_FEATURES = frozenset(
    {
        "detention",
        "dunnage",
        "inventory",
        "reconciliation",
        "cost_variance",
        "quality_or_claim",
        "storage_accessorial",
    }
)


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _vendor_terms(vendor_name: str) -> List[str]:
    key = normalize_vendor_name(vendor_name)
    ignored = {
        "transportation",
        "logistics",
        "services",
        "service",
        "packaging",
        "beverage",
        "container",
        "international",
        "distribution",
        "distributing",
        "storage",
    }
    terms = [token for token in key.split() if len(token) >= 4 and token not in ignored]
    compact = _compact(key)
    if len(compact) >= 8:
        terms.append(compact)
    return list(dict.fromkeys(terms))


def _filename_vendor_score(file_name: str, vendor_name: str) -> float:
    filename = str(file_name or "").lower()
    compact_name = _compact(filename)
    terms = _vendor_terms(vendor_name)
    if not terms:
        return 0.0
    score = 0.0
    for term in terms:
        if len(term) >= 8 and term in compact_name:
            score += 4.0
        elif re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", filename):
            score += 2.0
        elif term in compact_name:
            score += 1.0
    return score


def _filename_workflow_semantics(file_name: str) -> Set[str]:
    """Return route-neutral discriminating semantics visible in a filename."""
    return set(
        semantic_features({"file_name": str(file_name or "")})
    ).intersection(SEMANTIC_EXPANSION_FEATURES)


def _target_vendors(
    examples: List[Dict[str, Any]],
    *,
    max_vendors: int,
) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for example in examples:
        vendor_name = str(example.get("vendor_name") or "").strip()
        key = normalize_vendor_name(vendor_name)
        if not key:
            continue
        row = rows.setdefault(
            key,
            {
                "normalized_vendor": key,
                "vendor_name": vendor_name,
                "count": 0,
                "routes": set(),
            },
        )
        row["count"] += 1
        route = str(example.get("route_path") or "").strip()
        if route:
            row["routes"].add(route)

    ranked = []
    for row in rows.values():
        route_count = len(row["routes"])
        # Prioritize variable vendors first, then vendors already showing enough
        # activity to benefit from more labels. One-off sparse vendors are left
        # to the cross-vendor semantic learner until more Accounting examples
        # naturally accumulate.
        if route_count < 2 and row["count"] < 3:
            continue
        ranked.append(
            {
                "normalized_vendor": row["normalized_vendor"],
                "vendor_name": row["vendor_name"],
                "existing_count": row["count"],
                "route_count": route_count,
                "routes": sorted(row["routes"]),
            }
        )
    ranked.sort(key=lambda row: (-row["route_count"], -row["existing_count"], row["normalized_vendor"]))
    return ranked[: max(1, int(max_vendors))]


def _round_robin_vendor_routes(
    candidates: Dict[str, Dict[str, List[Dict[str, Any]]]],
    targets: List[Dict[str, Any]],
    *,
    desired_total_per_vendor: int,
    existing_counts: Dict[str, int],
    max_additional: int,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Select vendor-admitted labels while rotating across human route buckets.

    Candidate admission has already happened using filename/vendor evidence. The
    live Accounting placement is allowed here only to keep TRAIN representative;
    it is never converted into a routing rule. The cursor must advance after each
    pick so a large route cannot starve smaller legitimate workflows.
    """
    selected: List[Tuple[str, Dict[str, Any]]] = []
    target_map = {row["normalized_vendor"]: row for row in targets}
    per_vendor_added = Counter()
    route_indices: Dict[Tuple[str, str], int] = defaultdict(int)
    route_cursors = Counter()
    route_orders: Dict[str, List[str]] = {
        vendor_key: sorted(candidates.get(vendor_key, {}))
        for vendor_key in target_map
    }

    while len(selected) < max_additional:
        progressed = False
        for vendor_key in target_map:
            if existing_counts.get(vendor_key, 0) + per_vendor_added[vendor_key] >= desired_total_per_vendor:
                continue
            routes = route_orders.get(vendor_key) or []
            if not routes:
                continue

            start = route_cursors[vendor_key] % len(routes)
            chosen_position: Optional[int] = None
            for offset in range(len(routes)):
                position = (start + offset) % len(routes)
                route = routes[position]
                rows = candidates[vendor_key][route]
                idx_key = (vendor_key, route)
                idx = route_indices[idx_key]
                if idx >= len(rows):
                    continue
                selected.append((vendor_key, rows[idx]))
                route_indices[idx_key] += 1
                per_vendor_added[vendor_key] += 1
                chosen_position = position
                progressed = True
                break

            if chosen_position is not None:
                route_cursors[vendor_key] = (chosen_position + 1) % len(routes)
            if len(selected) >= max_additional:
                break
        if not progressed:
            break
    return selected


def _round_robin_semantic_workflows(
    labels: List[Dict[str, Any]],
    *,
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    max_additional: int,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, int]]:
    """Select live documents by filename workflow semantics without using routes.

    `route_path` is deliberately ignored for candidate membership, ranking, and
    round-robin selection. It remains attached only because hydration later uses
    the live Accounting placement as supervised truth.
    """
    if max_additional <= 0:
        return [], {}

    by_feature: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for label in labels:
        item_id = str(label.get("item_id") or "")
        if not item_id:
            continue
        if item_id in excluded_source_item_ids or item_id in already_selected_source_item_ids:
            continue
        for feature in sorted(_filename_workflow_semantics(label.get("file_name") or "")):
            by_feature[feature].append(label)

    for rows in by_feature.values():
        rows.sort(
            key=lambda row: (
                str(row.get("modified_at") or ""),
                str(row.get("file_name") or ""),
                str(row.get("item_id") or ""),
            ),
            reverse=True,
        )

    candidate_counts = {feature: len(rows) for feature, rows in sorted(by_feature.items())}
    selected: List[Tuple[str, Dict[str, Any]]] = []
    seen = set(already_selected_source_item_ids)
    indices = Counter()
    features = sorted(by_feature)

    while len(selected) < max_additional:
        progressed = False
        for feature in features:
            rows = by_feature[feature]
            idx = indices[feature]
            while idx < len(rows) and str(rows[idx].get("item_id") or "") in seen:
                idx += 1
            indices[feature] = idx
            if idx >= len(rows):
                continue
            row = rows[idx]
            indices[feature] += 1
            item_id = str(row.get("item_id") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            selected.append((f"semantic:{feature}", row))
            progressed = True
            if len(selected) >= max_additional:
                break
        if not progressed:
            break

    return selected, candidate_counts


def _emit_progress(
    callback: Optional[ProgressCallback],
    completed: int,
    total: int,
    row: Dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback(completed, total, row)
    except Exception:
        # Progress telemetry must never change routing evaluation semantics.
        return


async def expand_high_value_vendor_corpus(
    base_examples: List[Dict[str, Any]],
    *,
    routing_contract: Dict[str, Any],
    excluded_source_item_ids: Optional[Set[str]] = None,
    discovery_max_files: int = 50000,
    max_vendors: int = 10,
    desired_total_per_vendor: int = 30,
    max_additional: int = 180,
    concurrency: int = 2,
    retry_count: int = 3,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Add more live labels using bounded vendor/workflow selection.

    Vendor candidate admission uses vendor identity in filenames only. After a
    candidate is admitted, its live human Accounting placement may be used only
    to balance TRAIN sampling across that vendor's observed workflows. The second
    pass uses discriminating workflow semantics visible in filenames only. No
    selector turns a human route label into a rule for a new document.

    ``base_examples`` alone controls target-vendor ranking and existing vendor
    counts. ``excluded_source_item_ids`` is a route-neutral identity exclusion
    boundary: those source documents may not be selected or hydrated, but their
    labels never influence target ranking. This keeps held-out evidence isolated
    while still preventing any base document from re-entering TRAIN via expansion.

    `progress_callback`, when supplied, receives each completion as
    `(completed, total, result_row)`. It is telemetry only; callback failures are
    deliberately ignored so observability cannot affect evaluation behavior.
    """
    explicit_excluded_ids: Set[str] = {
        str(item_id)
        for item_id in (excluded_source_item_ids or set())
        if str(item_id or "").strip()
    }
    targets = _target_vendors(base_examples, max_vendors=max_vendors)

    discovered = await discover_accounting_temp_labels(max_files=discovery_max_files)
    canonical = _canonicalize_discovered_labels(discovered.get("files") or [], routing_contract)
    labels = canonical.get("labels") or []
    existing_ids: Set[str] = {
        str(example.get("source_item_id"))
        for example in base_examples
        if example.get("source_item_id")
    }
    existing_ids.update(explicit_excluded_ids)
    existing_counts = Counter(
        normalize_vendor_name(example.get("vendor_name"))
        for example in base_examples
        if normalize_vendor_name(example.get("vendor_name"))
    )

    candidates: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    target_names = {row["normalized_vendor"]: row["vendor_name"] for row in targets}

    for label in labels:
        if str(label.get("item_id") or "") in existing_ids:
            continue
        file_name = str(label.get("file_name") or "")
        scored = []
        for vendor_key, vendor_name in target_names.items():
            score = _filename_vendor_score(file_name, vendor_name)
            if score > 0:
                scored.append((score, vendor_key))
        if not scored:
            continue
        scored.sort(reverse=True)
        score, vendor_key = scored[0]
        if score < 1.5:
            continue
        candidates[vendor_key][str(label.get("route_path") or "")].append(label)

    for vendor_routes in candidates.values():
        for rows in vendor_routes.values():
            rows.sort(key=lambda row: (str(row.get("modified_at") or ""), str(row.get("file_name") or "")), reverse=True)

    selected_pairs = _round_robin_vendor_routes(
        candidates,
        targets,
        desired_total_per_vendor=max(1, int(desired_total_per_vendor)),
        existing_counts=existing_counts,
        max_additional=max(0, int(max_additional)),
    )

    already_selected_ids = {
        str(label.get("item_id") or "")
        for _, label in selected_pairs
        if str(label.get("item_id") or "")
    }
    semantic_pairs, semantic_candidate_counts = _round_robin_semantic_workflows(
        labels,
        excluded_source_item_ids=existing_ids,
        already_selected_source_item_ids=already_selected_ids,
        max_additional=max(0, int(max_additional) - len(selected_pairs)),
    )
    selected_pairs.extend(semantic_pairs)

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def hydrate(selection_key: str, label: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            last_error: Optional[Exception] = None
            for attempt in range(1, max(1, int(retry_count)) + 1):
                try:
                    example = await hydrate_accounting_label(
                        label,
                        routing_contract=routing_contract,
                    )
                    return {
                        "ok": True,
                        "selected_vendor": selection_key,
                        "example": example,
                        "attempt": attempt,
                    }
                except (httpx.TimeoutException, httpx.NetworkError, TimeoutError) as exc:
                    last_error = exc
                    if attempt < max(1, int(retry_count)):
                        await asyncio.sleep(min(4.0, 0.75 * (2 ** (attempt - 1))))
                        continue
                    break
                except Exception as exc:
                    last_error = exc
                    break
            return {
                "ok": False,
                "selected_vendor": selection_key,
                "file_name": label.get("file_name"),
                "route_path": label.get("route_path"),
                "error": f"{type(last_error).__name__}:{last_error}"[:500] if last_error else "unknown",
            }

    tasks = [
        asyncio.create_task(hydrate(selection_key, label))
        for selection_key, label in selected_pairs
    ]
    results: List[Dict[str, Any]] = []
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        row = await task
        results.append(row)
        completed += 1
        _emit_progress(progress_callback, completed, total, row)

    examples = [row["example"] for row in results if row.get("ok")]
    failures = [row for row in results if not row.get("ok")]

    by_vendor = Counter(
        normalize_vendor_name(example.get("vendor_name")) or "unknown"
        for example in examples
    )
    by_route = Counter(
        str(example.get("route_path") or "") or "unknown"
        for example in examples
    )
    return {
        "target_vendors": targets,
        "candidate_vendor_counts": {
            vendor: sum(len(rows) for rows in route_map.values())
            for vendor, route_map in candidates.items()
        },
        "semantic_candidate_counts": semantic_candidate_counts,
        "semantic_selected_count": len(semantic_pairs),
        "selected_count": len(selected_pairs),
        "hydrated_count": len(examples),
        "hydrated_by_vendor": dict(by_vendor),
        "hydrated_by_route": dict(by_route),
        "failure_count": len(failures),
        "excluded_source_item_id_count": len(explicit_excluded_ids),
        "examples": examples,
        "failures": failures[:100],
    }
