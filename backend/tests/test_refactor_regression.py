"""
GPI Document Hub - Refactor Regression Tests

This test suite validates that all endpoints continue to work after
the backend refactor from server:app to main:app. Tests cover:
- Health check endpoint
- Authentication (login + me)
- Document listing
- Dashboard stats + workflow intelligence
- AP workflow status counts
- Layout fingerprints
- Vendor aliases
- Automation rules
- Vendor intelligence
- Label corrections
- Alerts
- Pilot status
- Migration stats
- Mailbox sources
- Vendor match stats
- Square9 config
- Freight routing
- Events
- Cache status
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"


class TestHealthCheck:
    """Health check endpoint - validates app is running"""
    
    def test_health_endpoint_returns_200(self):
        """GET /api/health returns 200 with healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
        assert "service" in data
        print(f"✓ Health check passed: {data}")


class TestAuthentication:
    """Authentication endpoints - login and user info"""
    
    def test_login_returns_token(self):
        """POST /api/auth/login with valid credentials returns token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        
        data = response.json()
        assert "access_token" in data or "token" in data, f"No token in response: {data}"
        token = data.get("access_token") or data.get("token")
        assert isinstance(token, str) and len(token) > 0
        print(f"✓ Login successful, token received (length: {len(token)})")
        return token
    
    def test_auth_me_returns_user_info(self):
        """GET /api/auth/me returns current user info"""
        # First login to get token
        login_resp = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        assert login_resp.status_code == 200
        token = login_resp.json().get("access_token") or login_resp.json().get("token")
        
        # Now get user info
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, f"Auth/me failed: {response.text}"
        
        data = response.json()
        assert "username" in data or "user" in data or "sub" in data
        print(f"✓ Auth/me returned user info: {data}")


class TestDocuments:
    """Document listing endpoint"""
    
    def test_documents_list_returns_data(self):
        """GET /api/documents returns documents list with total count"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200, f"Documents list failed: {response.text}"
        
        data = response.json()
        assert "documents" in data or isinstance(data, list)
        
        # Check for total count
        if "total" in data:
            assert isinstance(data["total"], int)
            print(f"✓ Documents list: {data.get('total', len(data))} total documents")
        else:
            docs = data.get("documents", data)
            print(f"✓ Documents list returned {len(docs)} documents")


class TestDashboard:
    """Dashboard stats and workflow intelligence endpoints"""
    
    def test_dashboard_stats_returns_total_documents(self):
        """GET /api/dashboard/stats returns total_documents and status breakdown"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200, f"Dashboard stats failed: {response.text}"
        
        data = response.json()
        assert "total_documents" in data, f"Missing total_documents: {data}"
        assert isinstance(data["total_documents"], int)
        
        # Check for status breakdown
        if "by_status" in data:
            assert isinstance(data["by_status"], dict)
        
        print(f"✓ Dashboard stats: {data['total_documents']} total documents")
    
    def test_workflow_intelligence_returns_metrics(self):
        """GET /api/dashboard/workflow-intelligence returns comprehensive metrics"""
        response = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert response.status_code == 200, f"Workflow intelligence failed: {response.text}"
        
        data = response.json()
        # Check for expected keys
        expected_keys = ["total_documents", "vendor_intelligence", "validation_metrics", "processing_metrics"]
        for key in expected_keys:
            assert key in data, f"Missing key '{key}' in workflow intelligence response"
        
        print(f"✓ Workflow intelligence: {data['total_documents']} documents, {len(data.keys())} metric sections")


class TestAPWorkflow:
    """AP Invoice workflow endpoints"""
    
    def test_ap_workflow_status_counts(self):
        """GET /api/workflows/ap_invoice/status-counts returns status breakdown"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200, f"AP workflow status counts failed: {response.text}"
        
        data = response.json()
        # Response should have status counts or statuses field
        assert isinstance(data, dict)
        print(f"✓ AP workflow status counts returned: {data}")


class TestLayoutFingerprints:
    """Layout fingerprints endpoint"""
    
    def test_layout_fingerprints_stats(self):
        """GET /api/layout-fingerprints/stats returns family data"""
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/stats")
        assert response.status_code == 200, f"Layout fingerprints stats failed: {response.text}"
        
        data = response.json()
        # Check for expected fields
        expected_keys = ["total_families", "total_fingerprints"]
        for key in expected_keys:
            assert key in data, f"Missing key '{key}': {data}"
        
        print(f"✓ Layout fingerprints stats: {data.get('total_families', 0)} families, {data.get('total_fingerprints', 0)} fingerprints")


