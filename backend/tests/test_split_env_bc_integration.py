"""
Test Suite for Split-Environment BC Integration Feature
Tests that reads go to Production and writes go to Sandbox_11_3_2025
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://po-candidate-hub.preview.emergentagent.com').rstrip('/')


class TestBCEnvironmentStatus:
    """Tests for /api/bc/environment-status endpoint"""

    def test_environment_status_returns_200(self):
        """Test that environment status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        assert response.status_code == 200
        print(f"✅ /api/bc/environment-status returned 200")

    def test_environment_status_read_environment(self):
        """Test that read_environment is Production"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        data = response.json()
        assert data.get("read_environment") == "Production"
        print(f"✅ read_environment = Production")

    def test_environment_status_write_environment(self):
        """Test that write_environment is Sandbox_11_3_2025"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        data = response.json()
        assert data.get("write_environment") == "Sandbox_11_3_2025"
        print(f"✅ write_environment = Sandbox_11_3_2025")

    def test_environment_status_block_production_writes(self):
        """Test that block_production_writes is true"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        data = response.json()
        assert data.get("block_production_writes") == True
        print(f"✅ block_production_writes = True")

    def test_environment_status_has_credentials(self):
        """Test that has_credentials is true"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        data = response.json()
        assert data.get("has_credentials") == True
        print(f"✅ has_credentials = True")

    def test_environment_status_not_mock_mode(self):
        """Test that mock_mode is false"""
        response = requests.get(f"{BASE_URL}/api/bc/environment-status")
        data = response.json()
        assert data.get("mock_mode") == False
        print(f"✅ mock_mode = False")


class TestGPIIntegrationStatus:
    """Tests for /api/gpi-integration/status endpoint"""

    def test_gpi_integration_status_returns_200(self):
        """Test that GPI integration status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200
        print(f"✅ /api/gpi-integration/status returned 200")

    def test_gpi_integration_status_read_environment(self):
        """Test that read_environment is Production"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        data = response.json()
        assert data.get("read_environment") == "Production"
        print(f"✅ GPI Integration read_environment = Production")

    def test_gpi_integration_status_write_environment(self):
        """Test that write_environment is Sandbox_11_3_2025"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        data = response.json()
        assert data.get("write_environment") == "Sandbox_11_3_2025"
        print(f"✅ GPI Integration write_environment = Sandbox_11_3_2025")

    def test_gpi_integration_status_configured(self):
        """Test that GPI integration is configured"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        data = response.json()
        assert data.get("configured") == True
        print(f"✅ GPI Integration configured = True")


class TestBCSandboxStatus:
    """Tests for /api/bc-sandbox/status endpoint"""

    def test_bc_sandbox_status_returns_200(self):
        """Test that BC sandbox status endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status")
        assert response.status_code == 200
        print(f"✅ /api/bc-sandbox/status returned 200")

    def test_bc_sandbox_status_config_read_environment(self):
        """Test that config.read_environment is Production"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status")
        data = response.json()
        config = data.get("config", {})
        assert config.get("read_environment") == "Production"
        print(f"✅ BC Sandbox config.read_environment = Production")

    def test_bc_sandbox_status_config_write_environment(self):
        """Test that config.write_environment is Sandbox_11_3_2025"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status")
        data = response.json()
        config = data.get("config", {})
        assert config.get("write_environment") == "Sandbox_11_3_2025"
        print(f"✅ BC Sandbox config.write_environment = Sandbox_11_3_2025")

    def test_bc_sandbox_status_not_demo_mode(self):
        """Test that demo_mode is false"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status")
        data = response.json()
        assert data.get("demo_mode") == False
        print(f"✅ BC Sandbox demo_mode = False")

    def test_bc_sandbox_status_has_secret(self):
        """Test that has_secret is true in config"""
        response = requests.get(f"{BASE_URL}/api/bc-sandbox/status")
        data = response.json()
        config = data.get("config", {})
        assert config.get("has_secret") == True
        print(f"✅ BC Sandbox config.has_secret = True")


class TestVendorLookup:
    """Tests for vendor lookup (reads from Production)"""

    def test_vendor_search_returns_200(self):
        """Test that vendor search endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendors?search=test")
        assert response.status_code == 200
        print(f"✅ /api/ap-review/vendors returned 200")

    def test_vendor_search_returns_real_data(self):
        """Test that vendor search returns real data (not mock)"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendors?search=test")
        data = response.json()
        # Should have mock=false for real BC data
        assert data.get("mock") == False
        print(f"✅ Vendor search returns real BC data (mock=False)")

    def test_vendor_search_returns_vendors_array(self):
        """Test that vendor search returns vendors array"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendors?search=test")
        data = response.json()
        assert "vendors" in data
        assert isinstance(data["vendors"], list)
        print(f"✅ Vendor search returns vendors array with {len(data['vendors'])} items")


class TestBCIntegrationDashboard:
    """Tests for BC Integration Dashboard endpoint"""

    def test_dashboard_returns_200(self):
        """Test that dashboard endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard")
        assert response.status_code == 200
        print(f"✅ /api/gpi-integration/dashboard returned 200")

    def test_dashboard_returns_counts(self):
        """Test that dashboard returns counts object"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard")
        data = response.json()
        assert "counts" in data
        print(f"✅ Dashboard returns counts: {data['counts']}")

    def test_dashboard_returns_transactions(self):
        """Test that dashboard returns transactions array"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard")
        data = response.json()
        assert "transactions" in data
        assert isinstance(data["transactions"], list)
        print(f"✅ Dashboard returns transactions array")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
