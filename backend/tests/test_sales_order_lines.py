"""Tests for Sales Order line creation logic."""
import pytest
from routers.gpi_integration import _resolve_sales_lines


def _make_doc(line_items=None, amount=None, description=None):
    """Helper to create a minimal document dict."""
    doc = {"extracted_fields": {}, "normalized_fields": {}}
    if line_items is not None:
        doc["extracted_fields"]["line_items"] = line_items
    if amount is not None:
        doc["normalized_fields"]["amount"] = amount
    if description is not None:
        doc["extracted_fields"]["description"] = description
    return doc


class TestResolveSalesLines:
    """Tests for the _resolve_sales_lines helper."""

    def test_extracted_lines_mapped(self):
        """Extracted line items should be mapped to resolved lines."""
        doc = _make_doc(line_items=[
            {"description": "Widget A", "quantity": 10, "unit_price": 5.0, "total": 50.0},
            {"description": "Widget B", "quantity": 3, "unit_price": 12.0, "total": 36.0},
        ])
        lines = _resolve_sales_lines(doc)
        assert len(lines) == 2
        assert lines[0]["description"] == "Widget A"
        assert lines[0]["quantity"] == 10.0
        assert lines[0]["unitPrice"] == 5.0
        assert lines[0]["source"] == "extracted"
        assert lines[1]["description"] == "Widget B"

    def test_extracted_line_with_item_number(self):
        """Line with item_number should be mapped as Item type."""
        doc = _make_doc(line_items=[
            {"description": "Item XYZ", "item_number": "ITEM001", "quantity": 2, "unit_price": 100},
        ])
        lines = _resolve_sales_lines(doc)
        assert len(lines) == 1
        assert lines[0]["lineType"] == "Item"
        assert lines[0]["lineObjectNumber"] == "ITEM001"

    def test_extracted_line_without_item_number(self):
        """Line without item_number should be Comment type."""
        doc = _make_doc(line_items=[
            {"description": "Some service", "quantity": 1, "unit_price": 500},
        ])
        lines = _resolve_sales_lines(doc)
        assert lines[0]["lineType"] == "Comment"
        assert lines[0]["lineObjectNumber"] == ""

    def test_unit_price_derived_from_total(self):
        """If no unit_price but total exists, derive it."""
        doc = _make_doc(line_items=[
            {"description": "Bulk", "quantity": 4, "total": 100},
        ])
        lines = _resolve_sales_lines(doc)
        assert lines[0]["unitPrice"] == 25.0

    def test_no_lines_no_amount_returns_empty(self):
        """No lines and no amount → empty list (blocks creation)."""
        doc = _make_doc()
        lines = _resolve_sales_lines(doc)
        assert lines == []

    def test_fallback_with_amount_only(self):
        """No lines but amount exists → fallback comment line."""
        doc = _make_doc(amount=1500.0, description="Freight charge")
        lines = _resolve_sales_lines(doc)
        assert len(lines) == 1
        assert lines[0]["quantity"] == 1
        assert lines[0]["unitPrice"] == 1500.0
        assert lines[0]["source"].startswith("fallback")
        assert "Freight charge" in lines[0]["description"]

    def test_description_truncated(self):
        """Long descriptions should be truncated to 100 chars."""
        long_desc = "A" * 200
        doc = _make_doc(line_items=[
            {"description": long_desc, "quantity": 1, "unit_price": 10},
        ])
        lines = _resolve_sales_lines(doc)
        assert len(lines[0]["description"]) <= 100

    def test_empty_line_items_treated_as_no_lines(self):
        """Empty line_items list should trigger fallback."""
        doc = _make_doc(line_items=[], amount=999.0)
        lines = _resolve_sales_lines(doc)
        assert len(lines) == 1
        assert lines[0]["source"].startswith("fallback")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
