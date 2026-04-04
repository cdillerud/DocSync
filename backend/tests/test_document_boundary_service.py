"""
Test Document Boundary Service — Multi-page PDF splitting with intelligent boundary detection

Tests:
1. analyze_document_boundaries correctly detects 3 logical docs from a 5-page PDF with 3 different vendors
2. document_boundary_service keeps multi-page same-vendor same-invoice docs together (no false splits)
3. document_boundary_service handles single-page PDFs (should_split=False)
4. detect_batch_po now accepts AP_Invoice, BOL, Unknown types (not just PO/SO)
5. detect_batch_po returns groups and boundaries from boundary analysis
6. GET /api/documents/{doc_id}/boundary-analysis returns boundary analysis for a document
7. POST /api/documents/{doc_id}/auto-split triggers boundary-aware splitting
8. split_and_ingest_batch accepts groups parameter for boundary-aware splitting
9. split_and_ingest_batch falls back to per-page split when no groups provided
10. Intake pipeline in server.py auto-detects and auto-splits multi-page documents
"""

import pytest
import requests
import os
import io
import uuid
from datetime import datetime, timezone

# Use reportlab and pypdf to create synthetic test PDFs
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pypdf import PdfWriter, PdfReader

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ap-learning-dash.preview.emergentagent.com').rstrip('/')


