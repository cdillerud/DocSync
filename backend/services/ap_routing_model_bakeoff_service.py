"""TRAIN-only multi-model bakeoff for V117 AP routing.

This service compares LLM proposal quality without touching the frozen held-out
set or changing runtime routing. Every benchmark target is a human TRAIN label,
removed from its own evidence pool before retrieval/context generation. One
frozen prompt is built per target, SHA256-hashed, and sent byte-for-byte to every
model in the comparison. Model responses are then replayed through the existing
learned-autonomy + safety pipeline without another LLM call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.ap_routing_ai_primary_service import (
    _augment_prompt_with_train_context,
    _prompt_learning_example,
)
from services.ap_routing_decision_service import (
    _supervised_route_support,
    build_route_prompt,
    parse_route_prediction,
    route_is_allowed,
)
from services.ap_routing_learned_evaluation_service import _document_from_example
from services.ap_routing_learned_pipeline_service import decide_ap_route_learned
from services.ap_routing_learning_service import normalize_route_path
from services.ap_routing_relevant_learning_service import (
    build_relevant_learning_examples,
    is_train_human_example,
)
from services.ap_routing_train_context_service import build_train_learning_context

SYSTEM_MESSAGE = (
    "You make bounded Accounts Payable routing predictions from supplied evidence. "
    "Return valid JSON only. Never invent routes outside the supplied contract."
)

DEFAULT_MODEL_SPECS: Tuple[Dict[str, str], ...] = (
    {"provider": "gemini", "model": "gemini-2.5-pro", "name": "gemini-2.5-pro"},
    {"provider": "openai", "model": "gpt-5.6-sol", "name": "gpt-5.6-sol"},
    {"provider": "anthropic", "model": "claude-opus-4-6", "name": "claude-opus-4-6"},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "name": "claude-sonnet-4-6"},
)

DNP = "DO NOT PAY"


def _row_id(row: Dict[str, Any]) -> str:
    return str(
        row.get("fingerprint")
        or row.get("source_item_id")
        or row.get("document_id")
        or row.get("file_name")
        or ""
    )


def _stable_key(row: Dict[str, Any]) -> str:
    identity = _row_id(row)
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()


def _route(row: Dict[str, Any]) -> str:
    return normalize_route_path(row.get("route_path") or row.get("final_human_route"))


def _route_family(route: str) -> str:
    value = normalize_route_path(route)
    if value.startswith("Warehouse International") or value.startswith("Warehouse Not International"):
        return "warehouse"
    if value.startswith("Dropship International") or value.startswith("Dropship Not International"):
        return "dropship"
    if value == DNP:
        return "do_not_pay"
    if value.startswith("S&H Invoices"):
        return "shipping_handling"
    if value.startswith("Vendor Credit") or "Credit" in value:
        return "credit"
    return value.split("/", 1)[0] if value else ""


def parse_model_specs(value: Optional[str] = None) -> List[Dict[str, str]]:
    """Parse configurable provider/model specs without exposing credentials."""
    raw = value if value is not None else os.environ.get("V117_BAKEOFF_MODELS_JSON", "")
    if not str(raw or "").strip():
        return [dict(row) for row in DEFAULT_MODEL_SPECS]
    data = json.loads(str(raw))
    if not isinstance(data, list):
        raise ValueError("V117_BAKEOFF_MODELS_JSON must be a JSON list")
    result: List[Dict[str, str]] = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each bakeoff model spec must be an object")
        provider = str(item.get("provider") or "").strip().lower()
        model = str(item.get("model") or "").strip()
        name = str(item.get("name") or model).strip()
        if provider not in {"openai", "anthropic", "gemini"} or not model:
            raise ValueError(f"invalid bakeoff model spec: {item!r}")
        key = (provider, model)
        if key in seen:
            continue
        seen.add(key)
        result.append({"provider": provider, "model": model, "name": name})
    if not result:
        raise ValueError("no bakeoff model specs configured")
    return result


def route_balanced_sample(
    train_examples: Sequence[Dict[str, Any]],
    *,
    limit: int,
    excluded_ids: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Deterministically sample TRAIN labels with broad route coverage."""
    excluded = {str(value) for value in excluded_ids}
    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for source in train_examples:
        if not is_train_human_example(source):
            continue
        row = dict(source)
        identity = _row_id(row)
        route = _route(row)
        if not identity or identity in excluded or not route:
            continue
        by_route[route].append(row)
    for rows in by_route.values():
        rows.sort(key=lambda row: (_stable_key(row), _row_id(row)))

    selected: List[Dict[str, Any]] = []
    indexes: Counter[str] = Counter()
    routes = sorted(by_route)
    target = max(0, int(limit))
    while len(selected) < target:
        progressed = False
        for route in routes:
            idx = indexes[route]
            rows = by_route[route]
            if idx >= len(rows):
                continue
            selected.append(rows[idx])
            indexes[route] += 1
            progressed = True
            if len(selected) >= target:
                break
        if not progressed:
            break
    return selected


