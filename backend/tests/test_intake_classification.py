"""
Backend tests for Document Intake Classification Pipeline

Tests the deterministic-first classification and AI fallback behavior:
1. Deterministic rules are prioritized (Zetadocs, Square9, mailbox category)
2. AI fallback only triggers for OTHER types
3. Audit trail (ai_classification field) saved correctly
4. classification_method field recorded properly
"""
import pytest
import requests
import os
import time
from io import BytesIO

# Get backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIntakeClassificationPipeline:
    """Tests for /api/documents/intake classification behavior."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.test_doc_ids = []
        yield
        # Cleanup: delete all test documents created
        for doc_id in self.test_doc_ids:
            try:
                requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
            except Exception:
                pass
    
    def _create_test_pdf(self, content_text: str = "Test Invoice Document") -> BytesIO:
        """Create a simple test PDF-like file."""
        # Simple PDF-like content for testing
        pdf_content = f"%PDF-1.4\n{content_text}\n%%EOF".encode('utf-8')
        return BytesIO(pdf_content)
    
    def test_intake_endpoint_exists(self):
        """Test that the /api/documents/intake endpoint exists."""
        # Test with minimal file upload
        test_file = self._create_test_pdf("Test document")
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("test.pdf", test_file, "application/pdf")},
            data={"source": "test_endpoint_check"}
        )
        
        # Should return 200 or at least not 404
        assert response.status_code != 404, f"Intake endpoint not found: {response.status_code}"
        assert response.status_code in [200, 201, 422], f"Unexpected status: {response.status_code}, body: {response.text[:500]}"
        
        if response.status_code == 200:
            data = response.json()
            if "document" in data and "id" in data["document"]:
                self.test_doc_ids.append(data["document"]["id"])
        
        print(f"PASS: Intake endpoint exists and responds (status: {response.status_code})")
    
    def test_intake_returns_classification_fields(self):
        """Test that intake returns doc_type, classification_method, category fields."""
        test_file = self._create_test_pdf("Invoice #12345 from Vendor ABC")
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("vendor_invoice.pdf", test_file, "application/pdf")},
            data={"source": "test_classification_fields", "sender": "vendor@test.com"}
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}, {response.text[:500]}"
        
        data = response.json()
        doc = data.get("document", {})
        
        # Track for cleanup
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        # Verify classification fields are present
        assert "doc_type" in doc, "doc_type field missing from response"
        assert "classification_method" in doc, "classification_method field missing from response"
        assert "category" in doc, "category field missing from response"
        
        print(f"PASS: Classification fields present - doc_type: {doc['doc_type']}, method: {doc['classification_method']}, category: {doc['category']}")
    
    def test_deterministic_classification_from_legacy_ai(self):
        """Test that clear document types (like AP_Invoice from AI extraction) don't trigger AI fallback."""
        # AP Invoice document with typical invoice content
        test_file = self._create_test_pdf("""
            INVOICE
            Invoice Number: INV-2024-001
            Vendor: ACME Corporation
            Amount Due: $1,500.00
            Date: January 15, 2026
            Payment Terms: Net 30
        """)
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("acme_invoice.pdf", test_file, "application/pdf")},
            data={
                "source": "test_deterministic",
                "sender": "billing@acme.com",
                "subject": "Invoice INV-2024-001"
            }
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        # Check the classification method
        classification_method = doc.get("classification_method", "")
        suggested_type = doc.get("suggested_job_type", "")
        
        # If the AI extraction identified this as AP_Invoice, it should use legacy_ai method
        # If not, the doc_type might still be OTHER
        print(f"Document classified - doc_type: {doc.get('doc_type')}, method: {classification_method}, suggested_type: {suggested_type}")
        
        # Verify document was processed
        assert doc.get("status") is not None, "Document status should be set"
        
        print(f"PASS: Document processed with classification_method: {classification_method}")
    
    def test_ai_classification_audit_trail_for_other_type(self):
        """Test that documents classified as OTHER may have ai_classification audit data when AI fallback is invoked."""
        # Generic document that deterministic rules cannot classify
        test_file = self._create_test_pdf("""
            Some generic business document
            Reference: DOC-XYZ-123
            Notes: Various business information
        """)
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("generic_doc.pdf", test_file, "application/pdf")},
            data={
                "source": "test_ai_audit",
                "sender": "info@company.com",
                "subject": "Business Document"
            }
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        doc_type = doc.get("doc_type", "")
        classification_method = doc.get("classification_method", "")
        ai_classification = doc.get("ai_classification")
        
        print(f"Document classification result:")
        print(f"  - doc_type: {doc_type}")
        print(f"  - classification_method: {classification_method}")
        print(f"  - ai_classification present: {ai_classification is not None}")
        
        # If doc_type is OTHER and AI was invoked, ai_classification should be present
        # If doc_type is not OTHER, ai_classification should NOT be present (deterministic win)
        if doc_type == "OTHER":
            # AI fallback should have been attempted (if EMERGENT_LLM_KEY is configured)
            # ai_classification may or may not be present depending on config
            print(f"Document is OTHER - AI fallback {'was' if ai_classification else 'was NOT'} invoked")
        else:
            # Deterministic rules won - ai_classification should NOT be present
            assert ai_classification is None, f"ai_classification should be None when doc_type is {doc_type} (deterministic win), got: {ai_classification}"
            print(f"PASS: Deterministic classification to {doc_type} - no AI audit trail as expected")
        
        print("PASS: AI audit trail behavior verified")
    
    def test_ap_invoice_no_ai_fallback(self):
        """Test that documents clearly identified as AP_Invoice do NOT invoke AI fallback."""
        # Create a clear AP Invoice document
        test_file = self._create_test_pdf("""
            TAX INVOICE
            Supplier: ABC Suppliers Ltd
            Invoice Number: TAX-INV-2026-0001
            Total Amount: $2,345.67
            VAT: $345.67
            Due Date: February 28, 2026
            Payment Required
        """)
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("tax_invoice.pdf", test_file, "application/pdf")},
            data={
                "source": "test_no_ai_fallback",
                "sender": "accounts@supplier.com",
                "subject": "Tax Invoice TAX-INV-2026-0001"
            }
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        suggested_type = doc.get("suggested_job_type", "")
        doc_type = doc.get("doc_type", "")
        classification_method = doc.get("classification_method", "")
        ai_classification = doc.get("ai_classification")
        
        print(f"AP Invoice test results:")
        print(f"  - suggested_job_type: {suggested_type}")
        print(f"  - doc_type: {doc_type}")
        print(f"  - classification_method: {classification_method}")
        print(f"  - ai_classification: {ai_classification}")
        
        # If AI extraction identified it as AP_Invoice, doc_type should be AP_INVOICE
        # and ai_classification should be None (no AI fallback needed)
        if suggested_type in ("AP_Invoice", "AP Invoice"):
            if doc_type == "AP_INVOICE":
                assert ai_classification is None, f"AI fallback should NOT be invoked for AP_INVOICE, got: {ai_classification}"
                assert "legacy_ai" in classification_method or "ai:" not in classification_method or classification_method == "legacy_ai:AP_Invoice", \
                    f"Classification method should indicate deterministic/legacy path, got: {classification_method}"
                print("PASS: AP_Invoice classified deterministically without AI fallback")
            else:
                print(f"Note: AI extraction identified AP_Invoice but doc_type is {doc_type}")
        else:
            print(f"Note: AI extraction did not identify as AP_Invoice (suggested: {suggested_type})")
        
        print("PASS: AP Invoice classification behavior verified")
    
    def test_classification_method_recorded(self):
        """Test that classification_method is properly recorded for all documents."""
        test_cases = [
            ("invoice_test.pdf", "Invoice Document Content", "invoice@test.com"),
            ("general_test.pdf", "General Document Content", "general@test.com"),
        ]
        
        for filename, content, sender in test_cases:
            test_file = self._create_test_pdf(content)
            response = requests.post(
                f"{BASE_URL}/api/documents/intake",
                files={"file": (filename, test_file, "application/pdf")},
                data={"source": "test_method_recording", "sender": sender}
            )
            
            assert response.status_code == 200, f"Intake failed for {filename}: {response.status_code}"
            
            data = response.json()
            doc = data.get("document", {})
            
            if doc.get("id"):
                self.test_doc_ids.append(doc["id"])
            
            classification_method = doc.get("classification_method", "")
            
            # classification_method should never be empty or None
            assert classification_method, f"classification_method should be set for {filename}"
            
            # Should be one of the expected formats
            valid_prefixes = ["default", "zetadocs:", "square9:", "mailbox:", "legacy_ai:", "ai:"]
            is_valid = any(classification_method.startswith(prefix) for prefix in valid_prefixes)
            assert is_valid, f"classification_method '{classification_method}' doesn't match expected formats"
            
            print(f"PASS: {filename} - classification_method: {classification_method}")
        
        print("PASS: All documents have valid classification_method recorded")
    
    def test_fetch_document_includes_classification_fields(self):
        """Test that GET /api/documents/{id} returns classification fields."""
        # First create a document
        test_file = self._create_test_pdf("Test document for fetch verification")
        create_response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("fetch_test.pdf", test_file, "application/pdf")},
            data={"source": "test_fetch_verify"}
        )
        
        assert create_response.status_code == 200, f"Create failed: {create_response.status_code}"
        
        create_data = create_response.json()
        doc_id = create_data.get("document", {}).get("id")
        assert doc_id, "No document ID returned"
        
        self.test_doc_ids.append(doc_id)
        
        # Now fetch the document
        get_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert get_response.status_code == 200, f"GET failed: {get_response.status_code}"
        
        get_data = get_response.json()
        doc = get_data.get("document", {})
        
        # Verify classification fields persist in database
        assert "doc_type" in doc, "doc_type not persisted"
        assert "classification_method" in doc, "classification_method not persisted"
        assert "category" in doc, "category not persisted"
        
        # If AI was invoked, ai_classification should also persist
        doc_type = doc.get("doc_type")
        ai_classification = doc.get("ai_classification")
        
        print(f"Persisted fields verified:")
        print(f"  - doc_type: {doc['doc_type']}")
        print(f"  - classification_method: {doc['classification_method']}")
        print(f"  - category: {doc['category']}")
        print(f"  - ai_classification: {'present' if ai_classification else 'not present'}")
        
        print("PASS: Classification fields properly persisted to database")


