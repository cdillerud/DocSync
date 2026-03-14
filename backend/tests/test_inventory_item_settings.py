"""
Inventory Item Settings API Tests

Tests for:
- POST /api/inventory-items/settings - Create/Update (upsert) item settings
- GET /api/inventory-items/settings - List item settings with customer_id and optional item filter
- Validation: negative threshold/buffer returns 422, empty item returns 422
- GET /api/inventory-ledger/reorder-recommendations - Uses item settings when configured
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test customer ID (Hormel Foods)
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


class TestItemSettingsCreate:
    """POST /api/inventory-items/settings - Create new item settings (upsert)"""
    
    def test_create_new_item_settings(self):
        """Create new item settings successfully"""
        unique_item = f"TEST_ITEM_{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item,
            "reorder_threshold": 100,
            "safety_buffer": 25,
            "notes": "Test item settings creation"
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["customer_id"] == HORMEL_CUSTOMER_ID
        assert data["item"] == unique_item
        assert data["reorder_threshold"] == 100
        assert data["safety_buffer"] == 25
        assert data["notes"] == "Test item settings creation"
        assert "created_at" in data
        assert "updated_at" in data
        print(f"SUCCESS: Created new item settings for {unique_item}")
    
    def test_create_with_zero_threshold_and_buffer(self):
        """Zero values are allowed for threshold and buffer"""
        unique_item = f"TEST_ZERO_{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item,
            "reorder_threshold": 0,
            "safety_buffer": 0,
            "notes": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["reorder_threshold"] == 0
        assert data["safety_buffer"] == 0
        print(f"SUCCESS: Zero values accepted for {unique_item}")


class TestItemSettingsUpdate:
    """POST /api/inventory-items/settings - Update existing item settings (upsert)"""
    
    def test_update_existing_item_settings(self):
        """Update existing item settings via upsert"""
        unique_item = f"TEST_UPDATE_{uuid.uuid4().hex[:8].upper()}"
        
        # Create initial settings
        create_payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item,
            "reorder_threshold": 50,
            "safety_buffer": 10,
            "notes": "Initial notes"
        }
        create_response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=create_payload)
        assert create_response.status_code == 200
        
        # Update with new values
        update_payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item,
            "reorder_threshold": 200,
            "safety_buffer": 50,
            "notes": "Updated notes"
        }
        update_response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=update_payload)
        assert update_response.status_code == 200, f"Expected 200, got {update_response.status_code}: {update_response.text}"
        
        data = update_response.json()
        assert data["reorder_threshold"] == 200
        assert data["safety_buffer"] == 50
        assert data["notes"] == "Updated notes"
        
        # Verify via GET
        get_response = requests.get(f"{BASE_URL}/api/inventory-items/settings", params={
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item
        })
        assert get_response.status_code == 200
        settings = get_response.json()["settings"]
        assert len(settings) == 1
        assert settings[0]["reorder_threshold"] == 200
        print(f"SUCCESS: Updated settings for {unique_item} - threshold: 200, buffer: 50")


class TestItemSettingsList:
    """GET /api/inventory-items/settings - List item settings"""
    
    def test_list_settings_for_workspace(self):
        """List all item settings for a customer workspace"""
        response = requests.get(f"{BASE_URL}/api/inventory-items/settings", params={
            "customer_id": HORMEL_CUSTOMER_ID
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "settings" in data
        assert "total" in data
        assert isinstance(data["settings"], list)
        assert data["total"] == len(data["settings"])
        print(f"SUCCESS: Listed {data['total']} item settings for workspace")
    
    def test_filter_by_specific_item(self):
        """Filter settings by specific item name"""
        unique_item = f"TEST_FILTER_{uuid.uuid4().hex[:8].upper()}"
        
        # Create a setting first
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item,
            "reorder_threshold": 75,
            "safety_buffer": 15,
            "notes": "Filter test"
        }
        requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        
        # Filter by item
        response = requests.get(f"{BASE_URL}/api/inventory-items/settings", params={
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": unique_item
        })
        assert response.status_code == 200
        
        data = response.json()
        assert data["total"] == 1
        assert data["settings"][0]["item"] == unique_item
        print(f"SUCCESS: Filtered settings for item {unique_item}")
    
    def test_missing_customer_id_returns_422(self):
        """Missing customer_id query param returns validation error"""
        response = requests.get(f"{BASE_URL}/api/inventory-items/settings")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("SUCCESS: Missing customer_id returns 422")


class TestItemSettingsValidation:
    """POST /api/inventory-items/settings - Validation tests"""
    
    def test_negative_threshold_returns_422(self):
        """Negative reorder_threshold returns 422"""
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": "NEG_THRESHOLD_TEST",
            "reorder_threshold": -10,
            "safety_buffer": 25,
            "notes": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "negative" in data.get("detail", "").lower() or "threshold" in data.get("detail", "").lower()
        print("SUCCESS: Negative threshold returns 422")
    
    def test_negative_buffer_returns_422(self):
        """Negative safety_buffer returns 422"""
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": "NEG_BUFFER_TEST",
            "reorder_threshold": 100,
            "safety_buffer": -5,
            "notes": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "negative" in data.get("detail", "").lower() or "buffer" in data.get("detail", "").lower()
        print("SUCCESS: Negative buffer returns 422")
    
    def test_empty_item_returns_422(self):
        """Empty item returns 422"""
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": "",
            "reorder_threshold": 100,
            "safety_buffer": 25,
            "notes": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("SUCCESS: Empty item returns 422")
    
    def test_whitespace_only_item_returns_422(self):
        """Whitespace-only item returns 422"""
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": "   ",
            "reorder_threshold": 100,
            "safety_buffer": 25,
            "notes": ""
        }
        
        response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("SUCCESS: Whitespace-only item returns 422")


class TestReorderRecommendationsWithSettings:
    """GET /api/inventory-ledger/reorder-recommendations - Uses item settings"""
    
    def test_reorder_returns_threshold_and_buffer_columns(self):
        """Reorder recommendations include threshold and buffer columns"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations", params={
            "customer_id": HORMEL_CUSTOMER_ID
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        if recommendations:
            rec = recommendations[0]
            assert "reorder_threshold" in rec, "Missing reorder_threshold in response"
            assert "safety_buffer" in rec, "Missing safety_buffer in response"
            assert "has_settings" in rec, "Missing has_settings flag in response"
            print(f"SUCCESS: Reorder recommendations include threshold ({rec['reorder_threshold']}), buffer ({rec['safety_buffer']}), has_settings ({rec['has_settings']})")
        else:
            print("SKIP: No recommendations to validate columns (healthy inventory)")
    
    def test_reorder_uses_item_settings_when_configured(self):
        """Create item setting and verify it's used in reorder recommendation"""
        # Find an item that exists in balances for Hormel
        balances_response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        balances = balances_response.json().get("balances", [])
        
        if not balances:
            pytest.skip("No balance items to test with")
        
        # Get first item that has low/short status
        target_item = None
        for b in balances:
            if b.get("is_short") or b.get("available", 0) <= 0:
                target_item = b["item"]
                break
        
        if not target_item:
            target_item = balances[0]["item"]
            print(f"Using item {target_item} (may not be in reorder list if healthy)")
        
        # Create custom settings for this item
        custom_threshold = 500
        custom_buffer = 100
        settings_payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": target_item,
            "reorder_threshold": custom_threshold,
            "safety_buffer": custom_buffer,
            "notes": "Test custom settings for reorder"
        }
        settings_response = requests.post(f"{BASE_URL}/api/inventory-items/settings", json=settings_payload)
        assert settings_response.status_code == 200
        
        # Get reorder recommendations
        reorder_response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations", params={
            "customer_id": HORMEL_CUSTOMER_ID,
            "item": target_item
        })
        assert reorder_response.status_code == 200
        
        recommendations = reorder_response.json().get("recommendations", [])
        
        # Find our item in recommendations
        matching_rec = next((r for r in recommendations if r["item"] == target_item), None)
        
        if matching_rec:
            assert matching_rec["reorder_threshold"] == custom_threshold, \
                f"Expected threshold {custom_threshold}, got {matching_rec['reorder_threshold']}"
            assert matching_rec["safety_buffer"] == custom_buffer, \
                f"Expected buffer {custom_buffer}, got {matching_rec['safety_buffer']}"
            assert matching_rec["has_settings"] == True, "Expected has_settings=true"
            
            # Verify formula: recommended_qty = max(0, threshold - available) + buffer
            expected_qty = max(0, custom_threshold - matching_rec["available"]) + custom_buffer
            assert abs(matching_rec["recommended_qty"] - expected_qty) < 0.01, \
                f"Expected recommended_qty {expected_qty}, got {matching_rec['recommended_qty']}"
            print(f"SUCCESS: Item {target_item} uses custom settings - threshold: {custom_threshold}, buffer: {custom_buffer}, recommended_qty: {matching_rec['recommended_qty']}")
        else:
            print(f"INFO: Item {target_item} not in reorder list (available > threshold)")
    
    def test_reorder_uses_defaults_when_no_settings(self):
        """Verify fallback to defaults when no item settings exist"""
        # Create a unique item with opening balance that would trigger reorder
        unique_item = f"TEST_DEFAULT_{uuid.uuid4().hex[:8].upper()}"
        
        # First check reorder endpoint
        reorder_response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations", params={
            "customer_id": HORMEL_CUSTOMER_ID
        })
        assert reorder_response.status_code == 200
        
        recommendations = reorder_response.json().get("recommendations", [])
        
        # Find items without custom settings
        for rec in recommendations:
            if not rec.get("has_settings"):
                assert rec["reorder_threshold"] == 0, f"Expected default threshold 0, got {rec['reorder_threshold']}"
                assert rec["safety_buffer"] == 10, f"Expected default buffer 10, got {rec['safety_buffer']}"
                print(f"SUCCESS: Item {rec['item']} uses defaults - threshold: 0, buffer: 10, has_settings: False")
                return
        
        print("INFO: All recommendations have custom settings or no recommendations exist")


class TestRegressionExistingEndpoints:
    """Regression tests for existing inventory functionality"""
    
    def test_balances_still_work(self):
        """GET /api/inventory-ledger/customers/{id}/balances still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert response.status_code == 200
        assert "balances" in response.json()
        print("SUCCESS: Balances endpoint still works")
    
    def test_movements_still_work(self):
        """GET /api/inventory-ledger/customers/{id}/movements still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/movements")
        assert response.status_code == 200
        assert "movements" in response.json()
        print("SUCCESS: Movements endpoint still works")
    
    def test_incoming_still_work(self):
        """GET /api/inventory-ledger/customers/{id}/incoming still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/incoming")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        print("SUCCESS: Incoming supply endpoint still works")
    
    def test_summary_still_works(self):
        """GET /api/inventory-ledger/customers/{id}/summary still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data
        assert "shortage_count" in data
        print(f"SUCCESS: Summary endpoint still works - {data['total_items']} items, {data['shortage_count']} shortages")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
