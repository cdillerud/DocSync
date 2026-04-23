"""Planning / Import package (Lane C Step 8).

Coloplast-specific forecast-import foundation. Strictly deterministic
(no LLM). Parser + validator + typed row model only — no persistence,
no routes, no scheduler, no wire-in.

This package is INTENTIONALLY separate from the inventory-count
staging pipeline (``workflows/inventory/planning/staging.py``), which
serves a different semantic purpose (inventory ledger writes). Do not
conflate the two.

Public API:
  - ``parse_coloplast_sheet(sheet)``         — deterministic parser
  - ``validate_planning_rows(rows, ...)``    — structural validator
  - ``PlanningRow``, ``PlanningSheet``,
    ``PlanningParseResult``, ``PlanningRowError``,
    ``PlanningRowSeverity``                  — typed row model
"""

from .coloplast import parse_coloplast_sheet
from .types import (
    PlanningParseResult,
    PlanningRow,
    PlanningRowError,
    PlanningRowSeverity,
    PlanningSheet,
)
from .validate import validate_planning_rows

__all__ = [
    "PlanningRow",
    "PlanningRowError",
    "PlanningRowSeverity",
    "PlanningSheet",
    "PlanningParseResult",
    "parse_coloplast_sheet",
    "validate_planning_rows",
]
