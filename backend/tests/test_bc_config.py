"""
GPI Document Hub - BC Config Hardening Tests
Tests for centralized BC environment configuration:
- GET /api/admin/bc-config diagnostics endpoint
- GET /api/settings/status bc_environment, business_central_read, business_central_write
- Security: No secrets exposed in responses
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBCConfigDiagnostics:
    """Part 1: GET /api/admin/bc-config diagnostics endpoint"""
    
    def test_bc_config_returns_expected_fields(self):
        """Verify bc-config endpoint returns required fields"""
        response = requests.get(f"{BASE_URL}/api/admin/bc-config")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Part 1: Check bc_read_environment=Production
        assert "bc_read_environment" in data, "Missing bc_read_environment"
        assert data["bc_read_environment"] == "Production", f"Expected Production, got {data['bc_read_environment']}"
        
        # Part 1: Check bc_write_environment=Sandbox_11_3_2025
        assert "bc_write_environment" in data, "Missing bc_write_environment"
        assert data["bc_write_environment"] == "Sandbox_11_3_2025", f"Expected Sandbox_11_3_2025, got {data['bc_write_environment']}"
        
        # Part 1: Check writes_enabled=false
        assert "writes_enabled" in data, "Missing writes_enabled"
        assert data["writes_enabled"] is False, f"Expected False, got {data['writes_enabled']}"
        
        # Part 1: Check mode contains 'SAFE'
        assert "mode" in data, "Missing mode"
        assert "SAFE" in data["mode"], f"Expected mode to contain 'SAFE', got {data['mode']}"
        
    def test_bc_config_has_additional_fields(self):
        """Verify bc-config returns all expected diagnostic fields"""
        response = requests.get(f"{BASE_URL}/api/admin/bc-config")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check additional fields exist
        expected_fields = [
            "bc_read_environment", "bc_write_environment", "writes_enabled",
            "mode", "read_credentials_present", "write_credentials_present",
            "company_name", "is_read_production"
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            
    def test_bc_config_no_secrets_exposed(self):
        """Part 11: Verify no secrets are exposed in bc-config response"""
        response = requests.get(f"{BASE_URL}/api/admin/bc-config")
        assert response.status_code == 200
        
        data = response.json()
        
        # List of fields that should NOT be in the response
        forbidden_fields = ["client_secret", "client_id", "tenant_id"]
        
        for field in forbidden_fields:
            assert field not in data, f"Security violation: {field} exposed in response"
            
        # Also check no full tenant_id value (only masked/short versions allowed)
        response_str = str(data).lower()
        assert "client_secret" not in response_str, "Secret keyword found in response"


class TestSettingsStatusBCEnvironment:
    """Part 2-6: GET /api/settings/status bc_environment and connections tests"""
    
    def test_settings_status_bc_environment_object(self):
        """Part 2: Verify bc_environment object exists with correct values"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Part 2: Check bc_environment object
        assert "bc_environment" in data, "Missing bc_environment in response"
        bc_env = data["bc_environment"]
        
        # Part 2: read_environment=Production
        assert "read_environment" in bc_env, "Missing read_environment in bc_environment"
        assert bc_env["read_environment"] == "Production", f"Expected Production, got {bc_env['read_environment']}"
        
        # Part 2: is_read_production=true
        assert "is_read_production" in bc_env, "Missing is_read_production in bc_environment"
        assert bc_env["is_read_production"] is True, f"Expected True, got {bc_env['is_read_production']}"
        
    def test_settings_status_separate_bc_connections(self):
        """Part 3: Verify separate business_central_read and business_central_write objects"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        connections = data.get("connections", {})
        
        # Part 3: Check separate objects exist
        assert "business_central_read" in connections, "Missing business_central_read in connections"
        assert "business_central_write" in connections, "Missing business_central_write in connections"
        
    def test_bc_read_connection_environment(self):
        """Part 4: connections.business_central_read.environment should be 'Production'"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        bc_read = data.get("connections", {}).get("business_central_read", {})
        
        assert "environment" in bc_read, "Missing environment in business_central_read"
        assert bc_read["environment"] == "Production", f"Expected Production, got {bc_read['environment']}"
        
    def test_bc_write_connection_environment(self):
        """Part 5: connections.business_central_write.environment should be 'Sandbox_11_3_2025'"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        bc_write = data.get("connections", {}).get("business_central_write", {})
        
        assert "environment" in bc_write, "Missing environment in business_central_write"
        assert bc_write["environment"] == "Sandbox_11_3_2025", f"Expected Sandbox_11_3_2025, got {bc_write['environment']}"
        
    def test_bc_write_connection_writes_enabled(self):
        """Part 6: connections.business_central_write.writes_enabled should be false"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        data = response.json()
        bc_write = data.get("connections", {}).get("business_central_write", {})
        
        assert "writes_enabled" in bc_write, "Missing writes_enabled in business_central_write"
        assert bc_write["writes_enabled"] is False, f"Expected False, got {bc_write['writes_enabled']}"


class TestExistingAPIsWork:
    """Part 10: Verify existing APIs still work"""
    
    def test_auth_login(self):
        """Verify auth login still works with admin/admin"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200, f"Auth login failed: {response.status_code} - {response.text}"
        
        data = response.json()
        assert "access_token" in data or "token" in data, "Missing token in login response"
        
    def test_documents_list(self):
        """Verify documents list endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200, f"Documents list failed: {response.status_code}"
        
    def test_workflow_status_counts(self):
        """Verify workflow status-counts endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200, f"Status counts failed: {response.status_code}"
        
    def test_mailbox_sources(self):
        """Verify mailbox sources endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/settings/mailbox-sources")
        assert response.status_code == 200, f"Mailbox sources failed: {response.status_code}"
        

class TestBCConfigSecurity:
    """Part 11: Security tests - no secrets exposed"""
    
    def test_admin_bc_config_no_client_secret(self):
        """Verify no client_secret in bc-config response"""
        response = requests.get(f"{BASE_URL}/api/admin/bc-config")
        assert response.status_code == 200
        
        text = response.text.lower()
        assert "bdN8Q~" not in text, "Client secret value leaked in response"
        assert "x5n8q~" not in text.lower(), "Graph secret value leaked in response"
        
    def test_admin_bc_config_no_client_id_full(self):
        """Verify no full client_id in bc-config response"""
        response = requests.get(f"{BASE_URL}/api/admin/bc-config")
        assert response.status_code == 200
        
        data = response.json()
        # Should not have full credential fields exposed
        assert "client_id" not in data, "client_id field should not be in response"
        assert "client_secret" not in data, "client_secret field should not be in response"
        
    def test_settings_status_no_secrets(self):
        """Verify settings/status doesn't leak secrets"""
        response = requests.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200
        
        text = response.text.lower()
        # Secrets from .env file should not appear
        assert "bdn8q~" not in text, "BC client secret leaked"
        assert "x5n8q~" not in text, "Graph client secret leaked"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
