"""
Test Suite for Auto-Approve and Stable Vendor APIs
Tests the new endpoints for:
  - Stable Vendor config (GET/PUT)
  - Stable Vendor diagnostics
  - Stable Vendor threshold application
  - Stable Vendor evaluation
  - Auto-approve diagnose, dry-run, run
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestStableVendorConfig:
    """Test stable vendor config GET/PUT endpoints"""

    def test_get_config_returns_thresholds(self):
        """GET /api/stable-vendor/config returns all threshold fields"""
        r = requests.get(f"{BASE_URL}/api/stable-vendor/config")
        assert r.status_code == 200
        data = r.json()
        assert "config_id" in data
        assert "min_documents_processed" in data
        assert "min_automation_success_rate" in data
        assert "min_reference_resolution_rate" in data
        assert "max_correction_rate" in data
        assert "min_validation_pass_rate" in data
        # Values should be numeric
        assert isinstance(data["min_documents_processed"], (int, float))
        assert isinstance(data["min_automation_success_rate"], (int, float))

    def test_put_config_updates_thresholds(self):
        """PUT /api/stable-vendor/config updates and returns updated config"""
        payload = {
            "min_documents_processed": 10,
            "min_automation_success_rate": 0.50,
        }
        r = requests.put(f"{BASE_URL}/api/stable-vendor/config", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["min_documents_processed"] == 10
        assert data["min_automation_success_rate"] == 0.50
        assert "updated_at" in data


class TestStableVendorDiagnose:
    """Test stable vendor diagnostic endpoint"""

    def test_diagnose_returns_vendor_diagnostics(self):
        """GET /api/stable-vendor/diagnose returns vendor analysis"""
        r = requests.get(f"{BASE_URL}/api/stable-vendor/diagnose")
        assert r.status_code == 200
        data = r.json()
        assert "total_vendors" in data
        assert "currently_stable" in data
        assert "current_thresholds" in data
        assert "checks_pass_rate" in data
        assert "vendors" in data
        # vendors is a list with diagnostic info
        assert isinstance(data["vendors"], list)
        if len(data["vendors"]) > 0:
            v = data["vendors"][0]
            assert "vendor" in v
            assert "is_stable" in v
            assert "failing_checks" in v
            assert "checks_passed" in v

    def test_diagnose_returns_suggested_thresholds(self):
        """Diagnose endpoint returns suggested_thresholds"""
        r = requests.get(f"{BASE_URL}/api/stable-vendor/diagnose")
        assert r.status_code == 200
        data = r.json()
        assert "suggested_thresholds" in data
        # May be empty if not enough data, but key must exist


class TestApplySuggestedThresholds:
    """Test apply-suggested-thresholds endpoint"""

    def test_apply_suggested_thresholds(self):
        """POST /api/stable-vendor/apply-suggested-thresholds applies and returns result"""
        r = requests.post(f"{BASE_URL}/api/stable-vendor/apply-suggested-thresholds")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data["status"] in ("applied", "no_changes")
        if data["status"] == "applied":
            assert "thresholds_applied" in data
            assert "reevaluation" in data


class TestStableVendorEvaluate:
    """Test vendor stability evaluation"""

    def test_evaluate_vendor_returns_stability(self):
        """GET /api/stable-vendor/evaluate/{vendor_id} returns stability assessment"""
        # TUMALOC is known to exist in the test data
        r = requests.get(f"{BASE_URL}/api/stable-vendor/evaluate/TUMALOC")
        assert r.status_code == 200
        data = r.json()
        assert "stable_vendor_flag" in data
        assert "stable_vendor_score" in data
        assert "checks" in data
        assert "reasons" in data
        assert isinstance(data["checks"], list)
        # Each check should have passed, value, threshold
        if len(data["checks"]) > 0:
            c = data["checks"][0]
            assert "check" in c
            assert "passed" in c
            assert "value" in c


class TestStableVendorDetail:
    """Test vendor detail endpoint"""

    def test_get_vendor_detail(self):
        """GET /api/stable-vendor/vendors/{vendor_no} returns full detail"""
        r = requests.get(f"{BASE_URL}/api/stable-vendor/vendors/TUMALOC")
        assert r.status_code == 200
        data = r.json()
        assert data["vendor_no"] == "TUMALOC"
        assert "effective_status" in data
        assert "system_status" in data
        assert "stability_checks" in data
        assert "routing_impact" in data
        assert "quality_signals" in data


class TestAutoApproveDiagnose:
    """Test auto-approve diagnose endpoint"""

    def test_diagnose_backlog_returns_analysis(self):
        """GET /api/auto-approve/diagnose returns approval backlog analysis"""
        r = requests.get(f"{BASE_URL}/api/auto-approve/diagnose")
        assert r.status_code == 200
        data = r.json()
        assert "total_needs_approval" in data
        assert "auto_approvable_now" in data
        assert "needs_stable_vendor_first" in data
        assert "unique_vendors" in data
        assert "top_vendors" in data
        assert "recommendation" in data
        # Values should be non-negative integers
        assert isinstance(data["total_needs_approval"], int)
        assert data["total_needs_approval"] >= 0


class TestAutoApproveDryRun:
    """Test auto-approve dry-run endpoint"""

    def test_dry_run_returns_preview(self):
        """POST /api/auto-approve/dry-run returns preview of what would be approved"""
        r = requests.post(f"{BASE_URL}/api/auto-approve/dry-run")
        assert r.status_code == 200
        data = r.json()
        assert "total_candidates" in data
        assert "would_approve" in data
        assert "would_skip" in data
        assert "skip_reasons_summary" in data
        assert "require_stable_vendor" in data
        # Default should require stable vendor
        assert data["require_stable_vendor"] is True

    def test_dry_run_with_params(self):
        """Dry run with query params"""
        r = requests.post(
            f"{BASE_URL}/api/auto-approve/dry-run",
            params={"require_stable_vendor": False, "min_routing_score": 0}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["require_stable_vendor"] is False


class TestAutoApproveRun:
    """Test auto-approve run endpoint"""

    def test_run_auto_approve(self):
        """POST /api/auto-approve/run executes batch approval"""
        r = requests.post(f"{BASE_URL}/api/auto-approve/run")
        assert r.status_code == 200
        data = r.json()
        assert "total_candidates" in data
        assert "approved" in data
        assert "skipped" in data
        assert "by_vendor" in data
        assert "force_mode" in data
        assert "timestamp" in data
        assert data["force_mode"] is False

    def test_run_auto_approve_force_mode(self):
        """POST /api/auto-approve/run?force=true uses force mode"""
        r = requests.post(f"{BASE_URL}/api/auto-approve/run", params={"force": True})
        assert r.status_code == 200
        data = r.json()
        assert data["force_mode"] is True


class TestVendorsList:
    """Test vendors list endpoint"""

    def test_list_vendors(self):
        """GET /api/stable-vendor/vendors returns paginated list"""
        r = requests.get(f"{BASE_URL}/api/stable-vendor/vendors")
        assert r.status_code == 200
        data = r.json()
        assert "vendors" in data
        assert "total" in data
        assert "skip" in data
        assert "limit" in data
        assert isinstance(data["vendors"], list)

    def test_list_vendors_with_search(self):
        """Filter vendors by search"""
        r = requests.get(
            f"{BASE_URL}/api/stable-vendor/vendors",
            params={"search": "TUMALOC"}
        )
        assert r.status_code == 200
        data = r.json()
        # Should find TUMALOC
        vendor_names = [v["vendor_name"] for v in data["vendors"]]
        assert "TUMALOC" in vendor_names

    def test_list_vendors_with_status_filter(self):
        """Filter vendors by status"""
        r = requests.get(
            f"{BASE_URL}/api/stable-vendor/vendors",
            params={"status": "stable"}
        )
        assert r.status_code == 200
        data = r.json()
        # All returned should have stable effective status
        for v in data["vendors"]:
            assert v["effective_status"] == "stable"


class TestHealthEndpoint:
    """Basic health check"""

    def test_health(self):
        """GET /api/health returns healthy"""
        r = requests.get(f"{BASE_URL}/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
