"""TRAIN-only documented-business-context expansion for V117 evaluation.

This pass fills high-specificity business-context authority deficits that are
visible in TRAIN. It never receives HOLDOUT examples, never derives a route from
document facts, and never lowers authority thresholds. Live Accounting folder
placement remains the human label. SharePoint/BC use is read-only.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import httpx

from services.ap_routing_business_context_service import (
    authority_business_signature,
    business_context_signal_families,
)
from services.ap_routing_corpus_service import (
    _canonicalize_discovered_labels,
    discover_accounting_temp_labels,
    hydrate_accounting_label,
)
from services.ap_routing_learned_features_service import semantic_features
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import is_train_human_example

ProgressCallback = Callable[[int, int, Dict[str, Any]], None]
DNP = "DO NOT PAY"

_KIND_WEIGHT = {
    "same_vendor_document_type_business_context": 6,
    "cross_vendor_document_type_business_context": 4,
}


def _vendor(row: Dict[str, Any]) -> str:
    fields = row.get("extracted_fields") or {}
    return normalize_vendor_name(
        row.get("vendor_name")
        or row.get("normalized_vendor")
        or row.get("vendor_canonical")
        or fields.get("vendor")
        or fields.get("vendor_name")
        or ""
    )


def _doc_type(row: Dict[str, Any]) -> str:
    fields = row.get("extracted_fields") or {}
    return str(
        row.get("document_type")
        or row.get("suggested_job_type")
        or fields.get("document_type")
        or ""
    ).strip().lower()


def _route(row: Dict[str, Any]) -> str:
    return normalize_route_path(row.get("route_path") or row.get("final_human_route"))


def _source_id(row: Dict[str, Any]) -> str:
    return str(row.get("source_item_id") or row.get("item_id") or "").strip()


def _is_dynamic_child(route: str, contract: Dict[str, Any]) -> bool:
    normalized = normalize_route_path(route)
    for spec in contract.get("dynamic_routes") or []:
        prefix = normalize_route_path(spec.get("prefix"))
        if prefix and normalized.startswith(prefix + "/"):
            return True
    return False


def _manual_only_routes(contract: Dict[str, Any]) -> Set[str]:
    return {
        normalize_route_path(route)
        for route in (contract.get("manual_only_routes") or [])
        if normalize_route_path(route)
    }


def _additional_needed(
    support: int,
    contradictions: int,
    *,
    minimum_support: int,
    minimum_purity: float,
) -> Optional[int]:
    support = max(0, int(support))
    contradictions = max(0, int(contradictions))
    minimum_support = max(1, int(minimum_support))
    minimum_purity = float(minimum_purity)
    if minimum_purity >= 1.0:
        if contradictions:
            return None
        required_for_purity = support
    else:
        required_for_purity = max(
            support,
            math.ceil((minimum_purity * contradictions) / max(1e-9, 1.0 - minimum_purity)),
        )
    return max(0, max(minimum_support, required_for_purity) - support)


def _unique_leading_route(rows: Sequence[Dict[str, Any]]) -> Tuple[str, Counter[str]]:
    counts = Counter(route for row in rows if (route := _route(row)))
    if not counts:
        return "", counts
    ordered = counts.most_common()
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return "", counts
    return ordered[0][0], counts


def _add_deficit(
    deficits: List[Dict[str, Any]],
    *,
    kind: str,
    rows: Sequence[Dict[str, Any]],
    route: str,
    signature: Set[str],
    minimum_support: int,
    minimum_purity: float,
    vendor: str = "",
    document_type: str = "",
) -> None:
    if not rows or not route or not signature:
        return
    support = sum(1 for row in rows if _route(row) == route)
    contradictions = len(rows) - support
    needed = _additional_needed(
        support,
        contradictions,
        minimum_support=minimum_support,
        minimum_purity=minimum_purity,
    )
    if needed is None or needed <= 0:
        return
    deficits.append(
        {
            "kind": kind,
            "route_path": route,
            "vendor": vendor,
            "document_type": document_type,
            "business_signature": sorted(signature),
            "business_signal_families": sorted(business_context_signal_families(signature)),
            "required_semantics": ["explicit_stop_pay"] if route == DNP else [],
            "support_count": support,
            "contradiction_count": contradictions,
            "matched_human_count": len(rows),
            "minimum_support": int(minimum_support),
            "minimum_purity": float(minimum_purity),
            "additional_support_needed": int(needed),
        }
    )


def build_train_business_context_deficits(
    train_examples: Sequence[Dict[str, Any]],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build business-context support deficits using TRAIN human labels only."""
    contract = routing_contract or {}
    manual_only = _manual_only_routes(contract)
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    deficits: List[Dict[str, Any]] = []

    same_vendor_groups: Dict[Tuple[str, str, Tuple[str, ...]], List[Dict[str, Any]]] = defaultdict(list)
    cross_vendor_groups: Dict[Tuple[str, Tuple[str, ...]], List[Dict[str, Any]]] = defaultdict(list)

    for row in eligible:
        vendor = _vendor(row)
        doc_type = _doc_type(row)
        signature = tuple(sorted(authority_business_signature(row)))
        if not doc_type or not signature:
            continue
        if vendor:
            same_vendor_groups[(vendor, doc_type, signature)].append(row)
        if len(business_context_signal_families(signature)) >= 2:
            cross_vendor_groups[(doc_type, signature)].append(row)

    for (vendor, doc_type, signature_tuple), rows in sorted(same_vendor_groups.items()):
        leading, _ = _unique_leading_route(rows)
        if not leading or leading in manual_only:
            continue
        dynamic = _is_dynamic_child(leading, contract)
        _add_deficit(
            deficits,
            kind="same_vendor_document_type_business_context",
            rows=rows,
            route=leading,
            signature=set(signature_tuple),
            minimum_support=3,
            minimum_purity=1.0 if dynamic else 0.90,
            vendor=vendor,
            document_type=doc_type,
        )

    for (doc_type, signature_tuple), rows in sorted(cross_vendor_groups.items()):
        if len({_vendor(row) for row in rows if _vendor(row)}) < 2:
            continue
        leading, _ = _unique_leading_route(rows)
        if (
            not leading
            or leading == DNP
            or leading in manual_only
            or _is_dynamic_child(leading, contract)
        ):
            continue
        _add_deficit(
            deficits,
            kind="cross_vendor_document_type_business_context",
            rows=rows,
            route=leading,
            signature=set(signature_tuple),
            minimum_support=5,
            minimum_purity=0.95,
            document_type=doc_type,
        )

    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for deficit in deficits:
        key = (
            deficit["kind"],
            deficit["route_path"],
            deficit["vendor"],
            deficit["document_type"],
            tuple(deficit["business_signature"]),
        )
        current = unique.get(key)
        if current is None or int(deficit["additional_support_needed"]) < int(current["additional_support_needed"]):
            unique[key] = deficit

    result = list(unique.values())
    result.sort(
        key=lambda row: (
            -_KIND_WEIGHT.get(str(row["kind"]), 0),
            int(row["additional_support_needed"]),
            str(row["route_path"]),
            str(row["vendor"]),
            str(row["document_type"]),
            tuple(row["business_signature"]),
        )
    )
    return result


