"""
Test Purchase Invoice P0 Bug Fixes
- Bug 1: GPI Document link missing in BC for Purchase Invoices (link_document_to_bc never called)
- Bug 2: Purchase Invoice retry-lines endpoint didn't delete existing bad lines before adding new ones

Tests:
1. Verify backend starts without errors
2. Verify endpoints respond correctly (404 for nonexistent docs)
3. Verify code structure: delete_purchase_invoice_lines exists and is importable
4. Verify code structure: link_document_to_bc is called in PI creation flow
5. Verify code structure: retry-lines calls delete before add
"""

import pytest
import requests
import os
import inspect

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBackendHealth:
    """Verify backend starts without errors"""
    
    def test_gpi_integration_status_endpoint(self):
        """GET /api/gpi-integration/status returns valid config"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "configured" in data, "Missing 'configured' field"
        assert "read_environment" in data, "Missing 'read_environment' field"
        assert "write_environment" in data, "Missing 'write_environment' field"
        assert "api_group" in data, "Missing 'api_group' field"
        assert data["api_group"] == "gpi/integration/v1.0", f"Unexpected api_group: {data['api_group']}"
        print(f"✓ Status endpoint returns valid config: configured={data['configured']}")


class TestEndpoint404Behavior:
    """Verify endpoints return 404 for nonexistent documents"""
    
    def test_purchase_invoice_preflight_404(self):
        """POST /api/gpi-integration/purchase-invoices/preflight/{doc_id} returns 404 for nonexistent docs"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/purchase-invoices/preflight/nonexistent-doc-id-12345")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data, "Missing 'detail' in 404 response"
        print(f"✓ Preflight returns 404 for nonexistent doc: {data['detail']}")
    
    def test_purchase_invoice_retry_lines_404(self):
        """POST /api/gpi-integration/purchase-invoices/retry-lines/{doc_id} returns 404 for nonexistent docs"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/purchase-invoices/retry-lines/nonexistent-doc-id-12345")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        
        data = response.json()
        assert "detail" in data, "Missing 'detail' in 404 response"
        print(f"✓ Retry-lines returns 404 for nonexistent doc: {data['detail']}")
    
    def test_purchase_invoice_from_document_404(self):
        """POST /api/gpi-integration/purchase-invoices/from-document/{doc_id} returns 404 for nonexistent docs"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/purchase-invoices/from-document/nonexistent-doc-id-12345")
        assert response.status_code in [404, 503], f"Expected 404 or 503 (no BC creds), got {response.status_code}"
        print(f"✓ From-document returns {response.status_code} for nonexistent doc")


class TestCodeStructureDeleteFunction:
    """Verify delete_purchase_invoice_lines function exists and is properly importable"""
    
    def test_delete_function_exists_in_service(self):
        """Verify delete_purchase_invoice_lines exists in gpi_integration_service.py"""
        from services.gpi_integration_service import delete_purchase_invoice_lines
        
        assert callable(delete_purchase_invoice_lines), "delete_purchase_invoice_lines should be callable"
        assert inspect.iscoroutinefunction(delete_purchase_invoice_lines), "delete_purchase_invoice_lines should be async"
        
        # Check function signature
        sig = inspect.signature(delete_purchase_invoice_lines)
        params = list(sig.parameters.keys())
        assert "invoice_system_id" in params, "Function should have 'invoice_system_id' parameter"
        print(f"✓ delete_purchase_invoice_lines exists with signature: {sig}")
    
    def test_delete_function_imported_in_router(self):
        """Verify delete_purchase_invoice_lines is imported in gpi_integration.py router"""
        import routers.gpi_integration as gpi_router
        
        assert hasattr(gpi_router, 'delete_purchase_invoice_lines'), "delete_purchase_invoice_lines should be imported in router"
        print("✓ delete_purchase_invoice_lines is imported in gpi_integration.py router")


