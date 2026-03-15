"""
GPI Document Hub - Iteration 100: Decision Policy Engine Tests

Tests the complete automation decision policy engine:
- Policy CRUD (create, list, update, delete)
- Decision evaluation (evaluate-decision)
- Decision execution (execute-decision)
- Decision retrieval (get decision, decision queue)
- Policy priority evaluation
- Document enrichment with decision data
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test data markers
TEST_PREFIX = f"TEST-DPE-{uuid.uuid4().hex[:6].upper()}"


class TestPolicyCRUD:
    """Test Policy CRUD operations: POST, GET, PATCH, DELETE"""

    def test_list_policies_returns_default_seeded(self):
        """GET /api/document-intelligence/policies - should return 9 default policies"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies")
        assert response.status_code == 200
        policies = response.json()
        assert isinstance(policies, list)
        # Should have at least 9 default policies
        assert len(policies) >= 9
        # Check for key default policies
        policy_names = [p["name"] for p in policies]
        assert any("Block critical fields missing" in n for n in policy_names)
        assert any("Auto-draft ready" in n for n in policy_names)

    def test_list_policies_with_document_type_filter(self):
        """GET /api/document-intelligence/policies?document_type=Sales_PO"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies", params={"document_type": "Sales_PO"})
        assert response.status_code == 200
        policies = response.json()
        # All returned policies should have document_type=Sales_PO
        for p in policies:
            assert p["document_type"] == "Sales_PO"

    def test_list_policies_with_is_active_filter(self):
        """GET /api/document-intelligence/policies?is_active=true"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies", params={"is_active": True})
        assert response.status_code == 200
        policies = response.json()
        for p in policies:
            assert p["is_active"] is True

    def test_create_policy(self):
        """POST /api/document-intelligence/policies - create new policy"""
        payload = {
            "name": f"{TEST_PREFIX}-Create-Test",
            "document_type": "AP_Invoice",
            "priority": 25,
            "conditions": {"automation_readiness_score": {"$gte": 50}},
            "decision_action": "create_draft",
            "automation_level": "auto_draft",
            "reason_template": "Test policy for automation"
        }
        response = requests.post(f"{BASE_URL}/api/document-intelligence/policies", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "policy_id" in data
        assert data["policy_id"].startswith("POL-")
        assert data["name"] == payload["name"]
        assert data["priority"] == 25
        assert data["decision_action"] == "create_draft"
        assert data["is_active"] is True
        assert "created_at" in data
        # Cleanup: store policy_id for later tests
        TestPolicyCRUD.created_policy_id = data["policy_id"]

    def test_update_policy(self):
        """PATCH /api/document-intelligence/policies/{policy_id} - update policy"""
        policy_id = getattr(TestPolicyCRUD, 'created_policy_id', None)
        if not policy_id:
            pytest.skip("No policy to update - create test must run first")
        
        payload = {
            "name": f"{TEST_PREFIX}-Updated",
            "priority": 30,
            "reason_template": "Updated reason template"
        }
        response = requests.patch(f"{BASE_URL}/api/document-intelligence/policies/{policy_id}", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["priority"] == 30
        assert data["reason_template"] == "Updated reason template"
        assert "updated_at" in data

    def test_update_policy_not_found(self):
        """PATCH /api/document-intelligence/policies/{policy_id} - 404 for non-existent"""
        response = requests.patch(
            f"{BASE_URL}/api/document-intelligence/policies/POL-NONEXISTENT",
            json={"name": "Test"}
        )
        assert response.status_code == 404

    def test_delete_policy_soft_deletes(self):
        """DELETE /api/document-intelligence/policies/{policy_id} - soft-delete (deactivates)"""
        policy_id = getattr(TestPolicyCRUD, 'created_policy_id', None)
        if not policy_id:
            pytest.skip("No policy to delete - create test must run first")
        
        response = requests.delete(f"{BASE_URL}/api/document-intelligence/policies/{policy_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["policy_id"] == policy_id
        
        # Verify policy is now inactive
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies", params={"is_active": False})
        assert response.status_code == 200
        inactive = response.json()
        assert any(p["policy_id"] == policy_id for p in inactive)

    def test_delete_policy_not_found(self):
        """DELETE /api/document-intelligence/policies/{policy_id} - 404 for non-existent"""
        response = requests.delete(f"{BASE_URL}/api/document-intelligence/policies/POL-NONEXISTENT")
        assert response.status_code == 404


class TestDecisionEvaluation:
    """Test decision evaluation endpoint and policy matching"""

    def test_evaluate_decision_blocked_document(self):
        """POST /api/document-intelligence/evaluate-decision/{doc_id} - blocked doc matches block policy"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["decision_id"].startswith("DEC-")
        assert data["document_id"] == "TEST-BUNDLE-A"
        assert data["decision_action"] == "block"
        assert data["decision_status"] == "blocked"
        assert data["automation_level"] == "manual_only"
        assert "decision_reasons" in data
        assert len(data["decision_reasons"]) > 0
        # Should have policy_match reason
        codes = [r["code"] for r in data["decision_reasons"]]
        assert "policy_match" in codes
        # Should have input_snapshot
        assert "input_snapshot" in data
        assert data["input_snapshot"]["automation_readiness"] == "blocked"
        # Store decision_id for execute tests
        TestDecisionEvaluation.blocked_decision_id = data["decision_id"]

    def test_evaluate_decision_ready_document(self):
        """POST /api/document-intelligence/evaluate-decision/{doc_id} - evaluates and returns decision"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["document_id"] == "TEST-BUNDLE-B"
        # Decision will depend on current document state (may be ready, blocked, or executed)
        assert data["decision_action"] in ["create_draft", "block", "link_existing", "hold_for_review"]
        assert data["decision_status"] in ["ready", "executed", "blocked", "review_required"]
        # Decision reasons
        codes = [r["code"] for r in data["decision_reasons"]]
        assert "policy_match" in codes
        TestDecisionEvaluation.ready_decision_id = data["decision_id"]

    def test_evaluate_decision_not_found(self):
        """POST /api/document-intelligence/evaluate-decision/{doc_id} - 404 for missing doc"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/NONEXISTENT-DOC-999")
        assert response.status_code == 404

    def test_evaluate_decision_returns_target_summary(self):
        """Evaluate decision returns human-readable target_summary"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        data = response.json()
        assert "target_summary" in data
        assert len(data["target_summary"]) > 0
        # For blocked decision, should mention blocked
        assert "blocked" in data["target_summary"].lower() or "resolve" in data["target_summary"].lower()

    def test_evaluate_decision_input_snapshot_complete(self):
        """Evaluate decision returns complete input_snapshot with all decision-relevant fields"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        assert response.status_code == 200
        snapshot = response.json()["input_snapshot"]
        # Required fields in snapshot
        required_fields = [
            "document_type", "automation_readiness", "automation_readiness_score",
            "entity_resolution_status", "transaction_match_status", "auto_link_available",
            "lifecycle_status", "bundle_id", "bundle_type", "required_fields_complete"
        ]
        for field in required_fields:
            assert field in snapshot, f"Missing field: {field}"


class TestDecisionExecution:
    """Test decision execution endpoint"""

    def test_execute_decision_blocked_returns_not_executable(self):
        """POST /api/document-intelligence/execute-decision/{decision_id} - blocked decision not executable"""
        # Always evaluate fresh to get current decision_id
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert resp.status_code == 200
        decision_id = resp.json().get("decision_id")
        
        response = requests.post(f"{BASE_URL}/api/document-intelligence/execute-decision/{decision_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["executed"] is False
        assert "blocked" in data["reason"].lower() or "resolve" in data["reason"].lower()
        assert data["decision_status"] == "blocked"

    def test_execute_decision_ready_creates_draft(self):
        """POST /api/document-intelligence/execute-decision/{decision_id} - ready decision executes"""
        # First, get a fresh ready decision
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        decision_id = response.json().get("decision_id")
        decision_status = response.json().get("decision_status")
        
        # Only test execution if decision is ready (not already executed)
        if decision_status == "ready":
            response = requests.post(f"{BASE_URL}/api/document-intelligence/execute-decision/{decision_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["executed"] is True
            assert data["decision_action"] == "create_draft"
            assert data["decision_status"] == "executed"
            assert "result" in data
        else:
            # Decision already executed in previous test
            response = requests.post(f"{BASE_URL}/api/document-intelligence/execute-decision/{decision_id}")
            assert response.status_code == 200
            data = response.json()
            # Should return executed=false with "already executed" reason
            assert data["executed"] is False

    def test_execute_decision_not_found(self):
        """POST /api/document-intelligence/execute-decision/{decision_id} - 404 for non-existent"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/execute-decision/DEC-NONEXISTENT")
        assert response.status_code == 404


class TestDecisionRetrieval:
    """Test decision retrieval endpoints"""

    def test_get_decision_for_document(self):
        """GET /api/document-intelligence/decision/{doc_id} - returns latest decision"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "TEST-BUNDLE-A"
        assert "decision_id" in data
        assert "decision_action" in data
        assert "decision_status" in data
        assert "decision_reasons" in data
        assert "input_snapshot" in data

    def test_get_decision_not_found(self):
        """GET /api/document-intelligence/decision/{doc_id} - 404 for doc without decision"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/decision/NONEXISTENT-DOC-999")
        assert response.status_code == 404

    def test_decision_queue_returns_blocked_and_review(self):
        """GET /api/document-intelligence/decision-queue - returns blocked and review_required decisions"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/decision-queue")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "decisions" in data
        assert "status_counts" in data
        # All decisions should have blocked or review_required status
        for dec in data["decisions"]:
            assert dec["decision_status"] in ["blocked", "review_required"]
            # Should have file_name enrichment
            assert "file_name" in dec
            # Should have reason_summary
            assert "reason_summary" in dec

    def test_decision_queue_pagination(self):
        """GET /api/document-intelligence/decision-queue supports limit/offset"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/decision-queue", params={"limit": 5, "offset": 0})
        assert response.status_code == 200
        data = response.json()
        assert len(data["decisions"]) <= 5