def build_frozen_prompt(
    *,
    target: Dict[str, Any],
    train_pool: Sequence[Dict[str, Any]],
    contract: Dict[str, Any],
    few_shot_limit: int = 8,
) -> Dict[str, Any]:
    """Build the exact current REV7 prompt for one target with its label hidden."""
    target_id = _row_id(target)
    pool = [dict(row) for row in train_pool if _row_id(row) != target_id and is_train_human_example(row)]
    document = _document_from_example(target)
    context = target.get("bc_context") or {}
    document_with_context = {**document, "bc_context": context}
    relevant = build_relevant_learning_examples(
        document_with_context,
        pool,
        limit=max(1, min(8, int(few_shot_limit))),
    )
    learning_context = build_train_learning_context(
        document_with_context,
        pool,
        contract=contract,
    )
    prompt_examples = [_prompt_learning_example(item) for item in relevant[:8]]
    support = _supervised_route_support(document, context, prompt_examples)
    prompt = build_route_prompt(
        document,
        context,
        prompt_examples,
        contract,
        supervised_support=support,
    )
    prompt = _augment_prompt_with_train_context(prompt, learning_context)
    encoded = prompt.encode("utf-8")
    return {
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(encoded).hexdigest().upper(),
        "prompt_bytes": len(encoded),
        "target_id": target_id,
        "document": document,
        "bc_context": context,
        "train_pool": pool,
        "few_shot_ids": [_row_id(row) for row in relevant],
        "few_shot_routes": [_route(row) for row in relevant],
        "learning_context_example_count": int(learning_context.get("eligible_train_example_count") or 0),
    }


def _dynamic_child_unseen(route: str, contract: Dict[str, Any], train_pool: Sequence[Dict[str, Any]]) -> bool:
    normalized = normalize_route_path(route)
    if not normalized:
        return False
    is_dynamic = False
    for spec in contract.get("dynamic_routes") or []:
        prefix = normalize_route_path(spec.get("prefix"))
        if prefix and normalized.startswith(prefix + "/"):
            is_dynamic = True
            break
    if not is_dynamic:
        return False
    observed = {_route(row) for row in train_pool}
    return normalized not in observed


async def _send_provider_model(
    *,
    provider: str,
    model: str,
    prompt: str,
    api_key: str,
) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=api_key,
        session_id=f"v117-bakeoff-{uuid.uuid4()}",
        system_message=SYSTEM_MESSAGE,
    ).with_model(provider, model)
    return await chat.send_message(UserMessage(text=prompt))


