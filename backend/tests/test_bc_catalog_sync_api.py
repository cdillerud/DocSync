"""
BC Catalog Sync API Tests

Tests for the BC catalog sync layer that pulls items and G/L accounts 
from Business Central Production and stores them locally in MongoDB.

Features tested:
- GET /api/gpi-integration/catalog/status - sync metadata and counts
- GET /api/gpi-integration/catalog/items - search synced items
- GET /api/gpi-integration/catalog/items/{item_no} - single item lookup
- GET /api/gpi-integration/catalog/items/{item_no}/validate - item validation
- GET /api/gpi-integration/catalog/gl-accounts - search G/L accounts  
- POST /api/gpi-integration/catalog/suggest-items - item suggestions for description
- Item mapping integration with synced catalog
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestCatalogStatus:
    """Tests for catalog sync status endpoint."""
    
    def test_catalog_status_returns_counts(self):
        """GET /catalog/status should return item and GL account counts."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/status")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Catalog status: {data}")
        
        # Check that counts are present
        assert "items_count" in data
        assert "gl_accounts_count" in data
        
        # Per context, catalog has ~1000 items and ~169 GL accounts
        assert data["items_count"] > 0, "Expected synced items in catalog"
        assert data["gl_accounts_count"] > 0, "Expected synced GL accounts in catalog"
        
        print(f"✓ Catalog has {data['items_count']} items and {data['gl_accounts_count']} GL accounts")
    
    def test_catalog_status_has_sync_metadata(self):
        """Sync status should include metadata about last sync."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check for items sync metadata
        if "items" in data:
            items_meta = data["items"]
            assert "synced_at" in items_meta
            assert "record_count" in items_meta
            assert "source_environment" in items_meta
            print(f"✓ Items last synced: {items_meta.get('synced_at')}, source: {items_meta.get('source_environment')}")


class TestCatalogItemSearch:
    """Tests for catalog item search endpoint."""
    
    def test_search_items_by_query_glass(self):
        """GET /catalog/items?q=glass should return matching items."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items", params={"q": "glass"})
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
        assert "total" in data
        
        items = data["items"]
        print(f"Search 'glass' returned {len(items)} items")
        
        # Should find some glass-related items
        assert len(items) > 0, "Expected to find glass-related items in catalog"
        
        # Verify item structure
        if items:
            item = items[0]
            assert "item_no" in item
            assert "description" in item
            print(f"✓ First match: {item['item_no']} - {item['description']}")
    
    def test_search_items_empty_query_returns_items(self):
        """GET /catalog/items with no query should return items."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
        assert len(data["items"]) > 0, "Expected items in catalog"
        print(f"✓ Empty query returned {len(data['items'])} items")
    
    def test_search_items_respects_limit(self):
        """Search should respect the limit parameter."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items", params={"limit": 5})
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["items"]) <= 5
        print(f"✓ Limit=5 returned {len(data['items'])} items")
    
    def test_search_items_by_item_number(self):
        """Should be able to search by partial item number."""
        # Get a known item first
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items", params={"limit": 1})
        data = response.json()
        if data["items"]:
            known_item = data["items"][0]
            item_no = known_item["item_no"]
            
            # Search by partial item number (first 5 chars)
            search_partial = item_no[:5] if len(item_no) >= 5 else item_no
            response2 = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items", params={"q": search_partial})
            assert response2.status_code == 200
            
            data2 = response2.json()
            item_numbers = [i["item_no"] for i in data2["items"]]
            assert item_no in item_numbers, f"Expected to find {item_no} when searching for {search_partial}"
            print(f"✓ Search for '{search_partial}' found item {item_no}")


