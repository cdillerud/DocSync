"""
SharePoint Folder Routing API Tests

Tests the SharePoint routing feature including:
- GET /api/sharepoint-routing/folder-tree - folder tree structure
- GET /api/sharepoint-routing/vendor-mappings - vendor to folder mappings
- GET /api/sharepoint-routing/processor-assignments - processor assignments
- POST /api/sharepoint-routing/suggest-folder - folder suggestion for documents
- POST /api/sharepoint-routing/vendor-mappings - create vendor mapping
- DELETE /api/sharepoint-routing/vendor-mappings/{pattern} - delete vendor mapping
- POST /api/sharepoint-routing/seed-defaults - re-seed default configurations
"""

import pytest
import requests
import os
import urllib.parse

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthCheck:
    """Verify backend is running"""

    def test_health_endpoint(self):
        """Test health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: Health check passed")


class TestFolderTree:
    """Test folder tree structure endpoint"""

    def test_get_folder_tree(self):
        """GET /api/sharepoint-routing/folder-tree returns tree structure"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/folder-tree")
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "tree" in data, "Response should have 'tree' field"
        assert "rules" in data, "Response should have 'rules' field"
        assert "total_rules" in data, "Response should have 'total_rules' field"
        
        # Verify counts (should have ~37 rules with 15 top-level folders)
        tree = data["tree"]
        rules = data["rules"]
        total = data["total_rules"]
        
        assert len(tree) >= 10, f"Expected at least 10 top-level folders, got {len(tree)}"
        assert total >= 30, f"Expected at least 30 total rules, got {total}"
        
        print(f"PASS: Folder tree has {len(tree)} top-level folders and {total} total rules")

    def test_folder_tree_structure(self):
        """Verify folder tree has expected key folders"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/folder-tree")
        assert response.status_code == 200
        data = response.json()
        
        tree = data["tree"]
        folder_keys = [n["key"] for n in tree]
        
        # Check for key folders from the accounting document
        expected_keys = [
            "DO_NOT_PAY", "DROPSHIP_INTERNATIONAL", "DROPSHIP_DOMESTIC",
            "FREIGHT_ISSUES", "MISCELLANEOUS", "SH_APPROVED", "VENDOR_CREDITS",
            "TOOLING", "WAREHOUSE_DOMESTIC"
        ]
        
        for key in expected_keys:
            assert key in folder_keys, f"Expected folder {key} not found in tree"
        
        print(f"PASS: All expected folder keys found: {expected_keys}")


class TestVendorMappings:
    """Test vendor to folder mappings endpoints"""

    def test_get_vendor_mappings(self):
        """GET /api/sharepoint-routing/vendor-mappings returns mappings list"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/vendor-mappings")
        assert response.status_code == 200
        data = response.json()
        
        assert "mappings" in data, "Response should have 'mappings' field"
        assert "total" in data, "Response should have 'total' field"
        
        mappings = data["mappings"]
        total = data["total"]
        
        # Should have at least 25 default mappings
        assert total >= 25, f"Expected at least 25 vendor mappings, got {total}"
        
        # Check mapping structure
        if mappings:
            m = mappings[0]
            assert "vendor_pattern" in m, "Mapping should have vendor_pattern"
            assert "folder_target" in m, "Mapping should have folder_target"
            assert "vendor_category" in m, "Mapping should have vendor_category"
        
        print(f"PASS: Got {total} vendor mappings")

    def test_vendor_mappings_contains_expected_vendors(self):
        """Verify vendor mappings include key vendors"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/vendor-mappings")
        assert response.status_code == 200
        data = response.json()
        
        mappings = data["mappings"]
        patterns = [m["vendor_pattern"] for m in mappings]
        
        # Check for key vendor patterns
        expected = ["ball", "canpack", "anchor", "ups", "fedex"]
        for vendor in expected:
            assert vendor in patterns, f"Expected vendor mapping for '{vendor}' not found"
        
        print(f"PASS: Key vendor mappings found: {expected}")


class TestProcessorAssignments:
    """Test processor assignment endpoints"""

    def test_get_processor_assignments(self):
        """GET /api/sharepoint-routing/processor-assignments returns assignments"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/processor-assignments")
        assert response.status_code == 200
        data = response.json()
        
        assert "assignments" in data, "Response should have 'assignments' field"
        assert "total" in data, "Response should have 'total' field"
        
        assignments = data["assignments"]
        total = data["total"]
        
        # Should have at least 5 default processor assignments
        assert total >= 5, f"Expected at least 5 processor assignments, got {total}"
        
        # Check assignment structure
        if assignments:
            a = assignments[0]
            assert "folder_path" in a, "Assignment should have folder_path"
            assert "processor_name" in a, "Assignment should have processor_name"
        
        print(f"PASS: Got {total} processor assignments")

    def test_processor_assignments_contains_expected_processors(self):
        """Verify processor assignments include expected names"""
        response = requests.get(f"{BASE_URL}/api/sharepoint-routing/processor-assignments")
        assert response.status_code == 200
        data = response.json()
        
        assignments = data["assignments"]
        processors = [a["processor_name"] for a in assignments]
        
        # Check for key processors
        expected = ["Andy", "Meg", "Rhonda"]
        for proc in expected:
            assert proc in processors, f"Expected processor '{proc}' not found"
        
        print(f"PASS: Key processors found: {expected}")


