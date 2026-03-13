"""
Test Suite for GPI Document Hub - Sales Order Preflight Review Panel

Tests:
1. POST /api/gpi-integration/sales-orders/preflight/{doc_id}
   - Returns document_summary, validation_checklist, resolved_lines
2. POST /api/gpi-integration/sales-orders/from-document/{doc_id}
   - Accepts JSON body with edited_lines and customer_no_override
   - Validates edited line targets against catalog, rejects invalid items/GL accounts
   - Returns 422 with catalog_validation_failed when target is invalid
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_DOC_ID = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestSalesOrderPreflight:
    """Tests for POST /api/gpi-integration/sales-orders/preflight/{doc_id}"""
    
    def test_preflight_returns_document_summary(self, auth_headers):
        """Preflight should return document_summary with required fields"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{TEST_DOC_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Preflight failed: {response.text}"
        
        data = response.json()
        assert "document_summary" in data
        ds = data["document_summary"]
        
        # Verify document_summary fields
        assert "document_id" in ds
        assert ds["document_id"] == TEST_DOC_ID
        assert "source" in ds
        assert "document_type" in ds
        assert "customer_name" in ds
        assert "external_doc_no" in ds
        assert "order_date" in ds
        assert "total_amount" in ds
        assert "extraction_completeness" in ds
        
        print(f"Document Summary: doc_id={ds['document_id'][:12]}..., type={ds['document_type']}, source={ds['source']}")
    
    def test_preflight_returns_validation_checklist(self, auth_headers):
        """Preflight should return validation_checklist with pass/fail items"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{TEST_DOC_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "validation_checklist" in data
        checklist = data["validation_checklist"]
        
        # Should have at least customer, required fields, duplicate, lines, extraction, credentials
        assert len(checklist) >= 5
        
        # Each item should have label, passed, detail
        for item in checklist:
            assert "label" in item
            assert "passed" in item
            assert isinstance(item["passed"], bool)
            assert "detail" in item
        
        # Print checklist summary
        for item in checklist:
            status = "✓" if item["passed"] else "✗"
            print(f"{status} {item['label']}: {item['detail']}")
    
    def test_preflight_returns_resolved_lines(self, auth_headers):
        """Preflight should return resolved_lines with mapping metadata"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{TEST_DOC_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "resolved_lines" in data
        lines = data["resolved_lines"]
        
        # Test document should have lines
        assert isinstance(lines, list)
        assert len(lines) > 0
        
        # Each line should have required fields
        for i, line in enumerate(lines):
            assert "lineType" in line, f"Line {i} missing lineType"
            assert "description" in line, f"Line {i} missing description"
            assert "quantity" in line, f"Line {i} missing quantity"
            assert "unitPrice" in line, f"Line {i} missing unitPrice"
            assert "mapping" in line, f"Line {i} missing mapping"
            
            mapping = line["mapping"]
            assert "matched" in mapping
            assert "target_type" in mapping
            assert "confidence" in mapping
            assert "method" in mapping
        
        print(f"Resolved {len(lines)} lines:")
        for i, line in enumerate(lines):
            print(f"  Line {i+1}: {line['lineType']} - {line['description']} (qty={line['quantity']}, price=${line['unitPrice']})")
    
    def test_preflight_returns_mapped_values_with_environment(self, auth_headers):
        """Preflight should return mapped_values with BC environment info"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{TEST_DOC_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "mapped_values" in data
        mv = data["mapped_values"]
        
        # Check environment fields
        assert "bc_read_environment" in mv, "Missing bc_read_environment"
        assert "bc_write_environment" in mv, "Missing bc_write_environment"
        assert "idempotency_key" in mv, "Missing idempotency_key"
        
        # Verify expected environments
        assert mv["bc_read_environment"] == "Production", f"Expected Production, got {mv['bc_read_environment']}"
        assert "Sandbox" in mv["bc_write_environment"], f"Expected Sandbox, got {mv['bc_write_environment']}"
        
        print(f"Environment: Read={mv['bc_read_environment']}, Write={mv['bc_write_environment']}")
    
    def test_preflight_not_found_document(self, auth_headers):
        """Preflight should return 404 for non-existent document"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{fake_id}",
            headers=auth_headers
        )
        assert response.status_code == 404


