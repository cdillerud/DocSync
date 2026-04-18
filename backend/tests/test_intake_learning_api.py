"""
API tests for Intake Learning endpoints — hub-wide Giovanni-style BC + Spiro learning.

Tests:
  • GET /api/intake/learning/summary — dashboard metrics
  • POST /api/intake/learning/backfill — batch processing
  • GET /api/intake/flagged — actionable documents
  • GET /api/intake/insights/{doc_id} — per-doc insights
  • GET /api/intake/insights-xls/{staging_id} — per-XLS insights
  • POST /api/intake/learning/run/{doc_id} — manual run on doc
  • POST /api/intake/learning/run-xls/{staging_id} — manual run on XLS
  • Regression tests for existing endpoints
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIntakeLearningEndpoints:
    """Tests for the new /api/intake/* endpoints"""

    def test_learning_summary_returns_correct_shape(self):
        """GET /api/intake/learning/summary returns {hub, xls_staging, top_customers}"""
        response = requests.get(f"{BASE_URL}/api/intake/learning/summary")
        assert response.status_code == 200
        
        data = response.json()
        # Check top-level keys
        assert "generated_at" in data
        assert "hub" in data
        assert "xls_staging" in data
        assert "top_customers" in data
        
        # Check hub shape
        hub = data["hub"]
        assert "eligible_docs" in hub
        assert "with_insights" in hub
        assert "cold_start" in hub
        assert "actionable_findings" in hub
        assert "bounds_violations" in hub
        assert "coverage_pct" in hub
        
        # Check xls_staging shape
        xls = data["xls_staging"]
        assert "total" in xls
        assert "with_insights" in xls
        assert "cold_start" in xls
        assert "actionable" in xls
        
        # top_customers is a list
        assert isinstance(data["top_customers"], list)
        print(f"Summary: hub={hub['eligible_docs']} docs, xls={xls['total']} staging, {len(data['top_customers'])} top customers")

    def test_backfill_only_missing(self):
        """POST /api/intake/learning/backfill?only_missing=true processes new docs only"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/backfill?limit=10&only_missing=true")
        assert response.status_code == 200
        
        data = response.json()
        assert "hub_documents" in data
        assert "xls_staging" in data
        assert "generated_at" in data
        
        hub = data["hub_documents"]
        assert "processed" in hub
        assert "errors" in hub
        assert "actionable" in hub
        
        xls = data["xls_staging"]
        assert "processed" in xls
        assert "errors" in xls
        assert "actionable" in xls
        print(f"Backfill (only_missing=true): hub={hub['processed']}, xls={xls['processed']}")

    def test_backfill_force_rerun(self):
        """POST /api/intake/learning/backfill?only_missing=false force re-runs all docs"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/backfill?limit=5&only_missing=false")
        assert response.status_code == 200
        
        data = response.json()
        hub = data["hub_documents"]
        xls = data["xls_staging"]
        # Force re-run should process some docs (if any exist)
        print(f"Backfill (force): hub={hub['processed']}, xls={xls['processed']}")

    def test_flagged_documents_endpoint(self):
        """GET /api/intake/flagged returns documents with has_actionable_findings=true"""
        response = requests.get(f"{BASE_URL}/api/intake/flagged?limit=25")
        assert response.status_code == 200
        
        data = response.json()
        assert "total" in data
        assert "documents" in data
        assert isinstance(data["documents"], list)
        print(f"Flagged docs: {data['total']}")

    def test_flagged_with_customer_filter(self):
        """GET /api/intake/flagged?customer_no=X filters by customer"""
        response = requests.get(f"{BASE_URL}/api/intake/flagged?limit=10&customer_no=C-10250")
        assert response.status_code == 200
        
        data = response.json()
        assert "total" in data
        assert "documents" in data


class TestIntakeInsightsEndpoints:
    """Tests for per-document and per-XLS insights endpoints"""

    def test_xls_insights_endpoint(self):
        """GET /api/intake/insights-xls/{staging_id} returns persisted insights"""
        # First get a staging ID
        staging_res = requests.get(f"{BASE_URL}/api/inventory-xls/staging?limit=1")
        assert staging_res.status_code == 200
        staging_data = staging_res.json()
        
        if not staging_data.get("staging"):
            pytest.skip("No XLS staging records available")
        
        staging_id = staging_data["staging"][0]["id"]
        
        # Get insights for this staging record
        response = requests.get(f"{BASE_URL}/api/intake/insights-xls/{staging_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert "staging_id" in data
        assert "filename" in data
        assert "intake_insights" in data
        
        insights = data["intake_insights"]
        if insights:
            assert "scope" in insights
            assert insights["scope"] == "inventory_xls_staging"
            assert "ran_at" in insights
            print(f"XLS insights: staging_id={staging_id[:8]}, cold_start={insights.get('cold_start')}")

    def test_xls_insights_not_found(self):
        """GET /api/intake/insights-xls/{invalid_id} returns 404"""
        response = requests.get(f"{BASE_URL}/api/intake/insights-xls/nonexistent-id-12345")
        assert response.status_code == 404

    def test_doc_insights_not_found(self):
        """GET /api/intake/insights/{invalid_id} returns 404"""
        response = requests.get(f"{BASE_URL}/api/intake/insights/nonexistent-doc-id-12345")
        assert response.status_code == 404


class TestManualLearningRun:
    """Tests for manual learning run endpoints"""

    def test_run_learning_on_xls_staging(self):
        """POST /api/intake/learning/run-xls/{staging_id} manually runs learning"""
        # First get a staging ID
        staging_res = requests.get(f"{BASE_URL}/api/inventory-xls/staging?limit=1")
        assert staging_res.status_code == 200
        staging_data = staging_res.json()
        
        if not staging_data.get("staging"):
            pytest.skip("No XLS staging records available")
        
        staging_id = staging_data["staging"][0]["id"]
        
        # Run learning
        response = requests.post(f"{BASE_URL}/api/intake/learning/run-xls/{staging_id}?force=true")
        assert response.status_code == 200
        
        data = response.json()
        assert "staging_id" in data
        assert "scope" in data
        assert data["scope"] == "inventory_xls_staging"
        assert "ran_at" in data
        assert "stages_ran" in data
        print(f"Manual XLS run: staging_id={staging_id[:8]}, stages={data['stages_ran']}")

    def test_run_learning_on_invalid_xls(self):
        """POST /api/intake/learning/run-xls/{invalid_id} returns 404"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/run-xls/nonexistent-id-12345")
        assert response.status_code == 404

    def test_run_learning_on_invalid_doc(self):
        """POST /api/intake/learning/run/{invalid_id} returns 404"""
        response = requests.post(f"{BASE_URL}/api/intake/learning/run/nonexistent-doc-id-12345")
        assert response.status_code == 404


class TestRegressionEndpoints:
    """Regression tests for existing endpoints that should still work"""

    def test_inside_sales_pilot_documents(self):
        """GET /api/inside-sales-pilot/documents still works"""
        response = requests.get(f"{BASE_URL}/api/inside-sales-pilot/documents?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "documents" in data

    def test_inventory_xls_staging(self):
        """GET /api/inventory-xls/staging still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-xls/staging?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "staging" in data

    def test_inventory_ledger_health_summary(self):
        """GET /api/inventory-ledger/health-summary still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/health-summary")
        assert response.status_code == 200
        data = response.json()
        assert "generated_at" in data
        assert "thresholds" in data
        assert "totals" in data
        assert "per_customer" in data

    def test_inventory_ledger_customers(self):
        """GET /api/inventory-ledger/customers still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert response.status_code == 200
        # Returns list of customers
        data = response.json()
        assert isinstance(data, list) or "customers" in data

    def test_inventory_xls_learning_summary(self):
        """GET /api/inventory-xls/learning-summary still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-xls/learning-summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_learned_mappings" in data

    def test_health_endpoint(self):
        """GET /api/health still works"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestColdStartDetection:
    """Tests for cold-start detection behavior"""

    def test_xls_staging_shows_cold_start_when_no_bc_history(self):
        """XLS staging with customer but no BC history shows cold_start=true"""
        # Get a staging record with insights
        staging_res = requests.get(f"{BASE_URL}/api/inventory-xls/staging?limit=10")
        assert staging_res.status_code == 200
        staging_data = staging_res.json()
        
        if not staging_data.get("staging"):
            pytest.skip("No XLS staging records available")
        
        # Find one with intake_insights
        for s in staging_data["staging"]:
            if s.get("intake_insights"):
                insights = s["intake_insights"]
                # If cold_start is true, verify reason is present
                if insights.get("cold_start"):
                    assert "cold_start_reason" in insights
                    assert insights["cold_start_reason"]  # Not empty
                    print(f"Cold start staging: {s['id'][:8]}, reason: {insights['cold_start_reason']}")
                    return
        
        print("No cold-start staging records found (all may have BC history)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
