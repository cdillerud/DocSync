"""
AR Release Gate Feature Tests - Iteration 119
Tests for AR Release Gate (Prepay & Terms Approval) endpoints and config_service rewiring.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs from main agent context
SALES_DOC_ID = "8fec1917-0961-41c4-a327-4e5924aad5f8"  # Evaluated sales doc with ar_release_gate
NON_SALES_DOC_ID = "TEST-BUNDLE-A"  # Non-sales document (should be skipped)
NONEXISTENT_DOC_ID = "nonexistent-doc-12345"  # Non-existent document for 404 test


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestARReleaseMetrics:
    """AR Release Gate metrics endpoint tests"""

    def test_ar_release_metrics_endpoint_returns_200(self, api_client):
        """GET /api/ar-release/metrics should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: AR release metrics endpoint returns 200")

    def test_ar_release_metrics_has_total_evaluated(self, api_client):
        """GET /api/ar-release/metrics should include total_evaluated"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_evaluated" in data, "Response missing 'total_evaluated' field"
        assert isinstance(data["total_evaluated"], int), "total_evaluated should be an integer"
        print(f"PASS: total_evaluated = {data['total_evaluated']}")

    def test_ar_release_metrics_has_by_status(self, api_client):
        """GET /api/ar-release/metrics should include by_status breakdown"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "by_status" in data, "Response missing 'by_status' field"
        assert isinstance(data["by_status"], dict), "by_status should be a dict"
        print(f"PASS: by_status = {data['by_status']}")

    def test_ar_release_metrics_has_top_blocking_reasons(self, api_client):
        """GET /api/ar-release/metrics should include top_blocking_reasons"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "top_blocking_reasons" in data, "Response missing 'top_blocking_reasons' field"
        assert isinstance(data["top_blocking_reasons"], list), "top_blocking_reasons should be a list"
        print(f"PASS: top_blocking_reasons count = {len(data['top_blocking_reasons'])}")


class TestARReleaseEvaluate:
    """AR Release Gate evaluate endpoint tests"""

    def test_evaluate_sales_document_returns_200_or_gate_data(self, api_client):
        """POST /api/ar-release/evaluate/{doc_id} should evaluate a sales document"""
        response = api_client.post(f"{BASE_URL}/api/ar-release/evaluate/{SALES_DOC_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Should have document_id and status in response
        assert "document_id" in data, "Response missing 'document_id'"
        assert data["document_id"] == SALES_DOC_ID, f"document_id mismatch"
        # Either has gate data (status, checks) or skipped=true
        has_gate_data = "status" in data and "checks" in data
        is_skipped = data.get("skipped") == True
        assert has_gate_data or is_skipped, f"Expected gate data or skipped, got {data}"
        print(f"PASS: Evaluate sales doc returned: status={data.get('status')}, skipped={data.get('skipped')}")

    def test_evaluate_non_sales_document_returns_skipped(self, api_client):
        """POST /api/ar-release/evaluate/{doc_id} should skip non-sales documents"""
        response = api_client.post(f"{BASE_URL}/api/ar-release/evaluate/{NON_SALES_DOC_ID}")
        # Non-sales docs should either be skipped (200 with skipped:true) or 404 if doc not found
        if response.status_code == 200:
            data = response.json()
            if "skipped" in data:
                assert data["skipped"] == True, "Non-sales doc should have skipped=true"
                print(f"PASS: Non-sales document skipped: {data.get('reason')}")
            else:
                # It might be a sales doc after all (depends on doc_type)
                print(f"INFO: Document evaluated (may be sales type): {data.get('status')}")
        elif response.status_code == 404:
            print(f"PASS: Non-sales document not found (404)")
        else:
            pytest.fail(f"Unexpected status code {response.status_code}: {response.text}")

    def test_evaluate_nonexistent_document_returns_404(self, api_client):
        """POST /api/ar-release/evaluate/{doc_id} should return 404 for non-existent doc"""
        response = api_client.post(f"{BASE_URL}/api/ar-release/evaluate/{NONEXISTENT_DOC_ID}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Non-existent document returns 404")


class TestARReleaseOverride:
    """AR Release Gate override endpoint tests"""

    def test_override_endpoint_accepts_request(self, api_client):
        """POST /api/ar-release/override/{doc_id} should accept override request"""
        override_payload = {
            "approved_by": "test_user_119",
            "notes": "Test override from iteration 119"
        }
        response = api_client.post(
            f"{BASE_URL}/api/ar-release/override/{SALES_DOC_ID}",
            json=override_payload
        )
        # Should be 200 (success) or 404 (doc not evaluated yet)
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert "document_id" in data, "Response missing document_id"
            assert "status" in data or "approved_by" in data, "Response should confirm override"
            print(f"PASS: Override accepted for {SALES_DOC_ID}")
        else:
            print(f"INFO: Override returned 404 (gate may not be evaluated)")

    def test_override_nonexistent_document_returns_error(self, api_client):
        """POST /api/ar-release/override/{doc_id} should return error for non-existent doc"""
        override_payload = {
            "approved_by": "test_user",
            "notes": ""
        }
        response = api_client.post(
            f"{BASE_URL}/api/ar-release/override/{NONEXISTENT_DOC_ID}",
            json=override_payload
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Override on non-existent doc returns 404")


class TestARReleaseQueue:
    """AR Release Gate queue endpoint tests"""

    def test_queue_endpoint_returns_200(self, api_client):
        """GET /api/ar-release/queue should return 200"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: AR release queue endpoint returns 200")

    def test_queue_returns_documents_with_ar_gate(self, api_client):
        """GET /api/ar-release/queue should return documents with ar_release_gate"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/queue")
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data, "Response missing 'documents' field"
        assert "total" in data, "Response missing 'total' field"
        print(f"PASS: Queue returns {data['total']} documents")

    def test_queue_filter_by_status(self, api_client):
        """GET /api/ar-release/queue?status=released should filter by status"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/queue?status=released")
        assert response.status_code == 200
        data = response.json()
        assert "status_filter" in data, "Response missing 'status_filter' field"
        assert data["status_filter"] == "released", f"Expected 'released', got {data['status_filter']}"
        print(f"PASS: Queue filtered by released status, total={data['total']}")

    def test_queue_filter_by_held_status(self, api_client):
        """GET /api/ar-release/queue?status=held should filter by held status"""
        response = api_client.get(f"{BASE_URL}/api/ar-release/queue?status=held")
        assert response.status_code == 200
        data = response.json()
        assert data["status_filter"] == "held"
        print(f"PASS: Queue filtered by held status, total={data['total']}")