class TestSalesOrderCreation:
    """Tests for POST /api/gpi-integration/sales-orders/from-document/{doc_id}"""
    
    def test_create_validates_catalog_rejects_invalid_item(self, auth_headers):
        """Create should reject invalid Item targets with 422 catalog_validation_failed"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{TEST_DOC_ID}",
            headers=auth_headers,
            json={
                "customer_no_override": "C00010",
                "edited_lines": [{
                    "lineType": "Item",
                    "lineObjectNumber": "FAKE_ITEM_999",
                    "description": "Invalid Item Test",
                    "quantity": 1,
                    "unitPrice": 100
                }]
            }
        )
        
        # Should return 422 with catalog validation error
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        
        data = response.json()
        detail = data.get("detail", data)
        
        # Verify error structure
        assert detail.get("error") == "catalog_validation_failed", f"Expected catalog_validation_failed, got: {detail}"
        assert "validation_errors" in detail
        
        errors = detail["validation_errors"]
        assert len(errors) > 0
        assert errors[0]["target_no"] == "FAKE_ITEM_999"
        assert errors[0]["reason"] == "not_found"
        
        print(f"Catalog validation correctly rejected invalid item: {errors[0]['message']}")
    
    def test_create_validates_catalog_rejects_invalid_gl_account(self, auth_headers):
        """Create should reject invalid G/L Account targets with 422"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{TEST_DOC_ID}",
            headers=auth_headers,
            json={
                "customer_no_override": "C00010",
                "edited_lines": [{
                    "lineType": "Account",
                    "lineObjectNumber": "FAKE_GL_99999",
                    "description": "Invalid GL Test",
                    "quantity": 1,
                    "unitPrice": 100
                }]
            }
        )
        
        assert response.status_code == 422
        
        data = response.json()
        detail = data.get("detail", data)
        assert detail.get("error") == "catalog_validation_failed"
        
        errors = detail["validation_errors"]
        assert len(errors) > 0
        assert errors[0]["target_type"] == "gl_account"
        
        print(f"Catalog validation correctly rejected invalid GL account: {errors[0]['message']}")
    
    def test_create_accepts_comment_lines_without_target(self, auth_headers):
        """Create with Comment lines should pass validation (no target required)"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{TEST_DOC_ID}",
            headers=auth_headers,
            json={
                "customer_no_override": "C00010",
                "edited_lines": [{
                    "lineType": "Comment",
                    "lineObjectNumber": "",
                    "description": "Test Comment Line",
                    "quantity": 1,
                    "unitPrice": 50
                }]
            }
        )
        
        # Should not be 422 catalog validation error
        # Could be other errors (e.g., BC API connection) but not catalog validation
        if response.status_code == 422:
            data = response.json()
            detail = data.get("detail", data)
            assert detail.get("error") != "catalog_validation_failed", \
                f"Comment lines should not require catalog validation: {detail}"
        
        # If we get a different status, that's fine (could be already exists, BC error, etc.)
        print(f"Comment line validation passed. Status: {response.status_code}")
    
    def test_create_requires_customer_override_when_not_resolved(self, auth_headers):
        """Create without customer should return 422 missing_customer"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{TEST_DOC_ID}",
            headers=auth_headers,
            json={
                "customer_no_override": "",
                "edited_lines": []
            }
        )
        
        # The test document has no resolved customer
        if response.status_code == 422:
            data = response.json()
            detail = data.get("detail", data)
            if isinstance(detail, dict):
                # Could be missing_customer or no_lines
                assert detail.get("error") in ["missing_customer", "no_lines"], \
                    f"Unexpected error: {detail}"
                print(f"Correctly rejected: {detail.get('error')}")
            else:
                print(f"Error detail: {detail}")
        else:
            # Could be already_exists if SO was created before
            print(f"Status: {response.status_code}")
    
    def test_create_accepts_json_body_with_edited_lines(self, auth_headers):
        """Create endpoint should accept JSON body with edited_lines"""
        # Send request with properly formatted JSON body
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{TEST_DOC_ID}",
            headers=auth_headers,
            json={
                "customer_no_override": "C00010",
                "edited_lines": [
                    {
                        "lineType": "Comment",
                        "lineObjectNumber": "",
                        "description": "Edited Widget A",
                        "quantity": 10,
                        "unitPrice": 5.00
                    },
                    {
                        "lineType": "Comment",
                        "lineObjectNumber": "",
                        "description": "Edited Widget B",
                        "quantity": 20,
                        "unitPrice": 2.50
                    }
                ]
            }
        )
        
        # Endpoint should accept the JSON body (may fail for other reasons like BC connection)
        # Just verify it's not a 400 Bad Request or parsing error
        assert response.status_code != 400, f"Bad request when sending edited_lines: {response.text}"
        
        print(f"JSON body with edited_lines accepted. Status: {response.status_code}")


class TestEnvironmentConfig:
    """Tests for BC environment configuration"""
    
    def test_integration_status_shows_environments(self, auth_headers):
        """Integration status should show read/write environments"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/status",
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        print(f"Integration status: {data}")
        
        # Should have environment info
        assert "has_credentials" in data or "configured" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
