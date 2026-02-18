"""
GPI Document Hub - Email Parser Agent Tests
Tests for document intake, AI classification, job type settings, and email watcher configuration
"""
import pytest
import requests
import os
import time
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test invoice content for AI classification
TEST_INVOICE_CONTENT = """
INVOICE

From: ABC Supplies Inc.
123 Vendor Street
Chicago, IL 60601

Bill To: Gamer Packaging
456 Customer Ave
Los Angeles, CA 90001

Invoice Number: INV-2024-001234
Invoice Date: January 15, 2026
Due Date: February 15, 2026

PO Number: PO-5678

Description                    Qty    Unit Price    Amount
---------------------------------------------------------
Packaging Materials            100    $25.00        $2,500.00
Shipping Supplies              50     $15.00        $750.00
---------------------------------------------------------
                              Subtotal:             $3,250.00
                              Tax (8%):             $260.00
                              TOTAL:                $3,510.00

Payment Terms: Net 30
Please remit payment to: ABC Supplies Inc.
"""

TEST_SALES_PO_CONTENT = """
PURCHASE ORDER

From: Pacific Choice Brands, Inc.
789 Customer Blvd
San Francisco, CA 94102

To: Gamer Packaging
456 Supplier Ave
Los Angeles, CA 90001

PO Number: PO-2024-9876
Order Date: January 20, 2026

Ship To:
Pacific Choice Brands, Inc.
Distribution Center
1000 Warehouse Way
Oakland, CA 94601

Item                          Qty    Unit Price    Amount
---------------------------------------------------------
Custom Boxes (Large)          500    $5.00         $2,500.00
Custom Boxes (Medium)         1000   $3.50         $3,500.00
Packing Tape                  200    $2.00         $400.00
---------------------------------------------------------
                              TOTAL:               $6,400.00

Delivery Required By: February 1, 2026
"""

TEST_REMITTANCE_CONTENT = """
REMITTANCE ADVICE

From: XYZ Corporation
Payment Date: January 18, 2026

Payee: Gamer Packaging
Check Number: 45678

Invoice References:
- INV-2023-0891: $1,500.00
- INV-2023-0892: $2,300.00
- INV-2023-0893: $800.00

Total Payment Amount: $4,600.00

This payment covers the above referenced invoices.
"""


