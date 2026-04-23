"""
GPI Hub — Unified exception-queue taxonomy (Lane C Step 3A)

Declarative source of truth for the 10 canonical exception categories
defined in memory/LANE_A_SIGNED_SCOPE.md §6.1. Module provides:

  - ``ExceptionType`` Literal covering the 10 categories
  - ``Severity`` Literal covering the 3 severities
  - ``DEFAULT_SEVERITY`` map (per §6.1 semantics)
  - ``ExceptionRecord`` frozen dataclass
  - ``build_exception(...)`` pure constructor

This module is intentionally UNWIRED. It does not import from and is not
imported by:
  - backend/server.py
  - any other workflows/ module
  - services/*
  - routers/*

No I/O. No DB writes. No hub_documents writes. No endpoints.

Step 3B (EOD controller) will be the first consumer. Convergence plan is
documented on a separate Pre-Change Declaration that ships before 3B code.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal, Mapping, Optional

# -----------------------------------------------------------------------------
# §6.1 — 10-type exception taxonomy (ordering matches the signed scope)
# -----------------------------------------------------------------------------

ExceptionType = Literal[
    "missing_master_data",
    "duplicate_invoice_risk",
    "low_inventory",
    "missing_freight_docs",
    "receipt_invoice_mismatch",
    "cost_mismatch",
    "location_division_mismatch",
    "partial_post",
    "archived_doc_collision",
    "intentional_send_skip",
]

Severity = Literal["block", "warn", "info"]

# Tuple form for order-preserving enumeration in tests + catalogs.
# Must stay aligned with the Literal above.
EXCEPTION_TYPES: tuple[str, ...] = (
    "missing_master_data",
    "duplicate_invoice_risk",
    "low_inventory",
    "missing_freight_docs",
    "receipt_invoice_mismatch",
    "cost_mismatch",
    "location_division_mismatch",
    "partial_post",
    "archived_doc_collision",
    "intentional_send_skip",
)


# §6.1 semantics:
#   - intentional_send_skip is the zero-amount send audit marker → info
#   - partial_post, archived_doc_collision, cost_mismatch,
#     receipt_invoice_mismatch, duplicate_invoice_risk are hard operational
#     failures or integrity risks → block
#   - missing_master_data, low_inventory, missing_freight_docs,
#     location_division_mismatch surface work-to-do for operators → warn
_DEFAULT_SEVERITY_MUTABLE: dict[str, Severity] = {
    "missing_master_data":         "warn",
    "duplicate_invoice_risk":      "block",
    "low_inventory":               "warn",
    "missing_freight_docs":        "warn",
    "receipt_invoice_mismatch":    "block",
    "cost_mismatch":               "block",
    "location_division_mismatch":  "warn",
    "partial_post":                "block",
    "archived_doc_collision":      "block",
    "intentional_send_skip":       "info",
}

# Frozen, read-only view for public consumption. Callers cannot mutate.
DEFAULT_SEVERITY: Mapping[str, Severity] = MappingProxyType(_DEFAULT_SEVERITY_MUTABLE)


# Import-time invariants: the Literal, the tuple, and the severity map must
# agree on the exact 10 categories. Any drift fails module import.
assert set(EXCEPTION_TYPES) == set(_DEFAULT_SEVERITY_MUTABLE.keys()), (
    "EXCEPTION_TYPES and DEFAULT_SEVERITY must cover identical keys"
)
assert len(EXCEPTION_TYPES) == 10, (
    f"§6.1 mandates exactly 10 exception types; found {len(EXCEPTION_TYPES)}"
)


# -----------------------------------------------------------------------------
# ExceptionRecord — frozen, structured, declarative
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ExceptionRecord:
    """One categorized exception attached to a document.

    Notes:
      - ``doc_id`` is the ``hub_documents.id`` string (never the Mongo _id).
      - ``evidence`` is an immutable mapping of arbitrary JSON-serializable
        facts captured at construction time. An empty mapping is the default.
      - ``source_step`` names the EOD-controller step (or other caller) that
        produced the record; may be None for ad-hoc construction.
      - ``gate_id`` carries the originating gate identifier when the record
        was produced by a failing gate; None otherwise.
      - ``created_utc`` is an ISO-8601 string. When omitted, the builder
        stamps ``datetime.now(timezone.utc).isoformat()``.
    """
    doc_id: str
    exception_type: ExceptionType
    severity: Severity
    detail: str
    evidence: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    created_utc: str = ""
    source_step: Optional[str] = None
    gate_id: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_exception(
    doc_id: str,
    exception_type: ExceptionType,
    *,
    detail: str,
    evidence: Optional[Mapping[str, object]] = None,
    severity: Optional[Severity] = None,
    source_step: Optional[str] = None,
    gate_id: Optional[str] = None,
    created_utc: Optional[str] = None,
) -> ExceptionRecord:
    """Pure constructor for an ``ExceptionRecord``.

    - ``exception_type`` must be one of the 10 §6.1 categories; otherwise
      raises ``ValueError`` at construction time (no string-literal sprawl).
    - ``severity`` defaults to ``DEFAULT_SEVERITY[exception_type]``.
    - ``evidence`` is deep-frozen into a read-only mapping so downstream
      holders cannot mutate the record's view.
    - ``created_utc`` defaults to ``datetime.now(timezone.utc).isoformat()``
      and is accepted as an explicit argument so tests can pin a timestamp
      for determinism checks.
    """
    if exception_type not in _DEFAULT_SEVERITY_MUTABLE:
        raise ValueError(
            f"unknown exception_type {exception_type!r}; "
            f"expected one of {EXCEPTION_TYPES}"
        )

    effective_severity: Severity = (
        severity if severity is not None else _DEFAULT_SEVERITY_MUTABLE[exception_type]
    )

    if evidence is None:
        frozen_evidence: Mapping[str, object] = MappingProxyType({})
    else:
        # Snapshot into a plain dict first so a caller-held mutable dict
        # can't change the record's view afterward, then freeze.
        frozen_evidence = MappingProxyType(dict(evidence))

    return ExceptionRecord(
        doc_id=doc_id,
        exception_type=exception_type,
        severity=effective_severity,
        detail=detail,
        evidence=frozen_evidence,
        created_utc=created_utc if created_utc is not None else _now_iso(),
        source_step=source_step,
        gate_id=gate_id,
    )


__all__ = [
    "ExceptionType",
    "Severity",
    "EXCEPTION_TYPES",
    "DEFAULT_SEVERITY",
    "ExceptionRecord",
    "build_exception",
]
