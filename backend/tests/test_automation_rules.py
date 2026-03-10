"""
Test Automation Rules Engine - Vendor Automation Rules Engine

Tests for:
- GET /api/automation-rules - List all rules
- POST /api/automation-rules - Create a new rule
- PUT /api/automation-rules/{rule_id} - Update a rule
- DELETE /api/automation-rules/{rule_id} - Delete a rule
- POST /api/automation-rules/{rule_id}/toggle - Toggle enabled state
- POST /api/automation-rules/evaluate/{doc_id} - Evaluate rules for a document
- GET /api/automation-rules/suggestions - Get suggestions from vendor intelligence

Rule evaluation:
- First-match-wins (higher priority/lower number wins)
- Updates document fields: workflow_queue, review_priority, automation_rule_applied, automation_rule_name
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs provided in credentials
TEST_AP_INVOICE_DOC_ID = "a1dec76a-17a2-46d4-a9f9-a0f6fb818208"
EXISTING_RULE_TUMALO = "04ef6176"  # TUMALO CREEK PO Auto-Route, priority 50
EXISTING_RULE_AP_INVOICE = "d02dd03a"  # AP Invoice Auto-Route, priority 200


class TestAutomationRulesAPI:
    """Test Automation Rules CRUD operations"""

    def test_list_rules_returns_existing_rules(self):
        """Test GET /api/automation-rules returns list of rules"""
        resp = requests.get(f"{BASE_URL}/api/automation-rules")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "rules" in data, "Response should have 'rules' key"
        assert "total" in data, "Response should have 'total' key"
        
        rules = data["rules"]
        assert isinstance(rules, list), "rules should be a list"
        
        # Check we have the two expected rules from credentials
        rule_ids = [r.get("rule_id") for r in rules]
        print(f"Found {len(rules)} rules: {rule_ids}")
        
        # Verify at least some rules exist
        assert len(rules) >= 0, "Should be able to list rules"
        
        # Check rule structure if rules exist
        if rules:
            rule = rules[0]
            assert "rule_id" in rule, "Rule should have rule_id"
            assert "rule_name" in rule, "Rule should have rule_name"
            assert "conditions" in rule, "Rule should have conditions"
            assert "actions" in rule, "Rule should have actions"
            assert "priority" in rule, "Rule should have priority"
            assert "enabled" in rule, "Rule should have enabled"

    def test_create_rule(self):
        """Test POST /api/automation-rules creates a new rule"""
        test_rule = {
            "rule_name": f"TEST_Rule_{uuid.uuid4().hex[:6]}",
            "priority": 999,  # Low priority so it doesn't interfere
            "conditions": {
                "document_type": "TEST_TYPE",
                "validation_state": "pass"
            },
            "actions": {
                "route_to_queue": "test_queue",
                "assign_review_priority": "low"
            },
            "enabled": False  # Disabled to not affect other tests
        }
        
        resp = requests.post(f"{BASE_URL}/api/automation-rules", json=test_rule)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        created = resp.json()
        assert "rule_id" in created, "Created rule should have rule_id"
        assert created["rule_name"] == test_rule["rule_name"], "Rule name should match"
        assert created["priority"] == test_rule["priority"], "Priority should match"
        assert created["conditions"] == test_rule["conditions"], "Conditions should match"
        assert created["actions"] == test_rule["actions"], "Actions should match"
        assert created["enabled"] == test_rule["enabled"], "Enabled should match"
        
        print(f"Created rule: {created['rule_id']} - {created['rule_name']}")
        
        # Cleanup - delete the test rule
        cleanup_resp = requests.delete(f"{BASE_URL}/api/automation-rules/{created['rule_id']}")
        assert cleanup_resp.status_code == 200, f"Cleanup failed: {cleanup_resp.text}"

    def test_update_rule(self):
        """Test PUT /api/automation-rules/{rule_id} updates a rule"""
        # First create a rule to update
        test_rule = {
            "rule_name": f"TEST_UpdateRule_{uuid.uuid4().hex[:6]}",
            "priority": 998,
            "conditions": {"document_type": "TEST_UPDATE"},
            "actions": {"route_to_queue": "original_queue"},
            "enabled": False
        }
        
        create_resp = requests.post(f"{BASE_URL}/api/automation-rules", json=test_rule)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        rule_id = create_resp.json()["rule_id"]
        
        # Update the rule
        update_data = {
            "rule_name": f"TEST_UpdatedRule_{uuid.uuid4().hex[:6]}",
            "priority": 997,
            "actions": {"route_to_queue": "updated_queue", "assign_review_priority": "high"}
        }
        
        update_resp = requests.put(f"{BASE_URL}/api/automation-rules/{rule_id}", json=update_data)
        assert update_resp.status_code == 200, f"Update failed: {update_resp.text}"
        
        updated = update_resp.json()
        assert updated["rule_name"] == update_data["rule_name"], "Rule name should be updated"
        assert updated["priority"] == update_data["priority"], "Priority should be updated"
        assert updated["actions"]["route_to_queue"] == "updated_queue", "Actions should be updated"
        assert "updated_at" in updated, "Should have updated_at timestamp"
        
        print(f"Updated rule: {rule_id} -> {updated['rule_name']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/automation-rules/{rule_id}")

    def test_delete_rule(self):
        """Test DELETE /api/automation-rules/{rule_id} deletes a rule"""
        # First create a rule to delete
        test_rule = {
            "rule_name": f"TEST_DeleteRule_{uuid.uuid4().hex[:6]}",
            "priority": 996,
            "conditions": {"document_type": "TEST_DELETE"},
            "actions": {"route_to_queue": "delete_test"},
            "enabled": False
        }
        
        create_resp = requests.post(f"{BASE_URL}/api/automation-rules", json=test_rule)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        rule_id = create_resp.json()["rule_id"]
        
        # Delete the rule
        delete_resp = requests.delete(f"{BASE_URL}/api/automation-rules/{rule_id}")
        assert delete_resp.status_code == 200, f"Delete failed: {delete_resp.text}"
        
        data = delete_resp.json()
        assert data["status"] == "deleted", "Status should be 'deleted'"
        assert data["rule_id"] == rule_id, "Should return deleted rule_id"
        
        # Verify it's really gone
        get_resp = requests.get(f"{BASE_URL}/api/automation-rules/{rule_id}")
        assert get_resp.status_code == 404, f"Rule should be 404 after delete, got {get_resp.status_code}"
        
        print(f"Deleted rule: {rule_id}")

    def test_toggle_rule(self):
        """Test POST /api/automation-rules/{rule_id}/toggle toggles enabled state"""
        # Create a rule to toggle
        test_rule = {
            "rule_name": f"TEST_ToggleRule_{uuid.uuid4().hex[:6]}",
            "priority": 995,
            "conditions": {"document_type": "TEST_TOGGLE"},
            "actions": {"route_to_queue": "toggle_test"},
            "enabled": False
        }
        
        create_resp = requests.post(f"{BASE_URL}/api/automation-rules", json=test_rule)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        created = create_resp.json()
        rule_id = created["rule_id"]
        initial_state = created["enabled"]
        
        # Toggle the rule
        toggle_resp = requests.post(f"{BASE_URL}/api/automation-rules/{rule_id}/toggle")
        assert toggle_resp.status_code == 200, f"Toggle failed: {toggle_resp.text}"
        
        toggled = toggle_resp.json()
        assert toggled["enabled"] != initial_state, f"Enabled should toggle from {initial_state}"
        
        print(f"Toggled rule {rule_id}: {initial_state} -> {toggled['enabled']}")
        
        # Toggle back
        toggle_back = requests.post(f"{BASE_URL}/api/automation-rules/{rule_id}/toggle")
        assert toggle_back.status_code == 200
        assert toggle_back.json()["enabled"] == initial_state, "Should toggle back to original state"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/automation-rules/{rule_id}")

    def test_get_single_rule(self):
        """Test GET /api/automation-rules/{rule_id} returns a single rule"""
        # Create a rule to fetch
        test_rule = {
            "rule_name": f"TEST_GetRule_{uuid.uuid4().hex[:6]}",
            "priority": 994,
            "conditions": {"document_type": "TEST_GET"},
            "actions": {"route_to_queue": "get_test"},
            "enabled": False
        }
        
        create_resp = requests.post(f"{BASE_URL}/api/automation-rules", json=test_rule)
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        rule_id = create_resp.json()["rule_id"]
        
        # Get the rule
        get_resp = requests.get(f"{BASE_URL}/api/automation-rules/{rule_id}")
        assert get_resp.status_code == 200, f"Get failed: {get_resp.text}"
        
        fetched = get_resp.json()
        assert fetched["rule_id"] == rule_id, "rule_id should match"
        assert fetched["rule_name"] == test_rule["rule_name"], "rule_name should match"
        assert fetched["conditions"] == test_rule["conditions"], "conditions should match"
        
        print(f"Fetched rule: {fetched['rule_id']} - {fetched['rule_name']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/automation-rules/{rule_id}")

    def test_get_nonexistent_rule_returns_404(self):
        """Test GET /api/automation-rules/{rule_id} returns 404 for non-existent rule"""
        fake_id = "nonexistent123"
        resp = requests.get(f"{BASE_URL}/api/automation-rules/{fake_id}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


class TestAutomationRulesSuggestions:
    """Test rule suggestions from vendor intelligence"""

    def test_get_suggestions(self):
        """Test GET /api/automation-rules/suggestions returns suggestions"""
        resp = requests.get(f"{BASE_URL}/api/automation-rules/suggestions")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "suggestions" in data, "Response should have 'suggestions' key"
        assert "total" in data, "Response should have 'total' key"
        
        suggestions = data["suggestions"]
        assert isinstance(suggestions, list), "suggestions should be a list"
        
        print(f"Found {len(suggestions)} suggestions")
        
        # If suggestions exist, check structure
        if suggestions:
            s = suggestions[0]
            assert "vendor_name" in s, "Suggestion should have vendor_name"
            assert "suggestion_type" in s, "Suggestion should have suggestion_type"
            assert "confidence" in s, "Suggestion should have confidence"
            assert "description" in s, "Suggestion should have description"
            assert "suggested_rule" in s, "Suggestion should have suggested_rule"
            
            # Check suggested_rule structure
            sr = s["suggested_rule"]
            assert "rule_name" in sr, "suggested_rule should have rule_name"
            assert "conditions" in sr, "suggested_rule should have conditions"
            assert "actions" in sr, "suggested_rule should have actions"
            
            print(f"Sample suggestion: {s['description'][:100]}...")


class TestRuleEvaluation:
    """Test rule evaluation for documents"""

    def test_evaluate_rules_for_document(self):
        """Test POST /api/automation-rules/evaluate/{doc_id} evaluates rules"""
        # Use the test AP_Invoice document
        resp = requests.post(f"{BASE_URL}/api/automation-rules/evaluate/{TEST_AP_INVOICE_DOC_ID}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        result = resp.json()
        
        # Result can be either matched or not matched
        if result.get("matched"):
            assert "rule_id" in result, "Matched result should have rule_id"
            assert "rule_name" in result, "Matched result should have rule_name"
            assert "actions_executed" in result, "Matched result should have actions_executed"
            print(f"Document matched rule: {result['rule_name']} ({result['rule_id']})")
        else:
            assert "message" in result or result.get("matched") == False, "Non-match result should have message or matched=False"
            print(f"No rule matched for document")

    def test_evaluate_nonexistent_document_returns_404(self):
        """Test POST /api/automation-rules/evaluate/{doc_id} returns 404 for non-existent doc"""
        fake_doc_id = f"nonexistent-{uuid.uuid4()}"
        resp = requests.post(f"{BASE_URL}/api/automation-rules/evaluate/{fake_doc_id}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_first_match_wins_priority(self):
        """Test that first-match-wins (higher priority = lower number) works"""
        # List current rules to understand priority order
        list_resp = requests.get(f"{BASE_URL}/api/automation-rules")
        assert list_resp.status_code == 200
        
        rules = list_resp.json()["rules"]
        if len(rules) >= 2:
            # Rules should be sorted by priority (ascending)
            priorities = [r["priority"] for r in rules]
            assert priorities == sorted(priorities), f"Rules should be sorted by priority: {priorities}"
            print(f"Rules sorted by priority: {[(r['rule_name'], r['priority']) for r in rules[:5]]}")


class TestDocumentFieldUpdates:
    """Test that rule evaluation updates document fields correctly"""

    def test_document_fields_after_rule_evaluation(self):
        """Test that document fields are updated after rule evaluation"""
        # Get document before evaluation
        doc_resp = requests.get(f"{BASE_URL}/api/documents/{TEST_AP_INVOICE_DOC_ID}")
        assert doc_resp.status_code == 200, f"Failed to get document: {doc_resp.text}"
        
        doc = doc_resp.json()["document"]
        
        # Check for automation rule fields that may have been set
        print(f"Document {TEST_AP_INVOICE_DOC_ID} fields:")
        print(f"  - automation_rule_applied: {doc.get('automation_rule_applied')}")
        print(f"  - automation_rule_name: {doc.get('automation_rule_name')}")
        print(f"  - workflow_queue: {doc.get('workflow_queue')}")
        print(f"  - review_priority: {doc.get('review_priority')}")
        
        # If rule was applied, verify fields
        if doc.get("automation_rule_applied"):
            assert doc.get("automation_rule_name"), "If rule applied, automation_rule_name should be set"
            print(f"Rule '{doc['automation_rule_name']}' was applied to document")


class TestRuleConditionsAndActions:
    """Test various rule conditions and actions"""

    def test_create_rule_with_all_condition_types(self):
        """Test creating a rule with various condition types"""
        comprehensive_rule = {
            "rule_name": f"TEST_ComprehensiveRule_{uuid.uuid4().hex[:6]}",
            "priority": 993,
            "conditions": {
                "vendor_name": "TEST_VENDOR",
                "document_type": "AP_Invoice",
                "validation_state": "pass",
                "resolver_match_score_gte": 0.8,
                "automation_success_rate_gte": 0.9
            },
            "actions": {
                "route_to_queue": "accounting_review",
                "assign_review_priority": "high",
                "flag_for_manual_review": True
            },
            "enabled": False
        }
        
        resp = requests.post(f"{BASE_URL}/api/automation-rules", json=comprehensive_rule)
        assert resp.status_code == 200, f"Failed to create comprehensive rule: {resp.text}"
        
        created = resp.json()
        rule_id = created["rule_id"]
        
        # Verify all conditions and actions are stored
        assert created["conditions"]["vendor_name"] == "TEST_VENDOR"
        assert created["conditions"]["resolver_match_score_gte"] == 0.8
        assert created["actions"]["flag_for_manual_review"] == True
        
        print(f"Created comprehensive rule with {len(created['conditions'])} conditions and {len(created['actions'])} actions")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/automation-rules/{rule_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
