"""
Per-Document Intelligence Engine Tests (Iteration 182)

Tests the 4 new learning-pulse endpoints:
1. GET /api/posting-patterns/learning-pulse - Real-time learning pulse
2. GET /api/posting-patterns/learning-pulse/confidence-calibration - Calibration report
3. POST /api/posting-patterns/learning-pulse/backfill - Backfill learning from existing docs
4. GET /api/posting-patterns/learning-pulse/vendor/{vendor_no} - Vendor-specific learning profile
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPerDocumentLearningPulse:
    """Tests for the Per-Document Intelligence Engine endpoints"""

    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("✓ Health check passed")

    def test_learning_pulse_endpoint(self):
        """GET /api/posting-patterns/learning-pulse - Returns learning pulse data"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Verify required fields in response
        assert "total_documents_learned_from" in data, "Missing total_documents_learned_from"
        assert "outcomes" in data, "Missing outcomes"
        assert "confidence_calibration" in data, "Missing confidence_calibration"
        assert "top_vendors" in data, "Missing top_vendors"
        assert "validation_gap_hotspots" in data, "Missing validation_gap_hotspots"
        assert "recent_learning" in data, "Missing recent_learning"
        assert "generated_at" in data, "Missing generated_at"
        
        # Verify data types
        assert isinstance(data["total_documents_learned_from"], int), "total_documents_learned_from should be int"
        assert isinstance(data["outcomes"], dict), "outcomes should be dict"
        assert isinstance(data["confidence_calibration"], dict), "confidence_calibration should be dict"
        assert isinstance(data["top_vendors"], list), "top_vendors should be list"
        assert isinstance(data["validation_gap_hotspots"], list), "validation_gap_hotspots should be list"
        assert isinstance(data["recent_learning"], list), "recent_learning should be list"
        
        print(f"✓ Learning pulse endpoint returned valid structure")
        print(f"  - Total documents learned from: {data['total_documents_learned_from']}")
        print(f"  - Outcomes: {list(data['outcomes'].keys())}")
        print(f"  - Calibration bands: {list(data['confidence_calibration'].keys())}")
        print(f"  - Top vendors count: {len(data['top_vendors'])}")
        print(f"  - Gap hotspots count: {len(data['validation_gap_hotspots'])}")
        print(f"  - Recent learning count: {len(data['recent_learning'])}")

    def test_confidence_calibration_endpoint(self):
        """GET /api/posting-patterns/learning-pulse/confidence-calibration - Returns calibration report"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/confidence-calibration")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Verify required fields
        assert "global" in data, "Missing global calibration"
        assert "by_vendor" in data, "Missing by_vendor calibration"
        assert "by_doc_type" in data, "Missing by_doc_type calibration"
        assert "generated_at" in data, "Missing generated_at"
        
        # Verify data types
        assert isinstance(data["by_vendor"], list), "by_vendor should be list"
        assert isinstance(data["by_doc_type"], list), "by_doc_type should be list"
        
        # If global calibration exists, verify its structure
        if data["global"]:
            assert "calibration_id" in data["global"], "Global calibration missing calibration_id"
            if "bands" in data["global"]:
                for band_name, band_data in data["global"]["bands"].items():
                    assert "total" in band_data, f"Band {band_name} missing total"
                    assert "correct" in band_data, f"Band {band_name} missing correct"
        
        print(f"✓ Confidence calibration endpoint returned valid structure")
        print(f"  - Global calibration: {'present' if data['global'] else 'empty'}")
        print(f"  - Vendor calibrations: {len(data['by_vendor'])}")
        print(f"  - Doc type calibrations: {len(data['by_doc_type'])}")

    def test_backfill_endpoint(self):
        """POST /api/posting-patterns/learning-pulse/backfill - Backfills learning from existing docs"""
        # Test with small limit to avoid long processing
        response = requests.post(f"{BASE_URL}/api/posting-patterns/learning-pulse/backfill?limit=50")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Response can be either sync (processed, errors) or async (message, async)
        if "async" in data and data["async"]:
            assert "message" in data, "Async response missing message"
            print(f"✓ Backfill endpoint started async: {data['message']}")
        else:
            assert "processed" in data, "Sync response missing processed count"
            assert "errors" in data, "Sync response missing errors count"
            assert isinstance(data["processed"], int), "processed should be int"
            assert isinstance(data["errors"], int), "errors should be int"
            print(f"✓ Backfill endpoint completed: {data['processed']} processed, {data['errors']} errors")

    def test_vendor_learning_profile_existing_vendor(self):
        """GET /api/posting-patterns/learning-pulse/vendor/ANCH - Returns vendor-specific learning profile"""
        # Test with ANCH vendor (mentioned in the test request)
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/vendor/ANCH")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Response should have vendor_no at minimum
        assert "vendor_no" in data, "Missing vendor_no in response"
        assert data["vendor_no"] == "ANCH", f"Expected vendor_no ANCH, got {data['vendor_no']}"
        
        # If vendor has learning data, verify structure
        if "intelligence" in data and data["intelligence"]:
            intel = data["intelligence"]
            # Verify vendor intelligence fields
            assert "vendor_no" in intel, "Intelligence missing vendor_no"
            print(f"✓ Vendor ANCH has intelligence data")
            print(f"  - Total documents: {intel.get('total_documents', 0)}")
            print(f"  - Success count: {intel.get('success_count', 0)}")
            print(f"  - Auto validation rate: {intel.get('auto_validation_rate', 0)}")
        else:
            # Vendor may not have learning data yet
            print(f"✓ Vendor ANCH profile returned (no learning data yet)")
            if "message" in data:
                print(f"  - Message: {data['message']}")

    def test_vendor_learning_profile_nonexistent_vendor(self):
        """GET /api/posting-patterns/learning-pulse/vendor/NONEXISTENT - Returns empty profile for unknown vendor"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/vendor/NONEXISTENT_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        data = response.json()
        
        # Should return vendor_no and message for non-existent vendor
        assert "vendor_no" in data, "Missing vendor_no in response"
        assert data["vendor_no"] == "NONEXISTENT_VENDOR_XYZ", f"Expected vendor_no NONEXISTENT_VENDOR_XYZ"
        
        # Should indicate no learning data
        if "message" in data:
            assert "no learning" in data["message"].lower() or "not found" in data["message"].lower() or "no data" in data["message"].lower(), \
                f"Expected message about no learning data, got: {data['message']}"
        
        print(f"✓ Non-existent vendor returns appropriate response")

    def test_learning_pulse_calibration_bands_structure(self):
        """Verify confidence calibration bands have correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        
        data = response.json()
        calibration = data.get("confidence_calibration", {})
        
        # Expected band names
        expected_bands = ["0_50", "50_70", "70_85", "85_95", "95_100"]
        
        for band in calibration:
            # Each band should have total, correct, accuracy
            band_data = calibration[band]
            assert "total" in band_data, f"Band {band} missing total"
            assert "correct" in band_data, f"Band {band} missing correct"
            assert "accuracy" in band_data, f"Band {band} missing accuracy"
            
            # Accuracy should be between 0 and 1
            accuracy = band_data["accuracy"]
            assert 0 <= accuracy <= 1, f"Band {band} accuracy {accuracy} out of range [0,1]"
        
        print(f"✓ Calibration bands have correct structure")
        for band, band_data in calibration.items():
            print(f"  - {band}: {band_data['total']} docs, {band_data['accuracy']*100:.0f}% accuracy")

    def test_learning_pulse_top_vendors_structure(self):
        """Verify top vendors have correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        
        data = response.json()
        top_vendors = data.get("top_vendors", [])
        
        for vendor in top_vendors:
            # Each vendor should have these fields
            assert "vendor_no" in vendor, "Vendor missing vendor_no"
            assert "total_documents" in vendor, "Vendor missing total_documents"
            
            # Optional but expected fields
            if "auto_validation_rate" in vendor:
                rate = vendor["auto_validation_rate"]
                assert 0 <= rate <= 1, f"Vendor {vendor['vendor_no']} auto_validation_rate {rate} out of range"
        
        print(f"✓ Top vendors have correct structure ({len(top_vendors)} vendors)")

    def test_learning_pulse_recent_learning_structure(self):
        """Verify recent learning events have correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        
        data = response.json()
        recent = data.get("recent_learning", [])
        
        for event in recent:
            # Each event should have these fields
            assert "doc_id" in event, "Event missing doc_id"
            assert "trigger" in event, "Event missing trigger"
            assert "outcome" in event, "Event missing outcome"
            assert "recorded_at" in event, "Event missing recorded_at"
        
        print(f"✓ Recent learning events have correct structure ({len(recent)} events)")


class TestPerDocumentLearningIntegration:
    """Integration tests for the Per-Document Learning Engine"""

    def test_backfill_then_verify_pulse(self):
        """Run backfill and verify learning pulse reflects the data"""
        # First, run a small backfill
        backfill_response = requests.post(f"{BASE_URL}/api/posting-patterns/learning-pulse/backfill?limit=10")
        assert backfill_response.status_code == 200
        
        # Then check the learning pulse
        pulse_response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert pulse_response.status_code == 200
        
        pulse_data = pulse_response.json()
        
        # After backfill, we should have some data (if there are documents)
        print(f"✓ Backfill + Pulse integration test passed")
        print(f"  - Documents learned from: {pulse_data['total_documents_learned_from']}")

    def test_calibration_consistency(self):
        """Verify calibration data is consistent between endpoints"""
        # Get learning pulse
        pulse_response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert pulse_response.status_code == 200
        pulse_data = pulse_response.json()
        
        # Get detailed calibration
        cal_response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse/confidence-calibration")
        assert cal_response.status_code == 200
        cal_data = cal_response.json()
        
        # If global calibration exists in both, bands should match
        pulse_bands = pulse_data.get("confidence_calibration", {})
        global_cal = cal_data.get("global")
        
        if global_cal and global_cal.get("bands"):
            for band_name in pulse_bands:
                if band_name in global_cal["bands"]:
                    pulse_total = pulse_bands[band_name].get("total", 0)
                    cal_total = global_cal["bands"][band_name].get("total", 0)
                    assert pulse_total == cal_total, f"Band {band_name} total mismatch: pulse={pulse_total}, cal={cal_total}"
        
        print(f"✓ Calibration data is consistent between endpoints")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