class TestSuggestFolder:
    """Test folder suggestion endpoint with various document scenarios"""

    def test_suggest_folder_canpack_vendor(self):
        """Canpack vendor routes to Dropship Not International Documents/Canpack"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "AP_Invoice",
                "vendor": "Canpack",
                "is_international": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "suggested_folder" in data
        folder = data["suggested_folder"]
        
        assert "Canpack" in folder, f"Canpack vendor should route to Canpack folder, got: {folder}"
        assert "Dropship Not International Documents" in folder, f"Should be in Dropship domestic, got: {folder}"
        
        print(f"PASS: Canpack vendor routes to: {folder}")

    def test_suggest_folder_canpack_dunnage(self):
        """Canpack dunnage routes to Canpack/Dunnage return freight subfolder"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Freight_Document",
                "vendor": "Canpack",
                "description": "dunnage return freight invoice",
                "is_international": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "Dunnage return freight" in folder, f"Dunnage should route to Dunnage return freight, got: {folder}"
        assert "Canpack" in folder, f"Should be under Canpack folder, got: {folder}"
        
        print(f"PASS: Canpack dunnage routes to: {folder}")

    def test_suggest_folder_freight_issue(self):
        """Freight document with issue routes to Freight Issues"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Freight_Document",
                "vendor": "XPO Logistics",
                "has_freight_issue": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "Freight Issues" in folder, f"Freight issue should route to Freight Issues, got: {folder}"
        
        print(f"PASS: Freight issue routes to: {folder}")

    def test_suggest_folder_credit_memo_ball_dunnage(self):
        """Ball dunnage credit memo routes to Vendor Credit Memos/Ball Dunnage"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Return_Request",
                "vendor": "Ball Corporation",
                "description": "dunnage credit memo"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "Vendor Credit Memos" in folder, f"Credit memo should route to Vendor Credit Memos, got: {folder}"
        assert "Ball Dunnage" in folder, f"Ball dunnage should go to Ball Dunnage subfolder, got: {folder}"
        
        print(f"PASS: Ball dunnage credit routes to: {folder}")

    def test_suggest_folder_tooling_invoice(self):
        """Tooling invoice routes to Tooling Invoices"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "AP_Invoice",
                "vendor": "ABC Company",
                "description": "tooling charge for mold repair"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "Tooling Invoices" in folder, f"Tooling should route to Tooling Invoices, got: {folder}"
        
        print(f"PASS: Tooling invoice routes to: {folder}")

    def test_suggest_folder_sh_approved(self):
        """Approved S&H invoice routes to S&H Approved Documents/Andy to Process"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "AP_Invoice",
                "vendor": "Warehouse Co",
                "description": "storage and handling fee",
                "is_approved": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "S&H" in folder or "storage" in folder.lower() or "Approved" in folder, f"S&H approved should route to S&H Approved, got: {folder}"
        
        print(f"PASS: Approved S&H routes to: {folder}")

    def test_suggest_folder_unknown_document(self):
        """Unknown document routes to Miscellaneous Documents"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Unknown_Document",
                "vendor": "",
                "description": "random document"
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "Miscellaneous" in folder, f"Unknown doc should route to Miscellaneous, got: {folder}"
        assert "need approval" in folder, f"Should need approval, got: {folder}"
        
        print(f"PASS: Unknown document routes to: {folder}")

    def test_suggest_folder_response_structure(self):
        """Verify suggest-folder response includes all expected fields"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={"doc_type": "AP_Invoice", "vendor": "Test"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "suggested_folder" in data, "Response must have suggested_folder"
        assert "reason" in data, "Response must have reason"
        assert "details" in data, "Response must have details"
        
        details = data["details"]
        assert "doc_type" in details, "Details must have doc_type"
        assert "vendor" in details, "Details must have vendor"
        
        print(f"PASS: Response structure is correct with folder: {data['suggested_folder']}")


