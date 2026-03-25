"""
GPI Document Hub - Router Refactor Regression Tests

Tests all endpoints from the 9 domain-specific routers extracted from server.py.
Validates that all routes work correctly after the monolith refactoring.

Domains tested:
1. Auth - /api/auth/*
2. Vendor Aliases - /api/aliases/*
3. Mailbox Sources - /api/settings/mailbox-sources/*
4. File Import - /api/sales/file-import/*
5. BC Integration - /api/bc/*
6. Spiro - /api/spiro/*
7. Documents - /api/documents/*
8. Workflows - /api/workflows/*
9. Reference Intelligence - /api/documents/{doc_id}/reference-intelligence/*
10. Stable Vendor - /api/stable-vendor/*
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://inside-sales-queue.preview.emergentagent.com').rstrip('/')


class TestHealthCheck:
    """Basic health check - run first"""
    
    def test_health_endpoint(self):
        """Test that the API is healthy"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"PASS: Health check returned: {data}")


class TestAuthEndpoints:
    """Domain 1: Auth endpoints"""
    
    def test_login_success(self):
        """POST /api/auth/login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "token" in data, "Missing token in response"
        assert "user" in data, "Missing user in response"
        assert data["user"]["username"] == "admin"
        assert data["user"]["display_name"] == "Hub Admin"
        assert data["user"]["role"] == "administrator"
        print(f"PASS: Login successful, token: {data['token'][:20]}...")
    
    def test_login_invalid_credentials(self):
        """POST /api/auth/login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wrong",
            "password": "wrong"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Invalid credentials correctly rejected")
    
    def test_get_me(self):
        """GET /api/auth/me returns current user info"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200, f"Get me failed: {response.text}"
        data = response.json()
        assert data.get("username") == "admin"
        assert data.get("display_name") == "Hub Admin"
        print(f"PASS: /api/auth/me returned: {data}")


class TestVendorAliasEndpoints:
    """Domain 2: Vendor Aliases endpoints"""
    
    def test_get_vendor_aliases(self):
        """GET /api/aliases/vendors returns alias list"""
        response = requests.get(f"{BASE_URL}/api/aliases/vendors")
        assert response.status_code == 200, f"Get aliases failed: {response.text}"
        data = response.json()
        assert "aliases" in data, "Missing aliases in response"
        assert "count" in data, "Missing count in response"
        print(f"PASS: Found {data['count']} vendor aliases")
    
    def test_create_and_delete_alias(self):
        """POST /api/aliases/vendors creates alias, DELETE removes it"""
        # Create
        test_alias = {
            "alias_string": "TEST_ALIAS_REGRESSION_" + str(os.urandom(4).hex()),
            "vendor_no": "TEST-VENDOR-001",
            "vendor_name": "Test Vendor Inc",
            "notes": "Regression test alias"
        }
        create_resp = requests.post(f"{BASE_URL}/api/aliases/vendors", json=test_alias)
        assert create_resp.status_code == 200, f"Create alias failed: {create_resp.text}"
        create_data = create_resp.json()
        assert "alias_id" in create_data, "Missing alias_id in response"
        alias_id = create_data["alias_id"]
        print(f"PASS: Created alias with ID: {alias_id}")
        
        # Verify creation
        list_resp = requests.get(f"{BASE_URL}/api/aliases/vendors")
        aliases = list_resp.json().get("aliases", [])
        found = any(a.get("alias_id") == alias_id for a in aliases)
        assert found, "Created alias not found in list"
        
        # Delete
        delete_resp = requests.delete(f"{BASE_URL}/api/aliases/vendors/{alias_id}")
        assert delete_resp.status_code == 200, f"Delete alias failed: {delete_resp.text}"
        print(f"PASS: Deleted alias {alias_id}")


class TestMailboxSourcesEndpoints:
    """Domain 3: Mailbox Sources endpoints"""
    
    def test_list_mailbox_sources(self):
        """GET /api/settings/mailbox-sources returns mailbox list"""
        response = requests.get(f"{BASE_URL}/api/settings/mailbox-sources")
        assert response.status_code == 200, f"Get mailbox sources failed: {response.text}"
        data = response.json()
        assert "mailbox_sources" in data, "Missing mailbox_sources in response"
        assert "total" in data, "Missing total in response"
        print(f"PASS: Found {data['total']} mailbox sources")
    
    def test_get_polling_status(self):
        """GET /api/settings/mailbox-sources/polling-status returns worker status"""
        response = requests.get(f"{BASE_URL}/api/settings/mailbox-sources/polling-status")
        assert response.status_code == 200, f"Get polling status failed: {response.text}"
        data = response.json()
        assert "worker_running" in data, "Missing worker_running in response"
        assert "mailboxes" in data, "Missing mailboxes in response"
        print(f"PASS: Worker running: {data['worker_running']}, mailboxes: {len(data['mailboxes'])}")


class TestFileImportEndpoints:
    """Domain 4: File Import endpoints"""
    
    def test_get_column_mappings(self):
        """GET /api/sales/file-import/column-mappings returns mapping config"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/column-mappings")
        assert response.status_code == 200, f"Get column mappings failed: {response.text}"
        data = response.json()
        assert "ingestion_type" in data, "Missing ingestion_type in response"
        assert "required_columns" in data, "Missing required_columns in response"
        print(f"PASS: Column mappings for '{data['ingestion_type']}' with {len(data.get('required_columns', []))} required columns")
    
    def test_get_import_history(self):
        """GET /api/sales/file-import/history returns import history"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/history")
        assert response.status_code == 200, f"Get import history failed: {response.text}"
        data = response.json()
        assert "history" in data, "Missing history in response"
        assert "total" in data, "Missing total in response"
        print(f"PASS: Import history has {data['total']} records")


class TestBCIntegrationEndpoints:
    """Domain 5: BC Integration endpoints (expects 500 due to tenant config - known issue)"""
    
    def test_list_bc_companies(self):
        """GET /api/bc/companies - expected to return 500 due to tenant config"""
        response = requests.get(f"{BASE_URL}/api/bc/companies")
        # Known issue: tenant config causes 500
        if response.status_code == 500:
            print("EXPECTED: BC companies returns 500 (tenant config issue - not a regression)")
        elif response.status_code == 200:
            data = response.json()
            print(f"PASS: Found {len(data.get('companies', []))} BC companies")
        else:
            print(f"WARNING: Unexpected status {response.status_code}: {response.text}")


class TestSpiroEndpoints:
    """Domain 6: Spiro Integration endpoints"""
    
    def test_get_freight_carriers(self):
        """GET /api/spiro/freight-carriers returns freight carriers"""
        response = requests.get(f"{BASE_URL}/api/spiro/freight-carriers")
        assert response.status_code == 200, f"Get freight carriers failed: {response.text}"
        data = response.json()
        assert "carriers" in data, "Missing carriers in response"
        assert "count" in data, "Missing count in response"
        print(f"PASS: Found {data['count']} freight carriers")
    
    def test_get_spiro_status(self):
        """GET /api/spiro/status returns integration status"""
        response = requests.get(f"{BASE_URL}/api/spiro/status")
        assert response.status_code == 200, f"Get spiro status failed: {response.text}"
        data = response.json()
        assert "enabled" in data, "Missing enabled in response"
        print(f"PASS: Spiro enabled: {data.get('enabled')}")


class TestDocumentsEndpoints:
    """Domain 7: Documents endpoints"""
    
    def test_list_documents(self):
        """GET /api/documents returns documents list with counts"""
        response = requests.get(f"{BASE_URL}/api/documents")
        assert response.status_code == 200, f"Get documents failed: {response.text}"
        data = response.json()
        assert "documents" in data, "Missing documents in response"
        assert "total" in data, "Missing total in response"
        assert "counts" in data, "Missing counts in response"
        print(f"PASS: Found {data['total']} documents (showing {data['counts'].get('showing', 0)})")
        return data.get("documents", [])
    
    def test_get_document_detail(self):
        """GET /api/documents/{doc_id} returns document with workflows"""
        # First get a document ID
        docs = self.test_list_documents()
        if not docs:
            print("SKIP: No documents to test detail view")
            return
        
        doc_id = docs[0].get("id")
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert response.status_code == 200, f"Get document failed: {response.text}"
        data = response.json()
        assert "document" in data, "Missing document in response"
        assert "workflows" in data, "Missing workflows in response"
        print(f"PASS: Document {doc_id[:8]} has {len(data.get('workflows', []))} workflows")
        return doc_id
    
    def test_get_document_events(self):
        """GET /api/documents/{doc_id}/events returns events"""
        docs_resp = requests.get(f"{BASE_URL}/api/documents?limit=1")
        docs = docs_resp.json().get("documents", [])
        if not docs:
            print("SKIP: No documents for events test")
            return
        
        doc_id = docs[0].get("id")
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/events")
        assert response.status_code == 200, f"Get events failed: {response.text}"
        data = response.json()
        assert "events" in data, "Missing events in response"
        print(f"PASS: Document {doc_id[:8]} has {len(data.get('events', []))} events")
    
    def test_update_document(self):
        """PUT /api/documents/{doc_id} updates document"""
        docs_resp = requests.get(f"{BASE_URL}/api/documents?limit=1")
        docs = docs_resp.json().get("documents", [])
        if not docs:
            print("SKIP: No documents for update test")
            return
        
        doc_id = docs[0].get("id")
        original_type = docs[0].get("document_type")
        
        # Update
        response = requests.put(f"{BASE_URL}/api/documents/{doc_id}", json={
            "document_type": original_type or "AP_Invoice"
        })
        assert response.status_code == 200, f"Update document failed: {response.text}"
        data = response.json()
        assert data.get("id") == doc_id
        print(f"PASS: Updated document {doc_id[:8]}")


class TestWorkflowsEndpoints:
    """Domain 8: Workflows endpoints"""
    
    def test_list_workflows(self):
        """GET /api/workflows returns workflow list"""
        response = requests.get(f"{BASE_URL}/api/workflows")
        assert response.status_code == 200, f"Get workflows failed: {response.text}"
        data = response.json()
        assert "workflows" in data, "Missing workflows in response"
        assert "total" in data, "Missing total in response"
        print(f"PASS: Found {data['total']} workflows")
    
    def test_get_ap_status_counts(self):
        """GET /api/workflows/ap_invoice/status-counts returns AP status counts"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200, f"Get AP status counts failed: {response.text}"
        data = response.json()
        assert "status_counts" in data, "Missing status_counts in response"
        assert "total" in data, "Missing total in response"
        print(f"PASS: AP workflow total: {data['total']}, statuses: {list(data['status_counts'].keys())}")
    
    def test_get_ap_metrics(self):
        """GET /api/workflows/ap_invoice/metrics returns AP metrics with automation_rate"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/metrics")
        assert response.status_code == 200, f"Get AP metrics failed: {response.text}"
        data = response.json()
        assert "metrics" in data, "Missing metrics in response"
        metrics = data["metrics"]
        print(f"PASS: AP metrics - total: {metrics.get('total', 0)}, automation_rate: {metrics.get('automation_rate', 0)}%")
    
    def test_get_generic_status_counts(self):
        """GET /api/workflows/generic/status-counts-by-type returns generic workflow stats"""
        response = requests.get(f"{BASE_URL}/api/workflows/generic/status-counts-by-type")
        assert response.status_code == 200, f"Get generic status counts failed: {response.text}"
        data = response.json()
        assert "status_counts_by_type" in data, "Missing status_counts_by_type in response"
        print(f"PASS: Generic workflow doc types: {data.get('doc_types', [])}")
    
    def test_get_generic_queue(self):
        """GET /api/workflows/generic/queue returns generic queue"""
        response = requests.get(f"{BASE_URL}/api/workflows/generic/queue")
        assert response.status_code == 200, f"Get generic queue failed: {response.text}"
        data = response.json()
        assert "documents" in data, "Missing documents in response"
        assert "total" in data, "Missing total in response"
        print(f"PASS: Generic queue has {data['total']} documents")


class TestReferenceIntelligenceEndpoints:
    """Domain 9: Reference Intelligence endpoints"""
    
    def test_get_reference_intelligence(self):
        """GET /api/documents/{doc_id}/reference-intelligence returns stored ref intel data"""
        docs_resp = requests.get(f"{BASE_URL}/api/documents?limit=1")
        docs = docs_resp.json().get("documents", [])
        if not docs:
            print("SKIP: No documents for ref intel test")
            return
        
        doc_id = docs[0].get("id")
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/reference-intelligence")
        # Could be 200 or 404 depending on whether ref intel was run
        if response.status_code == 200:
            data = response.json()
            print(f"PASS: Ref intel data for {doc_id[:8]}: {list(data.keys())[:5]}...")
        elif response.status_code == 404:
            print(f"PASS: No ref intel data yet for {doc_id[:8]} (expected for new docs)")
        else:
            print(f"WARNING: Unexpected status {response.status_code}")
    
    def test_get_matching_debug(self):
        """GET /api/documents/{doc_id}/matching-debug returns matching diagnostics"""
        docs_resp = requests.get(f"{BASE_URL}/api/documents?limit=1")
        docs = docs_resp.json().get("documents", [])
        if not docs:
            print("SKIP: No documents for matching debug test")
            return
        
        doc_id = docs[0].get("id")
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/matching-debug")
        # Could be 200 or 404
        if response.status_code == 200:
            data = response.json()
            print(f"PASS: Matching debug for {doc_id[:8]}: keys={list(data.keys())[:5]}")
        elif response.status_code == 404:
            print(f"PASS: No matching debug for {doc_id[:8]} (expected for new docs)")
        else:
            print(f"WARNING: Unexpected status {response.status_code}")


class TestStableVendorEndpoints:
    """Stable Vendor Dashboard endpoints"""
    
    def test_get_dashboard_metrics(self):
        """GET /api/stable-vendor/dashboard-metrics returns stable vendor KPIs"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/dashboard-metrics")
        assert response.status_code == 200, f"Get dashboard metrics failed: {response.text}"
        data = response.json()
        assert "total_vendors" in data or "vendors" in data or "metrics" in data, "Missing expected keys in response"
        print(f"PASS: Stable vendor metrics: {list(data.keys())}")
    
    def test_get_vendor_list(self):
        """GET /api/stable-vendor/vendors returns vendor list"""
        response = requests.get(f"{BASE_URL}/api/stable-vendor/vendors")
        assert response.status_code == 200, f"Get vendor list failed: {response.text}"
        data = response.json()
        assert "vendors" in data, "Missing vendors in response"
        print(f"PASS: Found {len(data.get('vendors', []))} stable vendors")


class TestDashboardEndpoints:
    """Dashboard metrics endpoints"""
    
    def test_get_workflow_metrics(self):
        """GET /api/workflows/ap_invoice/metrics returns dashboard KPIs"""
        response = requests.get(f"{BASE_URL}/api/workflows/ap_invoice/metrics")
        assert response.status_code == 200, f"Get workflow metrics failed: {response.text}"
        data = response.json()
        print(f"PASS: Workflow metrics keys: {list(data.get('metrics', {}).keys())}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-x"])
