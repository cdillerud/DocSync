"""
Unit tests for the Vendor Alias Learning Service.

Tests cover:
  - Normalization (via vendor_name_helpers)
  - Alias learning from approvals (safety rules, creation, reinforcement, conflicts)
  - Alias lookup with usage tracking
  - Metrics computation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from services.vendor_name_helpers import normalize_vendor_name


# ---------------------------------------------------------------------------
# 1. Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizeVendorName:
    def test_basic_lowercase(self):
        assert normalize_vendor_name("ABC Corp") == "abc"

    def test_remove_llc(self):
        assert normalize_vendor_name("ABC Industrial Supply LLC") == "abc industrial supply"

    def test_remove_inc(self):
        assert normalize_vendor_name("Acme Inc.") == "acme"

    def test_remove_ltd(self):
        assert normalize_vendor_name("Global Trading Ltd") == "global trading"

    def test_remove_corporation(self):
        assert normalize_vendor_name("Big Corporation") == "big"

    def test_remove_company(self):
        assert normalize_vendor_name("Smith & Company") == "smith"

    def test_remove_co(self):
        assert normalize_vendor_name("Jones Co.") == "jones"

    def test_strip_punctuation(self):
        assert normalize_vendor_name("ABC Industrial Supply – Midwest Division") == "abc industrial supply midwest division"

    def test_multiple_spaces(self):
        assert normalize_vendor_name("  ABC   Industrial  ") == "abc industrial"

    def test_empty(self):
        assert normalize_vendor_name("") == ""

    def test_none(self):
        assert normalize_vendor_name(None) == ""

    def test_preserves_meaningful_words(self):
        result = normalize_vendor_name("Tumalo Creek Transportation")
        assert result == "tumalo creek transportation"


# ---------------------------------------------------------------------------
# 2. Alias learning tests
# ---------------------------------------------------------------------------

class TestLearnAliasFromApproval:
    @pytest.mark.asyncio
    async def test_learns_new_alias(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        doc = {
            "vendor_raw": "ABC Industrial Supply Midwest",
            "ai_confidence": 0.95,
        }

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="ABC Industrial Supply LLC")

        assert result is not None
        assert result["vendor_id"] == "V123"
        assert result["source"] == "auto_learned"
        mock_col.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_low_confidence(self):
        mock_db = MagicMock()
        mock_db.vendor_aliases = MagicMock()

        doc = {
            "vendor_raw": "ABC Industrial",
            "ai_confidence": 0.5,  # Below threshold
        }

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="ABC")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_empty_vendor_raw(self):
        mock_db = MagicMock()
        mock_db.vendor_aliases = MagicMock()

        doc = {"vendor_raw": "", "ai_confidence": 0.95}

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="ABC")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_identical_normalized(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        doc = {
            "vendor_raw": "ABC Industrial Supply LLC",
            "ai_confidence": 0.95,
        }

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(
                doc, vendor_id="V123", vendor_name="ABC Industrial Supply"
            )

        # Both normalize to "abc industrial supply" — no alias needed
        assert result is None

    @pytest.mark.asyncio
    async def test_reinforces_existing_alias(self):
        existing_alias = {
            "normalized_alias": "abc industrial supply midwest",
            "vendor_id": "V123",
            "usage_count": 3,
        }
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=existing_alias)
        mock_col.update_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        doc = {
            "vendor_raw": "ABC Industrial Supply Midwest",
            "ai_confidence": 0.95,
        }

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="ABC")

        assert result is not None
        assert result["usage_count"] == 4
        mock_col.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_conflicting_alias(self):
        existing_alias = {
            "normalized_alias": "abc industrial supply midwest",
            "vendor_id": "V999",  # Different vendor
            "usage_count": 5,
        }
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=existing_alias)

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        doc = {
            "vendor_raw": "ABC Industrial Supply Midwest",
            "ai_confidence": 0.95,
        }

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import learn_alias_from_approval
            result = await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="ABC")

        assert result is None


# ---------------------------------------------------------------------------
# 3. Alias lookup tests
# ---------------------------------------------------------------------------

class TestLookupAndTrackAlias:
    @pytest.mark.asyncio
    async def test_found_alias(self):
        alias = {
            "normalized_alias": "abc industrial supply midwest",
            "vendor_id": "V123",
            "vendor_name": "ABC Industrial Supply LLC",
            "vendor_no": "V123",
            "source": "auto_learned",
        }
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=alias)
        mock_col.update_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import lookup_and_track_alias
            result = await lookup_and_track_alias("ABC Industrial Supply Midwest")

        assert result is not None
        assert result["vendor_id"] == "V123"
        assert result["match_method"] == "learned_alias"
        mock_col.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_alias_found(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.vendor_aliases = mock_col

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import lookup_and_track_alias
            result = await lookup_and_track_alias("Unknown Vendor XYZ")

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_short_input(self):
        mock_db = MagicMock()
        mock_db.vendor_aliases = MagicMock()

        with patch("services.vendor_alias_learning_service.get_db", return_value=mock_db):
            from services.vendor_alias_learning_service import lookup_and_track_alias
            result = await lookup_and_track_alias("AB")

        assert result is None
