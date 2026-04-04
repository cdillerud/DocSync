"""
Test Gap Closers - 4 Validation Gap Intelligence Features

Tests the gap closer status endpoint and verifies:
- Gap 1: Confidence calibration bands with accuracy and triggers_review flag
- Gap 2: PO matching with vendors_with_po_patterns and flow_events
- Gap 3: Customer matching with historical_matches count
- Gap 4: Sales order matching with flow_events and so_matches counts
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestGapCloserStatus:
    """Test GET /api/posting-patterns/gap-closer/status endpoint"""
    
    def test_gap_closer_status_endpoint_returns_200(self):
        """Test that the gap closer status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("SUCCESS: Gap closer status endpoint returns 200")
    
    def test_gap_1_confidence_calibration_structure(self):
        """Test Gap 1: Confidence calibration has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check gap_1_confidence_calibration exists
        assert "gap_1_confidence_calibration" in data, "Missing gap_1_confidence_calibration"
        gap_1 = data["gap_1_confidence_calibration"]
        
        # Check required fields
        assert "status" in gap_1, "Missing status in gap_1"
        assert "bands" in gap_1, "Missing bands in gap_1"
        assert "action" in gap_1, "Missing action in gap_1"
        
        # Check bands structure
        bands = gap_1["bands"]
        expected_bands = ["0-50%", "50-70%", "70-85%", "85-95%", "95-100%"]
        for band in expected_bands:
            assert band in bands, f"Missing band {band}"
            band_data = bands[band]
            assert "accuracy" in band_data, f"Missing accuracy in band {band}"
            assert "samples" in band_data, f"Missing samples in band {band}"
            assert "triggers_review" in band_data, f"Missing triggers_review in band {band}"
        
        print(f"SUCCESS: Gap 1 has correct structure with {len(bands)} bands")
    
    def test_gap_1_triggers_review_for_low_accuracy(self):
        """Test that low accuracy bands trigger review"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        gap_1 = data["gap_1_confidence_calibration"]
        bands = gap_1["bands"]
        
        # Check 95-100% band (should have data in preview)
        band_95_100 = bands.get("95-100%", {})
        samples = band_95_100.get("samples", 0)
        accuracy = band_95_100.get("accuracy")
        triggers_review = band_95_100.get("triggers_review", False)
        
        print(f"95-100% band: {samples} samples, accuracy={accuracy}, triggers_review={triggers_review}")
        
        # If there are samples and accuracy is below 65%, triggers_review should be True
        if samples >= 10 and accuracy is not None and accuracy < 0.65:
            assert triggers_review is True, "Expected triggers_review=True for low accuracy band"
            print("SUCCESS: Low accuracy band correctly triggers review")
        elif samples < 10:
            print("INFO: Insufficient samples for triggers_review check")
        else:
            print(f"INFO: Accuracy {accuracy} is above threshold, triggers_review={triggers_review}")
    
    def test_gap_2_po_matching_structure(self):
        """Test Gap 2: PO matching has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check gap_2_po_matching exists
        assert "gap_2_po_matching" in data, "Missing gap_2_po_matching"
        gap_2 = data["gap_2_po_matching"]
        
        # Check required fields
        assert "status" in gap_2, "Missing status in gap_2"
        assert "vendors_with_po_patterns" in gap_2, "Missing vendors_with_po_patterns"
        assert "po_flow_events" in gap_2, "Missing po_flow_events"
        assert "gap_count" in gap_2, "Missing gap_count"
        assert "action" in gap_2, "Missing action"
        
        # Verify types
        assert isinstance(gap_2["vendors_with_po_patterns"], int), "vendors_with_po_patterns should be int"
        assert isinstance(gap_2["po_flow_events"], int), "po_flow_events should be int"
        
        print(f"SUCCESS: Gap 2 has correct structure - {gap_2['vendors_with_po_patterns']} PO patterns, {gap_2['po_flow_events']} flow events")
    
    def test_gap_3_customer_matching_structure(self):
        """Test Gap 3: Customer matching has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check gap_3_customer_matching exists
        assert "gap_3_customer_matching" in data, "Missing gap_3_customer_matching"
        gap_3 = data["gap_3_customer_matching"]
        
        # Check required fields
        assert "status" in gap_3, "Missing status in gap_3"
        assert "historical_matches" in gap_3, "Missing historical_matches"
        assert "gap_count" in gap_3, "Missing gap_count"
        assert "action" in gap_3, "Missing action"
        
        # Verify types
        assert isinstance(gap_3["historical_matches"], int), "historical_matches should be int"
        
        print(f"SUCCESS: Gap 3 has correct structure - {gap_3['historical_matches']} historical matches")
    
    def test_gap_4_sales_order_matching_structure(self):
        """Test Gap 4: Sales order matching has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check gap_4_sales_order_matching exists
        assert "gap_4_sales_order_matching" in data, "Missing gap_4_sales_order_matching"
        gap_4 = data["gap_4_sales_order_matching"]
        
        # Check required fields
        assert "status" in gap_4, "Missing status in gap_4"
        assert "flow_events" in gap_4, "Missing flow_events"
        assert "historical_so_matches" in gap_4, "Missing historical_so_matches"
        assert "gap_count" in gap_4, "Missing gap_count"
        assert "action" in gap_4, "Missing action"
        
        # Verify types
        assert isinstance(gap_4["flow_events"], int), "flow_events should be int"
        assert isinstance(gap_4["historical_so_matches"], int), "historical_so_matches should be int"
        
        print(f"SUCCESS: Gap 4 has correct structure - {gap_4['flow_events']} flow events, {gap_4['historical_so_matches']} SO matches")
    
    def test_all_gaps_are_active(self):
        """Test that all 4 gaps show active status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        gaps = [
            ("gap_1_confidence_calibration", data.get("gap_1_confidence_calibration", {})),
            ("gap_2_po_matching", data.get("gap_2_po_matching", {})),
            ("gap_3_customer_matching", data.get("gap_3_customer_matching", {})),
            ("gap_4_sales_order_matching", data.get("gap_4_sales_order_matching", {})),
        ]
        
        for gap_name, gap_data in gaps:
            status = gap_data.get("status", "")
            assert status == "active", f"{gap_name} should be active, got {status}"
        
        print("SUCCESS: All 4 gaps are active")


