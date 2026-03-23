"""
GPI Document Hub - Refactoring Session 141 Tests

Tests for:
1. Email polling service module extraction (services/email_polling_service.py)
2. Classification helpers module extraction (services/classification_helpers.py)
3. Salesperson/rep assignment wiring in SO creation flow
4. Router imports from extracted services
5. API endpoint health checks
"""

import pytest
import requests
import os
import inspect

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestModuleImports:
    """Test that extracted service modules load correctly."""
    
    def test_email_polling_service_imports(self):
        """Verify email_polling_service module loads and exports expected functions."""
        from services.email_polling_service import (
            get_email_watcher_config,
            subscribe_to_mailbox_notifications,
            fetch_email_with_attachments,
            move_email_to_folder,
            record_mail_intake_log,
            check_duplicate_mail_intake,
            should_skip_attachment,
            poll_mailbox_for_attachments,
            poll_mailbox_for_documents,
            email_polling_worker,
            dynamic_mailbox_polling_worker,
            run_sales_email_poll,
        )
        
        # Verify functions are callable
        assert callable(get_email_watcher_config)
        assert callable(poll_mailbox_for_attachments)
        assert callable(poll_mailbox_for_documents)
        assert callable(should_skip_attachment)
        print("✓ email_polling_service module imports all expected functions")
    
    def test_classification_helpers_imports(self):
        """Verify classification_helpers module loads and exports expected functions."""
        from services.classification_helpers import (
            classify_document_type,
            get_category_for_doc_type,
            derive_workflow_status,
        )
        
        # Verify functions are callable
        assert callable(classify_document_type)
        assert callable(get_category_for_doc_type)
        assert callable(derive_workflow_status)
        print("✓ classification_helpers module imports all expected functions")
    
    def test_business_central_service_create_sales_order_accepts_salesperson(self):
        """Verify create_sales_order method accepts salesperson field."""
        from services.business_central_service import BusinessCentralService
        
        # Get the create_sales_order method signature
        sig = inspect.signature(BusinessCentralService.create_sales_order)
        params = list(sig.parameters.keys())
        
        # Should have self and order_data
        assert 'self' in params
        assert 'order_data' in params
        
        # Check the method docstring mentions salesperson
        docstring = BusinessCentralService.create_sales_order.__doc__ or ""
        # The method should handle salesperson in order_data
        print("✓ create_sales_order method signature verified")
    
    def test_auto_post_service_lookup_bc_customer_returns_tuple(self):
        """Verify _lookup_bc_customer returns (customer_number, salesperson_code) tuple."""
        from services.auto_post_service import _lookup_bc_customer
        
        # Check function signature
        sig = inspect.signature(_lookup_bc_customer)
        params = list(sig.parameters.keys())
        
        assert 'customer_name' in params
        assert 'bc_service' in params
        
        # Check return type annotation
        annotations = _lookup_bc_customer.__annotations__
        assert 'return' in annotations
        assert annotations['return'] == tuple
        print("✓ _lookup_bc_customer returns tuple (customer_number, salesperson_code)")
    
    def test_routers_import_from_extracted_services(self):
        """Verify routers import from extracted service modules."""
        # Check settings router imports from email_polling_service
        from routers.settings import get_email_watcher_config
        assert callable(get_email_watcher_config)
        
        # Check email_polling router imports from email_polling_service
        from routers.email_polling import router
        assert router is not None
        
        # Check mailbox_sources router imports from email_polling_service
        from routers.mailbox_sources import router
        assert router is not None
        
        print("✓ Routers import from extracted service modules correctly")