async def preflight_models(
    model_specs: Sequence[Dict[str, str]],
    *,
    api_key: Optional[str] = None,
    timeout_seconds: float = 90.0,
) -> List[Dict[str, Any]]:
    """Perform one credential/provider/model smoke call per configured model."""
    key = api_key or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    prompt = (
        'Return JSON only: {"proposed_route":"DO NOT PAY","confidence":1.0,'
        '"evidence":["preflight"],"reasoning_summary":"preflight",'
        '"bc_refs_used":[],"unresolved":[],"matched_example_ids":[]}'
    )

    async def one(spec: Dict[str, str]) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            raw = await asyncio.wait_for(
                _send_provider_model(
                    provider=spec["provider"],
                    model=spec["model"],
                    prompt=prompt,
                    api_key=key,
                ),
                timeout=timeout_seconds,
            )
            parse_route_prediction(raw, model=spec["model"])
            return {
                **dict(spec),
                "available": True,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "error": "",
            }
        except Exception as exc:
            return {
                **dict(spec),
                "available": False,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}:{exc}"[:500],
            }

    return list(await asyncio.gather(*(one(dict(spec)) for spec in model_specs)))


async def evaluate_model_on_targets(
    *,
    spec: Dict[str, str],
    targets: Sequence[Dict[str, Any]],
    train_examples: Sequence[Dict[str, Any]],
    contract: Dict[str, Any],
    api_key: Optional[str] = None,
    concurrency: int = 2,
    timeout_seconds: float = 180.0,
) -> Dict[str, Any]:
    """Evaluate one model on TRAIN targets using frozen prompts and replay safety."""
    key = api_key or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def evaluate_one(target: Dict[str, Any]) -> Dict[str, Any]:
        frozen = build_frozen_prompt(target=target, train_pool=train_examples, contract=contract)
        prompt = str(frozen["prompt"])
        prompt_sha = str(frozen["prompt_sha256"])
        started = time.perf_counter()
        try:
            async with semaphore:
                raw = await asyncio.wait_for(
                    _send_provider_model(
                        provider=spec["provider"],
                        model=spec["model"],
                        prompt=prompt,
                        api_key=key,
                    ),
                    timeout=timeout_seconds,
                )
            latency = time.perf_counter() - started
            prediction = parse_route_prediction(raw, model=spec["model"])

            async def replay_sender(rebuilt_prompt: str, requested_model: str) -> str:
                rebuilt_sha = hashlib.sha256(rebuilt_prompt.encode("utf-8")).hexdigest().upper()
                if rebuilt_sha != prompt_sha:
                    raise RuntimeError(
                        f"bakeoff prompt replay drift: expected={prompt_sha};actual={rebuilt_sha}"
                    )
                if str(requested_model) != str(spec["model"]):
                    raise RuntimeError(
                        f"bakeoff replay model drift: expected={spec['model']};actual={requested_model}"
                    )
                return raw

            final = await decide_ap_route_learned(
                document=dict(frozen["document"]),
                bc_context=dict(frozen["bc_context"]),
                contract=contract,
                train_examples=list(frozen["train_pool"]),
                performance_outcomes=[],
                relevant_limit=8,
                model=spec["model"],
                llm_send=replay_sender,
            )
            expected = _route(target)
            proposed = normalize_route_path(prediction.proposed_route)
            auto = str(final.get("decision") or "") == "auto_route"
            final_route = normalize_route_path(final.get("route_path"))
            correct = bool(proposed and proposed == expected)
            return {
                "target_id": frozen["target_id"],
                "file_name": target.get("file_name"),
                "expected_route": expected,
                "expected_family": _route_family(expected),
                "proposed_route": proposed,
                "proposed_family": _route_family(proposed),
                "proposal_correct": correct,
                "family_correct": bool(proposed and _route_family(proposed) == _route_family(expected)),
                "confidence": float(prediction.confidence),
                "unresolved": list(prediction.unresolved),
                "contract_route_allowed": route_is_allowed(proposed, contract, frozen["bc_context"]),
                "dynamic_child_unseen_in_train": _dynamic_child_unseen(proposed, contract, frozen["train_pool"]),
                "dnp_false_positive": proposed == DNP and expected != DNP,
                "overconfident_wrong": bool(not correct and float(prediction.confidence) >= 0.90),
                "prompt_sha256": prompt_sha,
                "prompt_bytes": int(frozen["prompt_bytes"]),
                "few_shot_ids": frozen["few_shot_ids"],
                "few_shot_routes": frozen["few_shot_routes"],
                "train_context_count": frozen["learning_context_example_count"],
                "latency_seconds": round(latency, 3),
                "model_error": "",
                "safe_decision": final.get("decision"),
                "safe_route": final_route,
                "safe_auto": auto,
                "safe_auto_correct": bool(auto and final_route == expected),
                "safe_wrong_auto": bool(auto and final_route != expected),
                "earned_by": final.get("earned_by"),
                "safety_blockers": list(final.get("safety_blockers") or []),
            }
        except Exception as exc:
            return {
                "target_id": frozen["target_id"],
                "file_name": target.get("file_name"),
                "expected_route": _route(target),
                "expected_family": _route_family(_route(target)),
                "proposed_route": "",
                "proposed_family": "",
                "proposal_correct": False,
                "family_correct": False,
                "confidence": 0.0,
                "unresolved": [],
                "contract_route_allowed": False,
                "dynamic_child_unseen_in_train": False,
                "dnp_false_positive": False,
                "overconfident_wrong": False,
                "prompt_sha256": prompt_sha,
                "prompt_bytes": int(frozen["prompt_bytes"]),
                "few_shot_ids": frozen["few_shot_ids"],
                "few_shot_routes": frozen["few_shot_routes"],
                "train_context_count": frozen["learning_context_example_count"],
                "latency_seconds": round(time.perf_counter() - started, 3),
                "model_error": f"{type(exc).__name__}:{exc}"[:1000],
                "safe_decision": "model_error",
                "safe_route": "",
                "safe_auto": False,
                "safe_auto_correct": False,
                "safe_wrong_auto": False,
                "earned_by": "",
                "safety_blockers": [],
            }

    rows = list(await asyncio.gather(*(evaluate_one(dict(target)) for target in targets)))
    return {"spec": dict(spec), "rows": rows, "summary": summarize_model_rows(rows)}


