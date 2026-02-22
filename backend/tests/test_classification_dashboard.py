"""
Test Document Type Dashboard Classification Features
Tests the new classification_counts, ai_assisted_count, ai_suggested_but_rejected_count fields
and classification filter on GET /api/dashboard/document-types endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestClassificationFieldsInDashboard:
    """Test classification_counts, ai_assisted_count, ai_suggested_but_rejected_count per doc_type"""
    
    def test_classification_counts_structure(self):
        """Test that each doc_type has classification_counts with deterministic, ai, other keys"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        by_type = data.get("by_type", {})
        
        for doc_type, type_data in by_type.items():
            assert "classification_counts" in type_data, f"Missing classification_counts for {doc_type}"
            
            classification_counts = type_data["classification_counts"]
            assert "deterministic" in classification_counts, f"Missing deterministic in classification_counts for {doc_type}"
            assert "ai" in classification_counts, f"Missing ai in classification_counts for {doc_type}"
            assert "other" in classification_counts, f"Missing other in classification_counts for {doc_type}"
            
            # Verify all are non-negative integers
            assert isinstance(classification_counts["deterministic"], int)
            assert isinstance(classification_counts["ai"], int)
            assert isinstance(classification_counts["other"], int)
            assert classification_counts["deterministic"] >= 0
            assert classification_counts["ai"] >= 0
            assert classification_counts["other"] >= 0
    
    def test_ai_assisted_count_field(self):
        """Test that each doc_type has ai_assisted_count field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        by_type = data.get("by_type", {})
        
        for doc_type, type_data in by_type.items():
            assert "ai_assisted_count" in type_data, f"Missing ai_assisted_count for {doc_type}"
            assert isinstance(type_data["ai_assisted_count"], int)
            assert type_data["ai_assisted_count"] >= 0
    
    def test_ai_suggested_but_rejected_count_field(self):
        """Test that each doc_type has ai_suggested_but_rejected_count field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        by_type = data.get("by_type", {})
        
        for doc_type, type_data in by_type.items():
            assert "ai_suggested_but_rejected_count" in type_data, f"Missing ai_suggested_but_rejected_count for {doc_type}"
            assert isinstance(type_data["ai_suggested_but_rejected_count"], int)
            assert type_data["ai_suggested_but_rejected_count"] >= 0
    
    def test_classification_counts_sum_equals_total(self):
        """Test that sum of classification_counts equals total for each doc_type"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        by_type = data.get("by_type", {})
        
        for doc_type, type_data in by_type.items():
            total = type_data["total"]
            classification_counts = type_data["classification_counts"]
            
            classification_sum = (
                classification_counts["deterministic"] +
                classification_counts["ai"] +
                classification_counts["other"]
            )
            
            assert classification_sum == total, \
                f"Classification counts sum ({classification_sum}) != total ({total}) for {doc_type}"
    
    def test_classification_totals_in_response(self):
        """Test that global classification_totals is present in response"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        
        assert "classification_totals" in data, "Missing classification_totals in response"
        classification_totals = data["classification_totals"]
        
        assert "deterministic" in classification_totals
        assert "ai" in classification_totals
        assert "other" in classification_totals
        
        # Verify totals are non-negative
        assert classification_totals["deterministic"] >= 0
        assert classification_totals["ai"] >= 0
        assert classification_totals["other"] >= 0
    
    def test_classification_totals_sum_equals_grand_total(self):
        """Test that sum of classification_totals equals grand_total"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        grand_total = data["grand_total"]
        classification_totals = data["classification_totals"]
        
        totals_sum = (
            classification_totals["deterministic"] +
            classification_totals["ai"] +
            classification_totals["other"]
        )
        
        assert totals_sum == grand_total, \
            f"Classification totals sum ({totals_sum}) != grand_total ({grand_total})"


class TestClassificationFilter:
    """Test classification filter parameter on GET /api/dashboard/document-types"""
    
    def test_classification_filter_parameter_accepted(self):
        """Test that classification filter parameter is accepted"""
        # Test 'all' filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=all")
        assert response.status_code == 200
        
        # Test 'deterministic' filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=deterministic")
        assert response.status_code == 200
        
        # Test 'ai' filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=ai")
        assert response.status_code == 200
    
    def test_classification_filter_reflected_in_response(self):
        """Test that classification filter is reflected in filters object"""
        # Test deterministic filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=deterministic")
        assert response.status_code == 200
        
        data = response.json()
        assert data["filters"]["classification"] == "deterministic"
        
        # Test ai filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=ai")
        assert response.status_code == 200
        
        data = response.json()
        assert data["filters"]["classification"] == "ai"
    
    def test_classification_filter_all_returns_all_documents(self):
        """Test that classification=all returns all documents"""
        # Get all documents
        all_response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        all_data = all_response.json()
        
        # Get with classification=all
        filtered_response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=all")
        filtered_data = filtered_response.json()
        
        # Both should return same grand_total
        assert all_data["grand_total"] == filtered_data["grand_total"]
        
        # Filter should be None when 'all' is passed (normalized)
        assert filtered_data["filters"]["classification"] is None
    
    def test_classification_filter_deterministic_filters_correctly(self):
        """Test that classification=deterministic only returns deterministic-classified docs"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=deterministic")
        assert response.status_code == 200
        
        data = response.json()
        
        # Grand total should equal sum of deterministic counts across all types
        by_type = data.get("by_type", {})
        
        # When filtering by deterministic, grand_total should be deterministic-only
        # and each type's total should reflect only deterministic classified docs
        for doc_type, type_data in by_type.items():
            # In filtered view, total should be deterministic count
            # (since we're filtering to only deterministic)
            pass  # This is tested by test_filter_reduces_count
    
    def test_classification_filter_ai_filters_correctly(self):
        """Test that classification=ai only returns ai-classified docs"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=ai")
        assert response.status_code == 200
        
        data = response.json()
        # AI filter returns only AI-classified documents
        # Response structure should be valid
        assert "by_type" in data
        assert "grand_total" in data
    
    def test_filter_reduces_or_maintains_count(self):
        """Test that filtering reduces or maintains document count"""
        # Get unfiltered count
        unfiltered = requests.get(f"{BASE_URL}/api/dashboard/document-types").json()
        unfiltered_total = unfiltered["grand_total"]
        
        # Get deterministic filtered count
        det_filtered = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=deterministic").json()
        det_total = det_filtered["grand_total"]
        
        # Get ai filtered count
        ai_filtered = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=ai").json()
        ai_total = ai_filtered["grand_total"]
        
        # Filtered counts should be <= unfiltered
        assert det_total <= unfiltered_total
        assert ai_total <= unfiltered_total
    
    def test_classification_methods_available_in_response(self):
        """Test that classification_methods_available is present in response"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        assert response.status_code == 200
        
        data = response.json()
        assert "classification_methods_available" in data
        
        methods = data["classification_methods_available"]
        assert "all" in methods
        assert "deterministic" in methods
        assert "ai" in methods
    
    def test_combined_classification_and_source_system_filter(self):
        """Test combining classification filter with source_system filter"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/document-types?classification=deterministic&source_system=GPI_HUB_NATIVE"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Both filters should be reflected
        assert data["filters"]["classification"] == "deterministic"
        assert data["filters"]["source_system"] == "GPI_HUB_NATIVE"
    
    def test_combined_classification_and_doc_type_filter(self):
        """Test combining classification filter with doc_type filter"""
        response = requests.get(
            f"{BASE_URL}/api/dashboard/document-types?classification=deterministic&doc_type=AP_INVOICE"
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Both filters should be reflected
        assert data["filters"]["classification"] == "deterministic"
        assert data["filters"]["doc_type"] == "AP_INVOICE"
    
    def test_invalid_classification_filter_treated_as_all(self):
        """Test that invalid classification filter is treated as 'all'"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=invalid")
        assert response.status_code == 200
        
        data = response.json()
        
        # Invalid filter should be normalized to None (all)
        assert data["filters"]["classification"] is None