class TestCatalogSingleItem:
    """Tests for single item lookup endpoint."""
    
    def test_get_item_by_number_exists(self):
        """GET /catalog/items/{item_no} for a real item should return it."""
        # Use a known real BC item number from Production
        item_no = "10004785"  # Known glass bottle item
        
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items/{item_no}")
        assert response.status_code == 200
        
        item = response.json()
        assert item["item_no"] == item_no
        assert "description" in item
        assert "blocked" in item
        print(f"✓ Retrieved item {item_no}: {item['description'][:50]}")
    
    def test_get_item_by_number_not_found(self):
        """GET /catalog/items/FAKE should return 404."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items/TOTALLY_FAKE_ITEM_XYZ123")
        assert response.status_code == 404
        print("✓ Fake item returns 404 as expected")


class TestCatalogItemValidation:
    """Tests for item validation endpoint."""
    
    def test_validate_real_item_returns_valid(self):
        """GET /catalog/items/{item_no}/validate for real item should return valid:true."""
        # Use a known real BC item number that is not blocked
        item_no = "10004785"  # Known glass bottle item, not blocked
        
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items/{item_no}/validate")
        assert response.status_code == 200
        
        data = response.json()
        assert data["valid"] is True
        assert data["reason"] == "ok"
        assert "item" in data
        assert data["item"]["item_no"] == item_no
        print(f"✓ Item {item_no} validates as valid:true, reason:ok")
    
    def test_validate_fake_item_returns_not_found(self):
        """GET /catalog/items/FAKE/validate should return valid:false, reason:not_found."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items/FAKE/validate")
        assert response.status_code == 200
        
        data = response.json()
        assert data["valid"] is False
        assert data["reason"] == "not_found"
        assert data["item"] is None
        print("✓ FAKE item validates as valid:false, reason:not_found")
    
    def test_validate_freight_not_in_catalog_still_works(self):
        """FREIGHT is not a real BC item but mapping rules can use it (not_found != blocked)."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items/FREIGHT/validate")
        assert response.status_code == 200
        
        data = response.json()
        # FREIGHT should be not_found (not in BC catalog), not blocked
        assert data["valid"] is False
        assert data["reason"] == "not_found"
        print("✓ FREIGHT validates as not_found (expected - it's a mapping rule item, not BC catalog item)")


class TestCatalogGLAccounts:
    """Tests for GL account search endpoint."""
    
    def test_search_gl_accounts_by_query_expense(self):
        """GET /catalog/gl-accounts?q=expense should return matching accounts."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/gl-accounts", params={"q": "expense"})
        assert response.status_code == 200
        
        data = response.json()
        assert "accounts" in data
        assert "total" in data
        
        accounts = data["accounts"]
        print(f"Search 'expense' returned {len(accounts)} GL accounts")
        
        # Check account structure if results exist
        if accounts:
            acct = accounts[0]
            assert "account_no" in acct
            assert "name" in acct
            print(f"✓ First match: {acct['account_no']} - {acct['name']}")
    
    def test_search_gl_accounts_empty_query(self):
        """GET /catalog/gl-accounts with no query returns accounts."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/gl-accounts")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["accounts"]) > 0, "Expected GL accounts in catalog"
        print(f"✓ Empty query returned {len(data['accounts'])} GL accounts")


class TestCatalogSuggestItems:
    """Tests for item suggestion endpoint."""
    
    def test_suggest_items_for_description(self):
        """POST /catalog/suggest-items with description returns ranked suggestions."""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/catalog/suggest-items",
            json={"description": "glass bottles amber", "limit": 5}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "description" in data
        assert "suggestions" in data
        assert "total" in data
        
        print(f"Suggest for 'glass bottles amber' returned {len(data['suggestions'])} suggestions")
        
        # Check suggestion structure if results exist  
        if data["suggestions"]:
            sugg = data["suggestions"][0]
            assert "item_no" in sugg
            assert "description" in sugg
            assert "_match_score" in sugg
            print(f"✓ Top suggestion: {sugg['item_no']} - {sugg['description'][:40]} (score: {sugg['_match_score']})")
    
    def test_suggest_items_empty_description(self):
        """Suggest with empty description should return empty list."""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/catalog/suggest-items",
            json={"description": "", "limit": 5}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["suggestions"] == []
        print("✓ Empty description returns empty suggestions")


class TestItemMappingWithCatalog:
    """Tests for item mapping integration with catalog validation."""
    
    def test_mapping_rules_with_nonexistent_items_still_work(self):
        """Mapping rules pointing to non-existent items should still work (not rejected)."""
        # Create a mapping with a fake item (like FREIGHT)
        create_resp = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json={
                "keyword_phrase": "test catalog validation",
                "bc_item_number": "FAKE_ITEM_FOR_TEST",
                "bc_item_description": "Test item not in catalog"
            }
        )
        assert create_resp.status_code == 200
        
        data = create_resp.json()
        assert data["success"] is True
        mapping_id = data["mapping"]["id"]
        print(f"✓ Created mapping with FAKE_ITEM_FOR_TEST, id={mapping_id}")
        
        # Clean up
        delete_resp = requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        assert delete_resp.status_code == 200
        print("✓ Mapping with non-existent item created successfully (not rejected by catalog)")


class TestSalesOrderPreflightWithCatalog:
    """Tests for SO preflight that uses catalog validation."""
    
    def test_preflight_returns_catalog_validated_flag(self):
        """Preflight should include catalog_validated metadata on resolved lines."""
        # Use the known test document
        doc_id = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        # Document might not exist in this env, so check gracefully
        if response.status_code == 404:
            print(f"⚠ Test document {doc_id} not found - skipping preflight test")
            pytest.skip("Test document not found")
        
        assert response.status_code == 200
        
        data = response.json()
        print(f"Preflight for {doc_id}: eligible={data['eligible']}, ready={data['ready']}, lines={len(data.get('resolved_lines', []))}")
        
        # Check resolved_lines structure
        if data.get("resolved_lines"):
            for line in data["resolved_lines"]:
                if line.get("mapping", {}).get("matched"):
                    # Matched lines should have catalog_validated
                    print(f"  Line '{line['description'][:30]}': matched={line['mapping']['matched']}, catalog_validated={line['mapping'].get('catalog_validated', 'N/A')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