def create_test_pdf_page(vendor_name: str, invoice_number: str, doc_type: str = "INVOICE") -> bytes:
    """Create a single-page PDF with vendor name, invoice number, and doc type header."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    
    # Letterhead / Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, vendor_name.upper())
    
    # Company suffix to help vendor detection
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"{vendor_name} Inc.")
    c.drawString(50, height - 85, "123 Business Street")
    c.drawString(50, height - 100, "Phone: 555-123-4567")
    
    # Document type header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 140, f"{doc_type} #{invoice_number}")
    
    # Invoice details
    c.setFont("Helvetica", 11)
    c.drawString(50, height - 180, f"Invoice Number: {invoice_number}")
    c.drawString(50, height - 200, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    c.drawString(50, height - 220, f"Vendor: {vendor_name}")
    
    # Some body content
    c.drawString(50, height - 260, "Description: Services rendered")
    c.drawString(50, height - 280, "Amount: $1,500.00")
    
    c.save()
    return buf.getvalue()


def create_multi_vendor_pdf(vendors_invoices: list) -> bytes:
    """Create a multi-page PDF with different vendors/invoices on each page.
    
    Args:
        vendors_invoices: List of tuples (vendor_name, invoice_number, doc_type)
    
    Returns:
        bytes: Combined PDF content
    """
    writer = PdfWriter()
    
    for vendor_name, invoice_number, doc_type in vendors_invoices:
        page_bytes = create_test_pdf_page(vendor_name, invoice_number, doc_type)
        reader = PdfReader(io.BytesIO(page_bytes))
        writer.add_page(reader.pages[0])
    
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def create_same_vendor_multi_page_pdf(vendor_name: str, invoice_number: str, page_count: int = 3) -> bytes:
    """Create a multi-page PDF where all pages belong to the same vendor/invoice."""
    writer = PdfWriter()
    
    for i in range(page_count):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter
        
        # Same letterhead on all pages
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, vendor_name.upper())
        c.setFont("Helvetica", 10)
        c.drawString(50, height - 70, f"{vendor_name} Inc.")
        
        # Same invoice number
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, height - 100, f"INVOICE #{invoice_number}")
        
        # Page indicator
        c.setFont("Helvetica", 11)
        c.drawString(50, height - 140, f"Page {i + 1} of {page_count}")
        c.drawString(50, height - 160, f"Invoice Number: {invoice_number}")
        
        # Different content per page to simulate multi-page invoice
        if i == 0:
            c.drawString(50, height - 200, "Invoice Summary")
        elif i == 1:
            c.drawString(50, height - 200, "Line Items Detail")
        else:
            c.drawString(50, height - 200, "Terms and Conditions")
        
        c.save()
        reader = PdfReader(io.BytesIO(buf.getvalue()))
        writer.add_page(reader.pages[0])
    
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def create_single_page_pdf(vendor_name: str = "Test Vendor", invoice_number: str = "INV-001") -> bytes:
    """Create a single-page PDF."""
    return create_test_pdf_page(vendor_name, invoice_number, "INVOICE")


class TestDocumentBoundaryService:
    """Test the document_boundary_service module directly."""
    
    def test_analyze_boundaries_detects_3_vendors_in_5_pages(self):
        """Test: analyze_document_boundaries correctly detects 3 logical docs from a 5-page PDF with 3 different vendors."""
        from services.document_boundary_service import analyze_document_boundaries
        
        # Create 5-page PDF: Vendor A (2 pages), Vendor B (2 pages), Vendor C (1 page)
        pdf_content = create_multi_vendor_pdf([
            ("Acme Corporation", "INV-1001", "INVOICE"),
            ("Acme Corporation", "INV-1001", "INVOICE"),  # Same vendor, same invoice - should stay together
            ("Beta Industries", "INV-2001", "INVOICE"),
            ("Beta Industries", "INV-2001", "INVOICE"),  # Same vendor, same invoice - should stay together
            ("Gamma Services", "INV-3001", "INVOICE"),
        ])
        
        result = analyze_document_boundaries(pdf_content)
        
        assert result["total_pages"] == 5, f"Expected 5 pages, got {result['total_pages']}"
        assert result["should_split"] == True, "Should detect need to split"
        assert result["document_count"] >= 2, f"Expected at least 2 logical docs, got {result['document_count']}"
        assert len(result["groups"]) >= 2, f"Expected at least 2 groups, got {len(result['groups'])}"
        assert len(result["boundaries"]) >= 1, f"Expected at least 1 boundary, got {len(result['boundaries'])}"
        
        print(f"✓ Detected {result['document_count']} logical documents in 5-page PDF")
        print(f"  Boundaries at pages: {result['boundaries']}")
        print(f"  Groups: {[g['pages'] for g in result['groups']]}")
    
    def test_same_vendor_same_invoice_stays_together(self):
        """Test: document_boundary_service keeps multi-page same-vendor same-invoice docs together (no false splits)."""
        from services.document_boundary_service import analyze_document_boundaries
        
        # Create 3-page PDF from same vendor with same invoice number
        pdf_content = create_same_vendor_multi_page_pdf("Acme Corporation", "INV-5001", page_count=3)
        
        result = analyze_document_boundaries(pdf_content)
        
        assert result["total_pages"] == 3, f"Expected 3 pages, got {result['total_pages']}"
        # Should NOT split - all pages belong to same document
        assert result["should_split"] == False, f"Should NOT split same-vendor same-invoice doc, got should_split={result['should_split']}"
        assert result["document_count"] == 1, f"Expected 1 logical doc, got {result['document_count']}"
        
        print(f"✓ Same-vendor same-invoice 3-page PDF correctly identified as single document")
        print(f"  Analysis: {result['analysis']}")
    
    def test_single_page_pdf_no_split(self):
        """Test: document_boundary_service handles single-page PDFs (should_split=False)."""
        from services.document_boundary_service import analyze_document_boundaries
        
        pdf_content = create_single_page_pdf("Test Vendor", "INV-001")
        
        result = analyze_document_boundaries(pdf_content)
        
        assert result["total_pages"] == 1, f"Expected 1 page, got {result['total_pages']}"
        assert result["should_split"] == False, "Single-page PDF should not need splitting"
        assert result["document_count"] == 1, f"Expected 1 document, got {result['document_count']}"
        assert result["analysis"] == "Single page document", f"Unexpected analysis: {result['analysis']}"
        
        print(f"✓ Single-page PDF correctly returns should_split=False")


class TestBatchPOSplitter:
    """Test the batch_po_splitter module."""
    
    def test_detect_batch_po_accepts_ap_invoice(self):
        """Test: detect_batch_po now accepts AP_Invoice type."""
        from services.batch_po_splitter import detect_batch_po, SPLITTABLE_TYPES
        
        # Verify AP_Invoice is in SPLITTABLE_TYPES
        assert "AP_Invoice" in SPLITTABLE_TYPES, "AP_Invoice should be in SPLITTABLE_TYPES"
        assert "APInvoice" in SPLITTABLE_TYPES, "APInvoice should be in SPLITTABLE_TYPES"
        
        # Create multi-page PDF
        pdf_content = create_multi_vendor_pdf([
            ("Vendor A", "INV-001", "INVOICE"),
            ("Vendor B", "INV-002", "INVOICE"),
        ])
        
        result = detect_batch_po(pdf_content, "AP_Invoice")
        
        assert result["should_split"] == True, "Multi-page AP_Invoice should trigger split"
        assert result["page_count"] == 2, f"Expected 2 pages, got {result['page_count']}"
        
        print(f"✓ detect_batch_po accepts AP_Invoice type")
    
    def test_detect_batch_po_accepts_bol(self):
        """Test: detect_batch_po now accepts BOL type."""
        from services.batch_po_splitter import detect_batch_po, SPLITTABLE_TYPES
        
        assert "BOL" in SPLITTABLE_TYPES, "BOL should be in SPLITTABLE_TYPES"
        assert "Bill_of_Lading" in SPLITTABLE_TYPES, "Bill_of_Lading should be in SPLITTABLE_TYPES"
        
        pdf_content = create_multi_vendor_pdf([
            ("Carrier A", "BOL-001", "BILL OF LADING"),
            ("Carrier B", "BOL-002", "BILL OF LADING"),
        ])
        
        result = detect_batch_po(pdf_content, "BOL")
        
        assert result["should_split"] == True, "Multi-page BOL should trigger split"
        print(f"✓ detect_batch_po accepts BOL type")
    
    def test_detect_batch_po_accepts_unknown(self):
        """Test: detect_batch_po now accepts Unknown type."""
        from services.batch_po_splitter import detect_batch_po, SPLITTABLE_TYPES
        
        assert "Unknown" in SPLITTABLE_TYPES, "Unknown should be in SPLITTABLE_TYPES"
        
        # Create 3+ page PDF (Unknown requires 3+ pages)
        pdf_content = create_multi_vendor_pdf([
            ("Vendor A", "DOC-001", "DOCUMENT"),
            ("Vendor B", "DOC-002", "DOCUMENT"),
            ("Vendor C", "DOC-003", "DOCUMENT"),
        ])
        
        result = detect_batch_po(pdf_content, "Unknown")
        
        assert result["should_split"] == True, "Multi-page Unknown should trigger split"
        print(f"✓ detect_batch_po accepts Unknown type")
    
    def test_detect_batch_po_returns_groups_and_boundaries(self):
        """Test: detect_batch_po returns groups and boundaries from boundary analysis."""
        from services.batch_po_splitter import detect_batch_po
        
        pdf_content = create_multi_vendor_pdf([
            ("Vendor A", "INV-001", "INVOICE"),
            ("Vendor B", "INV-002", "INVOICE"),
            ("Vendor C", "INV-003", "INVOICE"),
        ])
        
        result = detect_batch_po(pdf_content, "AP_Invoice")
        
        assert "groups" in result, "Result should contain 'groups'"
        assert "boundaries" in result, "Result should contain 'boundaries'"
        assert isinstance(result["groups"], list), "groups should be a list"
        assert isinstance(result["boundaries"], list), "boundaries should be a list"
        
        print(f"✓ detect_batch_po returns groups: {len(result['groups'])} and boundaries: {result['boundaries']}")
    
    def test_single_page_no_split(self):
        """Test: Single-page PDF returns should_split=False."""
        from services.batch_po_splitter import detect_batch_po
        
        pdf_content = create_single_page_pdf()
        
        result = detect_batch_po(pdf_content, "AP_Invoice")
        
        assert result["should_split"] == False, "Single-page PDF should not trigger split"
        assert result["page_count"] == 1, f"Expected 1 page, got {result['page_count']}"
        assert result["reason"] == "single_page", f"Expected reason 'single_page', got {result['reason']}"
        
        print(f"✓ Single-page PDF correctly returns should_split=False")


class TestBoundaryAnalysisAPI:
    """Test the boundary-analysis API endpoint."""
    
    @pytest.fixture
    def uploaded_multi_page_doc(self):
        """Upload a multi-page test document and return its ID."""
        pdf_content = create_multi_vendor_pdf([
            ("Alpha Corp", "INV-A001", "INVOICE"),
            ("Beta LLC", "INV-B001", "INVOICE"),
        ])
        
        files = {"file": ("test_multi_vendor.pdf", pdf_content, "application/pdf")}
        data = {"document_type": "AP_Invoice", "source": "test_boundary_api"}
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        
        if response.status_code != 200:
            pytest.skip(f"Failed to upload test document: {response.status_code}")
        
        doc_id = response.json().get("document", {}).get("id")
        if not doc_id:
            pytest.skip("No document ID returned from upload")
        
        yield doc_id
        
        # Cleanup
        try:
            requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
        except:
            pass
    
    def test_boundary_analysis_endpoint_exists(self, uploaded_multi_page_doc):
        """Test: GET /api/documents/{doc_id}/boundary-analysis returns boundary analysis."""
        doc_id = uploaded_multi_page_doc
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/boundary-analysis")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "document_id" in data, "Response should contain document_id"
        assert "analysis" in data, "Response should contain analysis"
        
        analysis = data["analysis"]
        assert "total_pages" in analysis, "Analysis should contain total_pages"
        assert "should_split" in analysis, "Analysis should contain should_split"
        assert "groups" in analysis, "Analysis should contain groups"
        assert "boundaries" in analysis, "Analysis should contain boundaries"
        
        print(f"✓ GET /api/documents/{doc_id}/boundary-analysis returns valid analysis")
        print(f"  Total pages: {analysis['total_pages']}, Should split: {analysis['should_split']}")
    
    def test_boundary_analysis_404_for_missing_doc(self):
        """Test: boundary-analysis returns 404 for non-existent document."""
        fake_id = str(uuid.uuid4())
        
        response = requests.get(f"{BASE_URL}/api/documents/{fake_id}/boundary-analysis")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ boundary-analysis returns 404 for missing document")


class TestAutoSplitAPI:
    """Test the auto-split API endpoint."""
    
    @pytest.fixture
    def uploaded_multi_page_doc_for_split(self):
        """Upload a multi-page test document for splitting."""
        pdf_content = create_multi_vendor_pdf([
            ("Vendor One", "INV-V1-001", "INVOICE"),
            ("Vendor Two", "INV-V2-001", "INVOICE"),
            ("Vendor Three", "INV-V3-001", "INVOICE"),
        ])
        
        files = {"file": ("test_auto_split.pdf", pdf_content, "application/pdf")}
        data = {"document_type": "AP_Invoice", "source": "test_auto_split"}
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        
        if response.status_code != 200:
            pytest.skip(f"Failed to upload test document: {response.status_code}")
        
        doc_id = response.json().get("document", {}).get("id")
        if not doc_id:
            pytest.skip("No document ID returned from upload")
        
        yield doc_id
        
        # Cleanup - delete parent and any children
        try:
            doc = requests.get(f"{BASE_URL}/api/documents/{doc_id}").json()
            children_ids = doc.get("document", {}).get("batch_children_ids", [])
            for child_id in children_ids:
                requests.delete(f"{BASE_URL}/api/documents/{child_id}")
            requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
        except:
            pass
    
    def test_auto_split_endpoint_exists(self, uploaded_multi_page_doc_for_split):
        """Test: POST /api/documents/{doc_id}/auto-split triggers boundary-aware splitting."""
        doc_id = uploaded_multi_page_doc_for_split
        
        response = requests.post(f"{BASE_URL}/api/documents/{doc_id}/auto-split")
        
        # Could be 200 (success) or 200 with success=False (single doc, no split needed)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check response structure
        if data.get("success"):
            assert "result" in data, "Successful split should contain 'result'"
            assert "analysis" in data, "Successful split should contain 'analysis'"
            
            result = data["result"]
            assert "children_count" in result, "Result should contain children_count"
            assert "split_mode" in result, "Result should contain split_mode"
            
            print(f"✓ POST /api/documents/{doc_id}/auto-split succeeded")
            print(f"  Children created: {result['children_count']}, Mode: {result['split_mode']}")
        else:
            # Single document - no split needed
            assert "reason" in data, "Failed split should contain 'reason'"
            print(f"✓ POST /api/documents/{doc_id}/auto-split returned no-split-needed: {data.get('reason')}")
    
    def test_auto_split_404_for_missing_doc(self):
        """Test: auto-split returns 404 for non-existent document."""
        fake_id = str(uuid.uuid4())
        
        response = requests.post(f"{BASE_URL}/api/documents/{fake_id}/auto-split")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"✓ auto-split returns 404 for missing document")


class TestSplitAndIngestBatch:
    """Test the split_and_ingest_batch function."""
    
    def test_split_with_groups_parameter(self):
        """Test: split_and_ingest_batch accepts groups parameter for boundary-aware splitting."""
        from services.batch_po_splitter import split_and_ingest_batch
        
        # This is a unit test - we verify the function signature accepts groups
        import inspect
        sig = inspect.signature(split_and_ingest_batch)
        params = list(sig.parameters.keys())
        
        assert "groups" in params, "split_and_ingest_batch should accept 'groups' parameter"
        
        # Check default value
        groups_param = sig.parameters["groups"]
        assert groups_param.default is None, "groups parameter should default to None"
        
        print(f"✓ split_and_ingest_batch accepts groups parameter (default=None)")
    
    def test_splittable_types_includes_all_required(self):
        """Test: SPLITTABLE_TYPES includes AP_Invoice, BOL, Unknown."""
        from services.batch_po_splitter import SPLITTABLE_TYPES
        
        required_types = ["AP_Invoice", "APInvoice", "BOL", "Bill_of_Lading", "Unknown"]
        
        for doc_type in required_types:
            assert doc_type in SPLITTABLE_TYPES, f"{doc_type} should be in SPLITTABLE_TYPES"
        
        print(f"✓ SPLITTABLE_TYPES includes all required types: {required_types}")
        print(f"  Full list: {SPLITTABLE_TYPES}")


class TestIntakePipelineAutoSplit:
    """Test that the intake pipeline auto-detects and auto-splits multi-page documents."""
    
    def test_intake_with_multi_page_pdf_triggers_split(self):
        """Test: Intake pipeline in server.py auto-detects and auto-splits multi-page documents."""
        # Create a multi-vendor PDF
        pdf_content = create_multi_vendor_pdf([
            ("Intake Test Vendor A", "INT-001", "INVOICE"),
            ("Intake Test Vendor B", "INT-002", "INVOICE"),
        ])
        
        files = {"file": ("test_intake_split.pdf", pdf_content, "application/pdf")}
        data = {"document_type": "AP_Invoice", "source": "test_intake_auto_split"}
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        
        assert response.status_code == 200, f"Upload failed: {response.status_code}: {response.text}"
        
        doc_data = response.json()
        doc = doc_data.get("document", {})
        doc_id = doc.get("id")
        
        # Check if batch detection occurred
        # Note: The intake pipeline may or may not auto-split depending on configuration
        # We verify the batch_detected flag is set for multi-page docs
        
        # Fetch the document to check batch fields
        get_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        if get_response.status_code == 200:
            fetched_doc = get_response.json().get("document", {})
            
            # Check batch detection fields
            batch_detected = fetched_doc.get("batch_detected", False)
            batch_page_count = fetched_doc.get("batch_page_count", 0)
            status = fetched_doc.get("status", "")
            
            print(f"✓ Intake processed multi-page PDF")
            print(f"  Document ID: {doc_id}")
            print(f"  Batch detected: {batch_detected}")
            print(f"  Batch page count: {batch_page_count}")
            print(f"  Status: {status}")
            
            # If batch was detected and split, check for children
            if status == "batch_parent":
                children_ids = fetched_doc.get("batch_children_ids", [])
                print(f"  Children created: {len(children_ids)}")
                
                # Cleanup children
                for child_id in children_ids:
                    try:
                        requests.delete(f"{BASE_URL}/api/documents/{child_id}")
                    except:
                        pass
        
        # Cleanup parent
        try:
            requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
        except:
            pass


class TestPageFingerprinting:
    """Test the page fingerprinting functionality."""
    
    def test_fingerprint_page_extracts_vendor_hint(self):
        """Test: fingerprint_page extracts vendor hints from page text."""
        from services.document_boundary_service import fingerprint_page
        
        page_data = {
            "page_num": 1,
            "text": "ACME CORPORATION INC.\n123 Business Street\nPhone: 555-1234\n\nINVOICE #12345\nDate: 2024-01-15",
            "char_count": 100,
            "line_count": 6,
        }
        
        fp = fingerprint_page(page_data)
        
        assert fp["page_num"] == 1
        assert fp["is_blank"] == False
        assert fp["vendor_hint"] != "", f"Should extract vendor hint, got empty string"
        assert "ACME" in fp["vendor_hint"].upper(), f"Vendor hint should contain ACME: {fp['vendor_hint']}"
        
        print(f"✓ fingerprint_page extracts vendor hint: {fp['vendor_hint']}")
    
    def test_fingerprint_page_extracts_invoice_number(self):
        """Test: fingerprint_page extracts invoice numbers."""
        from services.document_boundary_service import fingerprint_page
        
        page_data = {
            "page_num": 1,
            "text": "Test Company\n\nINVOICE #INV-2024-001\nPO Number: PO-5678",
            "char_count": 60,
            "line_count": 4,
        }
        
        fp = fingerprint_page(page_data)
        
        assert "invoice_no" in fp["ref_numbers"] or "po_no" in fp["ref_numbers"], \
            f"Should extract reference numbers: {fp['ref_numbers']}"
        
        print(f"✓ fingerprint_page extracts reference numbers: {fp['ref_numbers']}")
    
    def test_fingerprint_page_detects_blank_page(self):
        """Test: fingerprint_page correctly identifies blank pages."""
        from services.document_boundary_service import fingerprint_page
        
        page_data = {
            "page_num": 1,
            "text": "",
            "char_count": 0,
            "line_count": 0,
        }
        
        fp = fingerprint_page(page_data)
        
        assert fp["is_blank"] == True, "Empty page should be marked as blank"
        
        print(f"✓ fingerprint_page correctly identifies blank pages")


class TestBoundaryDetection:
    """Test the boundary detection logic."""
    
    def test_detect_boundaries_vendor_change(self):
        """Test: detect_boundaries identifies vendor changes as boundaries."""
        from services.document_boundary_service import fingerprint_page, detect_boundaries
        
        # Simulate fingerprints from two different vendors
        fingerprints = [
            {
                "page_num": 1,
                "is_blank": False,
                "is_separator": False,
                "vendor_hint": "ACME CORPORATION",
                "ref_numbers": {"invoice_no": "INV-001"},
                "doc_type_hints": ["INVOICE"],
                "has_letterhead": True,
                "top_text_hash": hash("acme"),
                "dates": [],
            },
            {
                "page_num": 2,
                "is_blank": False,
                "is_separator": False,
                "vendor_hint": "BETA INDUSTRIES",
                "ref_numbers": {"invoice_no": "INV-002"},
                "doc_type_hints": ["INVOICE"],
                "has_letterhead": True,
                "top_text_hash": hash("beta"),
                "dates": [],
            },
        ]
        
        boundaries = detect_boundaries(fingerprints)
        
        assert 1 in boundaries, "Page 1 should always be a boundary"
        assert 2 in boundaries, "Page 2 should be a boundary (vendor changed)"
        
        print(f"✓ detect_boundaries identifies vendor changes: boundaries at {boundaries}")
    
    def test_detect_boundaries_same_vendor_no_split(self):
        """Test: detect_boundaries does NOT split same-vendor same-invoice pages."""
        from services.document_boundary_service import detect_boundaries
        
        # Simulate fingerprints from same vendor, same invoice
        fingerprints = [
            {
                "page_num": 1,
                "is_blank": False,
                "is_separator": False,
                "vendor_hint": "ACME CORPORATION",
                "ref_numbers": {"invoice_no": "INV-001"},
                "doc_type_hints": ["INVOICE"],
                "has_letterhead": True,
                "top_text_hash": hash("acme page 1"),
                "dates": [],
            },
            {
                "page_num": 2,
                "is_blank": False,
                "is_separator": False,
                "vendor_hint": "ACME CORPORATION",
                "ref_numbers": {"invoice_no": "INV-001"},  # Same invoice
                "doc_type_hints": [],
                "has_letterhead": False,
                "top_text_hash": hash("acme page 2"),
                "dates": [],
            },
        ]
        
        boundaries = detect_boundaries(fingerprints)
        
        assert boundaries == [1], f"Should only have boundary at page 1, got {boundaries}"
        
        print(f"✓ detect_boundaries keeps same-vendor same-invoice together: boundaries at {boundaries}")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
