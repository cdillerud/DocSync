"""Validation for read-only V117 human-evidence snapshot replay.

A snapshot is an optimization and an apples-to-apples evaluation aid, never a
new source of routing truth. It is usable only when it came from the expected
Gamer Accounting authority, is recent, internally consistent, contains only
human-authoritative evidence, and every stored route still satisfies the current
route contract. Invalid snapshots fail closed and the controller rebuilds the
live corpus instead.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict

from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import (
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    normalize_route_path,
)

LABEL_SOURCE_REVIEWER_CONFIRMATION = "reviewer_confirmation"
HUMAN_SNAPSHOT_SOURCES = {
    LABEL_SOURCE_ACCOUNTING_TEMP,
    LABEL_SOURCE_REVIEWER_CORRECTION,
    LABEL_SOURCE_REVIEWER_CONFIRMATION,
}


def snapshot_examples_sha256(examples: list[Dict[str, Any]]) -> str:
    """Stable digest for newly written snapshots.

    Old V117 snapshots did not carry a digest, so validation treats a missing
    digest as legacy metadata rather than as authority. New snapshots always
    emit and verify it.
    """
    canonical = json.dumps(
        examples,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_valid_evidence_snapshot(
    path: str | Path,
    *,
    expected_authority: str,
    contract: Dict[str, Any],
    max_age_hours: float = 24.0,
    minimum_examples: int = 20,
) -> Dict[str, Any]:
    """Return validated snapshot metadata; otherwise return a fail-closed result."""
    snapshot_path = Path(path)
    result: Dict[str, Any] = {
        "valid": False,
        "path": str(snapshot_path),
        "reason": "",
        "examples": [],
        "authority": "",
        "source_feature_commit": "",
        "age_seconds": None,
        "integrity": "unverified",
    }
    if not snapshot_path.is_file():
        result["reason"] = "snapshot_missing"
        return result

    try:
        age_seconds = max(0.0, time.time() - snapshot_path.stat().st_mtime)
        result["age_seconds"] = round(age_seconds, 3)
        if age_seconds > max(0.0, float(max_age_hours)) * 3600.0:
            result["reason"] = "snapshot_stale"
            return result
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            result["reason"] = "snapshot_payload_not_object"
            return result
    except Exception as exc:
        result["reason"] = f"snapshot_unreadable:{type(exc).__name__}"
        return result

    authority = str(payload.get("authority") or "")
    result["authority"] = authority
    result["source_feature_commit"] = str(payload.get("feature_commit") or "")
    if authority != expected_authority:
        result["reason"] = "authority_mismatch"
        return result

    raw_examples = payload.get("examples")
    if not isinstance(raw_examples, list):
        result["reason"] = "examples_not_list"
        return result
    examples = [dict(row) for row in raw_examples if isinstance(row, dict)]
    if len(examples) != len(raw_examples):
        result["reason"] = "non_object_example"
        return result

    try:
        declared_count = int(payload.get("example_count") or 0)
    except (TypeError, ValueError):
        result["reason"] = "invalid_example_count"
        return result
    if declared_count != len(examples):
        result["reason"] = "example_count_mismatch"
        return result
    if len(examples) < int(minimum_examples):
        result["reason"] = "insufficient_examples"
        return result

    declared_digest = str(payload.get("examples_sha256") or "").strip().lower()
    if declared_digest:
        actual_digest = snapshot_examples_sha256(examples)
        if declared_digest != actual_digest:
            result["reason"] = "snapshot_digest_mismatch"
            return result
        result["integrity"] = "sha256_verified"
    else:
        result["integrity"] = "legacy_no_digest"

    fingerprints = set()
    distinct_routes = set()
    for row in examples:
        source = str(row.get("label_source") or row.get("source") or "").strip().lower()
        if source not in HUMAN_SNAPSHOT_SOURCES:
            result["reason"] = f"non_human_label_source:{source or 'blank'}"
            return result
        if row.get("active") is False:
            result["reason"] = "inactive_example"
            return result
        if bool(row.get("is_holdout")):
            result["reason"] = "holdout_example_present"
            return result
        split = str(row.get("split") or row.get("evaluation_split") or "").strip().lower()
        if split in {"holdout", "test", "validation"}:
            result["reason"] = f"non_train_split:{split}"
            return result
        if bool(row.get("ai_generated")) and not bool(row.get("human_resolved")):
            result["reason"] = "unreviewed_ai_example"
            return result

        route = normalize_route_path(row.get("route_path") or row.get("final_human_route"))
        if not route:
            result["reason"] = "blank_route"
            return result
        if not route_is_allowed(route, contract, row.get("bc_context") or {}):
            result["reason"] = f"route_not_allowed:{route}"
            return result
        distinct_routes.add(route)

        fingerprint = str(
            row.get("fingerprint")
            or row.get("source_item_id")
            or row.get("document_id")
            or row.get("file_name")
            or ""
        ).strip()
        if not fingerprint:
            result["reason"] = "missing_example_identity"
            return result
        if fingerprint in fingerprints:
            result["reason"] = "duplicate_example_identity"
            return result
        fingerprints.add(fingerprint)

    if len(distinct_routes) < 2:
        result["reason"] = "insufficient_route_diversity"
        return result

    result.update(
        {
            "valid": True,
            "reason": "validated",
            "examples": examples,
            "example_count": len(examples),
            "distinct_route_count": len(distinct_routes),
            "schema_version": str(payload.get("schema_version") or "unknown"),
        }
    )
    return result