def _matches_deficit(example: Dict[str, Any], deficit: Dict[str, Any]) -> bool:
    if _route(example) != deficit["route_path"]:
        return False
    vendor = str(deficit.get("vendor") or "")
    if vendor and _vendor(example) != vendor:
        return False
    doc_type = str(deficit.get("document_type") or "")
    if doc_type and _doc_type(example) != doc_type:
        return False
    signature = set(deficit.get("business_signature") or [])
    if not signature.issubset(authority_business_signature(example)):
        return False
    required = set(deficit.get("required_semantics") or [])
    if required and not required.issubset(semantic_features(example)):
        return False
    return True


def select_hydrated_business_context_examples(
    hydrated_examples: Sequence[Dict[str, Any]],
    train_examples: Sequence[Dict[str, Any]],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
    initial_selected_route_counts: Optional[Dict[str, int]] = None,
    max_additional: int,
    max_additional_per_route: int,
) -> Dict[str, Any]:
    deficits = build_train_business_context_deficits(
        train_examples,
        routing_contract=routing_contract,
    )
    working = [dict(row, _remaining=int(row["additional_support_needed"])) for row in deficits]
    route_cap = max(1, int(max_additional_per_route))
    initial_counts = Counter(
        {
            normalize_route_path(route): int(count)
            for route, count in (initial_selected_route_counts or {}).items()
            if normalize_route_path(route) and int(count) > 0
        }
    )
    added_by_route: Counter[str] = Counter()
    selected: List[Dict[str, Any]] = []
    selected_reasons: Counter[str] = Counter()
    candidates = [dict(row) for row in hydrated_examples]

    while len(selected) < max(0, int(max_additional)):
        best: Optional[Tuple[Tuple[Any, ...], int, List[Dict[str, Any]]]] = None
        for idx, candidate in enumerate(candidates):
            if candidate.get("_v117_business_context_selected"):
                continue
            route = _route(candidate)
            if not route or initial_counts[route] + added_by_route[route] >= route_cap:
                continue
            matches = [
                deficit for deficit in working
                if int(deficit["_remaining"]) > 0 and _matches_deficit(candidate, deficit)
            ]
            if not matches:
                continue
            specificity = sum(_KIND_WEIGHT.get(str(row["kind"]), 0) for row in matches)
            signature_size = max(len(row.get("business_signature") or []) for row in matches)
            need = min(int(row["_remaining"]) for row in matches)
            score = (
                -specificity,
                -signature_size,
                -len(matches),
                need,
                route,
                str(candidate.get("file_name") or ""),
                _source_id(candidate),
                idx,
            )
            if best is None or score < best[0]:
                best = (score, idx, matches)
        if best is None:
            break
        _, idx, matches = best
        chosen = candidates[idx]
        chosen["_v117_business_context_selected"] = True
        selected.append(chosen)
        route = _route(chosen)
        added_by_route[route] += 1
        for deficit in matches:
            if int(deficit["_remaining"]) > 0:
                deficit["_remaining"] = int(deficit["_remaining"]) - 1
                selected_reasons[str(deficit["kind"])] += 1

    remaining = [
        {
            **{key: value for key, value in row.items() if not key.startswith("_")},
            "additional_support_remaining": int(row["_remaining"]),
        }
        for row in working
        if int(row["_remaining"]) > 0
    ]
    return {
        "selected_examples": selected,
        "selected_count": len(selected),
        "selected_by_route": dict(sorted(added_by_route.items())),
        "selected_by_deficit_kind": dict(sorted(selected_reasons.items())),
        "business_context_deficit_count_before": len(deficits),
        "business_context_deficit_count_remaining": len(remaining),
        "business_context_deficits_before": deficits,
        "business_context_deficits_remaining": remaining,
        "initial_expansion_route_counts": dict(sorted(initial_counts.items())),
    }