def summarize_model_rows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    proposals = [row for row in rows if row.get("proposed_route")]
    correct = [row for row in proposals if row.get("proposal_correct")]
    family_correct = [row for row in proposals if row.get("family_correct")]
    auto = [row for row in rows if row.get("safe_auto")]
    auto_correct = [row for row in auto if row.get("safe_auto_correct")]
    wrong_auto = [row for row in auto if row.get("safe_wrong_auto")]
    latencies = [float(row.get("latency_seconds") or 0.0) for row in rows if not row.get("model_error")]
    return {
        "target_count": total,
        "proposal_count": len(proposals),
        "proposal_accuracy": round(len(correct) / len(proposals), 4) if proposals else None,
        "family_accuracy": round(len(family_correct) / len(proposals), 4) if proposals else None,
        "contract_invalid_count": sum(1 for row in proposals if not row.get("contract_route_allowed")),
        "overconfident_wrong_count": sum(1 for row in rows if row.get("overconfident_wrong")),
        "dnp_false_positive_count": sum(1 for row in rows if row.get("dnp_false_positive")),
        "unseen_dynamic_child_count": sum(1 for row in rows if row.get("dynamic_child_unseen_in_train")),
        "unresolved_response_count": sum(1 for row in rows if row.get("unresolved")),
        "model_error_count": sum(1 for row in rows if row.get("model_error")),
        "safe_auto_count": len(auto),
        "safe_coverage": round(len(auto) / total, 4) if total else None,
        "safe_auto_accuracy": round(len(auto_correct) / len(auto), 4) if auto else None,
        "safe_wrong_auto_count": len(wrong_auto),
        "mean_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_latency_seconds": round(max(latencies), 3) if latencies else None,
    }


def model_selection_sort_key(result: Dict[str, Any]) -> Tuple[Any, ...]:
    """Order pilot models for advancement without using frozen holdout evidence."""
    summary = result.get("summary") or {}
    accuracy = summary.get("proposal_accuracy")
    family = summary.get("family_accuracy")
    return (
        -(float(accuracy) if accuracy is not None else -1.0),
        int(summary.get("overconfident_wrong_count") or 0),
        int(summary.get("contract_invalid_count") or 0),
        -(float(family) if family is not None else -1.0),
        int(summary.get("model_error_count") or 0),
        float(summary.get("mean_latency_seconds") or 999999.0),
        str((result.get("spec") or {}).get("name") or ""),
    )