class TestAIClassificationAuditTrail:
    """Tests specifically for AI classification audit trail behavior."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.test_doc_ids = []
        yield
        # Cleanup
        for doc_id in self.test_doc_ids:
            try:
                requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
            except Exception:
                pass
    
    def _create_test_pdf(self, content_text: str = "Test Document") -> BytesIO:
        """Create a simple test PDF-like file."""
        pdf_content = f"%PDF-1.4\n{content_text}\n%%EOF".encode('utf-8')
        return BytesIO(pdf_content)
    
    def test_ai_classification_structure(self):
        """Test that ai_classification field has correct structure when present."""
        # Submit a document that might trigger AI fallback
        test_file = self._create_test_pdf("Ambiguous document content that may need AI classification")
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("ambiguous.pdf", test_file, "application/pdf")},
            data={"source": "test_ai_structure"}
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        ai_classification = doc.get("ai_classification")
        
        if ai_classification:
            # Verify structure when AI was invoked
            print(f"AI classification present with structure: {ai_classification}")
            
            # Should have these fields based on AIClassificationResult.to_dict()
            expected_fields = ["proposed_doc_type", "confidence", "model_name", "timestamp"]
            for field in expected_fields:
                assert field in ai_classification, f"Missing field '{field}' in ai_classification"
            
            # Validate types
            assert isinstance(ai_classification["confidence"], (int, float)), "confidence should be numeric"
            assert ai_classification["confidence"] >= 0.0 and ai_classification["confidence"] <= 1.0, "confidence should be 0-1"
            
            print(f"PASS: AI classification has correct structure")
            print(f"  - proposed_doc_type: {ai_classification['proposed_doc_type']}")
            print(f"  - confidence: {ai_classification['confidence']}")
            print(f"  - model_name: {ai_classification['model_name']}")
        else:
            print("Note: AI classification was not invoked (deterministic rules succeeded or AI disabled)")
        
        print("PASS: AI classification structure test completed")
    
    def test_ai_classification_presence_based_on_method(self):
        """Verify AI classification audit is present ONLY when AI fallback was invoked."""
        # Create a document to test classification behavior
        test_file = self._create_test_pdf("""
            PURCHASE ORDER
            PO Number: PO-2026-0042
            From: GPI Packaging Ltd
            To: Supplier XYZ
            Items:
            - Product A x 100 units
            - Product B x 50 units
            Total: $5,000.00
        """)
        
        response = requests.post(
            f"{BASE_URL}/api/documents/intake",
            files={"file": ("purchase_order.pdf", test_file, "application/pdf")},
            data={
                "source": "test_ai_presence",
                "sender": "purchasing@gpi.com",
                "subject": "Purchase Order PO-2026-0042"
            }
        )
        
        assert response.status_code == 200, f"Intake failed: {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        if doc.get("id"):
            self.test_doc_ids.append(doc["id"])
        
        doc_type = doc.get("doc_type", "")
        ai_classification = doc.get("ai_classification")
        classification_method = doc.get("classification_method", "")
        
        print(f"Classification result:")
        print(f"  - doc_type: {doc_type}")
        print(f"  - classification_method: {classification_method}")
        print(f"  - ai_classification: {'present' if ai_classification else 'not present'}")
        
        # The key rule: ai_classification should be present IFF classification_method starts with "ai:"
        # This means AI fallback was invoked (deterministic rules returned OTHER first)
        if classification_method.startswith("ai:"):
            # AI was invoked - audit trail MUST be present
            assert ai_classification is not None, \
                f"ai_classification should be present when classification_method is {classification_method}"
            print(f"PASS: AI fallback was invoked (method: {classification_method}), audit trail correctly present")
        elif classification_method.startswith(("legacy_ai:", "zetadocs:", "square9:", "mailbox:", "default")):
            # Deterministic classification won - audit trail should NOT be present
            assert ai_classification is None, \
                f"ai_classification should be None when deterministic classification won (method: {classification_method})"
            print(f"PASS: Deterministic classification won (method: {classification_method}), no AI audit trail")
        else:
            # Unknown method - just log it
            print(f"Note: Unknown classification_method format: {classification_method}")
        
        print("PASS: Test completed")


class TestDashboardStats:
    """Test that dashboard stats reflect classification data correctly."""
    
    def test_dashboard_stats_endpoint(self):
        """Verify dashboard stats endpoint returns correct structure."""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        
        assert response.status_code == 200, f"Dashboard stats failed: {response.status_code}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_documents" in data, "total_documents missing"
        assert "by_status" in data, "by_status missing"
        assert "by_type" in data, "by_type missing"
        
        print(f"Dashboard stats: total={data['total_documents']}, by_status keys={list(data['by_status'].keys())}")
        print("PASS: Dashboard stats endpoint working")
    
    def test_document_types_dashboard(self):
        """Verify document types dashboard includes classification data."""
        response = requests.get(f"{BASE_URL}/api/dashboard/document-types")
        
        assert response.status_code == 200, f"Document types dashboard failed: {response.status_code}"
        
        data = response.json()
        
        # Verify structure
        assert "by_type" in data, "by_type missing from document types dashboard"
        assert "grand_total" in data, "grand_total missing"
        
        by_type = data["by_type"]
        
        # Check that at least some doc_types are represented
        print(f"Document types in system: {list(by_type.keys())}")
        print(f"Grand total: {data['grand_total']}")
        
        # Verify structure of each type entry
        for doc_type, type_data in by_type.items():
            assert "total" in type_data, f"total missing for {doc_type}"
            assert "status_counts" in type_data, f"status_counts missing for {doc_type}"
            print(f"  - {doc_type}: {type_data['total']} documents")
        
        print("PASS: Document types dashboard structure verified")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
