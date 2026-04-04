"""
Test Continuous Learning Engines (Iteration 181)

Tests the 4 NEW continuous learning engines:
A. Auto-learn from BC-posted invoices (detect-posted)
B. Cross-vendor pattern learning (cross-vendor)
C. Confidence auto-promotion (auto-promote)
D. Extraction learning from field corrections (extraction-profile)

Plus the master orchestrator (run-all)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestContinuousLearningEngines:
    """Test the 4 continuous learning engine endpoints"""

    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print("PASS: Health check returns 200")

    def test_run_all_learning_engines(self):
        """
        POST /api/posting-patterns/learning/run-all
        Should return valid JSON with posted_draft_detection, cross_vendor_learning, 
        confidence_auto_promotion, timestamp
        """
        response = requests.post(f"{BASE_URL}/api/posting-patterns/learning/run-all")
        assert response.status_code == 200, f"run-all failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required top-level keys
        assert "posted_draft_detection" in data, "Missing posted_draft_detection key"
        assert "cross_vendor_learning" in data, "Missing cross_vendor_learning key"
        assert "confidence_auto_promotion" in data, "Missing confidence_auto_promotion key"
        assert "timestamp" in data, "Missing timestamp key"
        
        # Verify timestamp is a valid ISO format string
        assert isinstance(data["timestamp"], str), "timestamp should be a string"
        assert "T" in data["timestamp"], "timestamp should be ISO format"
        
        print(f"PASS: run-all returns valid structure with timestamp={data['timestamp']}")
        print(f"  posted_draft_detection: {data['posted_draft_detection']}")
        print(f"  cross_vendor_learning: {data['cross_vendor_learning']}")
        print(f"  confidence_auto_promotion: {data['confidence_auto_promotion']}")

    def test_detect_posted_drafts(self):
        """
        POST /api/posting-patterns/learning/detect-posted
        Should return valid JSON with checked, posted_found, changes_learned, errors
        """
        response = requests.post(f"{BASE_URL}/api/posting-patterns/learning/detect-posted")
        assert response.status_code == 200, f"detect-posted failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required keys
        assert "checked" in data, "Missing checked key"
        assert "posted_found" in data, "Missing posted_found key"
        assert "changes_learned" in data, "Missing changes_learned key"
        assert "errors" in data, "Missing errors key"
        
        # Verify types (all should be integers)
        assert isinstance(data["checked"], int), "checked should be int"
        assert isinstance(data["posted_found"], int), "posted_found should be int"
        assert isinstance(data["changes_learned"], int), "changes_learned should be int"
        assert isinstance(data["errors"], int), "errors should be int"
        
        # Values should be >= 0
        assert data["checked"] >= 0, "checked should be >= 0"
        assert data["posted_found"] >= 0, "posted_found should be >= 0"
        assert data["changes_learned"] >= 0, "changes_learned should be >= 0"
        assert data["errors"] >= 0, "errors should be >= 0"
        
        print(f"PASS: detect-posted returns valid structure")
        print(f"  checked={data['checked']}, posted_found={data['posted_found']}, changes_learned={data['changes_learned']}, errors={data['errors']}")

    def test_cross_vendor_learning(self):
        """
        POST /api/posting-patterns/learning/cross-vendor
        Should return valid JSON with corrections_checked, propagated_to_vendors, propagations_applied
        """
        response = requests.post(f"{BASE_URL}/api/posting-patterns/learning/cross-vendor")
        assert response.status_code == 200, f"cross-vendor failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required keys
        assert "corrections_checked" in data, "Missing corrections_checked key"
        assert "propagated_to_vendors" in data, "Missing propagated_to_vendors key"
        assert "propagations_applied" in data, "Missing propagations_applied key"
        
        # Verify types (all should be integers)
        assert isinstance(data["corrections_checked"], int), "corrections_checked should be int"
        assert isinstance(data["propagated_to_vendors"], int), "propagated_to_vendors should be int"
        assert isinstance(data["propagations_applied"], int), "propagations_applied should be int"
        
        # Values should be >= 0
        assert data["corrections_checked"] >= 0, "corrections_checked should be >= 0"
        assert data["propagated_to_vendors"] >= 0, "propagated_to_vendors should be >= 0"
        assert data["propagations_applied"] >= 0, "propagations_applied should be >= 0"
        
        print(f"PASS: cross-vendor returns valid structure")
        print(f"  corrections_checked={data['corrections_checked']}, propagated_to_vendors={data['propagated_to_vendors']}, propagations_applied={data['propagations_applied']}")

    def test_auto_promote_confidence(self):
        """
        POST /api/posting-patterns/learning/auto-promote
        Should return valid JSON with promoted, demoted, unchanged
        """
        response = requests.post(f"{BASE_URL}/api/posting-patterns/learning/auto-promote")
        assert response.status_code == 200, f"auto-promote failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify required keys
        assert "promoted" in data, "Missing promoted key"
        assert "demoted" in data, "Missing demoted key"
        assert "unchanged" in data, "Missing unchanged key"
        
        # promoted and demoted should be lists
        assert isinstance(data["promoted"], list), "promoted should be a list"
        assert isinstance(data["demoted"], list), "demoted should be a list"
        
        # unchanged should be an integer
        assert isinstance(data["unchanged"], int), "unchanged should be int"
        assert data["unchanged"] >= 0, "unchanged should be >= 0"
        
        # If there are promoted items, verify structure
        if data["promoted"]:
            for item in data["promoted"]:
                assert "vendor" in item, "promoted item missing vendor"
                assert "from" in item, "promoted item missing from"
                assert "to" in item, "promoted item missing to"
        
        # If there are demoted items, verify structure
        if data["demoted"]:
            for item in data["demoted"]:
                assert "vendor" in item, "demoted item missing vendor"
                assert "from" in item, "demoted item missing from"
                assert "to" in item, "demoted item missing to"
        
        print(f"PASS: auto-promote returns valid structure")
        print(f"  promoted={len(data['promoted'])}, demoted={len(data['demoted'])}, unchanged={data['unchanged']}")

    def test_extraction_profile_existing_vendor(self):
        """
        GET /api/posting-patterns/learning/extraction-profile/TUMALOC
        Should return a valid profile. Note: TUMALOC has existing vendor intelligence data
        stored in vendor_extraction_profiles collection with different structure.
        The endpoint returns whatever is in the collection.
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning/extraction-profile/TUMALOC")
        assert response.status_code == 200, f"extraction-profile/TUMALOC failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Should have vendor_no
        assert "vendor_no" in data, "Missing vendor_no key"
        assert data["vendor_no"] == "TUMALOC", f"vendor_no should be TUMALOC, got {data['vendor_no']}"
        
        # TUMALOC has existing vendor intelligence data in this collection
        # It may have total_corrections OR source_correction_count depending on data source
        has_corrections_field = "total_corrections" in data or "source_correction_count" in data
        assert has_corrections_field, "Missing corrections count field (total_corrections or source_correction_count)"
        
        # Get the corrections count from whichever field exists
        corrections_count = data.get("total_corrections", data.get("source_correction_count", 0))
        
        print(f"PASS: extraction-profile/TUMALOC returns valid profile")
        print(f"  vendor_no={data['vendor_no']}, corrections_count={corrections_count}")
        print(f"  Profile keys: {list(data.keys())}")

    def test_extraction_profile_nonexistent_vendor(self):
        """
        GET /api/posting-patterns/learning/extraction-profile/NONEXIST
        Should return empty profile with vendor_no, total_corrections: 0, field_corrections: {}
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning/extraction-profile/NONEXIST")
        assert response.status_code == 200, f"extraction-profile/NONEXIST failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Should have vendor_no
        assert "vendor_no" in data, "Missing vendor_no key"
        assert data["vendor_no"] == "NONEXIST", f"vendor_no should be NONEXIST, got {data['vendor_no']}"
        
        # Should have total_corrections = 0
        assert "total_corrections" in data, "Missing total_corrections key"
        assert data["total_corrections"] == 0, f"total_corrections should be 0 for nonexistent vendor, got {data['total_corrections']}"
        
        # Should have field_corrections = {}
        assert "field_corrections" in data, "Missing field_corrections key"
        assert data["field_corrections"] == {}, f"field_corrections should be empty dict for nonexistent vendor, got {data['field_corrections']}"
        
        print(f"PASS: extraction-profile/NONEXIST returns empty profile")
        print(f"  vendor_no={data['vendor_no']}, total_corrections={data['total_corrections']}, field_corrections={data['field_corrections']}")

    def test_learning_dashboard_still_works(self):
        """
        GET /api/posting-patterns/learning-dashboard
        Verify the learning dashboard endpoint still works after adding new engines
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"learning-dashboard failed: {response.status_code} - {response.text}"
        
        data = response.json()
        
        # Verify summary exists
        assert "summary" in data, "Missing summary key"
        summary = data["summary"]
        
        # Verify key summary fields
        assert "total_learning_events" in summary, "Missing total_learning_events"
        assert "total_corrections" in summary, "Missing total_corrections"
        assert "total_posting_profiles" in summary, "Missing total_posting_profiles"
        
        print(f"PASS: learning-dashboard returns valid structure")
        print(f"  total_learning_events={summary['total_learning_events']}, total_corrections={summary['total_corrections']}, total_posting_profiles={summary['total_posting_profiles']}")


class TestContinuousLearningServiceExists:
    """Verify the continuous_learning_service.py has required functions"""

    def test_service_file_exists(self):
        """Verify continuous_learning_service.py exists"""
        import os
        service_path = "/app/backend/services/continuous_learning_service.py"
        assert os.path.exists(service_path), f"Service file not found: {service_path}"
        print(f"PASS: continuous_learning_service.py exists")

    def test_service_has_required_functions(self):
        """Verify service has all required functions"""
        # Read the service file
        with open("/app/backend/services/continuous_learning_service.py", "r") as f:
            content = f.read()
        
        required_functions = [
            "detect_posted_drafts",
            "propagate_cross_vendor_learning",
            "auto_promote_confidence",
            "learn_from_field_correction",
            "run_all_learning_engines"
        ]
        
        for func in required_functions:
            assert f"async def {func}" in content, f"Missing function: {func}"
            print(f"  Found: {func}")
        
        print(f"PASS: All {len(required_functions)} required functions found in continuous_learning_service.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
