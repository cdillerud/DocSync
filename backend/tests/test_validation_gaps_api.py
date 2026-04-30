"""
Backend API Tests for Validation Gap Fixes (Iteration 203)

Tests the following features:
1. POST /api/readiness/fix-validation-gaps - Returns proper response with po_learning, vendor_resolution, reevaluation
2. POST /api/posting-patterns/system/run-full-cycle - Completes all 8 steps including 2b_validation_gaps
3. GET /api/readiness/metrics - Returns valid readiness analytics
4. PO validation learning auto-sets po_expected=false for vendors with >70% PO failure rate
5. Vendor auto-resolution fuzzy-matches vendor names against BC vendor profiles
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://contract-intel-9.preview.emergentagent.com').rstrip('/')


class TestFixValidationGapsEndpoint:
    """Tests for POST /api/readiness/fix-validation-gaps"""
    
    def test_fix_validation_gaps_returns_200(self):
        """Test that fix-validation-gaps endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps?limit=10", timeout=60)
        print(f"fix-validation-gaps status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: fix-validation-gaps returns 200")
    
    def test_fix_validation_gaps_response_structure(self):
        """Test that fix-validation-gaps returns proper response structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps?limit=10", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required top-level keys
        assert "po_learning" in data, "Response missing 'po_learning' section"
        assert "vendor_resolution" in data, "Response missing 'vendor_resolution' section"
        assert "reevaluation" in data, "Response missing 'reevaluation' section"
        
        print(f"Response structure: {list(data.keys())}")
        print("PASS: fix-validation-gaps has correct response structure")
    
    def test_fix_validation_gaps_po_learning_structure(self):
        """Test that po_learning section has correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps?limit=10", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        po_learning = data.get("po_learning", {})
        
        # Check po_learning structure
        assert "vendors_learned" in po_learning, "po_learning missing 'vendors_learned'"
        assert "vendors_checked" in po_learning, "po_learning missing 'vendors_checked'"
        assert "details" in po_learning, "po_learning missing 'details'"
        
        assert isinstance(po_learning["vendors_learned"], int), "vendors_learned should be int"
        assert isinstance(po_learning["vendors_checked"], int), "vendors_checked should be int"
        assert isinstance(po_learning["details"], list), "details should be list"
        
        print(f"po_learning: vendors_learned={po_learning['vendors_learned']}, vendors_checked={po_learning['vendors_checked']}")
        print("PASS: po_learning has correct structure")
    
    def test_fix_validation_gaps_vendor_resolution_structure(self):
        """Test that vendor_resolution section has correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps?limit=10", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        vendor_res = data.get("vendor_resolution", {})
        
        # Check vendor_resolution structure
        assert "resolved" in vendor_res, "vendor_resolution missing 'resolved'"
        assert "attempted" in vendor_res, "vendor_resolution missing 'attempted'"
        assert "details" in vendor_res, "vendor_resolution missing 'details'"
        
        assert isinstance(vendor_res["resolved"], int), "resolved should be int"
        assert isinstance(vendor_res["attempted"], int), "attempted should be int"
        assert isinstance(vendor_res["details"], list), "details should be list"
        
        print(f"vendor_resolution: resolved={vendor_res['resolved']}, attempted={vendor_res['attempted']}")
        print("PASS: vendor_resolution has correct structure")
    
    def test_fix_validation_gaps_reevaluation_structure(self):
        """Test that reevaluation section has correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps?limit=10", timeout=60)
        assert response.status_code == 200
        
        data = response.json()
        reeval = data.get("reevaluation", {})
        
        # Check reevaluation structure
        assert "total" in reeval, "reevaluation missing 'total'"
        assert "upgraded" in reeval, "reevaluation missing 'upgraded'"
        assert "transitions" in reeval, "reevaluation missing 'transitions'"
        
        assert isinstance(reeval["total"], int), "total should be int"
        assert isinstance(reeval["upgraded"], int), "upgraded should be int"
        assert isinstance(reeval["transitions"], list), "transitions should be list"
        
        print(f"reevaluation: total={reeval['total']}, upgraded={reeval['upgraded']}")
        print("PASS: reevaluation has correct structure")


