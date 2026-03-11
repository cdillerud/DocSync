"""
Transaction Graph and Processor Specs API Tests
Testing the new features:
  - Transaction Graph: nodes, edges, document connections, stats, search
  - Processor Specs: CRUD, generation, status management
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTransactionGraphStats:
    """Test graph statistics endpoint"""
    
    def test_graph_stats_returns_200(self):
        """GET /api/graph/stats - Returns graph statistics"""
        response = requests.get(f"{BASE_URL}/api/graph/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "total_nodes" in data, "Missing total_nodes"
        assert "total_edges" in data, "Missing total_edges"
        assert "nodes_by_type" in data, "Missing nodes_by_type"
        assert "edges_by_type" in data, "Missing edges_by_type"
        assert "edges_by_provenance" in data, "Missing edges_by_provenance"
        assert "avg_edge_confidence" in data, "Missing avg_edge_confidence"
        assert "documents_in_graph" in data, "Missing documents_in_graph"
        
        # Data assertions - validate types
        assert isinstance(data["total_nodes"], int)
        assert isinstance(data["total_edges"], int)
        assert isinstance(data["nodes_by_type"], dict)
        assert isinstance(data["edges_by_type"], dict)
        
        print(f"Graph stats: {data['total_nodes']} nodes, {data['total_edges']} edges")


class TestTransactionGraphNodes:
    """Test graph nodes endpoints"""
    
    def test_list_nodes_returns_200(self):
        """GET /api/graph/nodes - Lists graph nodes"""
        response = requests.get(f"{BASE_URL}/api/graph/nodes?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "nodes" in data, "Missing nodes"
        assert "total" in data, "Missing total"
        assert "limit" in data, "Missing limit"
        assert "skip" in data, "Missing skip"
        
        # Data assertions
        assert isinstance(data["nodes"], list)
        assert data["limit"] == 10
        
        if len(data["nodes"]) > 0:
            node = data["nodes"][0]
            assert "node_id" in node, "Node missing node_id"
            assert "node_type" in node, "Node missing node_type"
            assert "reference_value" in node, "Node missing reference_value"
        
        print(f"Listed {len(data['nodes'])} nodes, total: {data['total']}")
    
    def test_list_nodes_with_type_filter(self):
        """GET /api/graph/nodes?node_type=document - Filters by type"""
        response = requests.get(f"{BASE_URL}/api/graph/nodes?node_type=document&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # All returned nodes should be of type document
        for node in data["nodes"]:
            assert node["node_type"] == "document", f"Expected document, got {node['node_type']}"
        
        print(f"Filtered to {len(data['nodes'])} document nodes")


class TestTransactionGraphEdges:
    """Test graph edges endpoints"""
    
    def test_list_edges_returns_200(self):
        """GET /api/graph/edges - Lists graph edges"""
        response = requests.get(f"{BASE_URL}/api/graph/edges?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "edges" in data, "Missing edges"
        assert "total" in data, "Missing total"
        
        # Data assertions
        assert isinstance(data["edges"], list)
        
        if len(data["edges"]) > 0:
            edge = data["edges"][0]
            assert "edge_id" in edge, "Edge missing edge_id"
            assert "from_node" in edge, "Edge missing from_node"
            assert "to_node" in edge, "Edge missing to_node"
            assert "edge_type" in edge, "Edge missing edge_type"
            assert "confidence" in edge, "Edge missing confidence"
            assert "provenance" in edge, "Edge missing provenance"
        
        print(f"Listed {len(data['edges'])} edges, total: {data['total']}")
    
    def test_list_edges_with_type_filter(self):
        """GET /api/graph/edges?edge_type=contains_reference - Filters by type"""
        response = requests.get(f"{BASE_URL}/api/graph/edges?edge_type=contains_reference&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # All returned edges should be contains_reference
        for edge in data["edges"]:
            assert edge["edge_type"] == "contains_reference", f"Expected contains_reference, got {edge['edge_type']}"
        
        print(f"Filtered to {len(data['edges'])} contains_reference edges")
    
    def test_list_edges_with_provenance_filter(self):
        """GET /api/graph/edges?provenance=linked_by_extraction - Filters by provenance"""
        response = requests.get(f"{BASE_URL}/api/graph/edges?provenance=linked_by_extraction&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        for edge in data["edges"]:
            assert edge["provenance"] == "linked_by_extraction", f"Expected linked_by_extraction, got {edge['provenance']}"
        
        print(f"Filtered to {len(data['edges'])} linked_by_extraction edges")


class TestTransactionGraphDocumentConnections:
    """Test document connections endpoint"""
    
    @pytest.fixture
    def sample_doc_id(self):
        """Get a document ID from nodes"""
        response = requests.get(f"{BASE_URL}/api/graph/nodes?node_type=document&limit=1")
        if response.status_code == 200:
            data = response.json()
            if data["nodes"]:
                return data["nodes"][0]["reference_value"]
        return None
    
    def test_document_connections_found(self, sample_doc_id):
        """GET /api/graph/document/{doc_id}/connections - Returns connections"""
        if not sample_doc_id:
            pytest.skip("No document nodes in graph")
        
        response = requests.get(f"{BASE_URL}/api/graph/document/{sample_doc_id}/connections")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "doc_id" in data, "Missing doc_id"
        assert "found" in data, "Missing found"
        assert "nodes" in data, "Missing nodes"
        assert "edges" in data, "Missing edges"
        
        if data["found"]:
            assert "doc_node_id" in data, "Missing doc_node_id when found"
            assert "connected_documents" in data, "Missing connected_documents"
            assert "node_count" in data, "Missing node_count"
            assert "edge_count" in data, "Missing edge_count"
            print(f"Document {sample_doc_id[:8]}... has {data['node_count']} nodes, {data['edge_count']} edges")
        else:
            print(f"Document {sample_doc_id[:8]}... not found in graph")
    
    def test_document_connections_not_found(self):
        """GET /api/graph/document/{doc_id}/connections - Returns found:false for missing doc"""
        response = requests.get(f"{BASE_URL}/api/graph/document/non_existent_doc_id/connections")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["found"] == False, "Expected found to be False"
        assert data["nodes"] == [], "Expected empty nodes"
        assert data["edges"] == [], "Expected empty edges"
        print("Correctly returns found:false for non-existent document")


class TestTransactionGraphSearch:
    """Test graph search endpoint"""
    
    def test_search_graph_valid_reference(self):
        """GET /api/graph/search?reference=VALUE - Searches by reference"""
        # First get a reference value from existing nodes
        nodes_response = requests.get(f"{BASE_URL}/api/graph/nodes?limit=5")
        if nodes_response.status_code != 200:
            pytest.skip("Cannot get nodes")
        
        nodes_data = nodes_response.json()
        if not nodes_data["nodes"]:
            pytest.skip("No nodes in graph")
        
        # Find a non-document node with a reference
        ref_value = None
        for node in nodes_data["nodes"]:
            if node["node_type"] != "document" and node.get("reference_value"):
                ref_value = node["reference_value"]
                break
        
        if not ref_value:
            ref_value = nodes_data["nodes"][0]["reference_value"]
        
        response = requests.get(f"{BASE_URL}/api/graph/search", params={"reference": ref_value})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "reference_value" in data, "Missing reference_value"
        assert "found" in data, "Missing found"
        assert "nodes" in data, "Missing nodes"
        assert "edges" in data, "Missing edges"
        
        print(f"Search for '{ref_value}': found={data['found']}, {len(data['nodes'])} nodes")
    
    def test_search_graph_short_reference_fails(self):
        """GET /api/graph/search?reference=X - Rejects short references"""
        response = requests.get(f"{BASE_URL}/api/graph/search", params={"reference": "X"})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("Correctly rejects short reference values")
    
    def test_search_graph_missing_reference_fails(self):
        """GET /api/graph/search - Missing reference parameter fails"""
        response = requests.get(f"{BASE_URL}/api/graph/search")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("Correctly requires reference parameter")


class TestTransactionGraphBulkIngest:
    """Test bulk ingest endpoint"""
    
    def test_bulk_ingest_returns_200(self):
        """POST /api/graph/bulk-ingest - Bulk ingests documents"""
        response = requests.post(f"{BASE_URL}/api/graph/bulk-ingest?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "total" in data, "Missing total"
        assert "ingested" in data, "Missing ingested"
        assert "errors" in data, "Missing errors"
        
        print(f"Bulk ingest: {data['ingested']}/{data['total']} docs, {data['errors']} errors")


class TestTransactionGraphManualIngest:
    """Test manual document ingestion"""
    
    @pytest.fixture
    def sample_doc_id(self):
        """Get a document ID"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if response.status_code == 200:
            data = response.json()
            if data.get("documents"):
                return data["documents"][0]["id"]
        return None
    
    def test_manual_ingest_existing_doc(self, sample_doc_id):
        """POST /api/graph/document/{doc_id}/ingest - Ingests existing doc"""
        if not sample_doc_id:
            pytest.skip("No documents available")
        
        response = requests.post(f"{BASE_URL}/api/graph/document/{sample_doc_id}/ingest")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response
        assert "doc_id" in data, "Missing doc_id"
        assert data["doc_id"] == sample_doc_id, "doc_id mismatch"
        
        print(f"Ingested doc {sample_doc_id[:8]}...: {data.get('nodes_created', 0)} nodes, {data.get('edges_created', 0)} edges")
    
    def test_manual_ingest_nonexistent_doc(self):
        """POST /api/graph/document/{doc_id}/ingest - Fails for missing doc"""
        response = requests.post(f"{BASE_URL}/api/graph/document/nonexistent_doc_id/ingest")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Correctly returns 404 for non-existent document")


