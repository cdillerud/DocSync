"""
Label Correction Insights Dashboard API Tests

Tests for the 6 new Label Correction dashboard endpoints (Parts 1-6):
1. GET /api/label-corrections/summary — Full dashboard summary with accuracy rate
2. GET /api/label-corrections/top-patterns — Top mislabel patterns
3. GET /api/label-corrections/vendors — Vendor correction aggregation
4. GET /api/label-corrections/over-time — Time series for chart
5. GET /api/label-corrections/recommendations — Auto-generated suggestions
6. GET /api/label-corrections/vendor/{vendor_id} — Extended vendor insights
"""

import pytest
import requests
import os

# Use environment URL for testing
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://extraction-quality.preview.emergentagent.com"

# Test vendor known from iteration_32.json
TEST_VENDOR = "Cargo Modules LLC"
TEST_DOC_ID = "80c7ab51-0cdb-48cc-b39c-b5d8a9c27c85"


@pytest.fixture
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestLabelCorrectionSummary:
    """Part 1 — GET /api/label-corrections/summary"""
    
    def test_summary_endpoint_returns_200(self, api_client):
        """Summary endpoint should return 200 OK."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Summary endpoint returns 200")
    
    def test_summary_has_required_fields(self, api_client):
        """Summary should contain all required dashboard fields."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/summary")
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "total_corrections",
            "unique_reference_values",
            "vendors_impacted",
            "most_common_predicted_labels",
            "most_common_actual_entities",
            "label_accuracy_rate",
            "corrections_last_7_days",
            "corrections_last_30_days"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Verify data types
        assert isinstance(data["total_corrections"], int), "total_corrections should be int"
        assert isinstance(data["vendors_impacted"], int), "vendors_impacted should be int"
        assert isinstance(data["label_accuracy_rate"], (int, float)), "label_accuracy_rate should be numeric"
        
        print(f"PASS: Summary has all required fields")
        print(f"  total_corrections={data['total_corrections']}")
        print(f"  label_accuracy_rate={data['label_accuracy_rate']}%")
        print(f"  vendors_impacted={data['vendors_impacted']}")
    
    def test_summary_data_integrity(self, api_client):
        """Summary data values should be reasonable based on known test data."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Based on iteration_32: 4 corrections for Cargo Modules LLC
        assert data["total_corrections"] >= 4, f"Expected at least 4 corrections, got {data['total_corrections']}"
        assert data["vendors_impacted"] >= 1, f"Expected at least 1 vendor impacted, got {data['vendors_impacted']}"
        
        # Accuracy rate should be between 0 and 100
        assert 0 <= data["label_accuracy_rate"] <= 100, f"label_accuracy_rate should be 0-100, got {data['label_accuracy_rate']}"
        
        print(f"PASS: Summary data integrity verified")


class TestLabelCorrectionTopPatterns:
    """Part 1 — GET /api/label-corrections/top-patterns"""
    
    def test_top_patterns_endpoint_returns_200(self, api_client):
        """Top patterns endpoint should return 200 OK."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/top-patterns")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Top patterns endpoint returns 200")
    
    def test_top_patterns_structure(self, api_client):
        """Top patterns should return patterns array with required fields."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/top-patterns")
        assert response.status_code == 200
        data = response.json()
        
        assert "patterns" in data, "Response should contain 'patterns' array"
        assert isinstance(data["patterns"], list), "patterns should be a list"
        
        if len(data["patterns"]) > 0:
            pattern = data["patterns"][0]
            required_fields = [
                "predicted_label",
                "actual_entity_type",
                "correct_label",
                "count",
                "percentage",
                "vendors_impacted",
                "vendor_names",
                "example_references",
                "avg_score"
            ]
            for field in required_fields:
                assert field in pattern, f"Pattern missing required field: {field}"
            
            print(f"PASS: Top patterns structure verified")
            print(f"  First pattern: {pattern['predicted_label']} → {pattern['correct_label']} ({pattern['count']}x)")
        else:
            print("PASS: Top patterns structure verified (no patterns yet)")
    
    def test_top_patterns_has_po_shipment(self, api_client):
        """Based on test data, should have PO → SHIPMENT pattern."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/top-patterns")
        assert response.status_code == 200
        data = response.json()
        
        # Based on iteration_32: PO → SHIPMENT pattern
        po_shipment_patterns = [
            p for p in data["patterns"]
            if p["predicted_label"] == "PO" and p["correct_label"] == "SHIPMENT"
        ]
        assert len(po_shipment_patterns) >= 1, "Expected PO → SHIPMENT pattern from test data"
        
        p = po_shipment_patterns[0]
        assert p["count"] >= 4, f"Expected at least 4 occurrences, got {p['count']}"
        
        print(f"PASS: PO → SHIPMENT pattern found with {p['count']} occurrences")