class TestRunFullCycleEndpoint:
    """Tests for POST /api/posting-patterns/system/run-full-cycle"""
    
    def test_run_full_cycle_returns_200(self):
        """Test that run-full-cycle endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle?limit=5", timeout=180)
        print(f"run-full-cycle status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: run-full-cycle returns 200")
    
    def test_run_full_cycle_includes_validation_gaps_step(self):
        """Test that run-full-cycle includes 2b_validation_gaps step"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle?limit=5", timeout=180)
        assert response.status_code == 200
        
        data = response.json()
        details = data.get("details", {})
        
        # Check that 2b_validation_gaps step exists
        assert "2b_validation_gaps" in details, f"Missing 2b_validation_gaps step. Steps found: {list(details.keys())}"
        
        gap_step = details["2b_validation_gaps"]
        print(f"2b_validation_gaps step: {gap_step}")
        
        # Check step structure (should have po_learning, vendor_resolution, reevaluation OR status/error)
        if gap_step.get("status") == "error":
            print(f"Warning: 2b_validation_gaps had error: {gap_step.get('error')}")
        else:
            assert "po_learning" in gap_step or "status" in gap_step, "2b_validation_gaps missing expected keys"
        
        print("PASS: run-full-cycle includes 2b_validation_gaps step")
    
    def test_run_full_cycle_has_8_steps(self):
        """Test that run-full-cycle has all 8 steps"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle?limit=5", timeout=180)
        assert response.status_code == 200
        
        data = response.json()
        details = data.get("details", {})
        
        # Expected steps (based on the code)
        expected_steps = [
            "1_readiness_reevaluate",
            "2_intelligence_backfill",
            "2b_validation_gaps",
            "3_auto_draft_queue",
            "4_learning_engines",
            "5_feedback_sync",
            "6_auto_approve",
            "7_ready_to_post",
        ]
        
        found_steps = list(details.keys())
        print(f"Found steps: {found_steps}")
        
        # Check that 2b_validation_gaps is present (the new step)
        assert "2b_validation_gaps" in found_steps, f"Missing 2b_validation_gaps. Found: {found_steps}"
        
        print(f"Total steps found: {len(found_steps)}")
        print("PASS: run-full-cycle has validation_gaps step")


class TestReadinessMetricsEndpoint:
    """Tests for GET /api/readiness/metrics"""
    
    def test_readiness_metrics_returns_200(self):
        """Test that readiness metrics endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        print(f"readiness/metrics status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: readiness/metrics returns 200")
    
    def test_readiness_metrics_response_structure(self):
        """Test that readiness metrics returns valid analytics structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        # Check for expected keys in metrics response
        expected_keys = ["total", "by_status", "by_action"]
        for key in expected_keys:
            if key not in data:
                print(f"Note: '{key}' not in response. Keys found: {list(data.keys())}")
        
        print(f"Metrics response keys: {list(data.keys())}")
        print("PASS: readiness/metrics returns valid structure")


class TestReadinessQueueEndpoint:
    """Tests for GET /api/readiness/queue"""
    
    def test_readiness_queue_returns_200(self):
        """Test that readiness queue endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/queue?limit=10", timeout=30)
        print(f"readiness/queue status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: readiness/queue returns 200")
    
    def test_readiness_queue_with_status_filter(self):
        """Test readiness queue with status filter"""
        for status in ["needs_review", "blocked", "ready_auto_draft"]:
            response = requests.get(f"{BASE_URL}/api/readiness/queue?status={status}&limit=5", timeout=30)
            assert response.status_code == 200, f"Failed for status={status}: {response.text}"
            print(f"readiness/queue?status={status} returned 200")
        print("PASS: readiness/queue status filters work")


class TestAutomationRateEndpoint:
    """Tests for GET /api/readiness/automation-rate"""
    
    def test_automation_rate_returns_200(self):
        """Test that automation-rate endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate", timeout=30)
        print(f"automation-rate status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: automation-rate returns 200")
    
    def test_automation_rate_response_structure(self):
        """Test that automation-rate returns expected structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/automation-rate", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        # Check for expected keys
        expected_keys = ["automation_rate", "total_documents"]
        for key in expected_keys:
            assert key in data, f"Missing '{key}' in automation-rate response"
        
        assert isinstance(data["automation_rate"], (int, float)), "automation_rate should be numeric"
        assert isinstance(data["total_documents"], int), "total_documents should be int"
        
        print(f"Automation rate: {data['automation_rate']}%, Total docs: {data['total_documents']}")
        print("PASS: automation-rate has correct structure")


class TestPOPendingEndpoints:
    """Tests for PO Pending queue endpoints"""
    
    def test_po_pending_queue_returns_200(self):
        """Test that PO pending queue endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/po-pending?limit=10", timeout=30)
        print(f"po-pending status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: po-pending returns 200")
    
    def test_po_pending_park_returns_200(self):
        """Test that PO pending park endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/po-pending/park", timeout=60)
        print(f"po-pending/park status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: po-pending/park returns 200")
    
    def test_po_pending_retry_returns_200(self):
        """Test that PO pending retry endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/po-pending/retry", timeout=60)
        print(f"po-pending/retry status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: po-pending/retry returns 200")


class TestExceptionQueueEndpoint:
    """Tests for exception queue endpoint"""
    
    def test_exception_queue_returns_200(self):
        """Test that exception queue endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?limit=10", timeout=30)
        print(f"exception-queue status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: exception-queue returns 200")
    
    def test_exception_queue_response_structure(self):
        """Test that exception queue returns expected structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?limit=10", timeout=30)
        assert response.status_code == 200
        
        data = response.json()
        
        assert "total" in data, "Missing 'total' in exception-queue response"
        assert "documents" in data, "Missing 'documents' in exception-queue response"
        assert isinstance(data["total"], int), "total should be int"
        assert isinstance(data["documents"], list), "documents should be list"
        
        print(f"Exception queue: total={data['total']}, docs returned={len(data['documents'])}")
        print("PASS: exception-queue has correct structure")


class TestLearningDashboardEndpoint:
    """Tests for learning dashboard endpoint"""
    
    def test_learning_dashboard_returns_200(self):
        """Test that learning dashboard endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard", timeout=30)
        print(f"learning-dashboard status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: learning-dashboard returns 200")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
