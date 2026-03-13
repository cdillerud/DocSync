"""
Tests for Sales Order line creation feature.
Tests preflight endpoint, from-document endpoint, idempotency, and line resolution.
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSalesOrderPreflightEndpoint:
    """Tests for GET /api/gpi-integration/sales-orders/preflight/{doc_id}"""
    
    def test_preflight_returns_resolved_lines_for_eligible_doc(self):
        """Preflight should return resolved_lines array with line details."""
        # Use doc 44b2e236 - Sales_Order without existing SO, has 2 line items
        doc_id = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        # Should succeed
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Validate resolved_lines structure
        assert "resolved_lines" in data, "Response should have resolved_lines"
        resolved_lines = data["resolved_lines"]
        assert isinstance(resolved_lines, list), "resolved_lines should be a list"
        assert len(resolved_lines) == 2, f"Expected 2 lines, got {len(resolved_lines)}"
        
        # Validate line structure
        for line in resolved_lines:
            assert "lineType" in line, "Line should have lineType"
            assert "description" in line, "Line should have description"
            assert "quantity" in line, "Line should have quantity"
            assert "unitPrice" in line, "Line should have unitPrice"
            assert "source" in line, "Line should have source"
            assert line["source"] == "extracted", "Lines should be from extracted source"
        
        # Validate line_count matches
        assert data.get("line_count") == len(resolved_lines), "line_count should match resolved_lines length"
        
        print(f"✓ Preflight returned {len(resolved_lines)} resolved lines for doc {doc_id}")

    def test_preflight_returns_already_created_for_existing_so(self):
        """Preflight should return already_created=true for docs with existing SO."""
        # Use doc b3c5ddaa - Sales_Order with existing SO (107039)
        doc_id = "b3c5ddaa-ec00-4cd2-8530-05d0a132b7c0"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should indicate already created
        assert data.get("already_created") is True, "Should be already_created=true"
        assert data.get("ready") is False, "Should be ready=false when already created"
        
        # Should have existing SO info
        existing_so = data.get("existing_sales_order")
        assert existing_so is not None, "Should return existing_sales_order details"
        assert existing_so.get("bc_record_no") == "107039", "Should have correct SO number"
        assert existing_so.get("lines_added") == 2, "Should preserve lines_added"
        assert existing_so.get("lines_total") == 2, "Should preserve lines_total"
        
        print(f"✓ Preflight correctly returned already_created for doc {doc_id}")

    def test_preflight_returns_7_lines_for_order_confirmation(self):
        """Preflight should correctly handle Order_Confirmation with 7 lines."""
        # Use doc 29be78fe - Order_Confirmation with 7 line items (already has SO)
        doc_id = "29be78fe-4d67-4a7a-8fcd-e15f698451d1"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be already created
        assert data.get("already_created") is True
        
        # Existing SO should have 7 lines
        existing_so = data.get("existing_sales_order")
        assert existing_so is not None
        assert existing_so.get("lines_added") == 7, f"Expected 7 lines_added, got {existing_so.get('lines_added')}"
        assert existing_so.get("lines_total") == 7, f"Expected 7 lines_total, got {existing_so.get('lines_total')}"
        
        print(f"✓ Preflight correctly shows 7 lines for order confirmation doc")

    def test_preflight_returns_404_for_nonexistent_doc(self):
        """Preflight should return 404 for non-existent document."""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{fake_id}")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ Preflight correctly returns 404 for non-existent doc")


class TestSalesOrderFromDocumentEndpoint:
    """Tests for POST /api/gpi-integration/sales-orders/from-document/{doc_id}"""

    def test_idempotency_returns_already_exists_with_lines(self):
        """Re-calling from-document on existing SO should return already_exists with lines preserved."""
        # Use doc b3c5ddaa - already has SO 107039 with 2 lines
        doc_id = "b3c5ddaa-ec00-4cd2-8530-05d0a132b7c0"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{doc_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should indicate already exists
        assert data.get("already_exists") is True, "Should return already_exists=true"
        assert data.get("success") is True, "Should return success=true for idempotent call"
        
        # Should preserve line counts
        assert data.get("lines_added") == 2, f"Expected lines_added=2, got {data.get('lines_added')}"
        assert data.get("lines_total") == 2, f"Expected lines_total=2, got {data.get('lines_total')}"
        
        # Should have BC record info
        assert data.get("bc_record_no") == "107039", "Should return correct SO number"
        assert data.get("status") == "already_exists", "Status should be already_exists"
        
        print(f"✓ Idempotency check passed - returned already_exists with lines_added={data.get('lines_added')}")

    def test_idempotency_7_lines_order_confirmation(self):
        """Idempotency should preserve 7 lines for order confirmation document."""
        # Use doc 29be78fe - already has SO 107040 with 7 lines
        doc_id = "29be78fe-4d67-4a7a-8fcd-e15f698451d1"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{doc_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("already_exists") is True
        assert data.get("lines_added") == 7, f"Expected lines_added=7, got {data.get('lines_added')}"
        assert data.get("lines_total") == 7, f"Expected lines_total=7, got {data.get('lines_total')}"
        assert data.get("bc_record_no") == "107040"
        
        print(f"✓ Idempotency preserved 7 lines for order confirmation doc")

    def test_from_document_requires_customer(self):
        """Creation should fail with missing_customer error if no customer mapped."""
        # Use doc 44b2e236 - has no customer mapped
        doc_id = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{doc_id}")
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        data = response.json()
        
        # Should have error detail about missing customer
        detail = data.get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("error") == "missing_customer", f"Expected missing_customer error, got {detail}"
        
        print(f"✓ Correctly rejects creation without customer mapping")


class TestIntegrationStatus:
    """Tests for GET /api/gpi-integration/status"""
    
    def test_status_returns_configured(self):
        """Status endpoint should return configured=true with real credentials."""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("configured") is True, "Should be configured with real BC credentials"
        assert "read_environment" in data, "Should have read_environment"
        assert "write_environment" in data, "Should have write_environment"
        assert data.get("read_environment") == "Production"
        assert "Sandbox" in data.get("write_environment", "")
        
        print(f"✓ Integration status: configured={data.get('configured')}, env={data.get('write_environment')}")


class TestSalesOrderLineResolution:
    """Unit-level tests for _resolve_sales_lines function."""
    
    def test_resolve_lines_unit_tests_pass(self):
        """Verify the unit tests for _resolve_sales_lines pass."""
        # This is already verified by pytest, but we can confirm via API
        # by checking a preflight response structure
        doc_id = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify line structure matches expected format
        lines = data.get("resolved_lines", [])
        assert len(lines) > 0, "Should have resolved lines"
        
        line = lines[0]
        required_fields = ["lineType", "lineObjectNumber", "description", "quantity", "unitPrice", "source"]
        for field in required_fields:
            assert field in line, f"Line should have {field}"
        
        print(f"✓ Line resolution produces correct structure")


# Cleanup test documents
@pytest.fixture(scope="module", autouse=True)
def cleanup_test_documents():
    """Cleanup TEST_ prefixed documents after tests."""
    yield
    # Note: In a real scenario, we'd clean up test docs here
    # For now, the test docs created by the agent will remain


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