def _vendor_filename_terms(vendor: str) -> Set[str]:
    ignored = {
        "inc", "llc", "corp", "corporation", "company", "co", "ltd",
        "packaging", "logistics", "transportation", "services", "service",
        "international", "distribution", "storage",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_vendor_name(vendor))
        if len(token) >= 4 and token not in ignored
    }


def _candidate_prefilter_score(label: Dict[str, Any], deficits: Sequence[Dict[str, Any]]) -> int:
    route = normalize_route_path(label.get("route_path"))
    if not route:
        return -1
    pseudo = {"file_name": str(label.get("file_name") or "")}
    pseudo_signature = authority_business_signature(pseudo)
    lower = str(label.get("file_name") or "").lower()
    score = 0
    for deficit in deficits:
        if route != deficit["route_path"]:
            continue
        local = 1
        vendor = str(deficit.get("vendor") or "")
        if vendor:
            terms = _vendor_filename_terms(vendor)
            if terms and any(term in lower for term in terms):
                local += 5
        signature = set(deficit.get("business_signature") or [])
        overlap = signature.intersection(pseudo_signature)
        local += min(8, 3 * len(overlap))
        score = max(score, local)
    return score


def _round_robin_prefilter_labels(
    labels: Sequence[Dict[str, Any]],
    deficits: Sequence[Dict[str, Any]],
    *,
    excluded_source_item_ids: Set[str],
    already_selected_source_item_ids: Set[str],
    max_candidates: int,
) -> List[Dict[str, Any]]:
    target_routes = {str(row["route_path"]) for row in deficits}
    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    excluded = {str(value) for value in excluded_source_item_ids}
    already = {str(value) for value in already_selected_source_item_ids}
    for source in labels:
        row = dict(source)
        item_id = str(row.get("item_id") or "")
        route = normalize_route_path(row.get("route_path"))
        if not item_id or item_id in excluded or item_id in already or route not in target_routes:
            continue
        score = _candidate_prefilter_score(row, deficits)
        if score < 0:
            continue
        row["_business_context_prefilter_score"] = score
        by_route[route].append(row)
    for rows in by_route.values():
        rows.sort(
            key=lambda row: (
                int(row.get("_business_context_prefilter_score") or 0),
                str(row.get("modified_at") or ""),
                str(row.get("file_name") or ""),
                str(row.get("item_id") or ""),
            ),
            reverse=True,
        )
    selected: List[Dict[str, Any]] = []
    indices: Counter[str] = Counter()
    routes = sorted(by_route)
    while len(selected) < max(0, int(max_candidates)):
        progressed = False
        for route in routes:
            idx = indices[route]
            rows = by_route[route]
            if idx >= len(rows):
                continue
            selected.append(rows[idx])
            indices[route] += 1
            progressed = True
            if len(selected) >= max_candidates:
                break
        if not progressed:
            break
    return selected


