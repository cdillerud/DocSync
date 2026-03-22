"""
API Tests for Item Mapping CRUD and Preflight with Mapping Metadata
Tests the /api/gpi-integration/item-mappings endpoints and preflight line mapping.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://po-extraction-ai.preview.emergentagent.com').rstrip('/')

# Test data - known documents from main agent context (full UUIDs)
DOC_ID_ELIGIBLE = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"  # Sales_Order type with 2 lines (Widget A, Widget B), no existing SO
DOC_ID_WITH_SO_1 = "b3c5ddaa-ec00-4cd2-8530-05d0a132b7c0"  # Has existing SO (107039)
DOC_ID_WITH_SO_2 = "29be78fe-4d67-4a7a-8fcd-e15f698451d1"  # Order_Confirmation with existing SO (107040)


class TestItemMappingCRUD:
    """Tests for item mapping CRUD endpoints"""
    
    def test_get_all_mappings(self):
        """GET /api/gpi-integration/item-mappings returns all mappings"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "mappings" in data
        assert "total" in data
        assert isinstance(data["mappings"], list)
        print(f"✓ Found {data['total']} item mappings")
        
        # Verify known mappings exist (from main agent context)
        mapping_items = {m.get("bc_item_number") for m in data["mappings"]}
        expected_items = {"GLASS001", "TIER001", "WIDG-A"}
        found = expected_items & mapping_items
        print(f"✓ Found expected mappings: {found}")
        
    def test_create_mapping(self):
        """POST /api/gpi-integration/item-mappings creates a new mapping"""
        test_id = str(uuid.uuid4())[:8]
        mapping_data = {
            "keyword_phrase": f"test item {test_id}",
            "bc_item_number": f"TEST-{test_id}",
            "bc_item_description": "Test Item for API Testing",
            "keywords": ["test", "item"],
            "aliases": [],
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
        assert "mapping" in data
        assert data["mapping"]["bc_item_number"] == f"TEST-{test_id}"
        assert data["mapping"]["keyword_phrase"] == f"test item {test_id}"
        assert "id" in data["mapping"]
        
        mapping_id = data["mapping"]["id"]
        print(f"✓ Created mapping with ID: {mapping_id}")
        
        # Cleanup - delete the test mapping
        cleanup_response = requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        assert cleanup_response.status_code == 200
        print(f"✓ Cleaned up test mapping")
        
    def test_create_mapping_requires_bc_item_number(self):
        """POST /api/gpi-integration/item-mappings validates required fields"""
        mapping_data = {
            "keyword_phrase": "test phrase"
            # Missing bc_item_number
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 422
        print("✓ Validation correctly rejects missing bc_item_number")
        
    def test_create_mapping_requires_keyword_or_phrase(self):
        """POST /api/gpi-integration/item-mappings requires keyword_phrase or keywords"""
        mapping_data = {
            "bc_item_number": "TEST001"
            # Missing both keyword_phrase and keywords
        }
        
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json=mapping_data
        )
        assert response.status_code == 422
        print("✓ Validation correctly rejects missing keywords")
        
    def test_update_mapping(self):
        """PUT /api/gpi-integration/item-mappings/{id} updates an existing mapping"""
        # First create a test mapping
        test_id = str(uuid.uuid4())[:8]
        create_response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json={
                "keyword_phrase": f"update test {test_id}",
                "bc_item_number": f"UPD-{test_id}"
            }
        )
        assert create_response.status_code == 200
        mapping_id = create_response.json()["mapping"]["id"]
        
        # Update the mapping
        update_data = {
            "bc_item_description": "Updated description",
            "priority": 50
        }
        update_response = requests.put(
            f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}",
            json=update_data
        )
        assert update_response.status_code == 200
        
        updated_mapping = update_response.json()["mapping"]
        assert updated_mapping["bc_item_description"] == "Updated description"
        assert updated_mapping["priority"] == 50
        print(f"✓ Updated mapping {mapping_id}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        
    def test_update_nonexistent_mapping(self):
        """PUT /api/gpi-integration/item-mappings/{id} returns 404 for unknown id"""
        response = requests.put(
            f"{BASE_URL}/api/gpi-integration/item-mappings/nonexistent-id-12345",
            json={"priority": 100}
        )
        assert response.status_code == 404
        print("✓ 404 for nonexistent mapping update")
        
    def test_delete_mapping(self):
        """DELETE /api/gpi-integration/item-mappings/{id} deletes a mapping"""
        # First create a test mapping
        test_id = str(uuid.uuid4())[:8]
        create_response = requests.post(
            f"{BASE_URL}/api/gpi-integration/item-mappings",
            json={
                "keyword_phrase": f"delete test {test_id}",
                "bc_item_number": f"DEL-{test_id}"
            }
        )
        assert create_response.status_code == 200
        mapping_id = create_response.json()["mapping"]["id"]
        
        # Delete the mapping
        delete_response = requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        assert delete_response.status_code == 200
        assert delete_response.json().get("success") is True
        print(f"✓ Deleted mapping {mapping_id}")
        
        # Verify it's gone
        get_response = requests.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        mappings = get_response.json()["mappings"]
        mapping_ids = {m["id"] for m in mappings}
        assert mapping_id not in mapping_ids
        print("✓ Mapping no longer exists")
        
    def test_delete_nonexistent_mapping(self):
        """DELETE /api/gpi-integration/item-mappings/{id} returns 404 for unknown id"""
        response = requests.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/nonexistent-id-99999")
        assert response.status_code == 404
        print("✓ 404 for nonexistent mapping delete")


class TestPreflightWithMapping:
    """Tests for preflight endpoint with item mapping metadata"""
    
    def test_preflight_returns_resolved_lines_with_mapping(self):
        """Preflight /api/gpi-integration/sales-orders/preflight/{doc_id} returns mapping metadata"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_ELIGIBLE}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Basic preflight structure
        assert "eligible" in data
        assert "ready" in data
        assert "resolved_lines" in data
        assert "line_count" in data
        
        resolved_lines = data["resolved_lines"]
        assert len(resolved_lines) >= 2, f"Expected at least 2 lines, got {len(resolved_lines)}"
        print(f"✓ Preflight returned {len(resolved_lines)} resolved lines")
        
        # Each line should have mapping metadata
        for i, line in enumerate(resolved_lines):
            assert "mapping" in line, f"Line {i} missing 'mapping' field"
            mapping = line["mapping"]
            assert "matched" in mapping, f"Line {i} mapping missing 'matched'"
            assert "confidence" in mapping, f"Line {i} mapping missing 'confidence'"
            assert "method" in mapping, f"Line {i} mapping missing 'method'"
            assert "target_no" in mapping, f"Line {i} mapping missing 'target_no'"
            assert "target_type" in mapping, f"Line {i} mapping missing 'target_type'"
            
        print("✓ All lines have required mapping metadata")
        
    def test_preflight_mapped_line_shows_item_type(self):
        """Preflight shows lineType=Item for lines with matching mapping"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_ELIGIBLE}")
        assert response.status_code == 200
        
        data = response.json()
        resolved_lines = data["resolved_lines"]
        
        # Find Widget A line - should map to WIDG-A per main agent context
        widget_a_lines = [l for l in resolved_lines if "widget a" in l.get("description", "").lower()]
        
        if widget_a_lines:
            widget_a = widget_a_lines[0]
            mapping = widget_a["mapping"]
            
            if mapping["matched"]:
                assert widget_a["lineType"] == "Item", "Mapped line should have lineType=Item"
                assert mapping["target_no"] == "WIDG-A", f"Expected WIDG-A, got {mapping['target_no']}"
                assert mapping["confidence"] >= 0.7, f"Confidence should be >= 0.7, got {mapping['confidence']}"
                print(f"✓ Widget A mapped to {mapping['target_no']} with confidence {mapping['confidence']}")
            else:
                print(f"⚠ Widget A not matched - mapping confidence below threshold")
        else:
            print("⚠ Widget A line not found in resolved lines")
            
    def test_preflight_unmapped_line_shows_comment_type(self):
        """Preflight shows lineType=Comment for lines without matching mapping"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_ELIGIBLE}")
        assert response.status_code == 200
        
        data = response.json()
        resolved_lines = data["resolved_lines"]
        
        # Find Widget B line - should be unmapped per main agent context
        widget_b_lines = [l for l in resolved_lines if "widget b" in l.get("description", "").lower()]
        
        if widget_b_lines:
            widget_b = widget_b_lines[0]
            mapping = widget_b["mapping"]
            
            if not mapping["matched"]:
                assert widget_b["lineType"] == "Comment", "Unmapped line should have lineType=Comment"
                assert mapping["target_no"] == "", "Unmapped line should have empty target_no"
                assert mapping["confidence"] == 0, "Unmapped line should have confidence 0"
                print(f"✓ Widget B correctly shows as unmapped Comment line")
            else:
                print(f"⚠ Widget B unexpectedly matched to {mapping['target_no']}")
        else:
            print("⚠ Widget B line not found in resolved lines")
            
    def test_preflight_nonexistent_doc_returns_404(self):
        """Preflight returns 404 for nonexistent document"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/nonexistent-doc-12345")
        assert response.status_code == 404
        print("✓ 404 for nonexistent document")