async def run_two_stage_bakeoff(
    *,
    train_examples: Sequence[Dict[str, Any]],
    contract: Dict[str, Any],
    model_specs: Optional[Sequence[Dict[str, str]]] = None,
    api_key: Optional[str] = None,
    pilot_size: int = 24,
    validation_size: int = 100,
    finalists: int = 2,
    concurrency_per_model: int = 2,
) -> Dict[str, Any]:
    """Run model preflight -> pilot -> disjoint validation, all on TRAIN only."""
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    specs = [dict(row) for row in (model_specs or parse_model_specs())]
    preflight = await preflight_models(specs, api_key=api_key)
    available_keys = {
        (row["provider"], row["model"])
        for row in preflight
        if row.get("available")
    }
    available = [
        spec for spec in specs
        if (spec["provider"], spec["model"]) in available_keys
    ]
    if len(available) < 2:
        return {
            "schema_version": "v117-model-bakeoff-rev1",
            "train_only": True,
            "holdout_used": False,
            "preflight": preflight,
            "error": "fewer_than_two_models_available",
            "pilot": [],
            "validation": [],
        }

    pilot_targets = route_balanced_sample(eligible, limit=pilot_size)
    pilot_ids = {_row_id(row) for row in pilot_targets}
    validation_targets = route_balanced_sample(
        eligible,
        limit=validation_size,
        excluded_ids=pilot_ids,
    )

    pilot_results = []
    for spec in available:
        pilot_results.append(
            await evaluate_model_on_targets(
                spec=spec,
                targets=pilot_targets,
                train_examples=eligible,
                contract=contract,
                api_key=api_key,
                concurrency=concurrency_per_model,
            )
        )
    ordered = sorted(pilot_results, key=model_selection_sort_key)
    finalist_specs = [dict(row["spec"]) for row in ordered[: max(1, int(finalists))]]

    validation_results = []
    for spec in finalist_specs:
        validation_results.append(
            await evaluate_model_on_targets(
                spec=spec,
                targets=validation_targets,
                train_examples=eligible,
                contract=contract,
                api_key=api_key,
                concurrency=concurrency_per_model,
            )
        )

    prompt_hashes: Dict[str, Dict[str, str]] = {}
    for result in pilot_results + validation_results:
        name = str((result.get("spec") or {}).get("name") or "")
        for row in result.get("rows") or []:
            target_id = str(row.get("target_id") or "")
            if not target_id:
                continue
            prompt_hashes.setdefault(target_id, {})[name] = str(row.get("prompt_sha256") or "")
    prompt_mismatches = []
    for target_id, hashes in prompt_hashes.items():
        nonempty = {value for value in hashes.values() if value}
        if len(nonempty) > 1:
            prompt_mismatches.append({"target_id": target_id, "hashes": hashes})

    return {
        "schema_version": "v117-model-bakeoff-rev1",
        "train_only": True,
        "holdout_used": False,
        "eligible_train_count": len(eligible),
        "pilot_target_count": len(pilot_targets),
        "validation_target_count": len(validation_targets),
        "pilot_validation_overlap_count": len(pilot_ids.intersection({_row_id(row) for row in validation_targets})),
        "pilot_route_counts": dict(sorted(Counter(_route(row) for row in pilot_targets).items())),
        "validation_route_counts": dict(sorted(Counter(_route(row) for row in validation_targets).items())),
        "preflight": preflight,
        "available_models": available,
        "pilot": pilot_results,
        "finalists": finalist_specs,
        "validation": validation_results,
        "prompt_hash_mismatch_count": len(prompt_mismatches),
        "prompt_hash_mismatches": prompt_mismatches[:20],
    }