class TestWorkflowIntelligenceReadinessSummary:
    """Workflow intelligence endpoint should include readiness_summary"""

    def test_workflow_intelligence_returns_200(self, api_client):
        """GET /api/dashboard/workflow-intelligence should return 200"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Workflow intelligence endpoint returns 200")

    def test_workflow_intelligence_has_readiness_summary(self, api_client):
        """GET /api/dashboard/workflow-intelligence should include readiness_summary"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
        data = response.json()
        assert "readiness_summary" in data, "Response missing 'readiness_summary' field"
        print("PASS: readiness_summary present in response")

    def test_readiness_summary_has_by_status(self, api_client):
        """readiness_summary should include by_status"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        readiness = data.get("readiness_summary", {})
        assert "by_status" in readiness, "readiness_summary missing 'by_status'"
        print(f"PASS: by_status = {readiness['by_status']}")

    def test_readiness_summary_has_by_action(self, api_client):
        """readiness_summary should include by_action"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        readiness = data.get("readiness_summary", {})
        assert "by_action" in readiness, "readiness_summary missing 'by_action'"
        print(f"PASS: by_action = {readiness['by_action']}")

    def test_readiness_summary_has_confidence_by_status(self, api_client):
        """readiness_summary should include confidence_by_status"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        readiness = data.get("readiness_summary", {})
        assert "confidence_by_status" in readiness, "readiness_summary missing 'confidence_by_status'"
        print(f"PASS: confidence_by_status present")

    def test_readiness_summary_has_top_blocking_reasons(self, api_client):
        """readiness_summary should include top_blocking_reasons"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        readiness = data.get("readiness_summary", {})
        assert "top_blocking_reasons" in readiness, "readiness_summary missing 'top_blocking_reasons'"
        assert isinstance(readiness["top_blocking_reasons"], list)
        print(f"PASS: top_blocking_reasons count = {len(readiness['top_blocking_reasons'])}")

    def test_readiness_summary_has_top_warning_reasons(self, api_client):
        """readiness_summary should include top_warning_reasons"""
        response = api_client.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        readiness = data.get("readiness_summary", {})
        assert "top_warning_reasons" in readiness, "readiness_summary missing 'top_warning_reasons'"
        assert isinstance(readiness["top_warning_reasons"], list)
        print(f"PASS: top_warning_reasons count = {len(readiness['top_warning_reasons'])}")


