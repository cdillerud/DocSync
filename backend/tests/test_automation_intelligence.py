"""
Test Suite for Automation Intelligence Features (iteration_120)

Tests 4 new features:
1. Automation Confidence Scoring with weighted signals
2. Decision Explainability Layer with structured explanation objects
3. Reviewer Assist Engine with one-click suggestions
4. Automation Metrics Dashboard

Also verifies no regression on existing readiness endpoints.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test document ID (blocked doc with suggestions) from main agent context
TEST_DOC_ID = "1acf983b-a65b-423a-bfcd-8e0ee63fd25d"
NONEXISTENT_DOC_ID = "nonexistent-doc-xyz"


@pytest.fixture(scope="module")
def api():
    """Create requests session for API calls."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


# =============================================================================
# Feature 1: Automation Metrics Dashboard
# =============================================================================

class TestAutomationMetrics:
    """Test GET /api/automation/metrics endpoint."""

    def test_metrics_endpoint_returns_200(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ /api/automation/metrics returns 200")

    def test_metrics_contains_total_documents(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "total_documents" in data, "Missing total_documents"
        assert data["total_documents"] >= 0, "total_documents should be >= 0"
        print(f"✓ total_documents = {data['total_documents']}")

    def test_metrics_contains_rates(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        for rate in ["automation_rate", "review_rate", "blocked_rate"]:
            assert rate in data, f"Missing {rate}"
            assert 0 <= data[rate] <= 1, f"{rate} should be between 0 and 1"
        print(f"✓ Rates: automation={data['automation_rate']:.2%}, review={data['review_rate']:.2%}, blocked={data['blocked_rate']:.2%}")

    def test_metrics_contains_avg_confidence(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "avg_confidence" in data, "Missing avg_confidence"
        assert 0 <= data["avg_confidence"] <= 1, "avg_confidence should be between 0 and 1"
        print(f"✓ avg_confidence = {data['avg_confidence']:.4f}")

    def test_metrics_contains_confidence_distribution(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "confidence_distribution" in data, "Missing confidence_distribution"
        dist = data["confidence_distribution"]
        assert isinstance(dist, dict), "confidence_distribution should be a dict"
        print(f"✓ confidence_distribution has {len(dist)} buckets")

    def test_metrics_contains_signal_averages(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "signal_averages" in data, "Missing signal_averages"
        signals = data["signal_averages"]
        expected_signals = ["vendor_resolution", "entity_resolution", "extraction_quality", "transaction_graph", "policy_compliance"]
        for sig in expected_signals:
            assert sig in signals, f"Missing signal_average: {sig}"
        print(f"✓ signal_averages contains {len(signals)} signals")

    def test_metrics_contains_top_review_causes(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "top_review_causes" in data, "Missing top_review_causes"
        assert isinstance(data["top_review_causes"], list), "top_review_causes should be a list"
        print(f"✓ top_review_causes has {len(data['top_review_causes'])} items")

    def test_metrics_contains_top_blocking_reasons(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "top_blocking_reasons" in data, "Missing top_blocking_reasons"
        assert isinstance(data["top_blocking_reasons"], list), "top_blocking_reasons should be a list"
        print(f"✓ top_blocking_reasons has {len(data['top_blocking_reasons'])} items")

    def test_metrics_contains_thresholds(self, api):
        res = api.get(f"{BASE_URL}/api/automation/metrics")
        data = res.json()
        assert "thresholds" in data, "Missing thresholds"
        assert "auto_execute" in data["thresholds"], "Missing thresholds.auto_execute"
        assert "review" in data["thresholds"], "Missing thresholds.review"
        print(f"✓ thresholds: auto_execute={data['thresholds']['auto_execute']}, review={data['thresholds']['review']}")


# =============================================================================
# Feature 2: Batch Evaluate
# =============================================================================

class TestBatchEvaluate:
    """Test POST /api/automation/batch-evaluate endpoint."""

    def test_batch_evaluate_returns_200(self, api):
        res = api.post(f"{BASE_URL}/api/automation/batch-evaluate?limit=5")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ /api/automation/batch-evaluate returns 200")

    def test_batch_evaluate_returns_counts(self, api):
        res = api.post(f"{BASE_URL}/api/automation/batch-evaluate?limit=5")
        data = res.json()
        assert "total" in data, "Missing total"
        assert "processed" in data, "Missing processed"
        assert "errors" in data, "Missing errors"
        print(f"✓ batch-evaluate: total={data['total']}, processed={data['processed']}, errors={data['errors']}")


# =============================================================================
# Feature 3: Decision Explainability
# =============================================================================

class TestDecisionExplanation:
    """Test GET /api/documents/{id}/decision-explanation endpoint."""

    def test_decision_explanation_returns_200(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ /api/documents/{id}/decision-explanation returns 200")

    def test_decision_explanation_contains_decision(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "decision" in data, "Missing decision"
        assert data["decision"] in ["auto_draft", "auto_link", "auto_execute", "assisted_review", "review", "hold", "manual_review"], f"Unexpected decision: {data['decision']}"
        print(f"✓ decision = {data['decision']}")

    def test_decision_explanation_contains_confidence(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "confidence" in data, "Missing confidence"
        assert 0 <= data["confidence"] <= 1, "confidence should be between 0 and 1"
        print(f"✓ confidence = {data['confidence']}")

    def test_decision_explanation_contains_status(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "status" in data, "Missing status"
        print(f"✓ status = {data['status']}")

    def test_decision_explanation_contains_signals(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "signals" in data, "Missing signals"
        assert isinstance(data["signals"], dict), "signals should be a dict"
        print(f"✓ signals contains {len(data['signals'])} items")

    def test_decision_explanation_contains_supporting_evidence(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "supporting_evidence" in data, "Missing supporting_evidence"
        assert isinstance(data["supporting_evidence"], list), "supporting_evidence should be a list"
        print(f"✓ supporting_evidence has {len(data['supporting_evidence'])} items")

    def test_decision_explanation_contains_risk_flags(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/decision-explanation")
        data = res.json()
        assert "risk_flags" in data, "Missing risk_flags"
        assert isinstance(data["risk_flags"], list), "risk_flags should be a list"
        print(f"✓ risk_flags has {len(data['risk_flags'])} items")

    def test_decision_explanation_404_for_nonexistent(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{NONEXISTENT_DOC_ID}/decision-explanation")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("✓ Returns 404 for nonexistent document")


# =============================================================================
# Feature 4: Automation Confidence
# =============================================================================

class TestAutomationConfidence:
    """Test GET /api/documents/{id}/automation-confidence endpoint."""

    def test_automation_confidence_returns_200(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ /api/documents/{id}/automation-confidence returns 200")

    def test_automation_confidence_contains_score(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        data = res.json()
        assert "score" in data, "Missing score"
        assert 0 <= data["score"] <= 1, "score should be between 0 and 1"
        print(f"✓ score = {data['score']}")

    def test_automation_confidence_contains_signals_dict(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        data = res.json()
        assert "signals" in data, "Missing signals"
        signals = data["signals"]
        expected_signals = [
            "vendor_resolution_score",
            "entity_resolution_confidence",
            "extraction_confidence",
            "transaction_graph_strength",
            "policy_pass_score",
            "duplicate_risk_penalty"
        ]
        for sig in expected_signals:
            assert sig in signals, f"Missing signal: {sig}"
        print(f"✓ signals contains all {len(expected_signals)} expected signals")

    def test_automation_confidence_contains_weights(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        data = res.json()
        assert "weights" in data, "Missing weights"
        assert isinstance(data["weights"], dict), "weights should be a dict"
        print(f"✓ weights contains {len(data['weights'])} items")

    def test_automation_confidence_contains_thresholds(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        data = res.json()
        assert "thresholds" in data, "Missing thresholds"
        assert "auto_execute" in data["thresholds"], "Missing auto_execute threshold"
        assert "review" in data["thresholds"], "Missing review threshold"
        print(f"✓ thresholds = {data['thresholds']}")

    def test_automation_confidence_contains_recommended_action(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/automation-confidence")
        data = res.json()
        assert "recommended_action" in data, "Missing recommended_action"
        assert data["recommended_action"] in ["auto_execute", "assisted_review", "manual_review"], f"Unexpected action: {data['recommended_action']}"
        print(f"✓ recommended_action = {data['recommended_action']}")

    def test_automation_confidence_404_for_nonexistent(self, api):
        res = api.get(f"{BASE_URL}/api/documents/{NONEXISTENT_DOC_ID}/automation-confidence")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("✓ Returns 404 for nonexistent document")


# =============================================================================
# Feature 5: Reviewer Assist
# =============================================================================

class TestReviewerAssist:
    """Test POST /api/documents/{id}/review-assist endpoint."""

    def test_review_assist_returns_200(self, api):
        res = api.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/review-assist")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ /api/documents/{id}/review-assist returns 200")

    def test_review_assist_returns_doc_id(self, api):
        res = api.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/review-assist")
        data = res.json()
        assert "doc_id" in data, "Missing doc_id"
        assert data["doc_id"] == TEST_DOC_ID, f"doc_id mismatch: {data['doc_id']}"
        print(f"✓ doc_id = {data['doc_id']}")

    def test_review_assist_returns_suggested_actions(self, api):
        res = api.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/review-assist")
        data = res.json()
        assert "suggested_actions" in data, "Missing suggested_actions"
        assert isinstance(data["suggested_actions"], list), "suggested_actions should be a list"
        print(f"✓ suggested_actions has {len(data['suggested_actions'])} suggestions")

    def test_review_assist_suggestion_structure(self, api):
        res = api.post(f"{BASE_URL}/api/documents/{TEST_DOC_ID}/review-assist")
        data = res.json()
        if data["suggested_actions"]:
            suggestion = data["suggested_actions"][0]
            assert "action" in suggestion, "Suggestion missing action"
            assert "field" in suggestion, "Suggestion missing field"
            assert "suggested_value" in suggestion, "Suggestion missing suggested_value"
            assert "confidence" in suggestion, "Suggestion missing confidence"
            assert "reason" in suggestion, "Suggestion missing reason"
            print(f"✓ First suggestion: action={suggestion['action']}, field={suggestion['field']}, confidence={suggestion['confidence']}")
        else:
            print("✓ No suggestions available (document may be ready)")

    def test_review_assist_404_for_nonexistent(self, api):
        res = api.post(f"{BASE_URL}/api/documents/{NONEXISTENT_DOC_ID}/review-assist")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("✓ Returns 404 for nonexistent document")


# =============================================================================
# Regression Tests: Readiness Metrics
# =============================================================================

class TestReadinessMetricsRegression:
    """Regression test: GET /api/readiness/metrics should still work."""

    def test_readiness_metrics_returns_200(self, api):
        res = api.get(f"{BASE_URL}/api/readiness/metrics")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ [REGRESSION] /api/readiness/metrics returns 200")

    def test_readiness_metrics_contains_expected_fields(self, api):
        res = api.get(f"{BASE_URL}/api/readiness/metrics")
        data = res.json()
        expected_fields = ["total_documents", "by_status", "by_action"]
        for field in expected_fields:
            assert field in data, f"Missing {field}"
        print(f"✓ [REGRESSION] readiness/metrics contains total_documents={data['total_documents']}, by_status has {len(data['by_status'])} statuses")


# =============================================================================
# Regression Tests: Workflow Intelligence (readiness_summary)
# =============================================================================

class TestWorkflowIntelligenceRegression:
    """Regression test: GET /api/dashboard/workflow-intelligence should include readiness_summary."""

    def test_workflow_intelligence_returns_200(self, api):
        res = api.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        print("✓ [REGRESSION] /api/dashboard/workflow-intelligence returns 200")

    def test_workflow_intelligence_contains_readiness_summary(self, api):
        res = api.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = res.json()
        assert "readiness_summary" in data, "Missing readiness_summary"
        rs = data["readiness_summary"]
        assert "by_status" in rs, "readiness_summary missing by_status"
        print(f"✓ [REGRESSION] workflow-intelligence includes readiness_summary with by_status={rs['by_status']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
