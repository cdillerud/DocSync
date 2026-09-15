"""TRAIN-only authority-deficit expansion for V117 AP routing evaluation.

This bounded expansion pass asks one question only: which additional human
Accounting examples would close authority-support deficits that are already
visible in TRAIN? It never inspects HOLDOUT evidence, never invents a route, and
never lowers an authority threshold. Live Accounting placement remains the label.

The pass is read-only with respect to SharePoint, Business Central, Mongo, and
runtime routing. Candidate hydration may enrich route-neutral vendor/document
 type/reference/semantic evidence, but only TRAIN-derived deficit definitions can
admit an example.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx

from services.ap_routing_corpus_service import (
    _canonicalize_discovered_labels,
    discover_accounting_temp_labels,
    hydrate_accounting_label,
)
from services.ap_routing_learned_features_service import reference_family, semantic_features
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import is_train_human_example

ProgressCallback = Callable[[int, int, Dict[str, Any]], None]

DNP = "DO NOT PAY"
STRUCTURAL_REFERENCE_FAMILIES = frozenset(
    {"w_reference", "wtr_reference", "wa_reference", "numeric_reference", "alpha_reference"}
)
DISCRIMINATING_SEMANTICS = frozenset(
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
_KIND_WEIGHT = {
    "same_vendor_document_type_reference_family": 5,
    "same_vendor_document_type_semantics": 4,
    "same_vendor_document_type": 3,
    "cross_vendor_document_type_reference_semantics": 2,
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
    """Return added same-route labels needed to satisfy support + purity."""
    support = max(0, int(support))
    contradictions = max(0, int(contradictions))
    minimum_support = max(1, int(minimum_support))
    minimum_purity = float(minimum_purity)

    if minimum_purity >= 1.0:
        if contradictions:
            return None
        purity_support = support
    elif minimum_purity <= 0.0:
        purity_support = support
    else:
        required_support_for_purity = math.ceil(
            (minimum_purity * contradictions) / (1.0 - minimum_purity)
        )
        purity_support = max(support, required_support_for_purity)

    target_support = max(minimum_support, purity_support)
    return max(0, target_support - support)


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
    minimum_support: int,
    minimum_purity: float,
    vendor: str = "",
    document_type: str = "",
    reference: str = "",
    semantics: Iterable[str] = (),
    required_semantics: Iterable[str] = (),
) -> None:
    if not rows or not route:
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
            "reference_family": reference,
            "semantic_signature": sorted(set(semantics)),
            "required_semantics": sorted(set(required_semantics)),
            "support_count": support,
            "contradiction_count": contradictions,
            "matched_human_count": len(rows),
            "minimum_support": int(minimum_support),
            "minimum_purity": float(minimum_purity),
            "additional_support_needed": int(needed),
        }
    )


def build_train_authority_deficits(
    train_examples: Sequence[Dict[str, Any]],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Describe authority-support deficits from TRAIN only.

    Only the unique leading human route for a TRAIN slice can become a target.
    Tied/ambiguous slices are skipped rather than broken by sampling. Thresholds
    mirror the existing V117 corroboration authority service.
    """
    contract = routing_contract or {}
    manual_only = _manual_only_routes(contract)
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    deficits: List[Dict[str, Any]] = []

    by_vendor_type: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        vendor = _vendor(row)
        doc_type = _doc_type(row)
        if vendor and doc_type:
            by_vendor_type[(vendor, doc_type)].append(row)

    for (vendor, doc_type), rows in sorted(by_vendor_type.items()):
        leading, _ = _unique_leading_route(rows)
        if not leading or leading in manual_only:
            continue
        dynamic = _is_dynamic_child(leading, contract)
        required_semantics = {"explicit_stop_pay"} if leading == DNP else set()
        _add_deficit(
            deficits,
            kind="same_vendor_document_type",
            rows=rows,
            route=leading,
            minimum_support=3 if dynamic else 5,
            minimum_purity=1.0 if dynamic else 0.90,
            vendor=vendor,
            document_type=doc_type,
            required_semantics=required_semantics,
        )

        by_ref: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            ref = reference_family(row)
            if ref in STRUCTURAL_REFERENCE_FAMILIES:
                by_ref[ref].append(row)
        for ref, ref_rows in sorted(by_ref.items()):
            ref_leading, _ = _unique_leading_route(ref_rows)
            if ref_leading != leading:
                continue
            _add_deficit(
                deficits,
                kind="same_vendor_document_type_reference_family",
                rows=ref_rows,
                route=leading,
                minimum_support=3 if dynamic else 5,
                minimum_purity=1.0 if dynamic else 0.85,
                vendor=vendor,
                document_type=doc_type,
                reference=ref,
                required_semantics=required_semantics,
            )

        signatures = {
            frozenset(semantic_features(row).intersection(DISCRIMINATING_SEMANTICS))
            for row in rows
        }
        signatures.discard(frozenset())
        for signature in sorted(signatures, key=lambda values: (len(values), sorted(values))):
            semantic_rows = [
                row for row in rows if signature.issubset(semantic_features(row))
            ]
            semantic_leading, _ = _unique_leading_route(semantic_rows)
            if semantic_leading != leading:
                continue
            _add_deficit(
                deficits,
                kind="same_vendor_document_type_semantics",
                rows=semantic_rows,
                route=leading,
                minimum_support=3,
                minimum_purity=0.90,
                vendor=vendor,
                document_type=doc_type,
                semantics=signature,
                required_semantics=required_semantics,
            )

    by_doc_ref: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        doc_type = _doc_type(row)
        ref = reference_family(row)
        if doc_type and ref in STRUCTURAL_REFERENCE_FAMILIES:
            by_doc_ref[(doc_type, ref)].append(row)

    for (doc_type, ref), rows in sorted(by_doc_ref.items()):
        signatures = {
            frozenset(semantic_features(row).intersection(DISCRIMINATING_SEMANTICS))
            for row in rows
        }
        signatures.discard(frozenset())
        for signature in sorted(signatures, key=lambda values: (len(values), sorted(values))):
            semantic_rows = [
                row for row in rows if signature.issubset(semantic_features(row))
            ]
            leading, _ = _unique_leading_route(semantic_rows)
            if (
                not leading
                or leading == DNP
                or leading in manual_only
                or _is_dynamic_child(leading, contract)
            ):
                continue
            _add_deficit(
                deficits,
                kind="cross_vendor_document_type_reference_semantics",
                rows=semantic_rows,
                route=leading,
                minimum_support=8,
                minimum_purity=0.95,
                document_type=doc_type,
                reference=ref,
                semantics=signature,
            )

    deficits.sort(
        key=lambda row: (
            -_KIND_WEIGHT.get(str(row["kind"]), 0),
            int(row["additional_support_needed"]),
            str(row["route_path"]),
            str(row["vendor"]),
            str(row["document_type"]),
            str(row["reference_family"]),
            tuple(row["semantic_signature"]),
        )
    )
    return deficits


