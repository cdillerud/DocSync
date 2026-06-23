"""Runtime helpers for sales-order automation.

These helpers normalize values arriving from MongoDB, AI extraction, forms, and
legacy records before deterministic preflight runs.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

_TRUE_VALUES = {"true", "1", "yes", "y", "on", "approved"}
_FALSE_VALUES = {"false", "0", "no", "n", "off", "", "none", "null"}


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parse booleans without treating the string ``"false"`` as truthy."""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return default


def prepare_sales_order_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return a defensive copy with known boolean fields normalized.

    The repository currently contains documents produced by several generations
    of ingestion code. Some records contain real booleans while others contain
    strings such as ``"false"``. Preflight should receive one consistent shape.
    """

    prepared = copy.deepcopy(doc)
    prepared["sales_order_approved"] = parse_bool(
        prepared.get("sales_order_approved")
    )

    for container_name in (
        "sales_order_lines",
        "mapped_lines",
        "line_items",
    ):
        _normalize_line_flags(prepared.get(container_name))

    for parent_name in ("normalized_fields", "extracted_fields", "data"):
        parent = prepared.get(parent_name)
        if not isinstance(parent, dict):
            continue
        _normalize_line_flags(parent.get("lines"))
        _normalize_line_flags(parent.get("line_items"))

    return prepared


def mongo_field_missing_or_null(field_name: str) -> Dict[str, Any]:
    """Build a Mongo predicate that accepts both absent and explicit null."""

    return {
        "$or": [
            {field_name: {"$exists": False}},
            {field_name: None},
        ]
    }


def append_validation_error(
    preflight_dict: Dict[str, Any],
    *,
    code: str,
    message: str,
    field: str | None = None,
    line: int | None = None,
) -> Dict[str, Any]:
    """Append a structured error to a serialized preflight result."""

    errors: List[Dict[str, Any]] = list(preflight_dict.get("errors") or [])
    errors.append(
        {
            "code": code,
            "message": message,
            "severity": "error",
            "field": field,
            "line": line,
        }
    )
    preflight_dict["errors"] = errors
    preflight_dict["can_create"] = False
    return preflight_dict


def _normalize_line_flags(lines: Any) -> None:
    if not isinstance(lines, list):
        return

    for line in lines:
        if not isinstance(line, dict):
            continue
        for key in (
            "mappingApproved",
            "mapping_approved",
            "item_mapping_approved",
        ):
            if key in line:
                line[key] = parse_bool(line.get(key))
