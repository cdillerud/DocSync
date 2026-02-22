"""
Test Document Type Dashboard API
Tests GET /api/dashboard/document-types endpoint with filters
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestDocumentTypesDashboard:
    """Tests for GET /api/dashboard/document-types endpoint"""
    
    def test_get_document_types_no_filter(self):
        """Test getting document types dashboard without filters"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify response structure
        assert "by_type" in data
        assert "filters" in data
        assert "source_systems_available" in data
        assert "doc_types_available" in data
        assert "grand_total" in data
        
        # Verify filters reflect no filtering
        assert data["filters"]["source_system"] is None
        assert data["filters"]["doc_type"] is None
        
        # Verify grand_total is a number
        assert isinstance(data["grand_total"], int)
        assert data["grand_total"] >= 0
    
    def test_get_document_types_by_type_structure(self):
        """Test that by_type entries have correct structure"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        by_type = data.get("by_type", {})
        
        # If there are any types with data, verify structure
        for doc_type, type_data in by_type.items():
            # Verify required fields
            assert "total" in type_data
            assert "status_counts" in type_data
            assert "extraction" in type_data
            assert "match_methods" in type_data
            assert "avg_confidence" in type_data
            
            # Verify extraction substructure
            extraction = type_data["extraction"]
            for field in ["vendor", "invoice_number", "amount", "po_number", "due_date"]:
                assert field in extraction
                assert "rate" in extraction[field]
                assert "count" in extraction[field]
                # Rate should be between 0 and 1
                assert 0 <= extraction[field]["rate"] <= 1
                assert extraction[field]["count"] >= 0
            
            # Verify total >= 0
            assert type_data["total"] >= 0
            
            # Verify avg_confidence is a number
            assert isinstance(type_data["avg_confidence"], (int, float))
    
    def test_filter_by_source_system(self):
        """Test filtering by source_system parameter"""
        # Test with GPI_HUB_NATIVE
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?source_system=GPI_HUB_NATIVE")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify filter is reflected
        assert data["filters"]["source_system"] == "GPI_HUB_NATIVE"
        
        # Grand total should be <= unfiltered total
        unfiltered = requests.get(f"{BASE_URL}/api/dashboard/document-types").json()
        assert data["grand_total"] <= unfiltered["grand_total"]
    
    def test_filter_by_doc_type_other(self):
        """Test filtering by doc_type=OTHER"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?doc_type=OTHER")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify filter is reflected
        assert data["filters"]["doc_type"] == "OTHER"
        
        # When filtering by doc_type, all supported doc_types should be in by_type
        # (even with 0 total - as per API behavior)
        assert "OTHER" in data["by_type"]
        
        # Verify doc_types_available shows all supported types when filtering
        assert len(data["doc_types_available"]) >= 1
    
    def test_filter_by_doc_type_ap_invoice(self):
        """Test filtering by doc_type=AP_INVOICE"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?doc_type=AP_INVOICE")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify filter is reflected
        assert data["filters"]["doc_type"] == "AP_INVOICE"
        
        # AP_INVOICE should be in by_type
        assert "AP_INVOICE" in data["by_type"]
    
    def test_combined_filters(self):
        """Test combining source_system and doc_type filters"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/document-types?source_system=GPI_HUB_NATIVE&doc_type=OTHER"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Both filters should be reflected
        assert data["filters"]["source_system"] == "GPI_HUB_NATIVE"
        assert data["filters"]["doc_type"] == "OTHER"
    
    def test_source_systems_available(self):
        """Test that source_systems_available contains valid systems with counts"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        source_systems = data.get("source_systems_available", {})
        
        # Each source system should have a count >= 0
        for system, count in source_systems.items():
            assert isinstance(count, int)
            assert count >= 0
    
    def test_status_counts_are_valid(self):
        """Test that status_counts contains valid workflow statuses"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        valid_statuses = [
            "captured", "classified", "extracted", "vendor_pending",
            "bc_validation_pending", "bc_validation_failed", 
            "data_correction_pending", "review_pending",
            "ready_for_approval", "approval_in_progress",
            "approved", "rejected", "exported", "archived", "failed",
            "none"  # for documents without workflow_status
        ]
        
        for doc_type, type_data in data.get("by_type", {}).items():
            for status in type_data.get("status_counts", {}).keys():
                assert status in valid_statuses, f"Unexpected status '{status}' for {doc_type}"
    
    def test_match_methods_are_valid(self):
        """Test that match_methods contains valid method names"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        valid_methods = ["exact", "normalized", "alias", "fuzzy", "manual", "none"]
        
        for doc_type, type_data in data.get("by_type", {}).items():
            for method in type_data.get("match_methods", {}).keys():
                assert method in valid_methods, f"Unexpected match method '{method}' for {doc_type}"
    
    def test_invalid_source_system_returns_empty(self):
        """Test that invalid source_system filter returns empty results"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/document-types?source_system=INVALID_SYSTEM"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Should return empty by_type or 0 grand_total
        assert data["grand_total"] == 0 or len(data.get("by_type", {})) == 0


class TestDocumentTypesDashboardWithData:
    """Tests verifying dashboard reflects actual document data"""
    
    def test_grand_total_equals_sum_of_by_type_totals(self):
        """Test that grand_total equals sum of all by_type totals"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        sum_totals = sum(type_data["total"] for type_data in data.get("by_type", {}).values())
        assert data["grand_total"] == sum_totals
    
    def test_extraction_count_not_exceed_total(self):
        """Test that extraction counts don't exceed total documents"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        for doc_type, type_data in data.get("by_type", {}).items():
            total = type_data["total"]
            extraction = type_data["extraction"]
            
            for field in ["vendor", "invoice_number", "amount", "po_number", "due_date"]:
                assert extraction[field]["count"] <= total, \
                    f"{field} count ({extraction[field]['count']}) exceeds total ({total}) for {doc_type}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
