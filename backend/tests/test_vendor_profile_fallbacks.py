"""
Tests for vendor-profile line-pattern fallback chain.

Fix targets the XPOLOGI-class bug: vendor has 1108 posted BC invoices, but
profile builder returns `default_gl_account: ""` because the open/draft
``purchaseInvoices`` endpoint yields 0 results for a vendor whose invoices
are always immediately posted. Every line then falls through to env_default
GL with a `default_fallback` warning on every preflight.

Fallback chain now:
  A. open/draft purchaseInvoices     (pre-existing)
  B. postedPurchaseInvoices          (NEW)
  C. local bc_pi_lines_posted        (NEW)
  D. bc_reference_cache stats only   (header-level — no lines)
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.vendor_invoice_profile_service import (
    _extract_lines_from_local_history,
    _analyze_line_patterns,
    build_vendor_profile,
)


# ---------------------------------------------------------------------------
# _extract_lines_from_local_history — pure function
# ---------------------------------------------------------------------------

class TestExtractLinesFromLocalHistory:
    def test_empty_history_returns_empty(self):
        assert _extract_lines_from_local_history([]) == []

    def test_doc_without_lines_is_skipped(self):
        docs = [{"bc_purchase_invoice": {"success": True}}]
        assert _extract_lines_from_local_history(docs) == []

    def test_populated_doc_becomes_synthetic_invoice(self):
        docs = [{
            "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-001"},
            "normalized_fields": {"amount": 649.97},
            "bc_pi_lines_posted": [
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "Freight", "quantity": 1, "unitCost": 649.97},
            ],
        }]
        synthetic = _extract_lines_from_local_history(docs)
        assert len(synthetic) == 1
        assert synthetic[0]["number"] == "PI-001"
        assert synthetic[0]["totalAmountIncludingTax"] == 649.97
        assert len(synthetic[0]["purchaseInvoiceLines"]) == 1
        assert synthetic[0]["purchaseInvoiceLines"][0]["lineObjectNumber"] == "60500"

    def test_synthetic_feeds_line_pattern_analyzer(self):
        """End-to-end: local history -> _analyze_line_patterns produces a
        usable default_gl_account. This is the core regression for the
        XPOLOGI empty-GL bug."""
        docs = [
            {
                "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-1"},
                "normalized_fields": {"amount": 100.0},
                "bc_pi_lines_posted": [
                    {"lineType": "Account", "lineObjectNumber": "60500",
                     "description": "Freight", "quantity": 1, "unitCost": 100.0},
                ],
            },
            {
                "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-2"},
                "normalized_fields": {"amount": 200.0},
                "bc_pi_lines_posted": [
                    {"lineType": "Account", "lineObjectNumber": "60500",
                     "description": "Freight", "quantity": 1, "unitCost": 200.0},
                ],
            },
            {
                "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-3"},
                "normalized_fields": {"amount": 50.0},
                "bc_pi_lines_posted": [
                    {"lineType": "Account", "lineObjectNumber": "55000",
                     "description": "Fuel surcharge", "quantity": 1, "unitCost": 50.0},
                ],
            },
        ]
        synthetic = _extract_lines_from_local_history(docs)
        patterns = _analyze_line_patterns(synthetic)
        # Dominant GL should be 60500 (2 occurrences vs 55000's 1)
        assert patterns["dominant_line_type"] == "Account"
        assert patterns["common_gl_accounts"][0]["account"] == "60500"
        assert patterns["common_gl_accounts"][0]["count"] == 2


# ---------------------------------------------------------------------------
# build_vendor_profile — fallback chain integration
# ---------------------------------------------------------------------------

class _MockCollection:
    """Minimal in-memory collection to satisfy build_vendor_profile's Mongo calls."""
    def __init__(self):
        self._storage = {}

    async def find_one(self, query, projection=None):
        key = query.get("vendor_no")
        return self._storage.get(key)

    async def update_one(self, query, update, upsert=False):
        key = query.get("vendor_no")
        self._storage[key] = update.get("$set", {})
        return None

    def aggregate(self, pipeline, **kwargs):
        class _Empty:
            async def to_list(self, length):
                return []
        return _Empty()

    async def find_anything(self):
        return []


class _MockDB:
    def __init__(self):
        self.vendor_invoice_profiles = _MockCollection()
        self.bc_reference_cache = _MockCollection()
        self.hub_documents = _MockCollection()

    def __getattr__(self, name):
        return _MockCollection()