class TestVendorMappingCRUD:
    """Test vendor mapping create/delete operations"""

    def test_create_and_delete_vendor_mapping(self):
        """Create a new vendor mapping and then delete it"""
        # Create
        new_mapping = {
            "vendor_pattern": "test_vendor_xyz",
            "folder_target": "TestFolder",
            "vendor_category": "general"
        }
        
        create_response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/vendor-mappings",
            json=new_mapping
        )
        assert create_response.status_code == 200
        create_data = create_response.json()
        
        assert "mapping" in create_data, "Create response should have mapping"
        assert create_data["mapping"]["vendor_pattern"] == "test_vendor_xyz"
        
        print(f"PASS: Created vendor mapping for 'test_vendor_xyz'")
        
        # Verify it exists
        list_response = requests.get(f"{BASE_URL}/api/sharepoint-routing/vendor-mappings")
        assert list_response.status_code == 200
        mappings = list_response.json()["mappings"]
        patterns = [m["vendor_pattern"] for m in mappings]
        assert "test_vendor_xyz" in patterns, "Created mapping should be in list"
        
        # Delete
        encoded_pattern = urllib.parse.quote("test_vendor_xyz")
        delete_response = requests.delete(
            f"{BASE_URL}/api/sharepoint-routing/vendor-mappings/{encoded_pattern}"
        )
        assert delete_response.status_code == 200
        
        print("PASS: Deleted vendor mapping for 'test_vendor_xyz'")
        
        # Verify it's gone
        list_response2 = requests.get(f"{BASE_URL}/api/sharepoint-routing/vendor-mappings")
        mappings2 = list_response2.json()["mappings"]
        patterns2 = [m["vendor_pattern"] for m in mappings2]
        assert "test_vendor_xyz" not in patterns2, "Deleted mapping should not be in list"
        
        print("PASS: Verified mapping was deleted")

    def test_delete_nonexistent_mapping(self):
        """Deleting non-existent mapping returns 404"""
        encoded_pattern = urllib.parse.quote("nonexistent_vendor_pattern_xyz123")
        response = requests.delete(
            f"{BASE_URL}/api/sharepoint-routing/vendor-mappings/{encoded_pattern}"
        )
        assert response.status_code == 404
        print("PASS: Delete non-existent mapping returns 404")


class TestSeedDefaults:
    """Test seed defaults endpoint"""

    def test_seed_defaults(self):
        """POST /api/sharepoint-routing/seed-defaults re-seeds all configurations"""
        response = requests.post(f"{BASE_URL}/api/sharepoint-routing/seed-defaults")
        assert response.status_code == 200
        data = response.json()
        
        assert "message" in data
        assert "rules" in data
        assert "vendor_mappings" in data
        assert "processor_assignments" in data
        
        # Verify counts after seeding
        assert data["rules"] >= 30, f"Expected at least 30 rules, got {data['rules']}"
        assert data["vendor_mappings"] >= 25, f"Expected at least 25 vendor mappings, got {data['vendor_mappings']}"
        assert data["processor_assignments"] >= 5, f"Expected at least 5 processor assignments, got {data['processor_assignments']}"
        
        print(f"PASS: Seeded {data['rules']} rules, {data['vendor_mappings']} vendor mappings, {data['processor_assignments']} processor assignments")


class TestInternationalRouting:
    """Test international vs domestic routing"""

    def test_international_shipment(self):
        """International document routes to international folders"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Shipping_Document",
                "vendor": "International Supplier",
                "is_international": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "International" in folder, f"International doc should route to International folder, got: {folder}"
        
        print(f"PASS: International document routes to: {folder}")

    def test_domestic_shipment(self):
        """Domestic document routes to domestic folders"""
        response = requests.post(
            f"{BASE_URL}/api/sharepoint-routing/suggest-folder",
            json={
                "doc_type": "Shipping_Document",
                "vendor": "Local Supplier",
                "is_international": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        folder = data["suggested_folder"]
        
        assert "International" not in folder or "Not International" in folder, f"Domestic should not be in International folder, got: {folder}"
        
        print(f"PASS: Domestic document routes to: {folder}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
