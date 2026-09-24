"""
Test Suite for Inbox Cleanup Feature - Iteration 197

Tests the critical readiness endpoints for the inbox cleanup feature:
1. GET /api/readiness/inbox-diagnostic - Preview what cleanup would do
2. POST /api/readiness/sync-status - Force cleanup using 7 rules
3. POST /api/readiness/reevaluate-all - Re-evaluate all documents
4. GET /api/readiness/automation-rate - Automation rate metrics
5. GET /api/readiness/metrics - Readiness analytics

The force cleanup endpoint uses 7 rules to move documents from Inbox:
- Rule 1: Has bc_purchase_invoice_no → Completed
- Rule 2: draft_review_status == approved → Completed
- Rule 3: auto_draft_created == true → Completed
- Rule 4: readiness.status is ready + no blockers → Completed
- Rule 5: Vendor resolved + fields complete → Completed
- Rule 6: ReadyForPost status → Completed
- Rule 7: Readiness ready catchall → Completed
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestInboxDiagnostic:
    """Tests for GET /api/readiness/inbox-diagnostic endpoint"""
    
    def test_inbox_diagnostic_returns_200(self):
        """Test that inbox-diagnostic endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: inbox-diagnostic returns 200")
    
    def test_inbox_diagnostic_response_structure(self):
        """Test that inbox-diagnostic returns correct JSON structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify required fields exist
        assert "total_in_inbox" in data, "Missing 'total_in_inbox' field"
        assert "would_fix" in data, "Missing 'would_fix' field"
        assert "would_remain_after_cleanup" in data, "Missing 'would_remain_after_cleanup' field"
        assert "breakdown" in data, "Missing 'breakdown' field"
        assert "action" in data, "Missing 'action' field"
        
        # Verify data types
        assert isinstance(data["total_in_inbox"], int), "total_in_inbox should be int"
        assert isinstance(data["would_fix"], int), "would_fix should be int"
        assert isinstance(data["would_remain_after_cleanup"], int), "would_remain_after_cleanup should be int"
        assert isinstance(data["breakdown"], list), "breakdown should be list"
        
        print(f"PASS: inbox-diagnostic response structure is correct")
        print(f"  - total_in_inbox: {data['total_in_inbox']}")
        print(f"  - would_fix: {data['would_fix']}")
        print(f"  - would_remain_after_cleanup: {data['would_remain_after_cleanup']}")
        print(f"  - breakdown items: {len(data['breakdown'])}")
    
    def test_inbox_diagnostic_breakdown_structure(self):
        """Test that breakdown items have correct structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200
        
        data = response.json()
        breakdown = data.get("breakdown", [])
        
        if len(breakdown) > 0:
            item = breakdown[0]
            # Check expected fields in breakdown items
            expected_fields = ["status", "readiness_status", "count", "cleanup_rule"]
            for field in expected_fields:
                assert field in item, f"Missing '{field}' in breakdown item"
            
            assert isinstance(item["count"], int), "count should be int"
            print(f"PASS: breakdown item structure is correct")
            print(f"  - Sample item: status={item.get('status')}, readiness={item.get('readiness_status')}, count={item.get('count')}")
        else:
            print(f"PASS: breakdown is empty (no stuck docs)")
    
    def test_inbox_diagnostic_math_consistency(self):
        """Test that would_fix + would_remain = total_in_inbox"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200
        
        data = response.json()
        total = data["total_in_inbox"]
        would_fix = data["would_fix"]
        would_remain = data["would_remain_after_cleanup"]
        
        assert would_fix + would_remain == total, \
            f"Math inconsistency: {would_fix} + {would_remain} != {total}"
        print(f"PASS: Math is consistent: {would_fix} + {would_remain} = {total}")


class TestReadinessMetrics:
    """Tests for GET /api/readiness/metrics endpoint"""
    
    def test_metrics_returns_200(self):
        """Test that metrics endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: metrics returns 200")
    
    def test_metrics_response_structure(self):
        """Test that metrics returns correct JSON structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify required fields
        required_fields = [
            "total_documents",
            "by_status",
            "by_action",
            "top_blocking_reasons",
            "top_warning_reasons"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing '{field}' field"
        
        # Verify data types
        assert isinstance(data["total_documents"], int), "total_documents should be int"
        assert isinstance(data["by_status"], dict), "by_status should be dict"
        assert isinstance(data["by_action"], dict), "by_action should be dict"
        assert isinstance(data["top_blocking_reasons"], list), "top_blocking_reasons should be list"
        assert isinstance(data["top_warning_reasons"], list), "top_warning_reasons should be list"
        
        print(f"PASS: metrics response structure is correct")
        print(f"  - total_documents: {data['total_documents']}")
        print(f"  - by_status: {data['by_status']}")
        print(f"  - by_action: {data['by_action']}")
        print(f"  - top_blocking_reasons: {len(data['top_blocking_reasons'])} items")
        print(f"  - top_warning_reasons: {len(data['top_warning_reasons'])} items")
    
    def test_metrics_blocking_reasons_structure(self):
        """Test that blocking reasons have correct structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200
        
        data = response.json()
        blocking_reasons = data.get("top_blocking_reasons", [])
        
        if len(blocking_reasons) > 0:
            item = blocking_reasons[0]
            assert "reason" in item, "Missing 'reason' in blocking reason item"
            assert "count" in item, "Missing 'count' in blocking reason item"
            assert isinstance(item["count"], int), "count should be int"
            print(f"PASS: blocking reasons structure is correct")
            print(f"  - Top reason: {item['reason']} ({item['count']} docs)")
        else:
            print(f"PASS: no blocking reasons (all docs clear)")


class TestEndpointIntegration:
    """Integration tests across multiple endpoints"""
    
    
    def test_all_endpoints_accessible(self):
        """Test that all readiness endpoints are accessible"""
        endpoints = [
            ("GET", "/api/readiness/inbox-diagnostic"),
            ("POST", "/api/readiness/sync-status"),
            ("POST", "/api/readiness/reevaluate-all?limit=1"),
            ("GET", "/api/readiness/automation-rate"),
            ("GET", "/api/readiness/metrics"),
        ]
        
        for method, endpoint in endpoints:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}")
            else:
                response = requests.post(f"{BASE_URL}{endpoint}")
            
            assert response.status_code == 200, \
                f"{method} {endpoint} failed with {response.status_code}: {response.text}"
            print(f"PASS: {method} {endpoint} - 200 OK")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