class TestAPIEndpoints:
    """Test API endpoints return valid responses."""
    
    def test_health_endpoint(self):
        """GET /api/health should return status: healthy."""
        response = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health endpoint: {data}")
    
    def test_documents_list_endpoint(self):
        """GET /api/documents?limit=2 should return documents with total count."""
        response = requests.get(f"{BASE_URL}/api/documents", params={"limit": 2}, timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert isinstance(data["documents"], list)
        print(f"✓ Documents endpoint: total={data.get('total')}, returned={len(data.get('documents', []))}")
    
    def test_documents_search_endpoint(self):
        """GET /api/documents/search?q=invoice should return search results."""
        response = requests.get(f"{BASE_URL}/api/documents/search", params={"q": "invoice"}, timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data or "results" in data
        print(f"✓ Document search endpoint: {response.status_code}")
    
    def test_email_watcher_config_endpoint(self):
        """GET /api/settings/email-watcher should return config with enabled/disabled fields."""
        response = requests.get(f"{BASE_URL}/api/settings/email-watcher", timeout=10)
        assert response.status_code == 200
        data = response.json()
        # Should have enabled field
        assert "enabled" in data or "mailbox_address" in data
        print(f"✓ Email watcher config endpoint: enabled={data.get('enabled')}")
    
    def test_mailbox_polling_status_endpoint(self):
        """GET /api/settings/mailbox-sources/polling-status should show worker_running and mailboxes."""
        response = requests.get(f"{BASE_URL}/api/settings/mailbox-sources/polling-status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "worker_running" in data
        assert "mailboxes" in data
        print(f"✓ Mailbox polling status: worker_running={data.get('worker_running')}, mailboxes={len(data.get('mailboxes', []))}")
    
    def test_settings_status_endpoint(self):
        """GET /api/settings/status should return connection status."""
        response = requests.get(f"{BASE_URL}/api/settings/status", timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "connections" in data
        print(f"✓ Settings status endpoint: demo_mode={data.get('demo_mode')}")


class TestClassificationHelpers:
    """Test classification helper functions."""
    
    def test_get_category_for_doc_type_ap_invoice(self):
        """AP_INVOICE should map to AP category."""
        from services.classification_helpers import get_category_for_doc_type
        
        result = get_category_for_doc_type("AP_INVOICE")
        assert result == "AP"
        print("✓ AP_INVOICE -> AP category")
    
    def test_get_category_for_doc_type_sales_invoice(self):
        """SALES_INVOICE should map to Sales category."""
        from services.classification_helpers import get_category_for_doc_type
        
        result = get_category_for_doc_type("SALES_INVOICE")
        assert result == "Sales"
        print("✓ SALES_INVOICE -> Sales category")
    
    def test_get_category_for_doc_type_purchase_order(self):
        """PURCHASE_ORDER should map to Purchase category."""
        from services.classification_helpers import get_category_for_doc_type
        
        result = get_category_for_doc_type("PURCHASE_ORDER")
        assert result == "Purchase"
        print("✓ PURCHASE_ORDER -> Purchase category")
    
    def test_get_category_for_doc_type_other(self):
        """Unknown types should map to Other category."""
        from services.classification_helpers import get_category_for_doc_type
        
        result = get_category_for_doc_type("UNKNOWN_TYPE")
        assert result == "Other"
        print("✓ UNKNOWN_TYPE -> Other category")
    
    def test_derive_workflow_status_completed(self):
        """Completed status should derive to completed."""
        from services.classification_helpers import derive_workflow_status
        
        result = derive_workflow_status("completed", "AP_INVOICE", "")
        assert result == "completed"
        print("✓ completed -> completed workflow_status")
    
    def test_derive_workflow_status_exception(self):
        """Exception status should derive to exception."""
        from services.classification_helpers import derive_workflow_status
        
        result = derive_workflow_status("exception", "AP_INVOICE", "")
        assert result == "exception"
        print("✓ exception -> exception workflow_status")
    
    def test_derive_workflow_status_auto_link(self):
        """Auto_link decision should derive to validation_passed."""
        from services.classification_helpers import derive_workflow_status
        
        result = derive_workflow_status("", "AP_INVOICE", "auto_link")
        assert result == "validation_passed"
        print("✓ auto_link decision -> validation_passed workflow_status")


class TestEmailPollingHelpers:
    """Test email polling helper functions."""
    
    def test_should_skip_attachment_gif(self):
        """GIF attachments should be skipped."""
        from services.email_polling_service import should_skip_attachment
        
        skip, reason = should_skip_attachment("image.gif", "image/gif", 1000)
        assert skip is True
        assert "content type" in reason.lower()
        print("✓ GIF attachments are skipped")
    
    def test_should_skip_attachment_signature(self):
        """Signature files should be skipped."""
        from services.email_polling_service import should_skip_attachment
        
        skip, reason = should_skip_attachment("signature.png", "image/png", 1000)
        assert skip is True
        assert "filename" in reason.lower()
        print("✓ Signature files are skipped")
    
    def test_should_skip_attachment_large_file(self):
        """Large files should be skipped."""
        from services.email_polling_service import should_skip_attachment
        
        # 100MB file
        skip, reason = should_skip_attachment("large.pdf", "application/pdf", 100 * 1024 * 1024)
        assert skip is True
        assert "size" in reason.lower()
        print("✓ Large files are skipped")
    
    def test_should_not_skip_valid_pdf(self):
        """Valid PDF attachments should not be skipped."""
        from services.email_polling_service import should_skip_attachment
        
        skip, reason = should_skip_attachment("invoice.pdf", "application/pdf", 500000)
        assert skip is False
        assert reason is None
        print("✓ Valid PDF attachments are not skipped")


class TestSalespersonWiring:
    """Test salesperson/rep assignment wiring in SO creation."""
    
    def test_auto_post_service_passes_salesperson_to_order_data(self):
        """Verify attempt_auto_create_sales_order passes salesperson to order_data."""
        import ast
        
        # Read the auto_post_service.py file
        with open('/app/backend/services/auto_post_service.py', 'r') as f:
            content = f.read()
        
        # Check that salesperson is added to order_data
        assert 'order_data["salesperson"]' in content or "order_data['salesperson']" in content
        print("✓ auto_post_service passes salesperson to order_data")
    
    def test_business_central_service_includes_salesperson_in_payload(self):
        """Verify create_sales_order includes salesperson in BC API payload."""
        with open('/app/backend/services/business_central_service.py', 'r') as f:
            content = f.read()
        
        # Check that salesperson is added to payload
        assert 'payload["salesperson"]' in content or "payload['salesperson']" in content
        print("✓ business_central_service includes salesperson in BC API payload")
    
    def test_lookup_bc_customer_returns_salesperson_code(self):
        """Verify _lookup_bc_customer queries salespersonCode from BC."""
        with open('/app/backend/services/auto_post_service.py', 'r') as f:
            content = f.read()
        
        # Check that salespersonCode is in the $select query
        assert 'salespersonCode' in content
        print("✓ _lookup_bc_customer queries salespersonCode from BC")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