class TestTransactionGraphLinkageBonus:
    """Test linkage bonus endpoint"""
    
    @pytest.fixture
    def sample_doc_id(self):
        """Get a document ID"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if response.status_code == 200:
            data = response.json()
            if data.get("documents"):
                return data["documents"][0]["id"]
        return None
    
    def test_linkage_bonus_endpoint(self, sample_doc_id):
        """GET /api/graph/document/{doc_id}/linkage-bonus - Returns bonus info"""
        if not sample_doc_id:
            pytest.skip("No documents available")
        
        response = requests.get(
            f"{BASE_URL}/api/graph/document/{sample_doc_id}/linkage-bonus",
            params={"bc_document_no": "TEST-DOC-123"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "has_graph_bonus" in data, "Missing has_graph_bonus"
        assert "graph_bonus" in data, "Missing graph_bonus"
        assert "graph_evidence" in data, "Missing graph_evidence"
        assert "connected_document_count" in data, "Missing connected_document_count"
        
        # Data type assertions
        assert isinstance(data["has_graph_bonus"], bool)
        assert isinstance(data["graph_bonus"], (int, float))
        assert isinstance(data["graph_evidence"], list)
        
        print(f"Linkage bonus: has_bonus={data['has_graph_bonus']}, bonus={data['graph_bonus']}")


# ═══════════════════════════════════════════════════════════════════════
# PROCESSOR SPECS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestProcessorSpecsStats:
    """Test processor specs statistics"""
    
    def test_specs_stats_returns_200(self):
        """GET /api/processor-specs/stats - Returns spec statistics"""
        response = requests.get(f"{BASE_URL}/api/processor-specs/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "total" in data, "Missing total"
        assert "by_status" in data, "Missing by_status"
        
        # Data type assertions
        assert isinstance(data["total"], int)
        assert isinstance(data["by_status"], dict)
        
        print(f"Specs stats: total={data['total']}, by_status={data['by_status']}")


class TestProcessorSpecsList:
    """Test processor specs list endpoint"""
    
    def test_list_specs_returns_200(self):
        """GET /api/processor-specs/list - Lists all specs"""
        response = requests.get(f"{BASE_URL}/api/processor-specs/list")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify response structure
        assert "specs" in data, "Missing specs"
        assert "total" in data, "Missing total"
        assert "limit" in data, "Missing limit"
        assert "skip" in data, "Missing skip"
        
        # Data assertions
        assert isinstance(data["specs"], list)
        
        if len(data["specs"]) > 0:
            spec = data["specs"][0]
            assert "spec_id" in spec, "Spec missing spec_id"
            assert "processor_name" in spec, "Spec missing processor_name"
            assert "spec_status" in spec, "Spec missing spec_status"
        
        print(f"Listed {len(data['specs'])} specs, total: {data['total']}")
    
    def test_list_specs_with_status_filter(self):
        """GET /api/processor-specs/list?status=ready - Filters by status"""
        response = requests.get(f"{BASE_URL}/api/processor-specs/list?status=ready")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # All returned specs should be ready status
        for spec in data["specs"]:
            assert spec["spec_status"] == "ready", f"Expected ready, got {spec['spec_status']}"
        
        print(f"Filtered to {len(data['specs'])} ready specs")


class TestProcessorSpecsCRUD:
    """Test processor specs CRUD operations"""
    
    @pytest.fixture
    def created_spec_id(self):
        """Create a test spec and return its ID"""
        unique_name = f"TEST_TestProcessor_{uuid.uuid4().hex[:8]}"
        payload = {
            "processor_name": unique_name,
            "doc_type": "TEST_TYPE",
            "description": "Test processor for automated testing",
            "detection_patterns": {
                "keywords": ["TEST", "AUTOMATED"],
                "vendor_patterns": [],
                "layout_hints": []
            },
            "field_mappings": [
                {"field_name": "test_field", "field_type": "string", "required": False}
            ],
            "vendor_hints": ["TestVendor"],
            "notes": "Created by automated test"
        }
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/create",
            json=payload
        )
        if response.status_code == 200:
            return response.json().get("spec_id")
        return None
    
    def test_create_spec(self):
        """POST /api/processor-specs/create - Creates new spec"""
        unique_name = f"TEST_CreateSpec_{uuid.uuid4().hex[:8]}"
        payload = {
            "processor_name": unique_name,
            "doc_type": "FREIGHT_BILL",
            "description": "Test spec creation",
            "detection_patterns": {
                "keywords": ["FREIGHT", "BILL"],
                "vendor_patterns": ["UPS", "FEDEX"],
                "layout_hints": []
            },
            "field_mappings": [
                {"field_name": "tracking_number", "field_type": "string", "required": True},
                {"field_name": "total_amount", "field_type": "number", "required": False}
            ],
            "vendor_hints": ["UPS", "FedEx"],
            "reference_hints": [
                {"label": "TRACKING", "pattern": r"\d{10,22}", "example": "1Z999AA10123456784"}
            ],
            "notes": "Automated test spec"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/create",
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response
        assert "spec_id" in data, "Missing spec_id"
        assert data["processor_name"] == unique_name, "processor_name mismatch"
        assert data["spec_status"] == "draft", "New spec should be draft"
        assert data["doc_type"] == "FREIGHT_BILL", "doc_type mismatch"
        
        print(f"Created spec {data['spec_id']} - {data['processor_name']}")
        
        # Cleanup - delete the test spec
        requests.delete(f"{BASE_URL}/api/processor-specs/{data['spec_id']}")
    
    def test_get_spec(self, created_spec_id):
        """GET /api/processor-specs/{spec_id} - Gets single spec"""
        if not created_spec_id:
            pytest.skip("Failed to create test spec")
        
        response = requests.get(f"{BASE_URL}/api/processor-specs/{created_spec_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["spec_id"] == created_spec_id, "spec_id mismatch"
        assert "processor_name" in data, "Missing processor_name"
        assert "spec_status" in data, "Missing spec_status"
        
        print(f"Got spec {created_spec_id}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{created_spec_id}")
    
    def test_get_spec_not_found(self):
        """GET /api/processor-specs/{spec_id} - Returns 404 for missing"""
        response = requests.get(f"{BASE_URL}/api/processor-specs/nonexistent_spec_id")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("Correctly returns 404 for non-existent spec")
    
    def test_update_spec(self, created_spec_id):
        """PUT /api/processor-specs/{spec_id} - Updates spec"""
        if not created_spec_id:
            pytest.skip("Failed to create test spec")
        
        update_payload = {
            "description": "Updated test description",
            "notes": "Updated by automated test"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/processor-specs/{created_spec_id}",
            json=update_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["description"] == "Updated test description", "description not updated"
        assert data["notes"] == "Updated by automated test", "notes not updated"
        
        print(f"Updated spec {created_spec_id}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{created_spec_id}")
    
    def test_delete_spec(self):
        """DELETE /api/processor-specs/{spec_id} - Deletes spec"""
        # First create a spec to delete
        unique_name = f"TEST_DeleteSpec_{uuid.uuid4().hex[:8]}"
        create_response = requests.post(
            f"{BASE_URL}/api/processor-specs/create",
            json={"processor_name": unique_name, "doc_type": "TEST"}
        )
        assert create_response.status_code == 200
        spec_id = create_response.json()["spec_id"]
        
        # Delete it
        response = requests.delete(f"{BASE_URL}/api/processor-specs/{spec_id}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["deleted"] == True, "deleted should be True"
        assert data["spec_id"] == spec_id, "spec_id mismatch"
        
        # Verify it's gone
        get_response = requests.get(f"{BASE_URL}/api/processor-specs/{spec_id}")
        assert get_response.status_code == 404, "Deleted spec should not be found"
        
        print(f"Deleted spec {spec_id}")


class TestProcessorSpecsGeneration:
    """Test processor spec generation"""
    
    @pytest.fixture
    def draft_spec_id(self):
        """Create a draft spec for generation testing"""
        unique_name = f"TEST_GenerateSpec_{uuid.uuid4().hex[:8]}"
        payload = {
            "processor_name": unique_name,
            "doc_type": "SHIPPING_MANIFEST",
            "description": "Processes shipping manifest documents",
            "detection_patterns": {
                "keywords": ["MANIFEST", "SHIPPING", "CARGO"],
                "vendor_patterns": ["MAERSK", "MSC"],
                "layout_hints": []
            },
            "field_mappings": [
                {"field_name": "manifest_number", "field_type": "string", "required": True, "extraction_hint": "Look for MANIFEST# or MBL#"},
                {"field_name": "vessel_name", "field_type": "string", "required": False},
                {"field_name": "container_count", "field_type": "number", "required": False}
            ],
            "vendor_hints": ["Maersk", "MSC", "CMA CGM"],
            "reference_hints": [
                {"label": "MBL", "pattern": r"[A-Z]{4}\d{10}", "example": "MAEU1234567890"}
            ],
            "notes": "For shipping manifest processing"
        }
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/create",
            json=payload
        )
        if response.status_code == 200:
            return response.json().get("spec_id")
        return None
    
    def test_generate_outputs(self, draft_spec_id):
        """POST /api/processor-specs/{spec_id}/generate - Generates outputs"""
        if not draft_spec_id:
            pytest.skip("Failed to create test spec")
        
        response = requests.post(f"{BASE_URL}/api/processor-specs/{draft_spec_id}/generate")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Verify all outputs generated
        assert "spec_id" in data, "Missing spec_id"
        assert "brief" in data, "Missing brief"
        assert "json_spec" in data, "Missing json_spec"
        assert "prompt" in data, "Missing prompt"
        
        # Verify brief content
        assert len(data["brief"]) > 100, "Brief too short"
        assert "SHIPPING_MANIFEST" in data["brief"] or "Shipping Manifest" in data["brief"].title(), "Brief missing doc type"
        
        # Verify JSON spec structure
        assert isinstance(data["json_spec"], dict)
        assert "processor_name" in data["json_spec"]
        assert "detection" in data["json_spec"]
        assert "fields" in data["json_spec"]
        
        # Verify prompt content
        assert len(data["prompt"]) > 100, "Prompt too short"
        assert "detect()" in data["prompt"] or "detect" in data["prompt"].lower(), "Prompt missing detect method"
        
        print(f"Generated outputs for {draft_spec_id}")
        
        # Verify status changed to ready
        get_response = requests.get(f"{BASE_URL}/api/processor-specs/{draft_spec_id}")
        if get_response.status_code == 200:
            spec_data = get_response.json()
            assert spec_data["spec_status"] == "ready", f"Status should be ready, got {spec_data['spec_status']}"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{draft_spec_id}")


class TestProcessorSpecsStatusWorkflow:
    """Test processor spec status transitions"""
    
    @pytest.fixture
    def ready_spec_id(self):
        """Create and generate a ready spec"""
        unique_name = f"TEST_StatusSpec_{uuid.uuid4().hex[:8]}"
        payload = {
            "processor_name": unique_name,
            "doc_type": "TEST_DOC",
            "description": "Test spec for status workflow",
            "detection_patterns": {"keywords": ["TEST"]}
        }
        create_response = requests.post(
            f"{BASE_URL}/api/processor-specs/create",
            json=payload
        )
        if create_response.status_code != 200:
            return None
        spec_id = create_response.json()["spec_id"]
        
        # Generate to make it ready
        requests.post(f"{BASE_URL}/api/processor-specs/{spec_id}/generate")
        return spec_id
    
    def test_set_status_approved(self, ready_spec_id):
        """POST /api/processor-specs/{spec_id}/set-status - Sets approved"""
        if not ready_spec_id:
            pytest.skip("Failed to create ready spec")
        
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/{ready_spec_id}/set-status",
            json={"status": "approved"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["spec_status"] == "approved", f"Expected approved, got {data['spec_status']}"
        print(f"Set spec {ready_spec_id} to approved")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{ready_spec_id}")
    
    def test_set_status_implemented(self, ready_spec_id):
        """POST /api/processor-specs/{spec_id}/set-status - Sets implemented"""
        if not ready_spec_id:
            pytest.skip("Failed to create ready spec")
        
        # First approve
        requests.post(
            f"{BASE_URL}/api/processor-specs/{ready_spec_id}/set-status",
            json={"status": "approved"}
        )
        
        # Then implement
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/{ready_spec_id}/set-status",
            json={"status": "implemented"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["spec_status"] == "implemented", f"Expected implemented, got {data['spec_status']}"
        print(f"Set spec {ready_spec_id} to implemented")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{ready_spec_id}")
    
    def test_set_status_rejected(self, ready_spec_id):
        """POST /api/processor-specs/{spec_id}/set-status - Sets rejected"""
        if not ready_spec_id:
            pytest.skip("Failed to create ready spec")
        
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/{ready_spec_id}/set-status",
            json={"status": "rejected"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data["spec_status"] == "rejected", f"Expected rejected, got {data['spec_status']}"
        print(f"Set spec {ready_spec_id} to rejected")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{ready_spec_id}")
    
    def test_set_invalid_status(self, ready_spec_id):
        """POST /api/processor-specs/{spec_id}/set-status - Invalid status fails"""
        if not ready_spec_id:
            pytest.skip("Failed to create ready spec")
        
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/{ready_spec_id}/set-status",
            json={"status": "invalid_status"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("Correctly rejects invalid status")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{ready_spec_id}")


class TestProcessorSpecsGenerateFromCandidate:
    """Test generate-from-candidate endpoint"""
    
    def test_generate_from_candidate(self):
        """POST /api/processor-specs/generate-from-candidate - Generates from candidate"""
        unique_name = f"TEST_CandidateSpec_{uuid.uuid4().hex[:8]}"
        candidate_payload = {
            "processor_name": unique_name,
            "layout_family_id": "layout_freight_001",
            "doc_type": "FREIGHT_INVOICE",
            "description": "Auto-generated from candidate",
            "sample_document_ids": ["doc-1", "doc-2"],
            "detected_keywords": ["FREIGHT", "INVOICE", "SHIPPING"],
            "detected_vendor_patterns": ["CARRIER INC", "LOGISTICS LLC"],
            "layout_hints": ["Two-column layout", "Header with logo"],
            "detected_fields": {
                "invoice_number": {"type": "string", "required": True, "hint": "Top right corner"},
                "total_amount": {"type": "number", "required": True, "sample_values": [1250.00, 985.50]}
            },
            "reference_patterns": [
                {"label": "PRO", "pattern": r"\d{8,10}", "example": "123456789"}
            ],
            "vendor_hints": ["UPS Freight", "XPO Logistics"],
            "source": "processor_discovery"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/processor-specs/generate-from-candidate",
            json=candidate_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify spec was created with outputs
        assert "spec_id" in data, "Missing spec_id"
        assert "processor_name" in data, "Missing processor_name"
        assert data["processor_name"] == unique_name, "processor_name mismatch"
        
        # Should auto-generate outputs
        assert "brief" in data or "generated_brief" in data, "Missing brief"
        assert "json_spec" in data or "generated_json_spec" in data, "Missing json_spec"
        
        # Status should be ready after generation
        spec_status = data.get("spec_status", "")
        assert spec_status == "ready", f"Expected ready status, got {spec_status}"
        
        print(f"Generated spec from candidate: {data['spec_id']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/processor-specs/{data['spec_id']}")


class TestExistingSpecIntegration:
    """Test with the existing PackingSlipProcessor spec"""
    
    def test_existing_spec_get(self):
        """Verify the pre-created PackingSlipProcessor spec exists"""
        # The spec_id from agent_to_agent_context_note
        spec_id = "spec_985cf54b9267"
        
        response = requests.get(f"{BASE_URL}/api/processor-specs/{spec_id}")
        # It may or may not exist depending on environment state
        if response.status_code == 200:
            data = response.json()
            assert data["spec_id"] == spec_id, "spec_id mismatch"
            assert "processor_name" in data, "Missing processor_name"
            print(f"Found existing spec: {data['processor_name']} ({data['spec_status']})")
        elif response.status_code == 404:
            print(f"Spec {spec_id} not found - may have been cleaned up")
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
