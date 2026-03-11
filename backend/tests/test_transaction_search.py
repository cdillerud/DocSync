"""
Transaction Search API Tests
Tests the new Transaction Search page endpoints:
  GET /api/transaction-search           — Main search (exact → normalized → fuzzy)
  GET /api/transaction-search/node/{node_id}/chain  — Chain from a node
  GET /api/transaction-search/document/{doc_id}/chain — Chain from a document
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestTransactionSearchMainEndpoint:
    """Tests for GET /api/transaction-search"""

    def test_exact_search_po12345(self):
        """Search for PO12345 - should return exact match with tier 'exact'"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO12345"})
        assert response.status_code == 200
        data = response.json()
        
        assert "query" in data
        assert data["query"] == "PO12345"
        assert "normalized" in data
        assert data["normalized"] == "12345"  # normalize_reference strips prefix
        assert "total_results" in data
        assert data["total_results"] >= 1
        assert "results" in data
        
        # Find the exact match
        exact_matches = [r for r in data["results"] if r["match_tier"] == "exact"]
        assert len(exact_matches) >= 1
        
        # Check structure of result
        first_result = data["results"][0]
        assert "node_id" in first_result
        assert "node_type" in first_result
        assert "reference_value" in first_result
        assert "match_tier" in first_result
        assert "match_confidence" in first_result
        assert "connected_count" in first_result
        assert "connected_doc_hint" in first_result

    def test_normalized_search_strips_prefix(self):
        """Search with space (PO 12345) - should normalize and find results"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO 12345"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["query"] == "PO 12345"
        assert data["normalized"] == "12345"  # normalized strips prefix
        assert data["total_results"] >= 1
        
        # Should have normalized or likely matches
        tiers = [r["match_tier"] for r in data["results"]]
        assert any(t in ["normalized", "likely", "exact"] for t in tiers)

    def test_numeric_partial_search(self):
        """Search for numeric '12345' - should find related nodes"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "12345"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["query"] == "12345"
        assert data["total_results"] >= 1
        
        # Should have exact match for invoice 12345
        exact_matches = [r for r in data["results"] if r["match_tier"] == "exact"]
        assert len(exact_matches) >= 1

    def test_bol_search(self):
        """Search for BOL reference 110743"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "110743"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_results"] >= 1
        
        # Should find bill_of_lading node
        bol_results = [r for r in data["results"] if r["node_type"] == "bill_of_lading"]
        assert len(bol_results) >= 1
        assert bol_results[0]["reference_value"] == "110743"

    def test_empty_results_for_nonexistent(self):
        """Search for nonexistent reference should return empty results"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "nonexistent123xyz"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_results"] == 0
        assert len(data["results"]) == 0

    def test_node_type_filter(self):
        """Filter by node_type=purchase_order"""
        response = requests.get(
            f"{BASE_URL}/api/transaction-search",
            params={"q": "PO12345", "node_type": "purchase_order"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_results"] >= 1
        # All results should be purchase_order type
        for result in data["results"]:
            assert result["node_type"] == "purchase_order"

    def test_vendor_filter(self):
        """Filter by vendor name"""
        response = requests.get(
            f"{BASE_URL}/api/transaction-search",
            params={"q": "12345", "vendor": "Acme"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_results"] >= 1
        # Should filter to Acme vendor
        for result in data["results"]:
            if result.get("vendor_name"):
                assert "acme" in result["vendor_name"].lower()

    def test_limit_parameter(self):
        """Test limit parameter works"""
        response = requests.get(
            f"{BASE_URL}/api/transaction-search",
            params={"q": "1", "limit": "5"}  # search for '1' to get many results
        )
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["results"]) <= 5

    def test_min_confidence_parameter_accepted(self):
        """Test min_confidence parameter is accepted (used for edge filtering in chains)"""
        response = requests.get(
            f"{BASE_URL}/api/transaction-search",
            params={"q": "12345", "min_confidence": "0.8"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # min_confidence is passed to API but primary use is for chain edge filtering
        # Search still returns all tier matches; frontend can filter display
        assert "results" in data


class TestNodeChainEndpoint:
    """Tests for GET /api/transaction-search/node/{node_id}/chain"""

    @pytest.fixture
    def po12345_node_id(self):
        """Get node_id for PO12345"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO12345"})
        data = response.json()
        po_results = [r for r in data["results"] if r["reference_value"] == "PO12345"]
        if po_results:
            return po_results[0]["node_id"]
        return None

    def test_chain_retrieval_default_depth(self, po12345_node_id):
        """Get chain with default depth (3)"""
        if not po12345_node_id:
            pytest.skip("PO12345 node not found")
        
        response = requests.get(f"{BASE_URL}/api/transaction-search/node/{po12345_node_id}/chain")
        assert response.status_code == 200
        data = response.json()
        
        assert data["start_node_id"] == po12345_node_id
        assert "chain_steps" in data
        assert len(data["chain_steps"]) >= 1
        assert "connected_documents" in data
        assert "total_nodes" in data
        assert "total_edges" in data
        assert data["max_depth_used"] == 3
        
        # Check chain step structure
        first_step = data["chain_steps"][0]
        assert "node_id" in first_step
        assert "node_type" in first_step
        assert "reference_value" in first_step
        assert "depth" in first_step
        assert "edges" in first_step

    def test_chain_with_shallow_depth(self, po12345_node_id):
        """Get chain with max_depth=1 (shallow)"""
        if not po12345_node_id:
            pytest.skip("PO12345 node not found")
        
        response = requests.get(
            f"{BASE_URL}/api/transaction-search/node/{po12345_node_id}/chain",
            params={"max_depth": 1}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["max_depth_used"] == 1
        # Shallow chain should have fewer nodes than default
        for step in data["chain_steps"]:
            assert step["depth"] <= 1

    def test_chain_with_deep_depth(self, po12345_node_id):
        """Get chain with max_depth=5 (deep)"""
        if not po12345_node_id:
            pytest.skip("PO12345 node not found")
        
        response = requests.get(
            f"{BASE_URL}/api/transaction-search/node/{po12345_node_id}/chain",
            params={"max_depth": 5}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["max_depth_used"] == 5

    def test_chain_nonexistent_node_404(self):
        """Chain for nonexistent node should return 404"""
        response = requests.get(f"{BASE_URL}/api/transaction-search/node/nonexistent_node_id/chain")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data.get("detail", "").lower()

    def test_chain_edges_have_provenance(self, po12345_node_id):
        """Verify chain step edges have provenance and confidence"""
        if not po12345_node_id:
            pytest.skip("PO12345 node not found")
        
        response = requests.get(f"{BASE_URL}/api/transaction-search/node/{po12345_node_id}/chain")
        assert response.status_code == 200
        data = response.json()
        
        # Find a step with edges
        steps_with_edges = [s for s in data["chain_steps"] if len(s.get("edges", [])) > 0]
        assert len(steps_with_edges) >= 1
        
        for step in steps_with_edges:
            for edge in step["edges"]:
                assert "edge_id" in edge
                assert "edge_type" in edge
                assert "confidence" in edge
                assert "provenance" in edge
                assert "direction" in edge
                assert "connected_to" in edge
                assert edge["direction"] in ["outgoing", "incoming"]


class TestDocumentChainEndpoint:
    """Tests for GET /api/transaction-search/document/{doc_id}/chain"""

    @pytest.fixture
    def document_id(self):
        """Get a document ID from the graph"""
        response = requests.get(
            f"{BASE_URL}/api/graph/nodes",
            params={"node_type": "document", "limit": 1}
        )
        data = response.json()
        if data.get("nodes"):
            return data["nodes"][0]["reference_value"]
        return None

    def test_document_chain_retrieval(self, document_id):
        """Get chain from a document"""
        if not document_id:
            pytest.skip("No document found in graph")
        
        response = requests.get(f"{BASE_URL}/api/transaction-search/document/{document_id}/chain")
        assert response.status_code == 200
        data = response.json()
        
        assert "start_node_id" in data
        assert "chain_steps" in data
        assert "connected_documents" in data
        assert "total_nodes" in data
        assert "total_edges" in data
        assert data.get("doc_id") == document_id

    def test_document_chain_nonexistent_404(self):
        """Chain for nonexistent document should return 404"""
        response = requests.get(f"{BASE_URL}/api/transaction-search/document/nonexistent_doc_id/chain")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data.get("detail", "").lower()

    def test_document_chain_with_depth(self, document_id):
        """Get document chain with custom depth"""
        if not document_id:
            pytest.skip("No document found in graph")
        
        response = requests.get(
            f"{BASE_URL}/api/transaction-search/document/{document_id}/chain",
            params={"max_depth": 2}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["max_depth_used"] == 2


class TestSearchResponseStructure:
    """Tests for search response structure and data integrity"""

    def test_match_tiers_are_valid(self):
        """Verify match_tier values are valid"""
        valid_tiers = {"exact", "normalized", "likely", "fuzzy"}
        
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO12345"})
        assert response.status_code == 200
        data = response.json()
        
        for result in data["results"]:
            assert result["match_tier"] in valid_tiers

    def test_match_confidence_range(self):
        """Verify match_confidence is between 0 and 1"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "12345"})
        assert response.status_code == 200
        data = response.json()
        
        for result in data["results"]:
            assert 0 <= result["match_confidence"] <= 1

    def test_tier_confidence_correlation(self):
        """Verify tier correlates with confidence"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO12345"})
        assert response.status_code == 200
        data = response.json()
        
        for result in data["results"]:
            tier = result["match_tier"]
            conf = result["match_confidence"]
            
            if tier == "exact":
                assert conf == 1.0
            elif tier == "normalized":
                assert conf == 0.9
            elif tier == "likely":
                assert conf == 0.7
            elif tier == "fuzzy":
                assert conf == 0.5


class TestEdgeCases:
    """Edge case and error handling tests"""

    def test_empty_query_rejected(self):
        """Empty query should be rejected"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": ""})
        assert response.status_code == 422  # validation error

    def test_whitespace_query(self):
        """Whitespace-only query should be handled"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "   "})
        # Should either fail validation or return empty results
        assert response.status_code in [200, 422]

    def test_special_characters_in_query(self):
        """Special characters should be handled"""
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "INV-99999"})
        assert response.status_code == 200
        data = response.json()
        # Should return results (INV-99999 exists in graph)
        assert "results" in data

    def test_long_query_handled(self):
        """Long query should be handled"""
        long_query = "A" * 200
        response = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": long_query})
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 0  # No match expected

    def test_invalid_max_depth(self):
        """Invalid max_depth should be rejected"""
        # Get a valid node first
        search_resp = requests.get(f"{BASE_URL}/api/transaction-search", params={"q": "PO12345"})
        node_id = search_resp.json()["results"][0]["node_id"]
        
        # Test max_depth > 5 (max allowed is 5)
        response = requests.get(
            f"{BASE_URL}/api/transaction-search/node/{node_id}/chain",
            params={"max_depth": 10}
        )
        assert response.status_code == 422  # validation error

    def test_invalid_min_confidence(self):
        """Invalid min_confidence should be rejected"""
        response = requests.get(
            f"{BASE_URL}/api/transaction-search",
            params={"q": "test", "min_confidence": 1.5}  # > 1.0
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