def _emit_progress(callback: Optional[ProgressCallback], completed: int, total: int, row: Dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(completed, total, row)
    except Exception:
        return


async def expand_train_business_context_deficits(
    train_examples: Sequence[Dict[str, Any]],
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
    deficits = build_train_business_context_deficits(train_examples, routing_contract=routing_contract)
    discovered = await discover_accounting_temp_labels(max_files=discovery_max_files)
    canonical = _canonicalize_discovered_labels(discovered.get("files") or [], routing_contract)
    labels = canonical.get("labels") or []
    candidate_limit = min(len(labels), max(0, int(max_additional)) * 4)
    candidate_labels = _round_robin_prefilter_labels(
        labels,
        deficits,
        excluded_source_item_ids=excluded_source_item_ids,
        already_selected_source_item_ids=already_selected_source_item_ids,
        max_candidates=candidate_limit,
    )

    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def hydrate(index: int, label: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            last_error: Optional[Exception] = None
            for attempt in range(1, max(1, int(retry_count)) + 1):
                try:
                    example = await hydrate_accounting_label(label, routing_contract=routing_contract)
                    return {"ok": True, "index": index, "example": example, "attempt": attempt}
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
                "index": index,
                "file_name": label.get("file_name"),
                "route_path": label.get("route_path"),
                "error": f"{type(last_error).__name__}:{last_error}"[:500] if last_error else "unknown",
            }

    tasks = [asyncio.create_task(hydrate(index, label)) for index, label in enumerate(candidate_labels)]
    results: List[Dict[str, Any]] = []
    total = len(tasks)
    completed = 0
    for task in asyncio.as_completed(tasks):
        row = await task
        results.append(row)
        completed += 1
        _emit_progress(progress_callback, completed, total, row)
    results.sort(key=lambda row: int(row.get("index") or 0))
    hydrated = [row["example"] for row in results if row.get("ok")]
    failures = [row for row in results if not row.get("ok")]

    selection = select_hydrated_business_context_examples(
        hydrated,
        train_examples,
        routing_contract=routing_contract,
        initial_selected_route_counts=initial_selected_route_counts,
        max_additional=max_additional,
        max_additional_per_route=max_additional_per_route,
    )
    examples = list(selection.pop("selected_examples"))
    base_counts = Counter(_route(row) or "unknown" for row in train_examples)
    candidate_counts = Counter(normalize_route_path(row.get("route_path")) or "unknown" for row in candidate_labels)
    final_counts = Counter(base_counts)
    final_counts.update({normalize_route_path(route): int(count) for route, count in (initial_selected_route_counts or {}).items() if normalize_route_path(route)})
    final_counts.update(_route(row) or "unknown" for row in examples)

    return {
        **selection,
        "base_train_route_counts": dict(sorted(base_counts.items())),
        "candidate_route_counts": dict(sorted(candidate_counts.items())),
        "train_route_counts_after_selection": dict(sorted(final_counts.items())),
        "prefiltered_candidate_count": len(candidate_labels),
        "hydrated_candidate_count": len(hydrated),
        "hydrated_count": len(examples),
        "failure_count": len(failures),
        "excluded_source_item_id_count": len(excluded_source_item_ids),
        "already_selected_source_item_id_count": len(already_selected_source_item_ids),
        "examples": examples,
        "failures": failures[:100],
    }
