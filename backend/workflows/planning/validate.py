"""Row-level validator for parsed planning rows.

Strictly deterministic. Complementary to the parser: the parser
establishes structure (item columns recognized, period columns
recognized, qty cells numeric); this validator enforces policy
(customer_no required, horizon bound, no-op emptiness).

Produces ``PlanningRowError[]`` — never mutates rows, never filters
them in place. Callers decide what to do with errors.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional, Sequence

from .types import PlanningRow, PlanningRowError


# Hard policy bounds — deliberate constants, not configurable in this step.
DEFAULT_HORIZON_WEEKS = 26
DEFAULT_BACKLOG_WEEKS = 1


def validate_planning_rows(
    rows: Sequence[PlanningRow],
    *,
    customer_no: Optional[str] = None,
    today: Optional[date] = None,
    horizon_weeks: int = DEFAULT_HORIZON_WEEKS,
    backlog_weeks: int = DEFAULT_BACKLOG_WEEKS,
) -> List[PlanningRowError]:
    """Validate a parsed planning-row set.

    Checks performed (all row-level):
      - item_no non-empty (defense-in-depth; parser should have caught)
      - customer_no non-empty on the row
      - if ``customer_no`` kwarg is provided, row.customer_no must equal it
      - target_qty is finite and non-negative
      - period_start within [today - backlog_weeks, today + horizon_weeks]

    The ``today`` / ``horizon_weeks`` / ``backlog_weeks`` knobs exist so
    tests can pin time; production callers omit them.
    """
    errors: List[PlanningRowError] = []
    cutoff_today = today or date.today()
    horizon_end = cutoff_today + timedelta(weeks=horizon_weeks)
    backlog_start = cutoff_today - timedelta(weeks=backlog_weeks)

    normalized_expected = (customer_no or "").strip()

    for row in rows:
        if not row.item_no.strip():
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="error",
                code="validator_missing_item_no",
                message="Row item_no is empty after trimming.",
                raw_value=row.item_no,
            ))

        if not row.customer_no.strip():
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=None,
                severity="error",
                code="validator_missing_customer_no",
                message="Row customer_no is empty after trimming.",
                raw_value=row.customer_no,
            ))
        elif normalized_expected and row.customer_no.strip() != normalized_expected:
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=None,
                severity="error",
                code="validator_customer_no_mismatch",
                message=(
                    f"Row customer_no {row.customer_no!r} does not match "
                    f"expected {normalized_expected!r}."
                ),
                raw_value=row.customer_no,
            ))

        # Finite-number discipline — parser admits any float, but NaN/inf
        # must not slip through policy.
        try:
            qty = float(row.target_qty)
        except (TypeError, ValueError):
            qty = float("nan")

        if qty != qty:  # NaN check
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="error",
                code="validator_qty_not_finite",
                message="target_qty is NaN.",
                raw_value=row.target_qty,
            ))
        elif qty in (float("inf"), float("-inf")):
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="error",
                code="validator_qty_not_finite",
                message="target_qty is infinite.",
                raw_value=row.target_qty,
            ))
        elif qty < 0:
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="error",
                code="validator_negative_qty",
                message=f"target_qty {qty} is negative.",
                raw_value=row.target_qty,
            ))

        if row.period_start < backlog_start:
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="warn",
                code="validator_period_behind_backlog_window",
                message=(
                    f"period_start {row.period_start.isoformat()} precedes "
                    f"backlog window start {backlog_start.isoformat()}."
                ),
                raw_value=row.period_label,
            ))
        elif row.period_start > horizon_end:
            errors.append(PlanningRowError(
                source_row_index=row.source_row_index,
                source_column_index=row.source_column_index,
                severity="warn",
                code="validator_period_beyond_horizon",
                message=(
                    f"period_start {row.period_start.isoformat()} is beyond "
                    f"horizon end {horizon_end.isoformat()} "
                    f"({horizon_weeks} weeks)."
                ),
                raw_value=row.period_label,
            ))

    return errors


__all__ = [
    "DEFAULT_HORIZON_WEEKS",
    "DEFAULT_BACKLOG_WEEKS",
    "validate_planning_rows",
]
