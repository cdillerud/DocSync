"""
Tests for Technical Debt Remediation Pass #2 - API Endpoint Verification

Verifies all API contracts preserved after consolidation of:
- reference_helpers.py (shared normalization, fuzzy matching)
- bc_access.py (BC token/company adapter)

Endpoints tested:
1. Health check
2. Auth login
3. Documents list
4. Pipeline stages and run
5. Learning summary
6. Policies
7. BC sandbox status
8. Dashboard stats
9. Spiro status
10. Inventory ledger summary
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndAuth:
    """Health check and authentication endpoints"""
    
    def test_health_check(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health", timeout=30)
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert "status" in data or "healthy" in str(data).lower(), f"Missing status in response: {data}"
        print(f"✓ Health check passed: {data}")
    
    def test_auth_login(self):
        """POST /api/auth/login with admin credentials returns token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"},
            timeout=30
        )
        assert response.status_code == 200, f"Auth failed: {response.status_code} {response.text}"
        data = response.json()
        assert "token" in data or "access_token" in data, f"No token in response: {data}"
        print(f"✓ Auth login passed, token received")
        return data.get("token") or data.get("access_token")


class TestDocumentIntelligence:
    """Document Intelligence pipeline endpoints"""
    
    def test_documents_list(self):
        """GET /api/documents returns data"""
        response = requests.get(f"{BASE_URL}/api/documents", timeout=30)
        assert response.status_code == 200, f"Documents list failed: {response.status_code} {response.text}"
        data = response.json()
        # May return list or dict with documents key
        assert isinstance(data, (list, dict)), f"Unexpected response type: {type(data)}"
        print(f"✓ Documents list passed: {len(data) if isinstance(data, list) else data.get('total', 'N/A')} documents")
    
    def test_pipeline_stages(self):
        """GET /api/document-intelligence/pipeline/stages returns 7 stages"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/pipeline/stages", timeout=30)
        assert response.status_code == 200, f"Pipeline stages failed: {response.status_code} {response.text}"
        data = response.json()
        stages = data if isinstance(data, list) else data.get("stages", [])
        assert len(stages) == 7, f"Expected 7 stages, got {len(stages)}: {stages}"
        print(f"✓ Pipeline stages passed: {len(stages)} stages")
    
    def test_pipeline_run(self):
        """POST /api/document-intelligence/pipeline/test-id returns structured result"""
        response = requests.post(
            f"{BASE_URL}/api/document-intelligence/pipeline/test-id",
            params={"stop_after": "classification"},
            timeout=60
        )
        assert response.status_code == 200, f"Pipeline run failed: {response.status_code} {response.text}"
        data = response.json()
        assert "stages" in data, f"No stages in pipeline result: {data}"
        print(f"✓ Pipeline run passed: {len(data.get('stages', []))} stages executed")
    
    def test_learning_summary(self):
        """GET /api/document-intelligence/learning/summary returns data"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/learning/summary", timeout=30)
        assert response.status_code == 200, f"Learning summary failed: {response.status_code} {response.text}"
        data = response.json()
        assert isinstance(data, dict), f"Expected dict response: {type(data)}"
        print(f"✓ Learning summary passed: {data}")
    
    def test_policies(self):
        """GET /api/document-intelligence/policies returns list"""
        response = requests.get(f"{BASE_URL}/api/document-intelligence/policies", timeout=30)
        assert response.status_code == 200, f"Policies failed: {response.status_code} {response.text}"
        data = response.json()
        # May return list or dict with policies
        assert isinstance(data, (list, dict)), f"Unexpected response type: {type(data)}"
        print(f"✓ Policies passed: {len(data) if isinstance(data, list) else 'dict response'}")


class TestBCAndDashboard:
    """BC sandbox and dashboard endpoints"""
    
    def test_bc_sandbox_status(self):
        """GET /api/bc-sandbox/status returns demo_mode field"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status", timeout=30)
        assert response.status_code == 200, f"BC sandbox status failed: {response.status_code} {response.text}"
        data = response.json()
        assert "demo_mode" in data, f"No demo_mode field in response: {data}"
        print(f"✓ BC sandbox status passed: demo_mode={data['demo_mode']}")
    
    def test_dashboard_stats(self):
        """GET /api/dashboard/stats returns data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", timeout=30)
        assert response.status_code == 200, f"Dashboard stats failed: {response.status_code} {response.text}"
        data = response.json()
        assert isinstance(data, dict), f"Expected dict response: {type(data)}"
        print(f"✓ Dashboard stats passed: {list(data.keys())[:5]}...")


class TestSpiroAndInventory:
    """Spiro and inventory ledger endpoints"""
    
    def test_spiro_status(self):
        """GET /api/spiro/status returns enabled field"""
        response = requests.get(f"{BASE_URL}/api/spiro/status", timeout=30)
        assert response.status_code == 200, f"Spiro status failed: {response.status_code} {response.text}"
        data = response.json()
        assert "enabled" in data, f"No enabled field in response: {data}"
        print(f"✓ Spiro status passed: enabled={data['enabled']}")
    
    def test_inventory_ledger(self):
        """GET /api/inventory-ledger/dashboard-summary returns total_items"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={"customer_id": "test"},
            timeout=30
        )
        assert response.status_code == 200, f"Inventory ledger failed: {response.status_code} {response.text}"
        data = response.json()
        assert "total_items" in data, f"No total_items field in response: {data}"
        print(f"✓ Inventory ledger passed: total_items={data['total_items']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