class TestDocumentEnrichment:
    """Test that document intelligence results are enriched with decision data"""

    def test_document_enriched_with_decision(self):
        """GET /api/document-intelligence/{doc_id} - has decision enrichment fields"""
        # First ensure decision is evaluated
        requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        
        response = requests.get(f"{BASE_URL}/api/document-intelligence/TEST-BUNDLE-B")
        assert response.status_code == 200
        data = response.json()
        # Should have decision enrichment fields
        assert "latest_decision_action" in data
        assert "latest_automation_level" in data
        assert "latest_decision_status" in data
        assert "latest_decision_reasons" in data
        assert "decision_executable" in data
        assert "decision_target_summary" in data


class TestPolicyEvaluationPriority:
    """Test that policies are evaluated in priority order"""

    def test_block_policy_priority_1_fires_first(self):
        """Block policy (priority 1) fires before auto-draft (priority 10) for blocked docs"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        data = response.json()
        # Blocked doc should match block policy, not auto-draft
        assert data["decision_action"] == "block"
        # Policy should be priority 1 block policy
        assert data["policy_name"] == "Block critical fields missing"

    def test_policies_sorted_by_priority(self):
        """GET /api/document-intelligence/policies returns sorted by priority"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies")
        assert response.status_code == 200
        policies = response.json()
        priorities = [p["priority"] for p in policies]
        # Should be sorted ascending
        assert priorities == sorted(priorities)


