"""
Test Split Preview Panel - Backend API Tests

Tests for the split preview UI feature:
- GET /api/documents/{doc_id}/boundary-analysis
- POST /api/documents/{doc_id}/auto-split
- Document visibility conditions (batch_split, batch_parent_id)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBoundaryAnalysisEndpoint:
    """Tests for GET /api/documents/{doc_id}/boundary-analysis"""
    
    def test_boundary_analysis_returns_3_groups(self):
        """Test that boundary analysis returns 3 document groups for test-multipage-split"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "analysis" in data, "Response should contain 'analysis' field"
        
        analysis = data["analysis"]
        assert analysis["total_pages"] == 5, f"Expected 5 pages, got {analysis['total_pages']}"
        assert analysis["should_split"] == True, "should_split should be True"
        assert analysis["document_count"] == 3, f"Expected 3 documents, got {analysis['document_count']}"
        print(f"SUCCESS: Boundary analysis returns {analysis['document_count']} groups for 5-page doc")
    
    def test_boundary_analysis_groups_have_correct_pages(self):
        """Test that groups have correct page assignments"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        groups = response.json()["analysis"]["groups"]
        
        # Group 1: Pages 1-2 (TUMALO CREEK TRANSPORTATION)
        assert groups[0]["pages"] == [1, 2], f"Group 1 should have pages [1, 2], got {groups[0]['pages']}"
        assert groups[0]["page_range"] == "1-2", f"Group 1 page_range should be '1-2'"
        assert "TUMALO" in groups[0]["vendor_hint"].upper(), f"Group 1 vendor should contain TUMALO"
        
        # Group 2: Page 3 (ANCHOR GLASS)
        assert groups[1]["pages"] == [3], f"Group 2 should have pages [3], got {groups[1]['pages']}"
        assert groups[1]["page_range"] == "3", f"Group 2 page_range should be '3'"
        assert "ANCHOR" in groups[1]["vendor_hint"].upper(), f"Group 2 vendor should contain ANCHOR"
        
        # Group 3: Pages 4-5 (PACIFIC FREIGHT)
        assert groups[2]["pages"] == [4, 5], f"Group 3 should have pages [4, 5], got {groups[2]['pages']}"
        assert groups[2]["page_range"] == "4-5", f"Group 3 page_range should be '4-5'"
        assert "PACIFIC" in groups[2]["vendor_hint"].upper(), f"Group 3 vendor should contain PACIFIC"
        
        print("SUCCESS: All 3 groups have correct page assignments")
    
    def test_boundary_analysis_groups_have_vendor_hints(self):
        """Test that groups include vendor hints"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        groups = response.json()["analysis"]["groups"]
        
        for i, group in enumerate(groups):
            assert "vendor_hint" in group, f"Group {i+1} should have vendor_hint"
            assert group["vendor_hint"], f"Group {i+1} vendor_hint should not be empty"
            print(f"Group {i+1} vendor_hint: {group['vendor_hint']}")
        
        print("SUCCESS: All groups have vendor hints")
    
    def test_boundary_analysis_groups_have_doc_type_hints(self):
        """Test that groups include document type hints"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        groups = response.json()["analysis"]["groups"]
        
        for i, group in enumerate(groups):
            assert "doc_type_hints" in group, f"Group {i+1} should have doc_type_hints"
            print(f"Group {i+1} doc_type_hints: {group['doc_type_hints']}")
        
        print("SUCCESS: All groups have doc_type_hints field")
    
    def test_boundary_analysis_groups_have_ref_numbers(self):
        """Test that groups include reference numbers"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        groups = response.json()["analysis"]["groups"]
        
        # Group 1 should have invoice_no
        assert "invoice_no" in groups[0]["ref_numbers"], "Group 1 should have invoice_no"
        assert groups[0]["ref_numbers"]["invoice_no"] == "TC-2026-001"
        
        # Group 2 should have invoice_no
        assert "invoice_no" in groups[1]["ref_numbers"], "Group 2 should have invoice_no"
        assert groups[1]["ref_numbers"]["invoice_no"] == "AG-8842"
        
        # Group 3 should have bol_no
        assert "bol_no" in groups[2]["ref_numbers"], "Group 3 should have bol_no"
        assert groups[2]["ref_numbers"]["bol_no"] == "PFS-330291"
        
        print("SUCCESS: All groups have correct reference numbers")
    
    def test_boundary_analysis_returns_boundaries(self):
        """Test that boundary analysis returns boundary page numbers"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        boundaries = response.json()["analysis"]["boundaries"]
        assert boundaries == [1, 3, 4], f"Expected boundaries [1, 3, 4], got {boundaries}"
        
        print("SUCCESS: Boundaries correctly identified at pages 1, 3, 4")
    
    def test_boundary_analysis_returns_fingerprints(self):
        """Test that boundary analysis returns page fingerprints"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        fingerprints = response.json()["analysis"]["fingerprints"]
        assert len(fingerprints) == 5, f"Expected 5 fingerprints, got {len(fingerprints)}"
        
        for i, fp in enumerate(fingerprints):
            assert fp["page_num"] == i + 1, f"Fingerprint {i} should have page_num {i+1}"
            assert "is_blank" in fp, f"Fingerprint {i} should have is_blank"
            assert "vendor_hint" in fp, f"Fingerprint {i} should have vendor_hint"
        
        print("SUCCESS: All 5 page fingerprints returned")
    
    def test_boundary_analysis_404_for_missing_doc(self):
        """Test that boundary analysis returns 404 for non-existent document"""
        response = requests.get(f"{BASE_URL}/api/documents/non-existent-doc-id/boundary-analysis")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("SUCCESS: Returns 404 for missing document")