class TestVendorAliases:
    """Vendor aliases endpoint"""
    
    def test_vendor_aliases_returns_list(self):
        """GET /api/aliases/vendors returns aliases array"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert response.status_code == 200, f"Vendor aliases failed: {response.text}"
        
        data = response.json()
        # Can be list or dict with aliases key
        aliases = data.get("aliases", data) if isinstance(data, dict) else data
        assert isinstance(aliases, list)
        print(f"✓ Vendor aliases: {len(aliases)} aliases returned")


class TestAutomationRules:
    """Automation rules endpoint"""
    
    def test_automation_rules_returns_array(self):
        """GET /api/automation-rules returns rules array"""
        response = requests.get(f"{BASE_URL}/api/automation-rules")
        assert response.status_code == 200, f"Automation rules failed: {response.text}"
        
        data = response.json()
        # Can be list or dict with rules key
        rules = data.get("rules", data) if isinstance(data, dict) else data
        assert isinstance(rules, list)
        print(f"✓ Automation rules: {len(rules)} rules returned")


class TestVendorIntelligence:
    """Vendor intelligence stats endpoint"""
    
    def test_vendor_intelligence_stats(self):
        """GET /api/vendor-intelligence/stats returns vendor stats"""
        response = requests.get(f"{BASE_URL}/api/vendor-intelligence/stats")
        assert response.status_code == 200, f"Vendor intelligence stats failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        # Check for some expected fields
        if "total_profiles" in data or "vendors" in data or "total_vendors" in data:
            print(f"✓ Vendor intelligence stats returned: {data}")
        else:
            print(f"✓ Vendor intelligence stats: {data}")


class TestLabelCorrections:
    """Label corrections stats endpoint"""
    
    def test_label_corrections_stats(self):
        """GET /api/label-corrections/stats returns correction stats"""
        response = requests.get(f"{BASE_URL}/api/label-corrections/stats")
        assert response.status_code == 200, f"Label corrections stats failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        print(f"✓ Label corrections stats: {data}")


class TestAlerts:
    """Alerts active endpoint"""
    
    def test_alerts_active(self):
        """GET /api/alerts/active returns active alerts"""
        response = requests.get(f"{BASE_URL}/api/alerts/active")
        assert response.status_code == 200, f"Alerts active failed: {response.text}"
        
        data = response.json()
        # Can be list or dict with alerts key
        alerts = data.get("alerts", data) if isinstance(data, dict) else data
        assert isinstance(alerts, list) or isinstance(data, dict)
        print(f"✓ Active alerts returned: {len(alerts) if isinstance(alerts, list) else data}")


class TestPilot:
    """Pilot status endpoint"""
    
    def test_pilot_status(self):
        """GET /api/pilot/status returns pilot status"""
        response = requests.get(f"{BASE_URL}/api/pilot/status")
        assert response.status_code == 200, f"Pilot status failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        print(f"✓ Pilot status: {data}")


class TestMigration:
    """Migration stats endpoint"""
    
    def test_migration_stats(self):
        """GET /api/migration/stats returns migration statistics"""
        response = requests.get(f"{BASE_URL}/api/migration/stats")
        assert response.status_code == 200, f"Migration stats failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        print(f"✓ Migration stats: {data}")


class TestSettings:
    """Settings/mailbox sources endpoint"""
    
    def test_mailbox_sources(self):
        """GET /api/settings/mailbox-sources returns mailbox config"""
        response = requests.get(f"{BASE_URL}/api/settings/mailbox-sources")
        assert response.status_code == 200, f"Mailbox sources failed: {response.text}"
        
        data = response.json()
        # Can be list or dict
        assert isinstance(data, (list, dict))
        print(f"✓ Mailbox sources: {data}")
    
    def test_settings_status(self):
        """GET /api/settings/status returns connection status"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200, f"Settings status failed: {response.text}"
        
        data = response.json()
        assert "connections" in data, f"Missing 'connections' in response: {data}"
        assert "demo_mode" in data, f"Missing 'demo_mode' in response: {data}"
        print(f"✓ Settings status: demo_mode={data['demo_mode']}, connections configured")


class TestVendorMatch:
    """Vendor match stats endpoint"""
    
    def test_vendor_match_stats(self):
        """GET /api/vendors/match-stats returns match statistics"""
        response = requests.get(f"{BASE_URL}/api/vendors/match-stats")
        assert response.status_code == 200, f"Vendor match stats failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        
        # Check for expected keys
        if "sources" in data:
            assert isinstance(data["sources"], dict)
        
        print(f"✓ Vendor match stats: {data}")


class TestSquare9:
    """Square9 config endpoint"""
    
    def test_square9_config_returns_stages(self):
        """GET /api/square9/config returns config with stages"""
        response = requests.get(f"{BASE_URL}/api/square9/config")
        assert response.status_code == 200, f"Square9 config failed: {response.text}"
        
        data = response.json()
        assert "config" in data, f"Missing 'config' key: {data}"
        assert "stages" in data, f"Missing 'stages' key: {data}"
        assert isinstance(data["stages"], list)
        assert len(data["stages"]) > 0, "No stages returned"
        
        print(f"✓ Square9 config: {len(data['stages'])} stages configured")


class TestFreightRouting:
    """Freight routing accounts endpoint"""
    
    def test_freight_routing_accounts(self):
        """GET /api/freight-routing/accounts returns accounts"""
        response = requests.get(f"{BASE_URL}/api/freight-routing/accounts")
        assert response.status_code == 200, f"Freight routing accounts failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, (list, dict))
        print(f"✓ Freight routing accounts: {data}")


class TestEvents:
    """Events recent endpoint"""
    
    def test_events_recent(self):
        """GET /api/events/recent?limit=5 returns recent events"""
        response = requests.get(f"{BASE_URL}/api/events/recent?limit=5")
        assert response.status_code == 200, f"Events recent failed: {response.text}"
        
        data = response.json()
        # Can be list or dict with events key
        events = data.get("events", data) if isinstance(data, dict) else data
        assert isinstance(events, list)
        print(f"✓ Recent events: {len(events)} events returned")


class TestCache:
    """Cache status endpoint"""
    
    def test_cache_status(self):
        """GET /api/cache/status returns cache status"""
        response = requests.get(f"{BASE_URL}/api/cache/status")
        assert response.status_code == 200, f"Cache status failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, dict)
        print(f"✓ Cache status: {data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
