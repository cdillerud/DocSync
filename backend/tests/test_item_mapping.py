"""Tests for item mapping service and integration with SO line resolution."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from services.item_mapping_service import (
    _normalize, _tokenize, _score_mapping, map_line_to_item,
    MIN_CONFIDENCE,
)


class TestNormalize:
    def test_basic(self):
        assert _normalize("  Hello World!  ") == "hello world"

    def test_punctuation_removed(self):
        assert _normalize("Glass-ware, on skids.") == "glass ware on skids"

    def test_multiple_spaces(self):
        assert _normalize("a   b    c") == "a b c"


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Glass on Skids") == {"glass", "on", "skids"}


class TestScoreMapping:
    def _mapping(self, phrase="", keywords=None, aliases=None):
        return {
            "keyword_phrase": phrase,
            "keywords": keywords or [],
            "aliases": aliases or [],
            "bc_item_number": "ITEM001",
        }

    def test_exact_phrase_match(self):
        m = self._mapping(phrase="glassware on skids")
        score = _score_mapping("glassware on skids", {"glassware", "on", "skids"}, m)
        assert score >= 0.95

    def test_phrase_contained(self):
        m = self._mapping(phrase="glassware on skids")
        score = _score_mapping("20 cases glassware on skids wrap", {"20", "cases", "glassware", "on", "skids", "wrap"}, m)
        assert score >= 0.70

    def test_keyword_token_full_match(self):
        m = self._mapping(keywords=["glass", "skids"])
        score = _score_mapping("glass on skids", {"glass", "on", "skids"}, m)
        assert score >= 0.80

    def test_keyword_token_partial(self):
        m = self._mapping(keywords=["glass", "skids", "pallets"])
        score = _score_mapping("just glass here", {"just", "glass", "here"}, m)
        # Only 1/3 matched
        assert score < MIN_CONFIDENCE

    def test_alias_match(self):
        m = self._mapping(phrase="food grade cans", aliases=["food cans", "canned goods"])
        score = _score_mapping("food cans", {"food", "cans"}, m)
        assert score >= 0.95  # Exact alias match

    def test_no_match(self):
        m = self._mapping(phrase="totally different")
        score = _score_mapping("something else", {"something", "else"}, m)
        assert score < 0.5


class TestMapLineToItem:
    """Tests for the async map_line_to_item function."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()

        # Mock collections with proper async mocks
        def make_collection(find_results=None):
            coll = MagicMock()
            find_mock = MagicMock()
            find_mock.sort = MagicMock(return_value=find_mock)
            find_mock.to_list = AsyncMock(return_value=find_results or [])
            coll.find = MagicMock(return_value=find_mock)
            coll.find_one = AsyncMock(return_value=None)
            coll.count_documents = AsyncMock(return_value=0)
            return coll

        collections = {}
        def get_collection(name):
            if name not in collections:
                collections[name] = make_collection()
            return collections[name]

        db.__getitem__ = MagicMock(side_effect=get_collection)
        return db

    @pytest.mark.asyncio
    async def test_extracted_sku_takes_priority(self, mock_db):
        result = await map_line_to_item(mock_db, description="Some Widget", extracted_sku="WIDGET01")
        assert result["matched"] is True
        assert result["target_no"] == "WIDGET01"
        assert result["target_type"] == "item"
        assert result["line_type"] == "Item"
        assert result["method"] == "extracted_sku"
        assert result["confidence"] >= 0.9

    @pytest.mark.asyncio
    async def test_no_match_returns_unmatched(self, mock_db):
        result = await map_line_to_item(mock_db, description="random unknown item")
        assert result["matched"] is False
        assert result["target_no"] == ""
        assert result["target_type"] == "comment"
        assert result["line_type"] == "Comment"

    @pytest.mark.asyncio
    async def test_exact_mapping_match(self):
        """Test with a real mapping that matches."""
        db = MagicMock()

        mapping_data = [{
            "id": "map-1",
            "keyword_phrase": "glassware on skids",
            "keywords": [],
            "aliases": [],
            "bc_item_number": "GLASS001",
            "active": True,
            "priority": 1,
            "customer_no": "",
        }]

        find_mock = MagicMock()
        find_mock.sort = MagicMock(return_value=find_mock)
        find_mock.to_list = AsyncMock(return_value=mapping_data)

        history_coll = MagicMock()
        history_coll.find_one = AsyncMock(return_value=None)

        catalog_coll = MagicMock()
        catalog_coll.count_documents = AsyncMock(return_value=0)
        catalog_coll.find_one = AsyncMock(return_value=None)

        def get_coll(name):
            if name == "bc_item_mapping_history":
                return history_coll
            if name == "bc_catalog_items":
                return catalog_coll
            mock_coll = MagicMock()
            mock_coll.find = MagicMock(return_value=find_mock)
            return mock_coll

        db.__getitem__ = MagicMock(side_effect=get_coll)

        result = await map_line_to_item(db, description="Glassware on Skids")
        assert result["matched"] is True
        assert result["target_no"] == "GLASS001"
        assert result["target_type"] == "item"
        assert result["line_type"] == "Item"
        assert result["confidence"] >= MIN_CONFIDENCE

    @pytest.mark.asyncio
    async def test_gl_account_mapping_match(self):
        """Test that a mapping with target_type=gl_account returns Account line type."""
        db = MagicMock()

        mapping_data = [{
            "id": "map-gl-1",
            "keyword_phrase": "freight charges",
            "keywords": ["freight"],
            "aliases": ["shipping charges"],
            "target_type": "gl_account",
            "target_no": "60500",
            "bc_item_number": "60500",
            "bc_item_description": "Shipping / Delivery",
            "active": True,
            "priority": 1,
            "customer_no": "",
        }]

        find_mock = MagicMock()
        find_mock.sort = MagicMock(return_value=find_mock)
        find_mock.to_list = AsyncMock(return_value=mapping_data)

        history_coll = MagicMock()
        history_coll.find_one = AsyncMock(return_value=None)

        gl_coll = MagicMock()
        gl_coll.count_documents = AsyncMock(return_value=0)  # No catalog = skip validation

        catalog_coll = MagicMock()
        catalog_coll.count_documents = AsyncMock(return_value=0)

        def get_coll(name):
            if name == "bc_item_mapping_history":
                return history_coll
            if name == "bc_catalog_gl_accounts":
                return gl_coll
            if name == "bc_catalog_items":
                return catalog_coll
            mock_coll = MagicMock()
            mock_coll.find = MagicMock(return_value=find_mock)
            return mock_coll

        db.__getitem__ = MagicMock(side_effect=get_coll)

        result = await map_line_to_item(db, description="Freight Charges")
        assert result["matched"] is True
        assert result["target_type"] == "gl_account"
        assert result["target_no"] == "60500"
        assert result["line_type"] == "Account"
        assert result["confidence"] >= MIN_CONFIDENCE

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back(self):
        """Ambiguous description should not match."""
        db = MagicMock()

        mapping_data = [{
            "id": "map-1",
            "keyword_phrase": "very specific product name",
            "keywords": [],
            "aliases": [],
            "bc_item_number": "SPEC001",
            "active": True,
            "priority": 1,
            "customer_no": "",
        }]

        find_mock = MagicMock()
        find_mock.sort = MagicMock(return_value=find_mock)
        find_mock.to_list = AsyncMock(return_value=mapping_data)

        history_coll = MagicMock()
        history_coll.find_one = AsyncMock(return_value=None)

        catalog_coll = MagicMock()
        catalog_coll.count_documents = AsyncMock(return_value=0)
        catalog_coll.find_one = AsyncMock(return_value=None)

        def get_coll(name):
            if name == "bc_item_mapping_history":
                return history_coll
            if name == "bc_catalog_items":
                return catalog_coll
            mock_coll = MagicMock()
            mock_coll.find = MagicMock(return_value=find_mock)
            return mock_coll

        db.__getitem__ = MagicMock(side_effect=get_coll)

        result = await map_line_to_item(db, description="totally unrelated item")
        assert result["matched"] is False
        assert result["target_no"] == ""

    @pytest.mark.asyncio
    async def test_empty_description(self, mock_db):
        result = await map_line_to_item(mock_db, description="")
        assert result["matched"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