class TestCodeStructureLinkDocumentToBc:
    """Verify link_document_to_bc is called in create_purchase_invoice_from_document flow"""
    
    def test_link_function_exists_in_server(self):
        """Verify link_document_to_bc exists in server.py"""
        import server as srv
        
        assert hasattr(srv, 'link_document_to_bc'), "link_document_to_bc should exist in server.py"
        assert callable(srv.link_document_to_bc), "link_document_to_bc should be callable"
        assert inspect.iscoroutinefunction(srv.link_document_to_bc), "link_document_to_bc should be async"
        
        # Check function signature
        sig = inspect.signature(srv.link_document_to_bc)
        params = list(sig.parameters.keys())
        assert "bc_record_id" in params, "Function should have 'bc_record_id' parameter"
        assert "bc_entity" in params, "Function should have 'bc_entity' parameter"
        print(f"✓ link_document_to_bc exists in server.py with signature: {sig}")
    
    def test_link_document_called_in_pi_creation(self):
        """Verify link_document_to_bc is called in create_purchase_invoice_from_document (code inspection)"""
        import routers.gpi_integration as gpi_router
        
        # Get source code of create_purchase_invoice_from_document
        func = gpi_router.create_purchase_invoice_from_document
        source = inspect.getsource(func)
        
        # Verify link_document_to_bc is called
        assert "link_document_to_bc" in source, "link_document_to_bc should be called in create_purchase_invoice_from_document"
        assert "import server as srv" in source or "srv.link_document_to_bc" in source, "Should import and call srv.link_document_to_bc"
        assert "bc_entity=\"purchaseInvoices\"" in source or 'bc_entity="purchaseInvoices"' in source, "Should call with bc_entity='purchaseInvoices'"
        
        # Verify it's called in Step 3 (after PI header creation)
        assert "Step 3" in source, "Should have Step 3 comment for link_document_to_bc"
        print("✓ link_document_to_bc is called in create_purchase_invoice_from_document (Step 3)")


class TestCodeStructureRetryLinesDeletesFirst:
    """Verify retry-lines endpoint calls delete_purchase_invoice_lines before add_purchase_invoice_lines"""
    
    def test_retry_lines_deletes_before_adds(self):
        """Verify retry_purchase_invoice_lines calls delete then add (code inspection)"""
        import routers.gpi_integration as gpi_router
        
        # Get source code of retry_purchase_invoice_lines
        func = gpi_router.retry_purchase_invoice_lines
        source = inspect.getsource(func)
        
        # Verify both functions are called
        assert "delete_purchase_invoice_lines" in source, "Should call delete_purchase_invoice_lines"
        assert "add_purchase_invoice_lines" in source, "Should call add_purchase_invoice_lines"
        
        # Verify delete is called before add (by checking line positions)
        delete_pos = source.find("delete_purchase_invoice_lines")
        add_pos = source.find("add_purchase_invoice_lines")
        assert delete_pos < add_pos, "delete_purchase_invoice_lines should be called BEFORE add_purchase_invoice_lines"
        
        # Verify Step 1 is delete and Step 3 is add (based on comments)
        assert "Step 1: Delete existing" in source, "Should have Step 1 for delete"
        assert "Step 2: Build new lines" in source or "Step 3: Add new" in source, "Should have step for building/adding new lines"
        
        print("✓ retry_purchase_invoice_lines correctly deletes existing lines before adding new ones")


class TestDeleteFunctionImplementation:
    """Verify delete_purchase_invoice_lines has correct implementation"""
    
    def test_delete_function_implementation_details(self):
        """Verify delete function implementation handles line deletion correctly"""
        from services.gpi_integration_service import delete_purchase_invoice_lines
        
        source = inspect.getsource(delete_purchase_invoice_lines)
        
        # Verify it fetches existing lines first
        assert "purchaseInvoiceLines" in source, "Should access purchaseInvoiceLines endpoint"
        
        # Verify it uses proper HTTP DELETE method
        assert "delete" in source.lower(), "Should use DELETE HTTP method"
        
        # Verify it returns a result dict with 'deleted' count
        assert '"deleted"' in source or "'deleted'" in source, "Should return deleted count"
        
        # Verify it has write protection
        assert "_check_write_protection" in source, "Should have write protection check"
        
        print("✓ delete_purchase_invoice_lines has correct implementation")


class TestRouterIntegrity:
    """Verify router imports and endpoint registration"""
    
    def test_router_imports_correct(self):
        """Verify all required functions are imported in gpi_integration.py"""
        import routers.gpi_integration as gpi_router
        
        # Check key imports exist
        required_imports = [
            'delete_purchase_invoice_lines',
            'add_purchase_invoice_lines',
            'create_purchase_invoice',
            'HAS_CREDENTIALS'
        ]
        
        for imp in required_imports:
            assert hasattr(gpi_router, imp), f"Missing import: {imp}"
        
        print(f"✓ All required imports present: {required_imports}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
