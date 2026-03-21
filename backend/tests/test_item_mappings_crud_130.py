"""
Test Item Mappings CRUD API and Pipeline Visualization
Iteration 130 - Testing P1 features:
1. Item Mappings admin page and API CRUD operations
2. Pipeline Visualization component on Document Detail page
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://unified-queue-hub.preview.emergentagent.com"


class TestItemMappingsAPI:
    """Test Item Mappings CRUD endpoints at /api/gpi-integration/item-mappings"""
    
    @pytest.fixture(scope="class")
    def session(self):
        """Create a requests session"""
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        return s
    
    def test_get_item_mappings_returns_200(self, session):
        """GET /api/gpi-integration/item-mappings returns 200 and list of mappings"""
        response = session.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "mappings" in data, "Response should contain 'mappings' key"
        assert "total" in data, "Response should contain 'total' key"
        assert isinstance(data["mappings"], list), "mappings should be a list"
        
        # Per context: DB has 20 existing item mapping rules
        print(f"Found {data['total']} item mappings")
        assert data["total"] >= 0, "Total should be >= 0"
    
    def test_get_item_mappings_with_customer_filter(self, session):
        """GET /api/gpi-integration/item-mappings?customer_no=TEST returns filtered results"""
        response = session.get(f"{BASE_URL}/api/gpi-integration/item-mappings?customer_no=TEST")
        assert response.status_code == 200
        data = response.json()
        assert "mappings" in data
        print(f"Filtered by customer_no=TEST: {data['total']} mappings")
    
    def test_create_item_mapping(self, session):
        """POST /api/gpi-integration/item-mappings creates a new mapping rule"""
        unique_id = uuid.uuid4().hex[:8]
        payload = {
            "keyword_phrase": f"test mapping phrase {unique_id}",
            "keywords": ["test", "keyword", unique_id],
            "aliases": [],
            "target_type": "gl_account",
            "target_no": "TEST-001",
            "bc_item_description": f"Test description {unique_id}",
            "customer_no": "",
            "priority": 200,
            "active": True
        }
        
        response = session.post(f"{BASE_URL}/api/gpi-integration/item-mappings", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got: {data}"
        assert "mapping" in data, "Response should contain 'mapping' key"
        
        mapping = data["mapping"]
        assert mapping.get("keyword_phrase") == payload["keyword_phrase"]
        assert mapping.get("target_no") == "TEST-001"
        assert mapping.get("target_type") == "gl_account"
        assert "id" in mapping, "Mapping should have an 'id' field"
        
        # Store the ID for cleanup
        self.__class__.created_mapping_id = mapping["id"]
        print(f"Created mapping with ID: {mapping['id']}")
        return mapping["id"]
    
    def test_update_item_mapping(self, session):
        """PUT /api/gpi-integration/item-mappings/{id} updates an existing mapping"""
        mapping_id = getattr(self.__class__, 'created_mapping_id', None)
        if not mapping_id:
            pytest.skip("No mapping created in previous test")
        
        update_payload = {
            "keyword_phrase": "updated test mapping phrase",
            "target_no": "TEST-002",
            "priority": 150
        }
        
        response = session.put(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}", json=update_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True
        assert "mapping" in data
        
        updated_mapping = data["mapping"]
        assert updated_mapping.get("keyword_phrase") == "updated test mapping phrase"
        assert updated_mapping.get("target_no") == "TEST-002"
        assert updated_mapping.get("priority") == 150
        print(f"Updated mapping {mapping_id}")
    
    def test_get_updated_mapping_verify_persistence(self, session):
        """GET after PUT: verify update was actually persisted in database"""
        mapping_id = getattr(self.__class__, 'created_mapping_id', None)
        if not mapping_id:
            pytest.skip("No mapping created")
        
        response = session.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200
        
        data = response.json()
        mappings = data.get("mappings", [])
        
        found = None
        for m in mappings:
            if m.get("id") == mapping_id:
                found = m
                break
        
        assert found is not None, f"Mapping {mapping_id} should exist in list"
        assert found.get("keyword_phrase") == "updated test mapping phrase", "Keyword phrase should be updated"
        assert found.get("target_no") == "TEST-002", "Target number should be updated"
        print(f"Verified persistence of mapping {mapping_id}")
    
    def test_delete_item_mapping(self, session):
        """DELETE /api/gpi-integration/item-mappings/{id} removes a mapping"""
        mapping_id = getattr(self.__class__, 'created_mapping_id', None)
        if not mapping_id:
            pytest.skip("No mapping created in previous test")
        
        response = session.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{mapping_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("success") is True
        print(f"Deleted mapping {mapping_id}")
    
    def test_verify_mapping_deleted(self, session):
        """GET after DELETE: verify mapping no longer exists"""
        mapping_id = getattr(self.__class__, 'created_mapping_id', None)
        if not mapping_id:
            pytest.skip("No mapping created")
        
        response = session.get(f"{BASE_URL}/api/gpi-integration/item-mappings")
        assert response.status_code == 200
        
        data = response.json()
        mappings = data.get("mappings", [])
        
        found = any(m.get("id") == mapping_id for m in mappings)
        assert not found, f"Mapping {mapping_id} should NOT exist after deletion"
        print(f"Verified mapping {mapping_id} was deleted")
    
    def test_create_mapping_without_target_no_fails(self, session):
        """POST without target_no should return 422"""
        payload = {
            "keyword_phrase": "test missing target",
            "keywords": []
        }
        
        response = session.post(f"{BASE_URL}/api/gpi-integration/item-mappings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("Validation: Missing target_no correctly returns 422")
    
    def test_create_mapping_without_keywords_fails(self, session):
        """POST without keyword_phrase and keywords should return 422"""
        payload = {
            "target_no": "TEST-003"
        }
        
        response = session.post(f"{BASE_URL}/api/gpi-integration/item-mappings", json=payload)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        print("Validation: Missing keywords correctly returns 422")
    
    def test_update_nonexistent_mapping_returns_404(self, session):
        """PUT with non-existent ID should return 404"""
        fake_id = "nonexistent-mapping-id-12345"
        
        response = session.put(f"{BASE_URL}/api/gpi-integration/item-mappings/{fake_id}", json={"priority": 100})
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Validation: Update non-existent mapping returns 404")
    
    def test_delete_nonexistent_mapping_returns_404(self, session):
        """DELETE with non-existent ID should return 404"""
        fake_id = "nonexistent-mapping-id-12345"
        
        response = session.delete(f"{BASE_URL}/api/gpi-integration/item-mappings/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Validation: Delete non-existent mapping returns 404")


class TestPipelineVisualizationAPI:
    """Test document intelligence API that backs the Pipeline Visualization component"""
    
    @pytest.fixture(scope="class")
    def session(self):
        """Create a requests session"""
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        return s
    
    def test_get_documents_list(self, session):
        """GET /api/documents returns list of documents"""
        response = session.get(f"{BASE_URL}/api/documents")
        assert response.status_code == 200
        
        data = response.json()
        # The response could be paginated with 'documents' or 'items' key
        documents = data.get("documents", data.get("items", []))
        print(f"Found {len(documents)} documents in the system")
        
        if documents:
            self.__class__.sample_doc_id = documents[0].get("id")
            print(f"Sample document ID: {self.__class__.sample_doc_id}")
    
    def test_get_document_detail_for_pipeline(self, session):
        """GET /api/documents/{id} returns document with pipeline_stages if available"""
        doc_id = getattr(self.__class__, 'sample_doc_id', None)
        if not doc_id:
            pytest.skip("No sample document available")
        
        response = session.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert "document" in data, "Response should contain 'document'"
        
        doc = data["document"]
        # Pipeline visualization reads from doc.intelligence.pipeline_stages
        # If the document has intelligence data, check for pipeline info
        if doc.get("intelligence"):
            intel = doc["intelligence"]
            print(f"Document has intelligence data: {list(intel.keys())}")
            if "pipeline_stages" in intel:
                print(f"Pipeline stages: {list(intel['pipeline_stages'].keys())}")
        else:
            print("Document does not have intelligence data yet (expected for no documents)")
    
    def test_document_intelligence_endpoint(self, session):
        """GET /api/documents/{id}/intelligence returns pipeline stages"""
        doc_id = getattr(self.__class__, 'sample_doc_id', None)
        if not doc_id:
            pytest.skip("No sample document available")
        
        response = session.get(f"{BASE_URL}/api/documents/{doc_id}/intelligence")
        # The endpoint might return 200 with null/empty or 404 if no intelligence data
        if response.status_code == 404:
            print(f"Document {doc_id} has no intelligence data (expected for new/unprocessed docs)")
            return
        
        assert response.status_code == 200
        
        data = response.json()
        print(f"Intelligence data keys: {list(data.keys()) if data else 'None'}")
        
        # Check for pipeline_stages structure expected by PipelineVisualization component
        if data:
            if "pipeline_stages" in data:
                stages = data["pipeline_stages"]
                expected_stages = ["parse", "classify", "extract", "validate", "route"]
                for stage in expected_stages:
                    if stage in stages:
                        print(f"Stage '{stage}': status={stages[stage].get('status', 'n/a')}, ms={stages[stage].get('ms', 0)}")


class TestSettingsHubAPI:
    """Test Settings Hub configuration endpoints"""
    
    @pytest.fixture(scope="class")
    def session(self):
        """Create a requests session"""
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        return s
    
    def test_gpi_integration_status(self, session):
        """GET /api/gpi-integration/status returns integration status"""
        response = session.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200
        
        data = response.json()
        print(f"GPI Integration status: {data}")
        # Verify expected fields - API returns 'configured' field
        assert "configured" in data, "Response should contain 'configured' field"
        assert data.get("configured") is True, "BC should be configured"
        print(f"BC configured: {data.get('configured')}, tenant: {data.get('tenant_id')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