def _matches_deficit(example: Dict[str, Any], deficit: Dict[str, Any]) -> bool:
    if _route(example) != deficit["route_path"]:
        return False
    vendor = str(deficit.get("vendor") or "")
    if vendor and _vendor(example) != vendor:
        return False
    doc_type = str(deficit.get("document_type") or "")
    if doc_type and _doc_type(example) != doc_type:
        return False
    ref = str(deficit.get("reference_family") or "")
    if ref and reference_family(example) != ref:
        return False
    features = semantic_features(example)
    if not set(deficit.get("semantic_signature") or []).issubset(features):
        return False
    if not set(deficit.get("required_semantics") or []).issubset(features):
        return False
    return True


def select_hydrated_authority_deficit_examples(
    hydrated_examples: Sequence[Dict[str, Any]],
    train_examples: Sequence[Dict[str, Any]],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
    initial_selected_route_counts: Optional[Dict[str, int]] = None,
    max_additional: int,
    max_additional_per_route: int,
) -> Dict[str, Any]:
    """Admit hydrated candidates only while they close TRAIN-derived deficits."""
    deficits = build_train_authority_deficits(
        train_examples,
        routing_contract=routing_contract,
    )
    working = [dict(row) for row in deficits]
    for index, row in enumerate(working):
        row["_index"] = index
        row["_remaining"] = int(row["additional_support_needed"])

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
    candidate_rows = [dict(row) for row in hydrated_examples]

    while len(selected) < max(0, int(max_additional)):
        best: Optional[Tuple[Tuple[Any, ...], int, List[Dict[str, Any]]]] = None
        for idx, candidate in enumerate(candidate_rows):
            if candidate.get("_v117_authority_deficit_selected"):
                continue
            route = _route(candidate)
            if not route:
                continue
            if initial_counts[route] + added_by_route[route] >= route_cap:
                continue
            matches = [
                deficit
                for deficit in working
                if int(deficit["_remaining"]) > 0 and _matches_deficit(candidate, deficit)
            ]
            if not matches:
                continue
            specificity = sum(_KIND_WEIGHT.get(str(row["kind"]), 0) for row in matches)
            benefit = len(matches)
            need = min(int(row["_remaining"]) for row in matches)
            source_id = _source_id(candidate)
            file_name = str(candidate.get("file_name") or "")
            score = (-specificity, -benefit, need, route, file_name, source_id, idx)
            if best is None or score < best[0]:
                best = (score, idx, matches)

        if best is None:
            break

        _, idx, matches = best
        chosen = candidate_rows[idx]
        chosen["_v117_authority_deficit_selected"] = True
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
        "authority_deficit_count_before": len(deficits),
        "authority_deficit_count_remaining": len(remaining),
        "authority_deficits_before": deficits,
        "authority_deficits_remaining": remaining,
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
    file_name = str(label.get("file_name") or "")
    lower = file_name.lower()
    pseudo = {"file_name": file_name}
    ref = reference_family(pseudo)
    features = semantic_features(pseudo)

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
        target_ref = str(deficit.get("reference_family") or "")
        if target_ref and target_ref == ref:
            local += 4
        signature = set(deficit.get("semantic_signature") or [])
        if signature and signature.issubset(features):
            local += 5
        required = set(deficit.get("required_semantics") or [])
        if required and required.issubset(features):
            local += 5
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
        if not item_id or item_id in excluded or item_id in already:
            continue
        if route not in target_routes:
            continue
        score = _candidate_prefilter_score(row, deficits)
        if score < 0:
            continue
        row["_authority_prefilter_score"] = score
        by_route[route].append(row)

    for rows in by_route.values():
        rows.sort(
            key=lambda row: (
                int(row.get("_authority_prefilter_score") or 0),
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


async def expand_train_authority_deficits(
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
    """Hydrate live labels and admit only examples closing TRAIN authority deficits."""
    deficits = build_train_authority_deficits(
        train_examples,
        routing_contract=routing_contract,
    )
    discovered = await discover_accounting_temp_labels(max_files=discovery_max_files)
    canonical = _canonicalize_discovered_labels(
        discovered.get("files") or [], routing_contract
    )
    labels = canonical.get("labels") or []
    candidate_limit = min(
        max(0, len(labels)),
        max(max(0, int(max_additional)), max(0, int(max_additional)) * 3),
    )
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
                    example = await hydrate_accounting_label(
                        label,
                        routing_contract=routing_contract,
                    )
                    return {
                        "ok": True,
                        "index": index,
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
                "index": index,
                "file_name": label.get("file_name"),
                "route_path": label.get("route_path"),
                "error": (
                    f"{type(last_error).__name__}:{last_error}"[:500]
                    if last_error
                    else "unknown"
                ),
            }

    tasks = [
        asyncio.create_task(hydrate(index, label))
        for index, label in enumerate(candidate_labels)
    ]
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

    selection = select_hydrated_authority_deficit_examples(
        hydrated,
        train_examples,
        routing_contract=routing_contract,
        initial_selected_route_counts=initial_selected_route_counts,
        max_additional=max_additional,
        max_additional_per_route=max_additional_per_route,
    )
    examples = list(selection.pop("selected_examples"))
    route_counts = Counter(_route(row) or "unknown" for row in train_examples)
    candidate_route_counts = Counter(
        normalize_route_path(row.get("route_path")) or "unknown"
        for row in candidate_labels
    )
    final_train_route_counts = Counter(route_counts)
    final_train_route_counts.update(
        {
            normalize_route_path(route): int(count)
            for route, count in (initial_selected_route_counts or {}).items()
            if normalize_route_path(route)
        }
    )
    final_train_route_counts.update(_route(row) or "unknown" for row in examples)

    return {
        **selection,
        "base_train_route_counts": dict(sorted(route_counts.items())),
        "candidate_route_counts": dict(sorted(candidate_route_counts.items())),
        "train_route_counts_after_selection": dict(sorted(final_train_route_counts.items())),
        "prefiltered_candidate_count": len(candidate_labels),
        "hydrated_candidate_count": len(hydrated),
        "hydrated_count": len(examples),
        "failure_count": len(failures),
        "excluded_source_item_id_count": len(excluded_source_item_ids),
        "already_selected_source_item_id_count": len(already_selected_source_item_ids),
        "examples": examples,
        "failures": failures[:100],
    }