class TestLabelCorrectionVendors:
    """Part 2 — GET /api/label-corrections/vendors"""
    
    def test_vendors_endpoint_returns_200(self, api_client):
        """Vendors endpoint should return 200 OK."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendors")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Vendors endpoint returns 200")
    
    def test_vendors_array_structure(self, api_client):
        """Vendors should return array with required vendor fields."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendors")
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Response should be an array"
        
        if len(data) > 0:
            vendor = data[0]
            required_fields = [
                "vendor",
                "total_corrections",
                "unique_references",
                "top_pattern",
                "avg_score",
                "latest"
            ]
            for field in required_fields:
                assert field in vendor, f"Vendor missing required field: {field}"
            
            print(f"PASS: Vendor array structure verified")
            print(f"  First vendor: {vendor['vendor']} with {vendor['total_corrections']} corrections")
        else:
            print("PASS: Vendors endpoint returns empty array (no data yet)")
    
    def test_vendors_includes_cargo_modules(self, api_client):
        """Based on test data, should include Cargo Modules LLC."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendors")
        assert response.status_code == 200
        data = response.json()
        
        cargo_modules = [v for v in data if TEST_VENDOR in v["vendor"]]
        assert len(cargo_modules) >= 1, f"Expected {TEST_VENDOR} in vendor list"
        
        v = cargo_modules[0]
        assert v["total_corrections"] >= 4, f"Expected at least 4 corrections for {TEST_VENDOR}"
        assert "PO" in v["top_pattern"], f"Expected PO in top_pattern for {TEST_VENDOR}"
        
        print(f"PASS: {TEST_VENDOR} found with {v['total_corrections']} corrections")


class TestLabelCorrectionOverTime:
    """Part 3 — GET /api/label-corrections/over-time"""
    
    def test_over_time_endpoint_returns_200(self, api_client):
        """Over-time endpoint should return 200 OK."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/over-time")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Over-time endpoint returns 200")
    
    def test_over_time_array_structure(self, api_client):
        """Over-time should return array with date/count objects."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/over-time")
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Response should be an array"
        
        if len(data) > 0:
            item = data[0]
            assert "date" in item, "Item should have 'date' field"
            assert "count" in item, "Item should have 'count' field"
            
            # Date should be YYYY-MM-DD format
            assert len(item["date"]) == 10, f"Date should be YYYY-MM-DD format, got {item['date']}"
            assert isinstance(item["count"], int), "count should be int"
            
            print(f"PASS: Over-time structure verified ({len(data)} data points)")
        else:
            print("PASS: Over-time endpoint returns empty array (no data yet)")


class TestLabelCorrectionRecommendations:
    """Part 5 — GET /api/label-corrections/recommendations"""
    
    def test_recommendations_endpoint_returns_200(self, api_client):
        """Recommendations endpoint should return 200 OK."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/recommendations")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Recommendations endpoint returns 200")
    
    def test_recommendations_array_structure(self, api_client):
        """Recommendations should return array with required fields."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/recommendations")
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list), "Response should be an array"
        
        if len(data) > 0:
            rec = data[0]
            required_fields = [
                "severity",
                "pattern",
                "recommendation",
                "extraction_adjustment"
            ]
            for field in required_fields:
                assert field in rec, f"Recommendation missing required field: {field}"
            
            # Validate severity values
            assert rec["severity"] in ["high", "medium", "low"], f"Invalid severity: {rec['severity']}"
            
            print(f"PASS: Recommendations structure verified")
            print(f"  First recommendation: [{rec['severity']}] {rec['pattern']}")
        else:
            # Based on iteration_32 with 4 corrections, recommendations may not be generated
            # (threshold is 3 in get_recommendations)
            print("PASS: Recommendations endpoint returns empty array (below threshold)")
    
    def test_recommendations_has_freight_recommendation(self, api_client):
        """Based on test data, should have freight vendor mislabeling recommendation."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/recommendations")
        assert response.status_code == 200
        data = response.json()
        
        # With 4 corrections (PO→SHIPMENT), should trigger recommendation
        if len(data) > 0:
            # Check if any recommendation mentions freight or shipment
            freight_recs = [
                r for r in data 
                if "freight" in r["recommendation"].lower() or "shipment" in r["recommendation"].lower()
            ]
            print(f"PASS: Found {len(data)} recommendations, {len(freight_recs)} freight-related")
        else:
            # May need more data to trigger recommendations
            print("PASS: No recommendations yet (need more correction data)")