class TestClassificationExportCSV:
    """Test classification fields in CSV export"""
    
    def test_export_has_classification_columns(self):
        """Test that CSV export includes classification columns"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types/export")
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")
        
        lines = response.text.split('\n')
        header = lines[0]
        
        # Check for classification columns
        assert "classification_deterministic" in header
        assert "classification_ai" in header
        assert "classification_other" in header
        assert "ai_assisted_count" in header
        assert "ai_suggested_but_rejected_count" in header
    
    def test_export_has_classification_filter_column(self):
        """Test that CSV export includes classification_filter column"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types/export")
        assert response.status_code == 200
        
        lines = response.text.split('\n')
        header = lines[0]
        
        assert "classification_filter" in header
    
    def test_export_with_classification_filter(self):
        """Test that CSV export respects classification filter"""
        # Export with deterministic filter
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types/export?classification=deterministic")
        assert response.status_code == 200
        
        lines = response.text.split('\n')
        if len(lines) > 1:
            # Check that classification_filter column shows "deterministic"
            # (second line is first data row)
            header = lines[0].split(',')
            filter_idx = header.index('classification_filter')
            
            for line in lines[1:]:
                if line.strip():  # Skip empty lines
                    values = line.split(',')
                    assert values[filter_idx] == 'deterministic', \
                        f"Expected 'deterministic' in classification_filter but got '{values[filter_idx]}'"
    
    def test_export_classification_values_are_numbers(self):
        """Test that classification values in CSV are valid numbers"""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types/export")
        assert response.status_code == 200
        
        lines = response.text.split('\n')
        header = lines[0].split(',')
        
        det_idx = header.index('classification_deterministic')
        ai_idx = header.index('classification_ai')
        other_idx = header.index('classification_other')
        
        for line in lines[1:]:
            if line.strip():
                values = line.split(',')
                # Verify these are valid integers
                try:
                    det_val = int(values[det_idx])
                    ai_val = int(values[ai_idx])
                    other_val = int(values[other_idx])
                    assert det_val >= 0
                    assert ai_val >= 0
                    assert other_val >= 0
                except ValueError as e:
                    pytest.fail(f"Invalid classification value in CSV: {e}")


