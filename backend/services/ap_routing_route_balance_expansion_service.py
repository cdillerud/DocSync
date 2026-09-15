"""TRAIN-only route-balanced expansion for V117 AP routing evaluation.

This module is a bounded third sampling pass. Vendor and semantic expansion keep
all of their existing behavior. Only unused expansion capacity is offered here,
and only to routes already represented in the human TRAIN split.

The pass is read-only with respect to SharePoint, Business Central, Mongo, and
runtime routing. Human Accounting placement remains the label. No route is
created, proposed, authorized, or promoted by this service.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import httpx

from services.ap_routing_corpus_service import (
    _canonicalize_discovered_labels,
    discover_accounting_temp_labels,
    hydrate_accounting_label,
)
from services.ap_routing_learning_service import normalize_route_path

ProgressCallback = Callable[[int, int, Dict[str, Any]], None]


def _route_counts(rows: Sequence[Dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        if route:
            counts[route] += 1
    return counts


def select_underrepresented_train_route_labels(
    labels: Sequence[Dict[str, Any]],
    base_train_examples: Sequence[Dict[str, Any]],
    *,
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    initial_selected_route_counts: Optional[Dict[str, int]] = None,
    max_additional: int,
    max_additional_per_route: int,
) -> Dict[str, Any]:
    """Select remaining live labels from the sparsest existing TRAIN routes.

    Route membership is constrained to routes already present in
    ``base_train_examples``. That means a held-out-only route or a route seen only
    in newly discovered live data cannot become a REV4 target. Source-item
    identity exclusion is independent of route and is expected to contain the
    full frozen base corpus, including holdout identities.
    """
    budget = max(0, int(max_additional))
    route_cap = max(1, int(max_additional_per_route))
    base_counts = _route_counts(base_train_examples)
    train_routes = set(base_counts)

    excluded = {
        str(item_id)
        for item_id in excluded_source_item_ids
        if str(item_id or "").strip()
    }
    already_selected = {
        str(item_id)
        for item_id in already_selected_source_item_ids
        if str(item_id or "").strip()
    }
    initial_expansion_counts: Counter[str] = Counter(
        {
            normalize_route_path(route): int(count)
            for route, count in (initial_selected_route_counts or {}).items()
            if normalize_route_path(route) and int(count) > 0
        }
    )

    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in labels:
        row = dict(source)
        item_id = str(row.get("item_id") or "")
        route = normalize_route_path(row.get("route_path"))
        if not item_id or item_id in excluded or item_id in already_selected:
            continue
        if not route or route not in train_routes:
            continue
        by_route[route].append(row)

    for rows in by_route.values():
        rows.sort(
            key=lambda row: (
                str(row.get("modified_at") or ""),
                str(row.get("file_name") or ""),
                str(row.get("item_id") or ""),
            ),
            reverse=True,
        )

    candidate_counts = {route: len(rows) for route, rows in sorted(by_route.items())}
    current_train_counts: Counter[str] = Counter(base_counts)
    current_train_counts.update(initial_expansion_counts)
    route_added_counts: Counter[str] = Counter()
    indices: Counter[str] = Counter()
    selected: List[Tuple[str, Dict[str, Any]]] = []

    while len(selected) < budget:
        available_routes = []
        for route in sorted(train_routes):
            if indices[route] >= len(by_route.get(route, [])):
                continue
            if initial_expansion_counts[route] + route_added_counts[route] >= route_cap:
                continue
            available_routes.append(route)
        if not available_routes:
            break

        route = min(
            available_routes,
            key=lambda value: (
                current_train_counts[value],
                base_counts[value],
                value,
            ),
        )
        row = by_route[route][indices[route]]
        indices[route] += 1
        route_added_counts[route] += 1
        current_train_counts[route] += 1
        selected.append((f"route_balance:{route}", row))

    return {
        "selected_pairs": selected,
        "base_train_route_counts": dict(sorted(base_counts.items())),
        "candidate_route_counts": candidate_counts,
        "initial_expansion_route_counts": dict(sorted(initial_expansion_counts.items())),
        "selected_by_route": dict(sorted(route_added_counts.items())),
        "train_route_counts_after_selection": dict(sorted(current_train_counts.items())),
        "selected_count": len(selected),
        "max_additional": budget,
        "max_additional_per_route": route_cap,
    }


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
        return


async def expand_underrepresented_train_routes(
    base_train_examples: Sequence[Dict[str, Any]],
    *,
    routing_contract: Dict[str, Any],
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    initial_selected_route_counts: Optional[Dict[str, int]] = None,
    discovery_max_files: int = 50000,
    max_additional: int = 0,
    max_additional_per_route: int = 30,
    concurrency: int = 4,
    retry_count: int = 3,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Hydrate a bounded third pass from underrepresented TRAIN routes."""
    discovered = await discover_accounting_temp_labels(max_files=discovery_max_files)
    canonical = _canonicalize_discovered_labels(
        discovered.get("files") or [], routing_contract
    )
    selection = select_underrepresented_train_route_labels(
        canonical.get("labels") or [],
        base_train_examples,
        excluded_source_item_ids=excluded_source_item_ids,
        already_selected_source_item_ids=already_selected_source_item_ids,
        initial_selected_route_counts=initial_selected_route_counts,
        max_additional=max_additional,
        max_additional_per_route=max_additional_per_route,
    )
    selected_pairs = list(selection["selected_pairs"])
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
                        "selection_key": selection_key,
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
                "selection_key": selection_key,
                "file_name": label.get("file_name"),
                "route_path": label.get("route_path"),
                "error": (
                    f"{type(last_error).__name__}:{last_error}"[:500]
                    if last_error
                    else "unknown"
                ),
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
    hydrated_by_route = Counter(
        normalize_route_path(row.get("route_path")) or "unknown"
        for row in examples
    )

    result = {
        key: value
        for key, value in selection.items()
        if key != "selected_pairs"
    }
    result.update(
        {
            "hydrated_count": len(examples),
            "hydrated_by_route": dict(sorted(hydrated_by_route.items())),
            "failure_count": len(failures),
            "excluded_source_item_id_count": len(excluded_source_item_ids),
            "already_selected_source_item_id_count": len(already_selected_source_item_ids),
            "examples": examples,
            "failures": failures[:100],
        }
    )
    return result
