"""
Iteration 204: Backend API Tests for Validation Gap Fixes
Tests:
1. POST /api/posting-patterns/system/run-full-cycle - 9 steps including 8_final_cleanup
2. POST /api/readiness/fix-validation-gaps - PO learning + vendor resolution + re-evaluation
3. POST /api/readiness/sync-status - Rules 23-25 (PO relaxed vendor, shipping supporting docs, no-blockers catchall)
4. GET /api/readiness/metrics - Analytics
5. GET /api/readiness/automation-rate - Automation rate
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestRunFullCycle:
    """Tests for POST /api/posting-patterns/system/run-full-cycle - 9 steps"""

    def test_run_full_cycle_returns_200(self):
        """run-full-cycle endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle", timeout=120)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: run-full-cycle returns 200")

    def test_run_full_cycle_has_9_steps(self):
        """run-full-cycle now has 9 steps (was 8 in iteration 203)"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle", timeout=120)
        data = response.json()
        assert data.get("steps_total") == 9, f"Expected 9 steps, got {data.get('steps_total')}"
        print("PASS: run-full-cycle has 9 steps")

    def test_run_full_cycle_includes_8_final_cleanup(self):
        """run-full-cycle includes new Step 8: 8_final_cleanup"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle", timeout=120)
        data = response.json()
        details = data.get("details", {})
        assert "8_final_cleanup" in details, f"Missing 8_final_cleanup step. Steps: {list(details.keys())}"
        cleanup = details["8_final_cleanup"]
        assert cleanup.get("status") == "ok", f"8_final_cleanup failed: {cleanup}"
        assert "total_fixed" in cleanup, "8_final_cleanup missing total_fixed"
        assert "remaining" in cleanup, "8_final_cleanup missing remaining"
        print(f"PASS: 8_final_cleanup step present with total_fixed={cleanup.get('total_fixed')}")

    def test_run_full_cycle_all_9_steps_present(self):
        """Verify all 9 steps are present in run-full-cycle"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle", timeout=120)
        data = response.json()
        details = data.get("details", {})
        expected_steps = [
            "1_cleanup",
            "2_intelligence",
            "2b_validation_gaps",
            "3_readiness",
            "4_auto_approve",
            "5_recalibrate",
            "6_learning_pulse",
            "7_deep_learning",
            "8_final_cleanup",
        ]
        for step in expected_steps:
            assert step in details, f"Missing step: {step}. Found: {list(details.keys())}"
        print(f"PASS: All 9 steps present: {expected_steps}")

    def test_run_full_cycle_2b_validation_gaps_structure(self):
        """2b_validation_gaps step has correct structure"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/system/run-full-cycle", timeout=120)
        data = response.json()
        step = data.get("details", {}).get("2b_validation_gaps", {})
        assert step.get("status") == "ok", f"2b_validation_gaps failed: {step}"
        assert "po_vendors_learned" in step, "Missing po_vendors_learned"
        assert "vendors_resolved" in step, "Missing vendors_resolved"
        assert "docs_upgraded" in step, "Missing docs_upgraded"
        print(f"PASS: 2b_validation_gaps structure correct: {step}")


class TestFixValidationGaps:
    """Tests for POST /api/readiness/fix-validation-gaps"""

    def test_fix_validation_gaps_returns_200(self):
        """fix-validation-gaps endpoint returns 200"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps", timeout=60)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: fix-validation-gaps returns 200")

    def test_fix_validation_gaps_has_po_learning(self):
        """fix-validation-gaps has po_learning section"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps", timeout=60)
        data = response.json()
        assert "po_learning" in data, f"Missing po_learning. Keys: {list(data.keys())}"
        po = data["po_learning"]
        assert "vendors_learned" in po, "Missing vendors_learned"
        assert "vendors_checked" in po, "Missing vendors_checked"
        assert "details" in po, "Missing details"
        print(f"PASS: po_learning section present: vendors_learned={po.get('vendors_learned')}")

    def test_fix_validation_gaps_has_vendor_resolution(self):
        """fix-validation-gaps has vendor_resolution section"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps", timeout=60)
        data = response.json()
        assert "vendor_resolution" in data, f"Missing vendor_resolution. Keys: {list(data.keys())}"
        vr = data["vendor_resolution"]
        assert "resolved" in vr, "Missing resolved"
        assert "attempted" in vr, "Missing attempted"
        assert "details" in vr, "Missing details"
        print(f"PASS: vendor_resolution section present: resolved={vr.get('resolved')}")

    def test_fix_validation_gaps_has_reevaluation(self):
        """fix-validation-gaps has reevaluation section"""
        response = requests.post(f"{BASE_URL}/api/readiness/fix-validation-gaps", timeout=60)
        data = response.json()
        assert "reevaluation" in data, f"Missing reevaluation. Keys: {list(data.keys())}"
        re = data["reevaluation"]
        assert "total" in re, "Missing total"
        assert "upgraded" in re, "Missing upgraded"
        assert "transitions" in re, "Missing transitions"
        print(f"PASS: reevaluation section present: upgraded={re.get('upgraded')}")


class TestReadinessMetrics:
    """Tests for GET /api/readiness/metrics"""

    def test_readiness_metrics_returns_200(self):
        """readiness/metrics endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: readiness/metrics returns 200")

    def test_readiness_metrics_has_valid_structure(self):
        """readiness/metrics has expected structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics", timeout=30)
        data = response.json()
        expected_keys = ["total_documents", "by_status", "by_action"]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}. Keys: {list(data.keys())}"
        print(f"PASS: readiness/metrics structure valid. total_documents={data.get('total_documents')}")


class TestUnitTestsDirectExecution:
    """Verify unit tests pass when run directly with python3"""

    def test_unit_tests_pass(self):
        """Unit tests in test_validation_gaps.py pass"""
        import subprocess
        result = subprocess.run(
            ["python3", "tests/test_validation_gaps.py"],
            cwd="/app/backend",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Unit tests failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "ALL TESTS PASSED" in result.stdout, f"Expected 'ALL TESTS PASSED' in output: {result.stdout}"
        print("PASS: Unit tests (test_validation_gaps.py) pass with direct python3 execution")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