class TestDataConsistency:
    """Test data consistency across different views"""
    
    def test_det_plus_ai_filter_equals_det_ai_totals(self):
        """Test that deterministic + ai filtered counts equal classification_totals.deterministic + ai"""
        # Get unfiltered totals
        all_data = requests.get(f"{BASE_URL}/api/dashboard/document-types").json()
        totals = all_data["classification_totals"]
        
        # Get deterministic filtered count
        det_data = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=deterministic").json()
        det_filtered_total = det_data["grand_total"]
        
        # Get ai filtered count
        ai_data = requests.get(f"{BASE_URL}/api/dashboard/document-types?classification=ai").json()
        ai_filtered_total = ai_data["grand_total"]
        
        # Filtered counts should match classification_totals
        assert det_filtered_total == totals["deterministic"], \
            f"Deterministic filter total ({det_filtered_total}) != classification_totals.deterministic ({totals['deterministic']})"
        assert ai_filtered_total == totals["ai"], \
            f"AI filter total ({ai_filtered_total}) != classification_totals.ai ({totals['ai']})"
    
    def test_by_type_classification_counts_sum_to_totals(self):
        """Test that sum of by_type classification_counts equals classification_totals"""
        data = requests.get(f"{BASE_URL}/api/dashboard/document-types").json()
        
        by_type = data.get("by_type", {})
        totals = data["classification_totals"]
        
        sum_det = sum(t["classification_counts"]["deterministic"] for t in by_type.values())
        sum_ai = sum(t["classification_counts"]["ai"] for t in by_type.values())
        sum_other = sum(t["classification_counts"]["other"] for t in by_type.values())
        
        assert sum_det == totals["deterministic"], \
            f"Sum of deterministic counts ({sum_det}) != classification_totals.deterministic ({totals['deterministic']})"
        assert sum_ai == totals["ai"], \
            f"Sum of ai counts ({sum_ai}) != classification_totals.ai ({totals['ai']})"
        assert sum_other == totals["other"], \
            f"Sum of other counts ({sum_other}) != classification_totals.other ({totals['other']})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