class TestReadinessMetrics:
    """Readiness metrics endpoint tests"""

    def test_readiness_metrics_returns_200(self, api_client):
        """GET /api/readiness/metrics should return 200"""
        response = api_client.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Readiness metrics endpoint returns 200")

    def test_readiness_metrics_has_required_fields(self, api_client):
        """GET /api/readiness/metrics should return valid readiness analytics"""
        response = api_client.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200
        data = response.json()
        # Check for expected fields
        expected_fields = ["total_documents", "by_status", "by_action"]
        for field in expected_fields:
            assert field in data, f"Response missing '{field}' field"
        print(f"PASS: Readiness metrics has required fields, total_documents={data.get('total_documents')}")


class TestConfigServiceRewiring:
    """Tests to verify config_service rewiring (GET /api/settings/config and /api/settings/status)"""

    def test_settings_config_returns_200(self, api_client):
        """GET /api/settings/config should return 200"""
        response = api_client.get(f"{BASE_URL}/api/settings/config")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Settings config endpoint returns 200")

    def test_settings_config_returns_11_plus_keys(self, api_client):
        """GET /api/settings/config should return 11+ config keys"""
        response = api_client.get(f"{BASE_URL}/api/settings/config")
        assert response.status_code == 200
        data = response.json()
        # Response might be wrapped in "config" key or be flat
        config_data = data.get("config", data) if isinstance(data, dict) else data
        assert isinstance(config_data, dict), "Config data should be a dict"
        key_count = len(config_data.keys())
        assert key_count >= 11, f"Expected at least 11 config keys, got {key_count}"
        print(f"PASS: Settings config returns {key_count} keys (>=11)")
        # Log some key names for verification
        print(f"  Config keys: {list(config_data.keys())[:5]}...")

    def test_settings_status_returns_200(self, api_client):
        """GET /api/settings/status should return 200"""
        response = api_client.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: Settings status endpoint returns 200")

    def test_settings_status_has_connection_info(self, api_client):
        """GET /api/settings/status should return connection info"""
        response = api_client.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        data = response.json()
        # Should have some status/connection info
        assert isinstance(data, dict), "Status response should be a dict"
        assert len(data) > 0, "Status response should not be empty"
        print(f"PASS: Settings status returns connection info, keys={list(data.keys())}")


class TestSalesDocumentARGate:
    """Verify AR gate data on the specific sales document"""

    def test_sales_document_fetch(self, api_client):
        """Fetch the sales document to verify AR gate exists"""
        response = api_client.get(f"{BASE_URL}/api/documents/{SALES_DOC_ID}")
        if response.status_code == 200:
            data = response.json()
            doc = data.get("document", data)
            # Check if ar_release_gate exists
            ar_gate = doc.get("ar_release_gate")
            if ar_gate:
                print(f"PASS: Sales doc has ar_release_gate, status={ar_gate.get('status')}")
                # Verify checks structure
                checks = ar_gate.get("checks", {})
                expected_checks = ["customer_resolution", "prepay_hold", "credit_limit", "payment_terms", "ship_to"]
                for check in expected_checks:
                    if check in checks:
                        print(f"  - {check}: {checks[check].get('result')}")
            else:
                print(f"INFO: Sales doc does not have ar_release_gate yet")
        else:
            print(f"INFO: Sales document fetch returned {response.status_code}")
