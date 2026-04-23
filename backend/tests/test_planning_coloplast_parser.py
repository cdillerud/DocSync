"""Pytest for Lane C Step 8 — Coloplast planning parser.

Proves the parser is:
  - deterministic (no LLM, no clock-sensitivity for year-qualified labels)
  - Coloplast-shape specific (horizontal layout, weekly/monthly headers)
  - strict on ambiguity (structured errors instead of inferred intent)
  - separated from the inventory-count staging lane
  - unwired (no external importer outside the package + tests)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from workflows.planning import (
    PlanningParseResult,
    PlanningRow,
    PlanningRowError,
    PlanningSheet,
    parse_coloplast_sheet,
)


def _sheet(header, data, customer_no="COLOPLAST"):
    return PlanningSheet(
        customer_no=customer_no,
        header_row=list(header),
        data_rows=[list(r) for r in data],
    )


# ===========================================================================
# 1. Happy path — canonical Coloplast shape (weekly, year-qualified)
# ===========================================================================

class TestCanonicalColoplastShape:
    def test_year_qualified_weekly_header(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "Description", "UOM", "2026-W15", "2026-W16"],
            data=[
                ["A-1", "Widget A", "EA", 100, 120],
                ["B-2", "Widget B", "EA", 50, None],
            ],
        ))
        assert isinstance(result, PlanningParseResult)
        assert result.errors == ()
        assert result.skipped_rows == ()
        assert result.column_map == {"item_no": 0, "description": 1, "uom": 2}
        assert len(result.period_columns) == 2
        labels = [p[1] for p in result.period_columns]
        assert labels == ["2026-W15", "2026-W16"]
        # Period starts are Mondays of ISO weeks.
        starts = {p[1]: p[2] for p in result.period_columns}
        assert starts["2026-W15"] == date.fromisocalendar(2026, 15, 1)
        assert starts["2026-W16"] == date.fromisocalendar(2026, 16, 1)
        # 3 qty cells: A/W15, A/W16, B/W15  (B/W16 was None → skipped)
        assert len(result.rows) == 3
        a_w15 = next(r for r in result.rows if r.item_no == "A-1" and r.period_label == "2026-W15")
        assert a_w15.target_qty == 100
        assert a_w15.uom == "EA"
        assert a_w15.period_kind == "weekly"
        assert a_w15.customer_no == "COLOPLAST"

    def test_numeric_monthly_header(self):
        result = parse_coloplast_sheet(_sheet(
            header=["SKU", "2026-04", "2026-05"],
            data=[
                ["X", 10, 15],
            ],
        ))
        assert result.errors == ()
        assert [p[1] for p in result.period_columns] == ["2026-04", "2026-05"]
        assert all(p[3] == "monthly" for p in result.period_columns)
        starts = {p[1]: p[2] for p in result.period_columns}
        assert starts["2026-04"] == date(2026, 4, 1)
        assert starts["2026-05"] == date(2026, 5, 1)
        assert len(result.rows) == 2

    def test_named_monthly_header(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item No", "Apr 2026", "April 2026", "May 2026"],
            data=[["A", 1, 2, 3]],
        ))
        # "Apr" and "April" both resolve to 2026-04; both are legitimate
        # columns and produce independent rows (deduplication is the
        # consumer's responsibility, not the parser's).
        assert result.errors == ()
        labels = [p[1] for p in result.period_columns]
        assert labels.count("2026-04") == 2
        assert labels.count("2026-05") == 1
        assert len(result.rows) == 3


# ===========================================================================
# 2. Alias recognition for canonical columns
# ===========================================================================

class TestColumnAliases:
    @pytest.mark.parametrize("alias", [
        "Item", "Item No", "Item Number", "SKU", "Part No", "Part Number",
        "ITEM NO", "  sku  ", "item_no",
    ])
    def test_item_no_aliases(self, alias):
        result = parse_coloplast_sheet(_sheet(
            header=[alias, "2026-W15"],
            data=[["A-1", 10]],
        ))
        assert result.column_map.get("item_no") == 0, f"alias {alias!r} not recognized"

    @pytest.mark.parametrize("alias", ["UOM", "UM", "Unit", "Unit of Measure"])
    def test_uom_aliases(self, alias):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", alias, "2026-W15"],
            data=[["A", "EA", 10]],
        ))
        assert result.column_map.get("uom") == 1
        assert result.rows[0].uom == "EA"


# ===========================================================================
# 3. Ambiguity → structured errors (never inferred intent)
# ===========================================================================

class TestStructuralErrors:
    def test_missing_item_no_column(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Description", "2026-W15"],
            data=[["widget", 10]],
        ))
        assert result.rows == ()
        codes = {e.code for e in result.errors}
        assert "missing_required_column_item_no" in codes

    def test_no_period_columns(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "Description"],
            data=[["A", "w"]],
        ))
        assert result.rows == ()
        codes = {e.code for e in result.errors}
        assert "no_period_columns_recognized" in codes

    def test_missing_both(self):
        result = parse_coloplast_sheet(_sheet(
            header=["xxx", "yyy"],
            data=[["a", "b"]],
        ))
        codes = {e.code for e in result.errors}
        assert "missing_required_column_item_no" in codes
        assert "no_period_columns_recognized" in codes

    def test_missing_item_no_cell_emits_row_error(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[
                ["A-1", 10],
                ["", 20],
                [None, 30],
            ],
        ))
        # Two rows produced (for A-1 + only A-1 because blanks error out).
        assert len(result.rows) == 1
        row_error_indexes = {
            e.source_row_index for e in result.errors
            if e.code == "missing_item_no"
        }
        assert row_error_indexes == {1, 2}

    def test_non_numeric_qty_emits_error(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[["A", "ten"]],
        ))
        codes = [e.code for e in result.errors]
        assert codes == ["qty_not_numeric"]
        assert result.rows == ()

    def test_negative_qty_emits_error_and_row_dropped(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15", "2026-W16"],
            data=[["A", -5, 10]],
        ))
        codes = [e.code for e in result.errors]
        assert codes == ["negative_qty"]
        assert len(result.rows) == 1
        assert result.rows[0].period_label == "2026-W16"
        assert result.rows[0].target_qty == 10

    def test_boolean_qty_rejected(self):
        # Booleans subclass int — must NOT be accepted as qty.
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[["A", True]],
        ))
        codes = {e.code for e in result.errors}
        assert "qty_not_numeric" in codes


# ===========================================================================
# 4. Row skipping — blanks, footers
# ===========================================================================

class TestRowSkipping:
    def test_blank_row_skipped_and_recorded(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[
                ["A", 10],
                [None, None],
                ["", "   "],
                ["B", 20],
            ],
        ))
        assert result.skipped_rows == (1, 2)
        assert {r.item_no for r in result.rows} == {"A", "B"}

    def test_footer_total_row_skipped(self):
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[
                ["A", 10],
                ["B", 20],
                ["Total", 30],
                ["Grand Total", 99],
                ["sum", 1],
                ["Totals", 99],
            ],
        ))
        assert result.skipped_rows == (2, 3, 4, 5)
        assert {r.item_no for r in result.rows} == {"A", "B"}


# ===========================================================================
# 5. Determinism — year-qualified labels are clock-independent
# ===========================================================================

class TestDeterminism:
    def test_same_input_same_output(self):
        sheet = _sheet(
            header=["Item", "2026-W15", "2026-04"],
            data=[["A", 10, 20]],
        )
        r1 = parse_coloplast_sheet(sheet)
        r2 = parse_coloplast_sheet(sheet)
        assert r1 == r2

    def test_year_qualified_weekly_is_not_clock_sensitive(self):
        # ISO week 2026-W15 is a fixed calendar anchor; it must resolve
        # to the same Monday regardless of today's date.
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[["A", 10]],
        ))
        assert result.rows[0].period_start == date.fromisocalendar(2026, 15, 1)

    def test_item_whitespace_is_preserved_not_coerced(self):
        # Whitespace in item_no is trimmed by _read_str, but internal
        # whitespace stays as-is (no silent normalization).
        result = parse_coloplast_sheet(_sheet(
            header=["Item", "2026-W15"],
            data=[["  A 1  ", 10]],
        ))
        assert result.rows[0].item_no == "A 1"


# ===========================================================================
# 6. Separation from inventory-count staging and sales workflow
# ===========================================================================

class TestSeparationFromInventoryStaging:
    def test_planning_package_does_not_import_inventory_staging(self):
        """workflows/planning must not touch workflows/inventory/planning/staging."""
        backend_root = Path(__file__).resolve().parent.parent
        planning_root = backend_root / "workflows" / "planning"
        offenders = []
        needles = (
            "workflows.inventory.planning.staging",
            "from workflows.inventory.planning import staging",
            "STAGING_COLL",
            "inv_import_staging",
            "inv_xls_learned_mappings",
        )
        for py in planning_root.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
        assert offenders == [], (
            "workflows/planning must stay separate from the inventory-count "
            "staging lane. Offenders:\n  " + "\n  ".join(offenders)
        )

    def test_planning_package_does_not_touch_sales_workflow(self):
        backend_root = Path(__file__).resolve().parent.parent
        planning_root = backend_root / "workflows" / "planning"
        needles = (
            "so_rules_engine",
            "document_readiness_service",
            "hub_documents",
            "workflow_engine",
            "business_central_service",
            "evaluate_and_persist",
        )
        offenders = []
        for py in planning_root.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
        assert offenders == [], (
            "workflows/planning must not touch sales workflow / posting logic. "
            "Offenders:\n  " + "\n  ".join(offenders)
        )

    def test_inventory_staging_lane_remains_authoritative(self):
        """Sanity: the live inventory-count staging module still exists
        with its public symbols intact — Step 8 did not touch it."""
        from workflows.inventory.planning import staging as inv_staging
        assert hasattr(inv_staging, "STAGING_COLL")
        assert inv_staging.STAGING_COLL == "inv_import_staging"


# ===========================================================================
# 7. Unwired guardrail
# ===========================================================================

class TestUnwiredGuardrail:
    def test_no_external_imports_of_planning_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "planning",
            backend_root / "tests" / "test_planning_coloplast_parser.py",
            backend_root / "tests" / "test_planning_validator.py",
        )
        needles = (
            "workflows.planning",
            "from workflows import planning",
        )
        offenders = []
        for py in backend_root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            if any(str(py).startswith(str(p)) for p in allowed_prefixes):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
                    break
        assert offenders == [], (
            "workflows.planning must stay UNWIRED in Step 8. "
            "Offenders:\n  " + "\n  ".join(offenders)
        )

    def test_no_llm_references_in_package(self):
        """The declaration says 'strictly deterministic, no LLM'. Guard
        against future drift."""
        backend_root = Path(__file__).resolve().parent.parent
        planning_root = backend_root / "workflows" / "planning"
        needles = (
            "emergentintegrations",
            "LlmChat",
            "openai",
            "anthropic",
            "gemini",
            "EMERGENT_LLM_KEY",
        )
        offenders = []
        for py in planning_root.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            lower = text.lower()
            for needle in needles:
                if needle.lower() in lower:
                    offenders.append(f"{py} -> {needle!r}")
        assert offenders == [], (
            "workflows/planning must remain LLM-free. Offenders:\n  "
            + "\n  ".join(offenders)
        )