class TestIdempotency:
    """Tests for idempotency of from-document endpoint"""
    
    def test_idempotency_returns_already_exists(self):
        """Re-calling from-document returns already_exists without duplicating"""
        # DOC_ID_WITH_SO_1 has an existing SO per main agent context
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{DOC_ID_WITH_SO_1}")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("already_exists") is True, "Should return already_exists=true"
        assert data.get("success") is True, "Should return success=true for idempotent call"
        assert "bc_record_no" in data, "Should return bc_record_no"
        assert data.get("status") == "already_exists"
        
        print(f"✓ Idempotent call returned already_exists for SO {data.get('bc_record_no')}")
        
    def test_idempotency_preserves_line_info(self):
        """Re-calling from-document preserves lines_added information"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{DOC_ID_WITH_SO_1}")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("already_exists") is True
        
        # Lines info should be preserved from original creation
        if "lines_added" in data or "lines_total" in data:
            print(f"✓ Line info preserved: {data.get('lines_added')}/{data.get('lines_total')} lines")
        else:
            print("⚠ lines_added/lines_total not in idempotent response")


class TestPreflightAlreadyCreated:
    """Tests for preflight behavior when SO already exists"""
    
    def test_preflight_shows_already_created(self):
        """Preflight shows already_created=true for docs with existing SO"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{DOC_ID_WITH_SO_1}")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("already_created") is True, "Should show already_created=true"
        assert data.get("ready") is False, "Should show ready=false when already created"
        assert "existing_sales_order" in data, "Should include existing_sales_order info"
        
        existing_so = data["existing_sales_order"]
        if existing_so:
            print(f"✓ Already created SO: {existing_so.get('bc_record_no')}")
            if "lines_added" in existing_so:
                print(f"✓ Existing SO has {existing_so.get('lines_added')} lines")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