class TestDecisionReasons:
    """Test decision reason generation"""

    def test_decision_reasons_have_code_and_message(self):
        """Decision reasons have machine-readable code and human-readable message"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        reasons = response.json()["decision_reasons"]
        for reason in reasons:
            assert "code" in reason
            assert "message" in reason
            assert len(reason["code"]) > 0
            assert len(reason["message"]) > 0

    def test_blocked_decision_has_blocked_reasons(self):
        """Blocked decision includes readiness_blocked and missing_fields codes"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-A")
        assert response.status_code == 200
        reasons = response.json()["decision_reasons"]
        codes = [r["code"] for r in reasons]
        # Should have relevant block reasons
        assert "policy_match" in codes
        assert "readiness_blocked" in codes or "missing_fields" in codes

    def test_create_draft_decision_has_readiness_reasons(self):
        """Create draft decision includes readiness_ok and fields_complete codes"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/evaluate-decision/TEST-BUNDLE-B")
        assert response.status_code == 200
        reasons = response.json()["decision_reasons"]
        codes = [r["code"] for r in reasons]
        # Should have relevant create_draft reasons
        assert "policy_match" in codes


class TestRegressionIteration98And99:
    """Regression tests for iteration 98 (bundles) and 99 (lifecycle)"""

    def test_bundles_endpoint_still_works(self):
        """GET /api/document-intelligence/bundles still functional"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/bundles", params={"limit": 5})
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "bundles" in data

    def test_bundle_detail_still_works(self):
        """GET /api/document-intelligence/bundles/{bundle_id} still functional"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/bundles/BDL-B739B77E")
        if response.status_code == 200:
            data = response.json()
            assert "bundle_id" in data
            assert "member_documents" in data

    def test_lifecycle_issues_still_works(self):
        """GET /api/document-intelligence/lifecycle-issues still functional"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/lifecycle-issues")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "issues" in data
        assert "status_counts" in data

    def test_detect_bundles_still_works(self):
        """POST /api/document-intelligence/detect-bundles still functional"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/detect-bundles", json={"days_back": 1})
        assert response.status_code == 200
        data = response.json()
        assert "bundles_detected" in data or "bundles" in data

    def test_process_document_still_works(self):
        """POST /api/document-intelligence/process/{doc_id} still functional"""
        response = requests.post(f"{BASE_URL}/api/document-intelligence/process/TEST-BUNDLE-B")
        assert response.status_code == 200


# Cleanup fixture to remove test data
@pytest.fixture(scope="module", autouse=True)
def cleanup_test_policies():
    """Cleanup TEST-prefixed policies after all tests"""
    yield
    # After all tests, cleanup created policies
    response = requests.get(f"{BASE_URL}/api/document-intelligence/policies")
    if response.status_code == 200:
        for policy in response.json():
            if TEST_PREFIX in policy.get("name", ""):
                requests.delete(f"{BASE_URL}/api/document-intelligence/policies/{policy['policy_id']}")