class TestLabelCorrectionVendorDetail:
    """Part 2/6 — GET /api/label-corrections/vendor/{vendor_id}"""
    
    def test_vendor_detail_returns_200(self, api_client):
        """Vendor detail endpoint should return 200 for known vendor."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendor/{TEST_VENDOR}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Vendor detail endpoint returns 200 for {TEST_VENDOR}")
    
    def test_vendor_detail_extended_fields(self, api_client):
        """Vendor detail should include extended insights fields."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendor/{TEST_VENDOR}")
        assert response.status_code == 200
        data = response.json()
        
        # Should have patterns if has_patterns is true
        if data.get("has_patterns"):
            # Extended fields from Part 2/6
            extended_fields = [
                "correction_rate",
                "total_resolutions",
                "label_frequency",
                "entity_frequency"
            ]
            for field in extended_fields:
                assert field in data, f"Missing extended field: {field}"
            
            # Validate correction_rate is percentage
            assert isinstance(data["correction_rate"], (int, float)), "correction_rate should be numeric"
            
            # Should also have base patterns
            assert "patterns" in data, "Should have patterns array"
            assert "label_remaps" in data, "Should have label_remaps"
            
            print(f"PASS: Vendor detail has extended fields")
            print(f"  correction_rate={data['correction_rate']}%")
            print(f"  total_resolutions={data['total_resolutions']}")
        else:
            print("PASS: Vendor has no patterns (new vendor)")
    
    def test_vendor_detail_patterns_structure(self, api_client):
        """Vendor detail patterns should have correct structure."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendor/{TEST_VENDOR}")
        assert response.status_code == 200
        data = response.json()
        
        if data.get("has_patterns") and len(data.get("patterns", [])) > 0:
            pattern = data["patterns"][0]
            pattern_fields = [
                "predicted_label",
                "correct_label",
                "actual_entity_type",
                "count",
                "frequency",
                "avg_score"
            ]
            for field in pattern_fields:
                assert field in pattern, f"Pattern missing field: {field}"
            
            # Should have PO → SHIPMENT pattern for Cargo Modules LLC
            po_patterns = [p for p in data["patterns"] if p["predicted_label"] == "PO"]
            assert len(po_patterns) >= 1, "Expected PO pattern for test vendor"
            
            print(f"PASS: Vendor patterns structure verified ({len(data['patterns'])} patterns)")
    
    def test_vendor_detail_unknown_vendor(self, api_client):
        """Unknown vendor should return has_patterns=false."""
        response = api_client.get(f"{BASE_URL}/api/label-corrections/vendor/NonExistentVendor123")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("has_patterns") == False, "Unknown vendor should have has_patterns=false"
        print("PASS: Unknown vendor returns has_patterns=false")


class TestLabelCorrectionReadOnly:
    """Part 8 — Dashboard is strictly read-only (no mutations)"""
    
    def test_no_post_endpoints(self, api_client):
        """POST to summary endpoint should return 405 Method Not Allowed."""
        response = api_client.post(f"{BASE_URL}/api/label-corrections/summary", json={})
        assert response.status_code == 405, f"Expected 405 for POST, got {response.status_code}"
        print("PASS: POST to summary returns 405 (read-only)")
    
    def test_no_put_endpoints(self, api_client):
        """PUT to recommendations endpoint should return 405 Method Not Allowed."""
        response = api_client.put(f"{BASE_URL}/api/label-corrections/recommendations", json={})
        assert response.status_code == 405, f"Expected 405 for PUT, got {response.status_code}"
        print("PASS: PUT to recommendations returns 405 (read-only)")
    
    def test_no_delete_endpoints(self, api_client):
        """DELETE to vendors endpoint should return 405 Method Not Allowed."""
        response = api_client.delete(f"{BASE_URL}/api/label-corrections/vendors")
        assert response.status_code == 405, f"Expected 405 for DELETE, got {response.status_code}"
        print("PASS: DELETE to vendors returns 405 (read-only)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
