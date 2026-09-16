"""Reliability-aware TRAIN-only model bakeoff orchestration for V117.

REV2 keeps the REV1 prompt construction, target sampling, authority replay, and
holdout exclusion intact while fixing two evaluation defects discovered in the
first live bakeoff:

* models with high call/parse failure rates cannot advance on accuracy computed
  only over their few successful responses;
* provider-budget exhaustion fails fast before or during validation instead of
  burning the remainder of a 100-row validation set.

No Production writes or holdout evaluation are introduced here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.ap_routing_model_bakeoff_service import (
    _row_id,
    _route,
    evaluate_model_on_targets,
    parse_model_specs,
    preflight_models,
    route_balanced_sample,
    summarize_model_rows,
)
from services.ap_routing_relevant_learning_service import is_train_human_example

DEFAULT_MIN_COMPLETION_RATE = 0.90
DEFAULT_VALIDATION_BATCH_SIZE = 10


def _response_success_rate(result: Dict[str, Any]) -> float:
    summary = result.get("summary") or {}
    target = int(summary.get("target_count") or 0)
    errors = int(summary.get("model_error_count") or 0)
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, (target - errors) / float(target)))


def _target_accuracy(result: Dict[str, Any]) -> float:
    rows = list(result.get("rows") or [])
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get("proposal_correct")) / float(len(rows))


def _target_family_accuracy(result: Dict[str, Any]) -> float:
    rows = list(result.get("rows") or [])
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get("family_correct")) / float(len(rows))


def reliability_aware_sort_key(result: Dict[str, Any]) -> Tuple[Any, ...]:
    """Rank complete/reliable pilot models before accuracy/latency tie-breaks."""
    summary = result.get("summary") or {}
    return (
        -_response_success_rate(result),
        -_target_accuracy(result),
        int(summary.get("overconfident_wrong_count") or 0),
        int(summary.get("contract_invalid_count") or 0),
        -_target_family_accuracy(result),
        int(summary.get("model_error_count") or 0),
        float(summary.get("mean_latency_seconds") or 999999.0),
        str((result.get("spec") or {}).get("name") or ""),
    )


def _budget_exceeded(rows: Sequence[Dict[str, Any]]) -> bool:
    for row in rows:
        message = str(row.get("model_error") or "").lower()
        if "budget has been exceeded" in message or "max budget" in message:
            return True
    return False


def _validation_summary(
    *,
    spec: Dict[str, str],
    rows: Sequence[Dict[str, Any]],
    expected_target_count: int,
    aborted_reason: str = "",
) -> Dict[str, Any]:
    summary = summarize_model_rows(rows)
    attempted = len(rows)
    errors = int(summary.get("model_error_count") or 0)
    successful = max(0, attempted - errors)
    expected = max(0, int(expected_target_count))
    summary.update(
        {
            "expected_target_count": expected,
            "attempted_target_count": attempted,
            "successful_response_count": successful,
            "response_sufficiency": round(successful / expected, 4) if expected else None,
            "validation_aborted_reason": aborted_reason,
        }
    )
    return {"spec": dict(spec), "rows": list(rows), "summary": summary}


async def _evaluate_validation_in_batches(
    *,
    spec: Dict[str, str],
    targets: Sequence[Dict[str, Any]],
    train_examples: Sequence[Dict[str, Any]],
    contract: Dict[str, Any],
    api_key: Optional[str],
    concurrency: int,
    batch_size: int,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    aborted_reason = ""
    size = max(1, int(batch_size))

    for start in range(0, len(targets), size):
        batch = list(targets[start : start + size])
        result = await evaluate_model_on_targets(
            spec=spec,
            targets=batch,
            train_examples=train_examples,
            contract=contract,
            api_key=api_key,
            concurrency=concurrency,
        )
        batch_rows = list(result.get("rows") or [])
        rows.extend(batch_rows)
        if _budget_exceeded(batch_rows):
            aborted_reason = "provider_budget_exceeded"
            break

    return _validation_summary(
        spec=spec,
        rows=rows,
        expected_target_count=len(targets),
        aborted_reason=aborted_reason,
    )


async def run_two_stage_bakeoff_rev2(
    *,
    train_examples: Sequence[Dict[str, Any]],
    contract: Dict[str, Any],
    model_specs: Optional[Sequence[Dict[str, str]]] = None,
    api_key: Optional[str] = None,
    pilot_size: int = 24,
    validation_size: int = 100,
    finalists: int = 2,
    concurrency_per_model: int = 2,
    min_completion_rate: float = DEFAULT_MIN_COMPLETION_RATE,
    validation_batch_size: int = DEFAULT_VALIDATION_BATCH_SIZE,
) -> Dict[str, Any]:
    """Run a reliability-aware TRAIN-only bakeoff with fail-fast validation."""
    eligible = [dict(row) for row in train_examples if is_train_human_example(row)]
    specs = [dict(row) for row in (model_specs or parse_model_specs())]

    preflight = await preflight_models(specs, api_key=api_key)
    available_keys = {
        (row["provider"], row["model"])
        for row in preflight
        if row.get("available")
    }
    available = [
        spec for spec in specs if (spec["provider"], spec["model"]) in available_keys
    ]
    if len(available) < 2:
        return {
            "schema_version": "v117-model-bakeoff-rev2",
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

    threshold = float(min_completion_rate)
    healthy_pilot = [
        result for result in pilot_results if _response_success_rate(result) >= threshold
    ]
    ordered = sorted(healthy_pilot, key=reliability_aware_sort_key)
    finalist_specs = [
        dict(row["spec"]) for row in ordered[: max(1, int(finalists))]
    ]
    if len(finalist_specs) < max(1, int(finalists)):
        return {
            "schema_version": "v117-model-bakeoff-rev2",
            "train_only": True,
            "holdout_used": False,
            "eligible_train_count": len(eligible),
            "pilot_target_count": len(pilot_targets),
            "validation_target_count": len(validation_targets),
            "pilot_validation_overlap_count": len(
                pilot_ids.intersection({_row_id(row) for row in validation_targets})
            ),
            "pilot_route_counts": dict(sorted(Counter(_route(row) for row in pilot_targets).items())),
            "validation_route_counts": dict(sorted(Counter(_route(row) for row in validation_targets).items())),
            "preflight": preflight,
            "available_models": available,
            "pilot": pilot_results,
            "healthy_pilot_models": [row.get("spec") for row in healthy_pilot],
            "finalists": finalist_specs,
            "validation": [],
            "prompt_hash_mismatch_count": 0,
            "prompt_hash_mismatches": [],
            "error": "fewer_than_required_healthy_pilot_models",
        }

    finalist_preflight = await preflight_models(finalist_specs, api_key=api_key)
    finalist_ready = {
        (row["provider"], row["model"])
        for row in finalist_preflight
        if row.get("available")
    }
    if len(finalist_ready) < len(finalist_specs):
        return {
            "schema_version": "v117-model-bakeoff-rev2",
            "train_only": True,
            "holdout_used": False,
            "eligible_train_count": len(eligible),
            "pilot_target_count": len(pilot_targets),
            "validation_target_count": len(validation_targets),
            "pilot_validation_overlap_count": len(
                pilot_ids.intersection({_row_id(row) for row in validation_targets})
            ),
            "pilot_route_counts": dict(sorted(Counter(_route(row) for row in pilot_targets).items())),
            "validation_route_counts": dict(sorted(Counter(_route(row) for row in validation_targets).items())),
            "preflight": preflight,
            "available_models": available,
            "pilot": pilot_results,
            "healthy_pilot_models": [row.get("spec") for row in healthy_pilot],
            "finalists": finalist_specs,
            "finalist_preflight": finalist_preflight,
            "validation": [],
            "prompt_hash_mismatch_count": 0,
            "prompt_hash_mismatches": [],
            "error": "finalist_preflight_failed_before_validation",
        }

    validation_results = []
    global_abort = ""
    for spec in finalist_specs:
        result = await _evaluate_validation_in_batches(
            spec=spec,
            targets=validation_targets,
            train_examples=eligible,
            contract=contract,
            api_key=api_key,
            concurrency=concurrency_per_model,
            batch_size=validation_batch_size,
        )
        validation_results.append(result)
        if str((result.get("summary") or {}).get("validation_aborted_reason") or ""):
            global_abort = str(result["summary"]["validation_aborted_reason"])
            break

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

    validation_sufficient = (
        not global_abort
        and len(validation_results) == len(finalist_specs)
        and all(
            float((row.get("summary") or {}).get("response_sufficiency") or 0.0) >= threshold
            for row in validation_results
        )
    )

    return {
        "schema_version": "v117-model-bakeoff-rev2",
        "train_only": True,
        "holdout_used": False,
        "eligible_train_count": len(eligible),
        "pilot_target_count": len(pilot_targets),
        "validation_target_count": len(validation_targets),
        "pilot_validation_overlap_count": len(
            pilot_ids.intersection({_row_id(row) for row in validation_targets})
        ),
        "pilot_route_counts": dict(sorted(Counter(_route(row) for row in pilot_targets).items())),
        "validation_route_counts": dict(sorted(Counter(_route(row) for row in validation_targets).items())),
        "preflight": preflight,
        "available_models": available,
        "pilot": pilot_results,
        "healthy_pilot_models": [row.get("spec") for row in healthy_pilot],
        "finalists": finalist_specs,
        "finalist_preflight": finalist_preflight,
        "validation": validation_results,
        "validation_response_sufficiency_pass": validation_sufficient,
        "validation_abort_reason": global_abort,
        "prompt_hash_mismatch_count": len(prompt_mismatches),
        "prompt_hash_mismatches": prompt_mismatches[:20],
        "error": "" if validation_sufficient else (global_abort or "validation_response_sufficiency_failed"),
    }
