"""Held-out evaluation and promotion gates for AP AI routing.

The objective is not merely high model confidence; it is measured reduction in
manual Accounting work without wrong automatic placements. Accuracy and
coverage are tracked separately so a model cannot look "safe" by reviewing
everything.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services.ap_routing_decision_service import DECISION_AUTO_ROUTE, decide_ap_route
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name

DEFAULT_MIN_EXAMPLES = 20
DEFAULT_TARGET_COVERAGE = 0.90
DEFAULT_MIN_AUTO_ROUTE_ACCURACY = 1.00


def _stable_bucket(example: Dict[str, Any], buckets: int = 5) -> int:
    key = str(
        example.get("fingerprint")
        or example.get("source_item_id")
        or example.get("document_id")
        or example.get("file_name")
        or ""
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def split_train_holdout(
    examples: List[Dict[str, Any]],
    *,
    holdout_bucket: int = 0,
    buckets: int = 5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Stable ~80/20 split without random-run drift."""
    train, holdout = [], []
    for example in examples:
        (holdout if _stable_bucket(example, buckets) == holdout_bucket else train).append(example)

    # Very small cohorts still need at least one held-out item when possible.
    if not holdout and len(train) >= 2:
        holdout.append(train.pop())
    return train, holdout


def _document_from_example(example: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": example.get("document_id") or example.get("source_item_id"),
        "file_name": example.get("file_name"),
        "document_type": example.get("document_type"),
        "suggested_job_type": example.get("document_type"),
        "confidence": example.get("classification_confidence"),
        "vendor_canonical": example.get("vendor_name"),
        "extracted_fields": example.get("extracted_fields") or {},
        "raw_text": example.get("raw_text_excerpt") or "",
    }


async def evaluate_holdout(
    *,
    examples: List[Dict[str, Any]],
    contract: Dict[str, Any],
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    model: str = "gemini-2.5-pro",
    vendor_auto_thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    train, holdout = split_train_holdout(examples)
    vendor_auto_thresholds = vendor_auto_thresholds or {}
    rows: List[Dict[str, Any]] = []

    for test in holdout:
        vendor = str(test.get("vendor_name") or "")
        vendor_key = normalize_vendor_name(vendor)
        # Prevent leakage from exact same source item/fingerprint.
        fp = test.get("fingerprint")
        context_examples = [e for e in train if not fp or e.get("fingerprint") != fp]
        result = await decide_ap_route(
            None,
            document=_document_from_example(test),
            bc_context=test.get("bc_context") or {},
            contract=contract,
            examples=context_examples,
            vendor_auto_threshold=vendor_auto_thresholds.get(vendor_key),
            model=model,
            llm_send=llm_send,
        )
        expected = normalize_route_path(test.get("route_path"))
        predicted = normalize_route_path(result.get("route_path"))
        auto = result.get("decision") == DECISION_AUTO_ROUTE
        correct = predicted == expected if auto else False
        rows.append(
            {
                "example_id": test.get("fingerprint") or test.get("source_item_id"),
                "file_name": test.get("file_name"),
                "vendor_name": vendor,
                "normalized_vendor": vendor_key,
                "expected_route": expected,
                "predicted_route": predicted,
                "decision": result.get("decision"),
                "confidence": result.get("confidence"),
                "auto_routed": auto,
                "auto_route_correct": correct,
                "reason": result.get("reason"),
            }
        )

    return summarize_evaluation(rows, train_count=len(train), holdout_count=len(holdout))


def summarize_evaluation(
    rows: List[Dict[str, Any]],
    *,
    train_count: int = 0,
    holdout_count: Optional[int] = None,
) -> Dict[str, Any]:
    total = len(rows) if holdout_count is None else holdout_count
    auto_rows = [r for r in rows if r.get("auto_routed")]
    correct_auto = [r for r in auto_rows if r.get("auto_route_correct")]
    wrong_auto = [r for r in auto_rows if not r.get("auto_route_correct")]

    by_vendor_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_vendor_rows[row.get("normalized_vendor") or "unknown"].append(row)

    by_vendor = []
    for vendor, vendor_rows in sorted(by_vendor_rows.items(), key=lambda x: len(x[1]), reverse=True):
        vendor_auto = [r for r in vendor_rows if r.get("auto_routed")]
        vendor_correct = [r for r in vendor_auto if r.get("auto_route_correct")]
        vendor_wrong = [r for r in vendor_auto if not r.get("auto_route_correct")]
        by_vendor.append(
            {
                "normalized_vendor": vendor,
                "holdout_count": len(vendor_rows),
                "auto_routed": len(vendor_auto),
                "reviewed": len(vendor_rows) - len(vendor_auto),
                "coverage": round(len(vendor_auto) / max(len(vendor_rows), 1), 4),
                "auto_route_accuracy": round(len(vendor_correct) / max(len(vendor_auto), 1), 4) if vendor_auto else None,
                "wrong_auto_routes": len(vendor_wrong),
            }
        )

    route_counts = Counter(r.get("expected_route") or "" for r in rows)
    return {
        "train_count": train_count,
        "holdout_count": total,
        "auto_routed": len(auto_rows),
        "reviewed": total - len(auto_rows),
        "coverage": round(len(auto_rows) / max(total, 1), 4),
        "auto_route_accuracy": round(len(correct_auto) / max(len(auto_rows), 1), 4) if auto_rows else None,
        "wrong_auto_routes": len(wrong_auto),
        "wrong_auto_route_examples": wrong_auto[:25],
        "expected_route_counts": dict(route_counts),
        "by_vendor": by_vendor,
        "rows": rows,
    }


def promotion_gate(
    evaluation: Dict[str, Any],
    *,
    labeled_example_count: int,
    minimum_examples: int = DEFAULT_MIN_EXAMPLES,
    target_coverage: float = DEFAULT_TARGET_COVERAGE,
    minimum_auto_route_accuracy: float = DEFAULT_MIN_AUTO_ROUTE_ACCURACY,
) -> Dict[str, Any]:
    """Gate runtime authority using held-out evidence, not model confidence."""
    reasons = []
    accuracy = evaluation.get("auto_route_accuracy")
    coverage = float(evaluation.get("coverage") or 0.0)
    wrong = int(evaluation.get("wrong_auto_routes") or 0)

    if labeled_example_count < minimum_examples:
        reasons.append(f"only {labeled_example_count} labels; need at least {minimum_examples}")
    if evaluation.get("holdout_count", 0) < 3:
        reasons.append("holdout set too small")
    if wrong > 0:
        reasons.append(f"{wrong} wrong auto-route(s) in holdout")
    if accuracy is None or float(accuracy) < minimum_auto_route_accuracy:
        reasons.append(
            f"auto-route accuracy {accuracy} below {minimum_auto_route_accuracy:.1%}"
        )
    if coverage < target_coverage:
        reasons.append(f"auto-route coverage {coverage:.1%} below {target_coverage:.1%}")

    return {
        "ready_for_runtime_authority": not reasons,
        "reasons": reasons,
        "labeled_example_count": labeled_example_count,
        "holdout_count": evaluation.get("holdout_count", 0),
        "coverage": coverage,
        "auto_route_accuracy": accuracy,
        "wrong_auto_routes": wrong,
        "targets": {
            "minimum_examples": minimum_examples,
            "target_coverage": target_coverage,
            "minimum_auto_route_accuracy": minimum_auto_route_accuracy,
            "wrong_auto_routes_allowed": 0,
        },
    }