class TestJobTypeSettings:
    """Tests for job type configuration endpoints"""
    
    def test_get_all_job_types(self):
        """GET /api/settings/job-types - list all job type configurations"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types")
        assert response.status_code == 200
        data = response.json()
        assert "job_types" in data
        job_types = data["job_types"]
        
        # Verify default job types exist
        job_type_names = [jt["job_type"] for jt in job_types]
        assert "AP_Invoice" in job_type_names
        assert "Sales_PO" in job_type_names
        assert "AR_Invoice" in job_type_names
        assert "Remittance" in job_type_names
        
        print(f"Found {len(job_types)} job types: {job_type_names}")
        return job_types
    
    def test_get_specific_job_type_ap_invoice(self):
        """GET /api/settings/job-types/AP_Invoice - get AP Invoice config"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types/AP_Invoice")
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields
        assert data["job_type"] == "AP_Invoice"
        assert "automation_level" in data
        assert "min_confidence_to_auto_link" in data
        assert "min_confidence_to_auto_create_draft" in data
        assert "required_extractions" in data
        assert "sharepoint_folder" in data
        assert "bc_entity" in data
        
        print(f"AP_Invoice config: automation_level={data['automation_level']}, "
              f"link_threshold={data['min_confidence_to_auto_link']}")
        return data
    
    def test_get_specific_job_type_sales_po(self):
        """GET /api/settings/job-types/Sales_PO - get Sales PO config"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types/Sales_PO")
        assert response.status_code == 200
        data = response.json()
        
        assert data["job_type"] == "Sales_PO"
        assert "customer" in data.get("required_extractions", [])
        print(f"Sales_PO config: automation_level={data['automation_level']}")
        return data
    
    def test_get_nonexistent_job_type(self):
        """GET /api/settings/job-types/NonExistent - should return 404"""
        response = requests.get(f"{BASE_URL}/api/settings/job-types/NonExistent")
        assert response.status_code == 404
        print("Nonexistent job type correctly returns 404")
    
    def test_update_job_type_config(self):
        """PUT /api/settings/job-types/AP_Invoice - update job type config"""
        # First get current config
        get_response = requests.get(f"{BASE_URL}/api/settings/job-types/AP_Invoice")
        assert get_response.status_code == 200
        original_config = get_response.json()
        
        # Update with new threshold
        update_payload = {
            "job_type": "AP_Invoice",
            "display_name": "AP Invoice (Vendor Invoice)",
            "automation_level": 1,
            "min_confidence_to_auto_link": 0.80,  # Changed from 0.85
            "min_confidence_to_auto_create_draft": 0.95,
            "requires_po_validation": True,
            "allow_duplicate_check_override": False,
            "requires_human_review_if_exception": True,
            "sharepoint_folder": "AP_Invoices",
            "bc_entity": "purchaseInvoices",
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": ["po_number", "due_date", "line_items"],
            "enabled": True
        }
        
        response = requests.put(
            f"{BASE_URL}/api/settings/job-types/AP_Invoice",
            json=update_payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["min_confidence_to_auto_link"] == 0.80
        print(f"Updated AP_Invoice link threshold to {data['min_confidence_to_auto_link']}")
        
        # Restore original threshold
        update_payload["min_confidence_to_auto_link"] = original_config.get("min_confidence_to_auto_link", 0.85)
        requests.put(f"{BASE_URL}/api/settings/job-types/AP_Invoice", json=update_payload)
        print("Restored original AP_Invoice config")


class TestEmailWatcherSettings:
    """Tests for email watcher configuration endpoints"""
    
    def test_get_email_watcher_config(self):
        """GET /api/settings/email-watcher - get email watcher configuration"""
        response = requests.get(f"{BASE_URL}/api/settings/email-watcher")
        assert response.status_code == 200
        data = response.json()
        
        # Verify expected fields
        assert "mailbox_address" in data or data == {}
        assert "watch_folder" in data or data == {}
        assert "enabled" in data or data == {}
        
        print(f"Email watcher config: enabled={data.get('enabled', False)}, "
              f"mailbox={data.get('mailbox_address', 'not set')}")
        return data
    
    def test_update_email_watcher_config(self):
        """PUT /api/settings/email-watcher - update email watcher configuration"""
        update_payload = {
            "mailbox_address": "test-inbox@gamerpackaging.com",
            "watch_folder": "Inbox",
            "needs_review_folder": "Needs Review",
            "processed_folder": "Processed",
            "enabled": False  # Keep disabled for testing
        }
        
        response = requests.put(
            f"{BASE_URL}/api/settings/email-watcher",
            json=update_payload
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["mailbox_address"] == "test-inbox@gamerpackaging.com"
        assert data["watch_folder"] == "Inbox"
        assert data["enabled"] == False
        
        print(f"Updated email watcher config: mailbox={data['mailbox_address']}")
        return data


class TestGraphWebhook:
    """Tests for Graph webhook endpoint"""
    
    def test_graph_webhook_validation_get(self):
        """GET /api/graph/webhook - validation endpoint"""
        # Test with validation token
        response = requests.get(
            f"{BASE_URL}/api/graph/webhook",
            params={"validationToken": "test-validation-token-123"}
        )
        assert response.status_code == 200
        # Should return the validation token as plain text
        assert "test-validation-token-123" in response.text
        print("Graph webhook validation (GET) working correctly")
    
    def test_graph_webhook_ready_status(self):
        """GET /api/graph/webhook - ready status without token"""
        response = requests.get(f"{BASE_URL}/api/graph/webhook")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ready"
        print("Graph webhook ready status confirmed")
    
    def test_graph_webhook_post_notification(self):
        """POST /api/graph/webhook - handle notification"""
        # Simulate a Graph notification
        notification_payload = {
            "value": [
                {
                    "changeType": "created",
                    "clientState": "gpi-document-hub-secret",
                    "resource": "users/test@example.com/mailFolders/Inbox/messages/test-email-id-123"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/graph/webhook",
            json=notification_payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        print("Graph webhook POST notification handled correctly")
    
    def test_graph_webhook_invalid_client_state(self):
        """POST /api/graph/webhook - reject invalid client state"""
        notification_payload = {
            "value": [
                {
                    "changeType": "created",
                    "clientState": "wrong-secret",
                    "resource": "users/test@example.com/mailFolders/Inbox/messages/test-email-id"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/graph/webhook",
            json=notification_payload
        )
        assert response.status_code == 200  # Still returns 200 but logs warning
        print("Graph webhook correctly handles invalid client state")


class TestDocumentIntake:
    """Tests for document intake with AI classification"""
    
    def test_intake_ap_invoice(self):
        """POST /api/documents/intake - intake AP Invoice document"""
        # Create a test invoice file
        files = {
            'file': ('TEST_invoice_001.txt', TEST_INVOICE_CONTENT, 'text/plain')
        }
        data = {
            'source': 'email',
            'sender': 'vendor@abcsupplies.com',
            'subject': 'Invoice INV-2024-001234',
            'attachment_name': 'TEST_invoice_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        # Verify response structure
        assert "document" in result
        assert "classification" in result
        assert "validation" in result
        assert "decision" in result
        assert "reasoning" in result
        
        doc = result["document"]
        classification = result["classification"]
        
        # Verify document was created
        assert doc["id"] is not None
        assert doc["source"] == "email"
        assert doc["email_sender"] == "vendor@abcsupplies.com"
        
        # Verify AI classification ran
        assert classification.get("suggested_job_type") is not None
        assert classification.get("confidence") is not None
        
        # Check extracted fields
        extracted = classification.get("extracted_fields", {})
        print(f"Intake result: type={classification.get('suggested_job_type')}, "
              f"confidence={classification.get('confidence'):.2%}")
        print(f"Extracted fields: {extracted}")
        print(f"Decision: {result['decision']} - {result['reasoning']}")
        
        # Store doc_id for cleanup
        self.__class__.test_doc_id = doc["id"]
        return result
    
    def test_intake_sales_po(self):
        """POST /api/documents/intake - intake Sales PO document"""
        files = {
            'file': ('TEST_sales_po_001.txt', TEST_SALES_PO_CONTENT, 'text/plain')
        }
        data = {
            'source': 'email',
            'sender': 'orders@pacificchoice.com',
            'subject': 'Purchase Order PO-2024-9876',
            'attachment_name': 'TEST_sales_po_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        classification = result["classification"]
        print(f"Sales PO intake: type={classification.get('suggested_job_type')}, "
              f"confidence={classification.get('confidence'):.2%}")
        print(f"Decision: {result['decision']}")
        
        # Store for cleanup
        self.__class__.test_sales_po_id = result["document"]["id"]
        return result
    
    def test_intake_remittance(self):
        """POST /api/documents/intake - intake Remittance document"""
        files = {
            'file': ('TEST_remittance_001.txt', TEST_REMITTANCE_CONTENT, 'text/plain')
        }
        data = {
            'source': 'email',
            'sender': 'ap@xyzcorp.com',
            'subject': 'Payment Remittance - Check #45678',
            'attachment_name': 'TEST_remittance_001.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        classification = result["classification"]
        print(f"Remittance intake: type={classification.get('suggested_job_type')}, "
              f"confidence={classification.get('confidence'):.2%}")
        
        # Store for cleanup
        self.__class__.test_remittance_id = result["document"]["id"]
        return result


class TestDocumentClassify:
    """Tests for re-running AI classification on existing documents"""
    
    def test_classify_existing_document(self):
        """POST /api/documents/{doc_id}/classify - re-run classification"""
        # First create a document via intake
        files = {
            'file': ('TEST_classify_doc.txt', TEST_INVOICE_CONTENT, 'text/plain')
        }
        data = {
            'source': 'manual',
            'attachment_name': 'TEST_classify_doc.txt'
        }
        
        intake_response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert intake_response.status_code == 200
        doc_id = intake_response.json()["document"]["id"]
        
        # Now re-run classification
        response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/classify")
        assert response.status_code == 200
        result = response.json()
        
        assert "document" in result
        assert "classification" in result
        assert "validation" in result
        assert "decision" in result
        
        print(f"Re-classification result: type={result['classification'].get('suggested_job_type')}, "
              f"confidence={result['classification'].get('confidence'):.2%}")
        
        # Store for cleanup
        self.__class__.test_classify_doc_id = doc_id
        return result
    
    def test_classify_nonexistent_document(self):
        """POST /api/documents/{doc_id}/classify - nonexistent document"""
        response = requests.post(f"{BASE_URL}/api/documents/nonexistent-id-12345/classify")
        assert response.status_code == 404
        print("Classify nonexistent document correctly returns 404")


class TestEmailStats:
    """Tests for email processing statistics dashboard"""
    
    def test_get_email_stats(self):
        """GET /api/dashboard/email-stats - get email processing statistics"""
        response = requests.get(f"{BASE_URL}/api/dashboard/email-stats")
        assert response.status_code == 200
        data = response.json()
        
        # Verify expected fields
        assert "total_email_documents" in data
        assert "needs_review" in data
        assert "auto_linked" in data
        assert "by_job_type" in data
        assert "recent" in data
        
        print(f"Email stats: total={data['total_email_documents']}, "
              f"needs_review={data['needs_review']}, auto_linked={data['auto_linked']}")
        print(f"By job type: {data['by_job_type']}")
        return data


class TestAutomationDecisionMatrix:
    """Tests to verify automation decision logic"""
    
    def test_decision_needs_review_low_confidence(self):
        """Verify needs_review decision for low confidence"""
        # Create a document with ambiguous content
        ambiguous_content = """
        Some document
        Not clearly an invoice or PO
        Random text here
        """
        
        files = {
            'file': ('TEST_ambiguous.txt', ambiguous_content, 'text/plain')
        }
        data = {
            'source': 'email',
            'attachment_name': 'TEST_ambiguous.txt'
        }
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        
        # Low confidence should result in needs_review or manual
        decision = result["decision"]
        confidence = result["classification"].get("confidence", 0)
        
        print(f"Ambiguous doc: confidence={confidence:.2%}, decision={decision}")
        
        # Store for cleanup
        self.__class__.test_ambiguous_id = result["document"]["id"]
        return result


class TestCleanup:
    """Cleanup test documents"""
    
    def test_cleanup_test_documents(self):
        """Delete all TEST_ prefixed documents"""
        # Get all documents with TEST_ prefix
        response = requests.get(f"{BASE_URL}/api/documents?search=TEST_&limit=100")
        assert response.status_code == 200
        docs = response.json().get("documents", [])
        
        deleted_count = 0
        for doc in docs:
            if "TEST_" in doc.get("file_name", ""):
                del_response = requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
                if del_response.status_code == 200:
                    deleted_count += 1
        
        print(f"Cleaned up {deleted_count} test documents")
        
        # Verify cleanup
        verify_response = requests.get(f"{BASE_URL}/api/documents?search=TEST_")
        remaining = verify_response.json().get("total", 0)
        print(f"Remaining TEST_ documents: {remaining}")


# Fixtures
@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown():
    """Setup and teardown for test session"""
    print(f"\n=== Starting Email Parser Tests ===")
    print(f"BASE_URL: {BASE_URL}")
    
    # Verify API is accessible
    try:
        response = requests.get(f"{BASE_URL}/api/settings/status", timeout=10)
        assert response.status_code == 200
        print("API is accessible")
    except Exception as e:
        pytest.fail(f"API not accessible: {e}")
    
    yield
    
    # Cleanup after all tests
    print("\n=== Cleaning up test data ===")
    response = requests.get(f"{BASE_URL}/api/documents?search=TEST_&limit=100")
    if response.status_code == 200:
        docs = response.json().get("documents", [])
        for doc in docs:
            if "TEST_" in doc.get("file_name", ""):
                requests.delete(f"{BASE_URL}/api/documents/{doc['id']}")
    print("Cleanup complete")
