"""Pytest for Lane C Step 8 — Planning row validator.

Exercises ``validate_planning_rows`` in isolation (no parser coupling).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from workflows.planning import PlanningRow, validate_planning_rows
from workflows.planning.validate import (
    DEFAULT_BACKLOG_WEEKS,
    DEFAULT_HORIZON_WEEKS,
)


def _row(
    *,
    item_no="A-1",
    customer_no="COLOPLAST",
    period_label="2026-W15",
    period_start=date(2026, 4, 6),
    target_qty=10.0,
    uom="EA",
    row_idx=0,
    col_idx=3,
    period_kind="weekly",
):
    return PlanningRow(
        customer_no=customer_no,
        item_no=item_no,
        period_label=period_label,
        period_start=period_start,
        period_kind=period_kind,
        target_qty=target_qty,
        uom=uom,
        source_row_index=row_idx,
        source_column_index=col_idx,
    )


class TestHappyPath:
    def test_clean_row_produces_no_errors(self):
        today = date(2026, 4, 1)
        errors = validate_planning_rows(
            [_row(period_start=today + timedelta(weeks=2))],
            today=today,
        )
        assert errors == []

    def test_multiple_clean_rows(self):
        today = date(2026, 4, 1)
        rows = [
            _row(period_start=today + timedelta(weeks=i), row_idx=i)
            for i in range(1, 5)
        ]
        assert validate_planning_rows(rows, today=today) == []


class TestRequiredFields:
    def test_empty_item_no_emits_error(self):
        errors = validate_planning_rows([_row(item_no="   ")], today=date(2026, 4, 1))
        codes = [e.code for e in errors]
        assert "validator_missing_item_no" in codes

    def test_empty_customer_no_emits_error(self):
        errors = validate_planning_rows([_row(customer_no="")], today=date(2026, 4, 1))
        codes = [e.code for e in errors]
        assert "validator_missing_customer_no" in codes

    def test_customer_mismatch_emits_error(self):
        errors = validate_planning_rows(
            [_row(customer_no="OTHER")],
            customer_no="COLOPLAST",
            today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_customer_no_mismatch" in codes

    def test_customer_match_trimmed(self):
        # Both sides trim whitespace consistently.
        errors = validate_planning_rows(
            [_row(customer_no="  COLOPLAST  ")],
            customer_no="COLOPLAST",
            today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_customer_no_mismatch" not in codes


class TestQtyDiscipline:
    def test_negative_qty_emits_error(self):
        errors = validate_planning_rows(
            [_row(target_qty=-1.0)], today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_negative_qty" in codes

    def test_nan_qty_emits_error(self):
        errors = validate_planning_rows(
            [_row(target_qty=float("nan"))], today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_qty_not_finite" in codes

    def test_inf_qty_emits_error(self):
        errors = validate_planning_rows(
            [_row(target_qty=float("inf"))], today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_qty_not_finite" in codes

    def test_zero_qty_allowed(self):
        errors = validate_planning_rows(
            [_row(target_qty=0.0)], today=date(2026, 4, 1),
        )
        codes = [e.code for e in errors]
        assert "validator_negative_qty" not in codes
        assert "validator_qty_not_finite" not in codes


class TestHorizonBounds:
    def test_period_far_behind_is_warn(self):
        today = date(2026, 4, 1)
        errors = validate_planning_rows(
            [_row(period_start=today - timedelta(weeks=5))],
            today=today,
        )
        codes = [e.code for e in errors]
        severities = [e.severity for e in errors]
        assert "validator_period_behind_backlog_window" in codes
        assert "warn" in severities

    def test_period_beyond_horizon_is_warn(self):
        today = date(2026, 4, 1)
        errors = validate_planning_rows(
            [_row(period_start=today + timedelta(weeks=DEFAULT_HORIZON_WEEKS + 4))],
            today=today,
        )
        codes = [e.code for e in errors]
        assert "validator_period_beyond_horizon" in codes
        assert all(e.severity == "warn" for e in errors)

    def test_within_backlog_window_is_ok(self):
        today = date(2026, 4, 1)
        errors = validate_planning_rows(
            [_row(period_start=today - timedelta(days=1))],
            today=today,
        )
        codes = [e.code for e in errors]
        assert "validator_period_behind_backlog_window" not in codes

    def test_horizon_boundary_inclusive(self):
        today = date(2026, 4, 1)
        horizon_edge = today + timedelta(weeks=DEFAULT_HORIZON_WEEKS)
        errors = validate_planning_rows(
            [_row(period_start=horizon_edge)],
            today=today,
        )
        codes = [e.code for e in errors]
        assert "validator_period_beyond_horizon" not in codes


class TestErrorsAreStructured:
    def test_all_errors_carry_source_row_index(self):
        today = date(2026, 4, 1)
        errors = validate_planning_rows(
            [_row(item_no="", target_qty=-1.0, row_idx=7)],
            today=today,
        )
        assert errors, "expected some errors"
        assert all(e.source_row_index == 7 for e in errors)
        # All errors carry a non-empty code + message.
        for e in errors:
            assert e.code
            assert e.message

    def test_validator_is_pure_does_not_mutate_rows(self):
        today = date(2026, 4, 1)
        row = _row(target_qty=-1.0)
        validate_planning_rows([row], today=today)
        # Frozen dataclass — any in-place mutation would have raised.
        assert row.target_qty == -1.0
