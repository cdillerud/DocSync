"""Tests for Sales Order subtype classification (DS vs WH)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.document_intel_helpers import _classify_so_subtype


class TestSOSubtypeClassification:
    """Test _classify_so_subtype returns correct subtypes."""

    def test_dropship_keyword_in_text(self):
        """PO with 'drop ship' in raw text → DS_Sales_Order."""
        doc = {"raw_text": "Please drop ship directly to customer address in Dallas TX"}
        ef = {"ship_to": "Customer Inc, 123 Main St, Dallas TX"}
        assert _classify_so_subtype(doc, ef) == "DS_Sales_Order"

    def test_dropship_keyword_variations(self):
        """Various DS keyword forms should all return DS_Sales_Order."""
        for kw in ["drop ship", "dropship", "drop-ship", "direct ship", "ship direct"]:
            doc = {"raw_text": f"This order is {kw} to end customer"}
            assert _classify_so_subtype(doc, {}) == "DS_Sales_Order", f"Failed for keyword: {kw}"

    def test_warehouse_location_code_msc(self):
        """Ship-to location code 'MSC' → WH_Sales_Order."""
        doc = {"raw_text": "Standard warehouse order"}
        ef = {"ship_to_location_code": "MSC", "ship_to": ""}
        assert _classify_so_subtype(doc, ef) == "WH_Sales_Order"

    def test_warehouse_location_code_main(self):
        """Ship-to location code 'MAIN' → WH_Sales_Order."""
        doc = {}
        ef = {"location_code": "MAIN"}
        assert _classify_so_subtype(doc, ef) == "WH_Sales_Order"

    def test_warehouse_location_codes_all(self):
        """All default WH codes should trigger WH_Sales_Order."""
        for code in ["MSC", "00", "65", "MAIN", "WH"]:
            doc = {}
            ef = {"ship_to_location_code": code}
            assert _classify_so_subtype(doc, ef) == "WH_Sales_Order", f"Failed for code: {code}"

    def test_warehouse_gpi_address(self):
        """Ship-to containing 'gamer packaging' → WH_Sales_Order."""
        doc = {}
        ef = {"ship_to_address": "Gamer Packaging Inc, 1234 Industrial Blvd, Minneapolis MN"}
        assert _classify_so_subtype(doc, ef) == "WH_Sales_Order"

    def test_warehouse_gpi_patterns(self):
        """Various GPI address patterns → WH_Sales_Order."""
        for pat in ["Gamer Packaging", "GPI Warehouse", "Minneapolis Warehouse"]:
            doc = {}
            ef = {"ship_to_name": pat}
            assert _classify_so_subtype(doc, ef) == "WH_Sales_Order", f"Failed for: {pat}"

    def test_external_shipto_is_dropship(self):
        """Non-GPI ship-to address (external customer) → DS_Sales_Order."""
        doc = {}
        ef = {"ship_to": "ABC Corp, 555 Oak Ave, Chicago IL 60601"}
        assert _classify_so_subtype(doc, ef) == "DS_Sales_Order"

    def test_ambiguous_returns_sales_order(self):
        """No text, no ship-to, no location → Sales_Order (unchanged)."""
        doc = {}
        ef = {}
        assert _classify_so_subtype(doc, ef) == "Sales_Order"

    def test_empty_doc_returns_sales_order(self):
        """Completely empty inputs → Sales_Order."""
        assert _classify_so_subtype({}, {}) == "Sales_Order"

    def test_never_raises(self):
        """Even with bad input types, should return Sales_Order."""
        assert _classify_so_subtype(None, None) == "Sales_Order"
        assert _classify_so_subtype("bad", 123) == "Sales_Order"

    def test_ds_keyword_priority_over_wh_location(self):
        """DS keyword takes priority even if location code is WH."""
        doc = {"raw_text": "drop ship this order please"}
        ef = {"ship_to_location_code": "MSC"}
        # DS keywords have higher priority (Rule 1 before Rule 2)
        assert _classify_so_subtype(doc, ef) == "DS_Sales_Order"

    def test_description_field_checked(self):
        """DS keyword in 'description' extracted field → DS_Sales_Order."""
        doc = {}
        ef = {"description": "This is a drop-ship order for the customer"}
        assert _classify_so_subtype(doc, ef) == "DS_Sales_Order"
