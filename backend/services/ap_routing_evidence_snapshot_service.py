"""Validation for read-only V117 human-evidence snapshot replay.

A snapshot is an optimization and an apples-to-apples evaluation aid, never a
new source of routing truth. It is usable only when it came from the expected
Gamer Accounting authority, is recent, internally consistent, and every stored
route still satisfies the current route contract. Invalid snapshots fail closed
and the controller rebuilds the live corpus instead.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import normalize_route_path


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
    except Exception as exc:
        result["reason"] = f"snapshot_unreadable:{type(exc).__name__}"
        return result

    authority = str(payload.get("authority") or "")
    result["authority"] = authority
    result["source_feature_commit"] = str(payload.get("feature_commit") or "")
    if authority != expected_authority:
        result["reason"] = "authority_mismatch"
        return result

    examples = list(payload.get("examples") or [])
    declared_count = int(payload.get("example_count") or 0)
    if declared_count != len(examples):
        result["reason"] = "example_count_mismatch"
        return result
    if len(examples) < int(minimum_examples):
        result["reason"] = "insufficient_examples"
        return result

    fingerprints = set()
    route_count = 0
    for row in examples:
        route = normalize_route_path(row.get("route_path"))
        if not route:
            result["reason"] = "blank_route"
            return result
        if not route_is_allowed(route, contract, row.get("bc_context") or {}):
            result["reason"] = f"route_not_allowed:{route}"
            return result
        route_count += 1
        fingerprint = str(
            row.get("fingerprint")
            or row.get("source_item_id")
            or row.get("document_id")
            or row.get("file_name")
            or ""
        )
        if not fingerprint:
            result["reason"] = "missing_example_identity"
            return result
        if fingerprint in fingerprints:
            result["reason"] = "duplicate_example_identity"
            return result
        fingerprints.add(fingerprint)

    distinct_routes = {normalize_route_path(row.get("route_path")) for row in examples}
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