@pytest.mark.asyncio
class TestBuildVendorProfileFallbacks:
    """Verify the fallback ladder is tried in order and produces a
    useful default_gl_account when only some sources have data."""

    @staticmethod
    def _posted_invoice_sample(gl="60500", amount=500.0):
        """Shape of a postedPurchaseInvoices response item after normalization."""
        return {
            "id": "inv-1",
            "number": "PI-XPO-001",
            "vendorInvoiceNumber": "XPO-INV-001",
            "vendorNumber": "XPOLOGI",
            "vendorName": "XPOLOGI",
            "totalAmountIncludingTax": amount,
            "postingDate": "2026-03-13",
            "purchaseInvoiceLines": [
                {"lineType": "Account", "lineObjectNumber": gl,
                 "description": "Freight charges", "quantity": 1,
                 "unitCost": amount},
            ],
        }

    async def test_posted_fallback_populates_default_gl(self):
        """When open-invoice endpoint is empty, the posted fallback runs and
        its line patterns produce a non-empty default_gl_account."""
        db = _MockDB()
        posted = [
            self._posted_invoice_sample("60500", 500.0),
            self._posted_invoice_sample("60500", 649.97),
            self._posted_invoice_sample("60500", 1200.0),
        ]

        with patch(
            "services.vendor_invoice_profile_service.fetch_vendor_card",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_invoices_from_bc",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_local_posting_history",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_posted_invoices_from_bc",
            new=AsyncMock(return_value=posted),
        ), patch(
            "services.vendor_invoice_profile_service._learn_from_reference_cache",
            new=AsyncMock(return_value=None),
        ):
            profile = await build_vendor_profile(db, "XPOLOGI", force_refresh=True)

        assert profile["default_gl_account"] == "60500", (
            f"Expected GL 60500 learned from posted invoices, "
            f"got {profile['default_gl_account']!r}"
        )
        assert profile["default_line_type"] == "Account"
        assert profile["bc_invoice_count"] == 3

    async def test_local_history_fallback_when_bc_unavailable(self):
        """When both BC endpoints are empty, our own successful postings
        become the learning source."""
        db = _MockDB()
        local = [
            {
                "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-1"},
                "normalized_fields": {"amount": 100.0},
                "bc_pi_lines_posted": [
                    {"lineType": "Account", "lineObjectNumber": "60200",
                     "description": "Freight", "quantity": 1, "unitCost": 100.0},
                ],
            },
            {
                "bc_purchase_invoice": {"success": True, "bc_record_no": "PI-2"},
                "normalized_fields": {"amount": 200.0},
                "bc_pi_lines_posted": [
                    {"lineType": "Account", "lineObjectNumber": "60200",
                     "description": "Freight", "quantity": 1, "unitCost": 200.0},
                ],
            },
        ]

        with patch(
            "services.vendor_invoice_profile_service.fetch_vendor_card",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_invoices_from_bc",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_local_posting_history",
            new=AsyncMock(return_value=local),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_posted_invoices_from_bc",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service._learn_from_reference_cache",
            new=AsyncMock(return_value=None),
        ):
            profile = await build_vendor_profile(db, "ABC-VENDOR", force_refresh=True)

        assert profile["default_gl_account"] == "60200"
        assert profile["default_line_type"] == "Account"

    async def test_no_fallbacks_yields_empty_gl_but_no_crash(self):
        """Total whiteout: all sources empty -> profile builds safely with
        empty GL (and env_default is used downstream in build_smart_pi_lines)."""
        db = _MockDB()

        with patch(
            "services.vendor_invoice_profile_service.fetch_vendor_card",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_invoices_from_bc",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_local_posting_history",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_posted_invoices_from_bc",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service._learn_from_reference_cache",
            new=AsyncMock(return_value=None),
        ):
            profile = await build_vendor_profile(db, "UNKNOWN", force_refresh=True)

        # Should not crash, empty GL is acceptable here (env_default kicks in later)
        assert profile["default_gl_account"] == ""
        assert profile["bc_invoice_count"] == 0

    async def test_open_invoices_take_precedence_over_posted(self):
        """If the open/draft endpoint has data, we do NOT call the posted
        fallback — preserves pre-fix behavior for active vendors."""
        db = _MockDB()
        open_invs = [self._posted_invoice_sample("70000", 300.0)]
        posted_mock = AsyncMock(return_value=[self._posted_invoice_sample("80000", 1.0)])

        with patch(
            "services.vendor_invoice_profile_service.fetch_vendor_card",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_invoices_from_bc",
            new=AsyncMock(return_value=open_invs),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_local_posting_history",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.vendor_invoice_profile_service.fetch_vendor_posted_invoices_from_bc",
            new=posted_mock,
        ), patch(
            "services.vendor_invoice_profile_service._learn_from_reference_cache",
            new=AsyncMock(return_value=None),
        ):
            profile = await build_vendor_profile(db, "ACTIVE-VENDOR", force_refresh=True)

        posted_mock.assert_not_called()
        assert profile["default_gl_account"] == "70000"
