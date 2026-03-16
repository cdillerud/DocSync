"""
Test Readiness Summary in Dashboard API - Iteration 118
Tests for the readiness_summary field added to workflow-intelligence endpoint
and the GET /api/readiness/metrics endpoint.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestWorkflowIntelligenceReadinessSummary:
    """Tests for readiness_summary in /api/dashboard/workflow-intelligence endpoint"""
    
    def test_workflow_intelligence_returns_200(self):
        """GET /api/dashboard/workflow-intelligence returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200
    
    def test_workflow_intelligence_contains_readiness_summary(self):
        """Response contains readiness_summary object"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        assert "readiness_summary" in data, "readiness_summary field missing"
        
    def test_readiness_summary_has_by_status(self):
        """readiness_summary contains by_status field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        assert "by_status" in rs, "by_status missing from readiness_summary"
        
    def test_readiness_summary_has_by_action(self):
        """readiness_summary contains by_action field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        assert "by_action" in rs, "by_action missing from readiness_summary"
        
    def test_readiness_summary_has_confidence_by_status(self):
        """readiness_summary contains confidence_by_status field"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        assert "confidence_by_status" in rs, "confidence_by_status missing from readiness_summary"
        
    def test_readiness_summary_has_top_blocking_reasons(self):
        """readiness_summary contains top_blocking_reasons list"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        assert "top_blocking_reasons" in rs, "top_blocking_reasons missing"
        assert isinstance(rs["top_blocking_reasons"], list), "top_blocking_reasons should be a list"
        
    def test_readiness_summary_has_top_warning_reasons(self):
        """readiness_summary contains top_warning_reasons list"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        assert "top_warning_reasons" in rs, "top_warning_reasons missing"
        assert isinstance(rs["top_warning_reasons"], list), "top_warning_reasons should be a list"
    
    def test_blocking_reasons_have_reason_and_count(self):
        """Each blocking reason has 'reason' and 'count' fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        for item in rs.get("top_blocking_reasons", []):
            assert "reason" in item, "blocking reason item missing 'reason'"
            assert "count" in item, "blocking reason item missing 'count'"
            
    def test_warning_reasons_have_reason_and_count(self):
        """Each warning reason has 'reason' and 'count' fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("readiness_summary", {})
        for item in rs.get("top_warning_reasons", []):
            assert "reason" in item, "warning reason item missing 'reason'"
            assert "count" in item, "warning reason item missing 'count'"


class TestReadinessMetricsEndpoint:
    """Tests for /api/readiness/metrics endpoint"""
    
    def test_readiness_metrics_returns_200(self):
        """GET /api/readiness/metrics returns 200"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert response.status_code == 200
    
    def test_readiness_metrics_has_total_documents(self):
        """Response contains total_documents"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "total_documents" in data
        assert isinstance(data["total_documents"], int)
        
    def test_readiness_metrics_has_by_status(self):
        """Response contains by_status breakdown"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "by_status" in data
        
    def test_readiness_metrics_has_by_action(self):
        """Response contains by_action breakdown"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "by_action" in data
        
    def test_readiness_metrics_has_top_blocking_reasons(self):
        """Response contains top_blocking_reasons"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "top_blocking_reasons" in data
        
    def test_readiness_metrics_has_top_warning_reasons(self):
        """Response contains top_warning_reasons"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "top_warning_reasons" in data
        
    def test_readiness_metrics_has_confidence_by_status(self):
        """Response contains confidence_by_status"""
        response = requests.get(f"{BASE_URL}/api/readiness/metrics")
        data = response.json()
        assert "confidence_by_status" in data


class TestDashboardStatsEndpoint:
    """Tests for /api/dashboard/stats endpoint (non-regression)"""
    
    def test_dashboard_stats_returns_200(self):
        """GET /api/dashboard/stats returns 200"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        
    def test_dashboard_stats_has_total_documents(self):
        """Response contains total_documents"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        data = response.json()
        assert "total_documents" in data


class TestRoutingSummaryPresence:
    """Tests for routing_summary in workflow-intelligence (non-regression)"""
    
    def test_routing_summary_present(self):
        """routing_summary still present in workflow-intelligence"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        assert "routing_summary" in data, "routing_summary field missing"
        
    def test_routing_summary_has_counts(self):
        """routing_summary contains counts"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = response.json()
        rs = data.get("routing_summary", {})
        assert "counts" in rs or "total_routed" in rs, "routing_summary structure unexpected"