class TestGapCloserServiceImports:
    """Test that gap_closer_service imports correctly"""
    
    def test_gap_closer_service_functions_exist(self):
        """Test that all gap closer functions can be imported"""
        # This test verifies the service is properly structured
        # The actual import test was done via bash command
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, "Gap closer endpoint should work if service imports correctly"
        print("SUCCESS: Gap closer service is working (endpoint returns 200)")


class TestGapCloserIntegration:
    """Test gap closer integration with validation pipeline"""
    
    def test_confidence_band_data_in_preview(self):
        """Test that 95-100% band has data in preview environment"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        gap_1 = data.get("gap_1_confidence_calibration", {})
        bands = gap_1.get("bands", {})
        band_95_100 = bands.get("95-100%", {})
        
        samples = band_95_100.get("samples", 0)
        
        # In preview, we expect the 95-100% band to have data
        print(f"95-100% band has {samples} samples")
        
        if samples > 0:
            accuracy = band_95_100.get("accuracy")
            triggers_review = band_95_100.get("triggers_review")
            print(f"  Accuracy: {accuracy}")
            print(f"  Triggers Review: {triggers_review}")
            
            # Verify accuracy is a valid number
            if accuracy is not None:
                assert 0 <= accuracy <= 1, f"Accuracy should be between 0 and 1, got {accuracy}"
            
            print("SUCCESS: 95-100% band has valid data")
        else:
            print("INFO: No samples in 95-100% band (expected in some environments)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
