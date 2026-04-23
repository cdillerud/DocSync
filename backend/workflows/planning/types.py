"""Typed row model for Coloplast-style forecast imports.

Immutable dataclasses only — no Mongo-bound models, no Pydantic,
no validation in constructors. Parsing and validation live in
``coloplast.py`` and ``validate.py`` respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Tuple


PlanningRowSeverity = Literal["error", "warn"]


@dataclass(frozen=True)
class PlanningRow:
    """One (item × period) forecast quantity.

    ``period_label`` is the human-readable form from the sheet header
    (e.g. ``"2026-W15"`` or ``"2026-04"``). ``period_start`` is the
    normalized first calendar day of that period — Monday for weekly
    periods, first-of-month for monthly periods.
    """

    customer_no: str
    item_no: str
    period_label: str
    period_start: date
    period_kind: Literal["weekly", "monthly"]
    target_qty: float
    uom: Optional[str]
    source_row_index: int
    source_column_index: int


@dataclass(frozen=True)
class PlanningRowError:
    """Structured parse or validation error.

    ``source_row_index`` / ``source_column_index`` are 0-based indexes
    into the input ``PlanningSheet.data_rows`` / ``header_row`` where
    they are meaningful (``source_column_index`` is ``None`` for
    whole-row errors).
    """

    source_row_index: int
    source_column_index: Optional[int]
    severity: PlanningRowSeverity
    code: str
    message: str
    raw_value: Optional[Any] = None


@dataclass(frozen=True)
class PlanningSheet:
    """Raw sheet payload handed to the parser.

    Callers are responsible for loading the workbook and passing the
    header row + data rows in; this package has no I/O dependencies.

    ``customer_no`` is required — the Coloplast parser is strictly
    per-customer and will not guess it from sheet contents.
    """

    customer_no: str
    header_row: List[str]
    data_rows: List[List[Any]]
    source_filename: Optional[str] = None


@dataclass(frozen=True)
class PlanningParseResult:
    """Outcome of ``parse_coloplast_sheet``.

    All collections are immutable tuples. ``column_map`` keys are the
    canonical column names (``"item_no"``, ``"description"``, ``"uom"``);
    values are 0-based column indexes into ``PlanningSheet.header_row``.
    ``period_columns`` carries ``(col_idx, period_label, period_start,
    period_kind)`` for each recognized period column.
    """

    rows: Tuple[PlanningRow, ...]
    errors: Tuple[PlanningRowError, ...]
    column_map: Dict[str, int] = field(default_factory=dict)
    period_columns: Tuple[Tuple[int, str, date, str], ...] = field(default_factory=tuple)
    skipped_rows: Tuple[int, ...] = field(default_factory=tuple)


__all__ = [
    "PlanningRow",
    "PlanningRowError",
    "PlanningRowSeverity",
    "PlanningSheet",
    "PlanningParseResult",
]
