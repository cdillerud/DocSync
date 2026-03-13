"""Tests for Sales Order line creation logic (async with item mapping)."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from routers.gpi_integration import _resolve_sales_lines


def _make_doc(line_items=None, amount=None, description=None):
    """Helper to create a minimal document dict."""
    doc = {"extracted_fields": {}, "normalized_fields": {}, "id": "test-doc-001"}
    if line_items is not None:
        doc["extracted_fields"]["line_items"] = line_items
    if amount is not None:
        doc["normalized_fields"]["amount"] = amount
    if description is not None:
        doc["extracted_fields"]["description"] = description
    return doc


def _mock_db():
    """Return a mock DB where item mapping finds nothing (no mappings configured)."""
    db = MagicMock()
    find_mock = MagicMock()
    find_mock.sort = MagicMock(return_value=find_mock)
    find_mock.to_list = AsyncMock(return_value=[])

    history_coll = MagicMock()
    history_coll.find_one = AsyncMock(return_value=None)

    def get_coll(name):
        if name == "bc_item_mapping_history":
            return history_coll
        mock_coll = MagicMock()
        mock_coll.find = MagicMock(return_value=find_mock)
        return mock_coll

    db.__getitem__ = MagicMock(side_effect=get_coll)
    return db


class TestResolveSalesLines:
    """Tests for the async _resolve_sales_lines helper."""

    @pytest.mark.asyncio
    async def test_extracted_lines_mapped(self):
        """Extracted line items should be resolved."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[
                {"description": "Widget A", "quantity": 10, "unit_price": 5.0, "total": 50.0},
                {"description": "Widget B", "quantity": 3, "unit_price": 12.0, "total": 36.0},
            ])
            lines = await _resolve_sales_lines(doc)
            assert len(lines) == 2
            assert lines[0]["description"] == "Widget A"
            assert lines[0]["quantity"] == 10.0
            assert lines[0]["unitPrice"] == 5.0
            assert lines[1]["description"] == "Widget B"

    @pytest.mark.asyncio
    async def test_extracted_line_with_item_number(self):
        """Line with item_number should be mapped as Item type via extracted_sku."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[
                {"description": "Item XYZ", "item_number": "ITEM001", "quantity": 2, "unit_price": 100},
            ])
            lines = await _resolve_sales_lines(doc)
            assert len(lines) == 1
            assert lines[0]["lineType"] == "Item"
            assert lines[0]["mapping"]["item_number"] == "ITEM001"

    @pytest.mark.asyncio
    async def test_extracted_line_without_item_number(self):
        """Line without item_number and no mapping → Comment type."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[
                {"description": "Some service", "quantity": 1, "unit_price": 500},
            ])
            lines = await _resolve_sales_lines(doc)
            assert lines[0]["lineType"] == "Comment"
            assert lines[0]["lineObjectNumber"] == ""

    @pytest.mark.asyncio
    async def test_unit_price_derived_from_total(self):
        """If no unit_price but total exists, derive it."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[
                {"description": "Bulk", "quantity": 4, "total": 100},
            ])
            lines = await _resolve_sales_lines(doc)
            assert lines[0]["unitPrice"] == 25.0

    @pytest.mark.asyncio
    async def test_no_lines_no_amount_returns_empty(self):
        """No lines and no amount → empty list (blocks creation)."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc()
            lines = await _resolve_sales_lines(doc)
            assert lines == []

    @pytest.mark.asyncio
    async def test_fallback_with_amount_only(self):
        """No lines but amount exists → fallback line."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(amount=1500.0, description="Freight charge")
            lines = await _resolve_sales_lines(doc)
            assert len(lines) == 1
            assert lines[0]["quantity"] == 1
            assert lines[0]["unitPrice"] == 1500.0
            assert lines[0]["source"].startswith("fallback")
            assert "Freight charge" in lines[0]["description"]

    @pytest.mark.asyncio
    async def test_description_truncated(self):
        """Long descriptions should be truncated to 100 chars."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            long_desc = "A" * 200
            doc = _make_doc(line_items=[
                {"description": long_desc, "quantity": 1, "unit_price": 10},
            ])
            lines = await _resolve_sales_lines(doc)
            assert len(lines[0]["description"]) <= 100

    @pytest.mark.asyncio
    async def test_empty_line_items_treated_as_no_lines(self):
        """Empty line_items list should trigger fallback."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[], amount=999.0)
            lines = await _resolve_sales_lines(doc)
            assert len(lines) == 1
            assert lines[0]["source"].startswith("fallback")

    @pytest.mark.asyncio
    async def test_mapping_metadata_present(self):
        """Each resolved line should include mapping metadata."""
        with patch("routers.gpi_integration.get_db", return_value=_mock_db()):
            doc = _make_doc(line_items=[
                {"description": "Test", "quantity": 1, "unit_price": 10},
            ])
            lines = await _resolve_sales_lines(doc)
            assert "mapping" in lines[0]
            assert "matched" in lines[0]["mapping"]
            assert "confidence" in lines[0]["mapping"]
            assert "method" in lines[0]["mapping"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