class TestAutoSplitEndpoint:
    """Tests for POST /api/documents/{doc_id}/auto-split"""
    
    def test_auto_split_returns_success_structure(self):
        """Test that auto-split returns proper response structure"""
        # Note: This will actually split the document, so we check the response structure
        response = requests.post(f"{BASE_URL}/api/documents/test-multipage-split/auto-split")
        
        # Could be 200 (success) or 200 with success=False (already split)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "success" in data, "Response should contain 'success' field"
        
        if data["success"]:
            assert "result" in data, "Successful split should contain 'result'"
            assert "analysis" in data, "Successful split should contain 'analysis'"
            print(f"SUCCESS: Auto-split completed - {data['result'].get('children_count', 0)} children created")
        else:
            assert "reason" in data, "Failed split should contain 'reason'"
            print(f"INFO: Auto-split not performed - {data.get('reason', 'unknown reason')}")
    
    def test_auto_split_404_for_missing_doc(self):
        """Test that auto-split returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/documents/non-existent-doc-id/auto-split")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("SUCCESS: Returns 404 for missing document")


class TestDocumentVisibilityConditions:
    """Tests for Split Preview panel visibility conditions"""
    
    def test_document_has_batch_detected_flag(self):
        """Test that test document has batch_detected=true"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split")
        assert response.status_code == 200
        
        doc = response.json()["document"]
        assert doc.get("batch_detected") == True, "Document should have batch_detected=true"
        print("SUCCESS: Document has batch_detected=true")
    
    def test_document_has_batch_page_count(self):
        """Test that test document has batch_page_count=5"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split")
        assert response.status_code == 200
        
        doc = response.json()["document"]
        assert doc.get("batch_page_count") == 5, f"Expected batch_page_count=5, got {doc.get('batch_page_count')}"
        print("SUCCESS: Document has batch_page_count=5")
    
    def test_document_has_batch_split_suggested(self):
        """Test that test document has batch_split_suggested=true"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split")
        assert response.status_code == 200
        
        doc = response.json()["document"]
        assert doc.get("batch_split_suggested") == True, "Document should have batch_split_suggested=true"
        print("SUCCESS: Document has batch_split_suggested=true")
    
    def test_document_not_already_split(self):
        """Test that test document is not already split (batch_split should be false/null)"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split")
        assert response.status_code == 200
        
        doc = response.json()["document"]
        # batch_split should be False or not present for the panel to show
        batch_split = doc.get("batch_split", False)
        assert batch_split != True, "Document should not have batch_split=true (would hide panel)"
        print(f"SUCCESS: Document batch_split={batch_split} (panel should be visible)")
    
    def test_document_has_no_batch_parent_id(self):
        """Test that test document has no batch_parent_id (not a child doc)"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split")
        assert response.status_code == 200
        
        doc = response.json()["document"]
        # batch_parent_id should be None/not present for the panel to show
        batch_parent_id = doc.get("batch_parent_id")
        assert batch_parent_id is None, f"Document should not have batch_parent_id, got {batch_parent_id}"
        print("SUCCESS: Document has no batch_parent_id (panel should be visible)")


class TestAnalysisResponseStructure:
    """Tests for the complete analysis response structure"""
    
    def test_analysis_has_all_required_fields(self):
        """Test that analysis response has all required fields"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        data = response.json()
        
        # Top-level fields
        assert "document_id" in data, "Response should have document_id"
        assert "filename" in data, "Response should have filename"
        assert "analysis" in data, "Response should have analysis"
        
        analysis = data["analysis"]
        
        # Analysis fields
        required_fields = ["total_pages", "should_split", "document_count", "groups", "boundaries", "fingerprints", "analysis"]
        for field in required_fields:
            assert field in analysis, f"Analysis should have '{field}' field"
        
        print("SUCCESS: Analysis response has all required fields")
    
    def test_group_structure_is_complete(self):
        """Test that each group has all required fields"""
        response = requests.get(f"{BASE_URL}/api/documents/test-multipage-split/boundary-analysis")
        assert response.status_code == 200
        
        groups = response.json()["analysis"]["groups"]
        
        required_group_fields = ["group_num", "pages", "page_range", "page_count", "vendor_hint", "doc_type_hints", "ref_numbers"]
        
        for i, group in enumerate(groups):
            for field in required_group_fields:
                assert field in group, f"Group {i+1} should have '{field}' field"
        
        print("SUCCESS: All groups have complete structure")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
