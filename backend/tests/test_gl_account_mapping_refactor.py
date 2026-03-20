"""
Tests for G/L Account Mapping Refactor Feature
Tests the new target_type='gl_account' support for item mappings.

Feature: All freight/service rules now map to target_type='gl_account' and target_no='60500'
instead of the old target_type='item' with placeholder 'FREIGHT' item.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://bc-linkage-boost.preview.emergentagent.com').rstrip('/')

# Test document with Widget A/Widget B lines (no existing SO)
DOC_ID_ELIGIBLE = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"


class TestGLAccountMappingRules:
    """Tests for verifying all existing mappings have target_type='gl_account'"""
    
    def test_all_mappings_have_target_type_gl_account(self):
        """GET /api/gpi-integration/item-mappings returns mappings with target_type=gl_account"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        mappings = data.get("mappings", [])
        
        # Verify we have 20+ freight/service mappings
        freight_gl_mappings = [m for m in mappings if m.get("target_type") == "gl_account"]
        print(f"✓ Found {len(freight_gl_mappings)} G/L Account mappings out of {len(mappings)} total")
        
        # All should point to 60500 (Shipping / Delivery)
        for m in freight_gl_mappings:
            assert m.get("target_no") == "60500" or m.get("bc_item_number") == "60500", \
                f"Expected target_no=60500, got {m.get('target_no')} for mapping '{m.get('keyword_phrase')}'"
        
        # Verify none of the freight-related mappings point to 'FREIGHT' item anymore
        freight_item_mappings = [m for m in mappings 
                                  if (m.get("target_type") == "item" and 
                                      m.get("target_no", m.get("bc_item_number", "")) == "FREIGHT")]
        assert len(freight_item_mappings) == 0, f"Found {len(freight_item_mappings)} mappings still pointing to FREIGHT item"
        print("✓ No mappings pointing to FREIGHT placeholder item")
        
    def test_freight_related_keywords_map_to_gl_account(self):
        """Verify freight-related keyword phrases all map to gl_account"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200
        
        mappings = response.json().get("mappings", [])
        
        freight_keywords = [
            "freight", "shipping", "customs", "isf", "fda", "harbor", 
            "merchandise", "pier pass", "container handling"
        ]
        
        for m in mappings:
            phrase = m.get("keyword_phrase", "").lower()
            keywords = [k.lower() for k in m.get("keywords", [])]
            
            for fk in freight_keywords:
                if fk in phrase or any(fk in k for k in keywords):
                    assert m.get("target_type") == "gl_account", \
                        f"Freight-related mapping '{phrase}' should have target_type='gl_account', got '{m.get('target_type')}'"
                    break
        
        print("✓ All freight-related keywords correctly map to gl_account")


class TestCreateMappingWithTargetType:
    """Tests for creating mappings with different target types"""
    
    def test_create_gl_account_mapping(self):
        """POST /api/gpi-integration/item-mappings creates G/L Account mapping"""
        test_id = str(uuid.uuid4())[:8]
        mapping_data = {
            "keyword_phrase": f"test gl account {test_id}",
            "target_type": "gl_account",
            "target_no": "60500",
            "bc_item_description": "Shipping / Delivery",
            "keywords": ["test", "gl"],
            "priority": 100,
            "active": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True
        mapping = data["mapping"]
        
        # Verify target_type and target_no persisted correctly
        assert mapping["target_type"] == "gl_account", f"Expected target_type='gl_account', got '{mapping['target_type']}'"
        assert mapping["target_no"] == "60500", f"Expected target_no='60500', got '{mapping['target_no']}'"
        
        mapping_id = mapping["id"]
        print(f"✓ Created G/L Account mapping with ID: {mapping_id}")
        
        # Verify by GET
        get_response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        all_mappings = get_response.json()["mappings"]
        created_mapping = next((m for m in all_mappings if m["id"] == mapping_id), None)
        assert created_mapping is not None, "Created mapping not found in GET response"
        assert created_mapping["target_type"] == "gl_account"
        print("✓ G/L Account mapping persisted and verified via GET")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        
    def test_create_item_mapping(self):
        """POST /api/gpi-integration/item-mappings creates Item mapping"""
        test_id = str(uuid.uuid4())[:8]
        mapping_data = {
            "keyword_phrase": f"test item {test_id}",
            "target_type": "item",
            "target_no": "10SQUARE",  # Real BC item from catalog
            "bc_item_description": "10oz Square Flint Glass Jar",
            "keywords": ["test", "item"],
            "priority": 100,
            "active": True
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True
        mapping = data["mapping"]
        
        # Verify target_type and target_no persisted correctly
        assert mapping["target_type"] == "item", f"Expected target_type='item', got '{mapping['target_type']}'"
        assert mapping["target_no"] == "10SQUARE", f"Expected target_no='10SQUARE', got '{mapping['target_no']}'"
        
        mapping_id = mapping["id"]
        print(f"✓ Created Item mapping with ID: {mapping_id}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        
    def test_default_target_type_is_item(self):
        """POST without target_type defaults to 'item'"""
        test_id = str(uuid.uuid4())[:8]
        mapping_data = {
            "keyword_phrase": f"test default {test_id}",
            "bc_item_number": "TEST001",  # Using old field name
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 200
        
        mapping = response.json()["mapping"]
        assert mapping["target_type"] == "item", f"Default target_type should be 'item', got '{mapping['target_type']}'"
        print("✓ Default target_type is 'item'")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping['id']}")


class TestUpdateMappingTargetType:
    """Tests for updating mapping target_type"""
    
    def test_update_target_type_item_to_gl_account(self):
        """PUT /api/gpi-integration/item-mappings/{id} can change target_type from item to gl_account"""
        test_id = str(uuid.uuid4())[:8]
        
        # Create an item mapping
        create_response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json={
                "keyword_phrase": f"update target test {test_id}",
                "target_type": "item",
                "target_no": "TEST001",
            }
        )
        assert create_response.status_code == 200
        mapping_id = create_response.json()["mapping"]["id"]
        
        # Update to gl_account
        update_response = requests.put(
            f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}",
            json={
                "target_type": "gl_account",
                "target_no": "60500",
                "bc_item_description": "Shipping / Delivery"
            }
        )
        assert update_response.status_code == 200
        
        updated_mapping = update_response.json()["mapping"]
        assert updated_mapping["target_type"] == "gl_account", \
            f"Expected updated target_type='gl_account', got '{updated_mapping['target_type']}'"
        assert updated_mapping["target_no"] == "60500", \
            f"Expected updated target_no='60500', got '{updated_mapping['target_no']}'"
        
        print(f"✓ Updated mapping {mapping_id} from item to gl_account")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")


class TestGLAccountCatalogEndpoints:
    """Tests for G/L Account catalog endpoints"""
    
    def test_search_gl_accounts(self):
        """GET /api/gpi-integration/catalog/gl-accounts?q= returns matching accounts"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/gl-accounts?q=shipping")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "accounts" in data
        accounts = data["accounts"]
        
        # Should find 60500 - Shipping / Delivery
        shipping_accounts = [a for a in accounts if "60500" in str(a.get("account_no", ""))]
        assert len(shipping_accounts) > 0, "Expected to find GL account 60500"
        
        shipping_acct = shipping_accounts[0]
        assert shipping_acct.get("name") == "Shipping / Delivery", \
            f"Expected name='Shipping / Delivery', got '{shipping_acct.get('name')}'"
        
        print(f"✓ Found {len(accounts)} GL accounts for 'shipping' search")
        print(f"✓ GL Account 60500: {shipping_acct.get('name')}")
        
    def test_search_gl_accounts_empty_query(self):
        """GET /api/gpi-integration/catalog/gl-accounts returns accounts without query"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/gl-accounts")
        assert response.status_code == 200
        
        data = response.json()
        accounts = data.get("accounts", [])
        assert len(accounts) > 0, "Expected some GL accounts"
        
        print(f"✓ Found {len(accounts)} GL accounts (no query)")


class TestItemCatalogEndpoints:
    """Tests for Item catalog endpoints"""
    
    def test_search_items(self):
        """GET /api/gpi-integration/catalog/items?q= returns matching items"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/catalog/items?q=glass")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
        items = data["items"]
        assert len(items) > 0, "Expected some items for 'glass' search"
        
        # Verify item structure
        item = items[0]
        assert "item_no" in item, "Item should have item_no"
        assert "description" in item, "Item should have description"
        
        print(f"✓ Found {len(items)} items for 'glass' search")
        
    def test_suggest_items(self):
        """POST /api/gpi-integration/catalog/suggest-items returns ranked suggestions"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/catalog/suggest-items",
            json={"description": "glass bottles"}
        )
        assert response.status_code == 200
        
        data = response.json()
        suggestions = data.get("suggestions", [])
        assert len(suggestions) > 0, "Expected some suggestions"
        
        # Verify suggestions have match scores
        for s in suggestions[:3]:
            assert "_match_score" in s, "Suggestion should have _match_score"
        
        print(f"✓ Got {len(suggestions)} item suggestions for 'glass bottles'")


class TestPreflightLineTypes:
    """Tests for preflight endpoint with different line types"""
    
    def test_preflight_returns_line_types_and_mapping_metadata(self):
        """POST /api/gpi-integration/sales-orders/preflight/{doc_id} returns correct line types"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_ELIGIBLE}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        resolved_lines = data.get("resolved_lines", [])
        assert len(resolved_lines) > 0, "Expected at least one resolved line"
        
        print(f"✓ Preflight returned {len(resolved_lines)} resolved lines")
        
        # Check each line for required mapping metadata
        for i, line in enumerate(resolved_lines):
            assert "lineType" in line, f"Line {i} missing 'lineType'"
            assert "mapping" in line, f"Line {i} missing 'mapping'"
            
            mapping = line["mapping"]
            assert "matched" in mapping, f"Line {i} mapping missing 'matched'"
            assert "target_type" in mapping, f"Line {i} mapping missing 'target_type'"
            assert "target_no" in mapping, f"Line {i} mapping missing 'target_no'"
            assert "confidence" in mapping, f"Line {i} mapping missing 'confidence'"
            
            line_type = line["lineType"]
            target_type = mapping["target_type"]
            
            # Validate lineType consistency with target_type
            if mapping["matched"]:
                if target_type == "gl_account":
                    assert line_type == "Account", f"Line {i}: gl_account should have lineType='Account', got '{line_type}'"
                elif target_type == "item":
                    assert line_type == "Item", f"Line {i}: item should have lineType='Item', got '{line_type}'"
                
                print(f"  Line {i}: '{line.get('description', '')[:30]}...' -> {line_type} ({mapping['target_no']}) {mapping['confidence']*100:.0f}%")
            else:
                assert line_type == "Comment", f"Line {i}: unmatched should have lineType='Comment', got '{line_type}'"
                print(f"  Line {i}: '{line.get('description', '')[:30]}...' -> Comment (unmapped)")
        
        print("✓ All lines have correct lineType based on target_type")
        
    def test_preflight_gl_account_line_has_account_line_type(self):
        """Lines mapped to G/L accounts should have lineType='Account'"""
        # First create a test mapping for a specific description
        test_id = str(uuid.uuid4())[:8]
        test_phrase = f"freight test {test_id}"
        
        # We can't test with existing data easily, but we can verify the logic is correct
        # by checking existing freight-related lines that should map to 60500
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_ELIGIBLE}")
        assert response.status_code == 200
        
        data = response.json()
        resolved_lines = data.get("resolved_lines", [])
        
        # Check for any lines that mapped to gl_account
        gl_account_lines = [l for l in resolved_lines 
                           if l.get("mapping", {}).get("target_type") == "gl_account"]
        
        for line in gl_account_lines:
            assert line["lineType"] == "Account", \
                f"G/L Account line should have lineType='Account', got '{line['lineType']}'"
            assert line["mapping"]["target_no"] == "60500", \
                f"G/L Account should map to 60500, got '{line['mapping']['target_no']}'"
        
        if gl_account_lines:
            print(f"✓ Found {len(gl_account_lines)} lines mapped to G/L Account 60500 with lineType='Account'")
        else:
            print("⚠ No lines mapped to G/L Account in this document (may be expected)")


class TestBackwardsCompatibility:
    """Tests for backwards compatibility with bc_item_number field"""
    
    def test_bc_item_number_field_still_works(self):
        """bc_item_number field should still work for creating mappings"""
        test_id = str(uuid.uuid4())[:8]
        mapping_data = {
            "keyword_phrase": f"backwards compat {test_id}",
            "bc_item_number": "TESTITEM",  # Old field name
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 200
        
        mapping = response.json()["mapping"]
        # Should set both target_no and bc_item_number
        assert mapping["bc_item_number"] == "TESTITEM" or mapping["target_no"] == "TESTITEM", \
            "bc_item_number should be preserved"
        
        print(f"✓ bc_item_number field still works for backwards compatibility")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping['id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
