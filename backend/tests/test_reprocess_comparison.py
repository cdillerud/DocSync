"""
Test suite for Reprocess Comparison API endpoints
Tests the bulk reprocess feature for GPI Document Hub including:
- Compare (Preview) - re-runs LLM on docs and shows before/after
- Apply Improvements - commits improved results back to production
- Full Pipeline Reprocess - re-runs complete pipeline on non-terminal docs
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestReprocessComparisonStatus:
    """Test status endpoints for reprocess comparison"""

    def test_comparison_status_returns_valid_response(self):
        """GET /api/reprocess-comparison/status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["idle", "running", "completed"]
        print(f"Comparison status: {data['status']}")

    def test_apply_status_returns_valid_response(self):
        """GET /api/reprocess-comparison/apply-status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/apply-status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["idle", "running", "completed"]
        print(f"Apply status: {data['status']}")

    def test_full_status_returns_valid_response(self):
        """GET /api/reprocess-comparison/full-status returns valid status"""
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/full-status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["idle", "running", "completed"]
        print(f"Full reprocess status: {data['status']}")


class TestReprocessComparisonRuns:
    """Test runs listing endpoint"""

    def test_list_runs_returns_array(self):
        """GET /api/reprocess-comparison/runs returns list of runs"""
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/runs")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)
        print(f"Found {len(data['runs'])} comparison runs")
        
        # If runs exist, verify structure
        if data["runs"]:
            run = data["runs"][0]
            assert "run_id" in run
            assert "status" in run
            print(f"Latest run: {run['run_id']} - {run['status']}")


class TestReprocessComparisonRun:
    """Test starting a comparison run"""

    def test_start_comparison_run(self):
        """POST /api/reprocess-comparison/run starts a comparison"""
        # Wait for any running comparison to complete
        for _ in range(10):
            status_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/status")
            if status_resp.json().get("status") != "running":
                break
            time.sleep(2)
        
        response = requests.post(f"{BASE_URL}/api/reprocess-comparison/run?limit=2")
        assert response.status_code == 200
        data = response.json()
        
        # Either started or already running
        if "error" in data:
            assert "already running" in data["error"].lower()
            print(f"Comparison already running: {data.get('run_id')}")
        else:
            assert "run_id" in data
            assert data["status"] == "started"
            assert data["limit"] == 2
            print(f"Started comparison run: {data['run_id']}")

    def test_start_comparison_with_doc_type_filter(self):
        """POST /api/reprocess-comparison/run with doc_type filter"""
        # Wait for any running comparison to complete
        for _ in range(15):
            status_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/status")
            if status_resp.json().get("status") != "running":
                break
            time.sleep(2)
        
        response = requests.post(f"{BASE_URL}/api/reprocess-comparison/run?limit=1&doc_type=Invoice")
        assert response.status_code == 200
        data = response.json()
        
        if "error" not in data:
            assert data["filter"] == "Invoice"
            print(f"Started filtered comparison: {data['run_id']}")


class TestReprocessComparisonApply:
    """Test apply improvements endpoint"""

    def test_apply_nonexistent_run_returns_error(self):
        """POST /api/reprocess-comparison/apply/{run_id} with non-existent run returns error"""
        response = requests.post(f"{BASE_URL}/api/reprocess-comparison/apply/nonexistent-run-xyz")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "not found" in data["error"].lower()
        print(f"Correctly returned error for non-existent run")

    def test_apply_with_valid_completed_run(self):
        """POST /api/reprocess-comparison/apply/{run_id} with completed run"""
        # Get list of runs to find a completed one
        runs_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/runs")
        runs = runs_resp.json().get("runs", [])
        
        completed_run = None
        for run in runs:
            if run.get("status") == "completed":
                completed_run = run
                break
        
        if not completed_run:
            pytest.skip("No completed runs available to test apply")
        
        # Wait for any running apply to complete
        for _ in range(10):
            apply_status = requests.get(f"{BASE_URL}/api/reprocess-comparison/apply-status")
            if apply_status.json().get("status") != "running":
                break
            time.sleep(2)
        
        response = requests.post(f"{BASE_URL}/api/reprocess-comparison/apply/{completed_run['run_id']}?improved_only=true")
        assert response.status_code == 200
        data = response.json()
        
        # Either started or already applied
        if "error" in data:
            print(f"Apply returned: {data['error']}")
        else:
            assert data["status"] == "started"
            assert data["run_id"] == completed_run["run_id"]
            print(f"Started apply for run: {completed_run['run_id']}")


class TestReprocessComparisonFull:
    """Test full pipeline reprocess endpoint"""

    def test_start_full_reprocess(self):
        """POST /api/reprocess-comparison/run-full starts full reprocess"""
        # Wait for any running full reprocess to complete
        for _ in range(10):
            status_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/full-status")
            if status_resp.json().get("status") != "running":
                break
            time.sleep(2)
        
        response = requests.post(f"{BASE_URL}/api/reprocess-comparison/run-full?limit=1&skip_terminal=true")
        assert response.status_code == 200
        data = response.json()
        
        if "error" in data:
            assert "already running" in data["error"].lower()
            print(f"Full reprocess already running: {data.get('run_id')}")
        else:
            assert "run_id" in data
            assert data["status"] == "started"
            assert data["skip_terminal"] == True
            print(f"Started full reprocess: {data['run_id']}")


class TestReprocessComparisonResults:
    """Test results endpoint"""

    def test_results_for_nonexistent_run(self):
        """GET /api/reprocess-comparison/results/{run_id} for non-existent run"""
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/results/nonexistent-run-xyz")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        print("Correctly returned error for non-existent run results")

    def test_results_for_existing_run(self):
        """GET /api/reprocess-comparison/results/{run_id} for existing run"""
        # Get list of runs to find one
        runs_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/runs")
        runs = runs_resp.json().get("runs", [])
        
        if not runs:
            pytest.skip("No runs available to test results")
        
        run_id = runs[0]["run_id"]
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/results/{run_id}")
        assert response.status_code == 200
        data = response.json()
        
        if "error" not in data:
            assert "run" in data
            assert "results" in data
            print(f"Got results for run {run_id}: {data.get('total_results', 0)} results")

    def test_results_with_changes_only_filter(self):
        """GET /api/reprocess-comparison/results/{run_id}?changes_only=true"""
        runs_resp = requests.get(f"{BASE_URL}/api/reprocess-comparison/runs")
        runs = runs_resp.json().get("runs", [])
        
        if not runs:
            pytest.skip("No runs available to test results")
        
        run_id = runs[0]["run_id"]
        response = requests.get(f"{BASE_URL}/api/reprocess-comparison/results/{run_id}?changes_only=true")
        assert response.status_code == 200
        data = response.json()
        
        if "error" not in data:
            print(f"Got changes-only results for run {run_id}: {data.get('total_results', 0)} results")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
