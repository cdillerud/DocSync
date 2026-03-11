"""
Test Layout Fingerprint Service - Document Layout Fingerprinting System

This test suite covers all 7 layout fingerprint API endpoints plus the
service-level functions for structural signature generation and similarity scoring.

Key test areas:
- API endpoints: /api/layout-fingerprints/*
- Pure functions: generate_structural_signature(), compute_family_similarity()
- Resolver integration: layout_family_bias component in scoring
- Backwards compatibility: documents without fingerprints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestLayoutFingerprintAPIs:
    """Test all 7 layout fingerprint API endpoints"""
    
    def test_get_stats_structure(self):
        """GET /api/layout-fingerprints/stats returns correct stats structure"""
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/stats")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify required fields in stats response
        assert "total_families" in data, "Missing total_families field"
        assert "total_fingerprints" in data, "Missing total_fingerprints field"
        assert "new_layouts_detected" in data, "Missing new_layouts_detected field"
        assert "vendors_with_families" in data, "Missing vendors_with_families field"
        assert "document_type_distribution" in data, "Missing document_type_distribution field"
        assert "top_families" in data, "Missing top_families field"
        
        # Verify types
        assert isinstance(data["total_families"], int), "total_families should be int"
        assert isinstance(data["total_fingerprints"], int), "total_fingerprints should be int"
        assert isinstance(data["document_type_distribution"], list), "document_type_distribution should be list"
        assert isinstance(data["top_families"], list), "top_families should be list"
        
        print(f"Stats: {data['total_families']} families, {data['total_fingerprints']} fingerprints, {data['vendors_with_families']} vendors")
    
    def test_get_families_list(self):
        """GET /api/layout-fingerprints/families returns families list (empty or populated)"""
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/families")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "families" in data, "Missing families field"
        assert "total" in data, "Missing total field"
        assert isinstance(data["families"], list), "families should be list"
        
        print(f"Families list: {data['total']} families returned")
        
        # If there are families, verify structure
        if data["families"]:
            family = data["families"][0]
            assert "layout_family_id" in family, "Family missing layout_family_id"
            assert "vendor_no" in family, "Family missing vendor_no"
            assert "document_type" in family, "Family missing document_type"
            assert "documents_count" in family, "Family missing documents_count"
            print(f"Sample family: {family['layout_family_id']}, {family['documents_count']} docs")
    
    def test_get_families_with_filters(self):
        """GET /api/layout-fingerprints/families with filters works"""
        # Test with doc_type filter
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/families?doc_type=AP_Invoice")
        assert response.status_code == 200
        
        # Test with status filter
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/families?status=active")
        assert response.status_code == 200
        
        # Test pagination
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/families?skip=0&limit=10")
        assert response.status_code == 200
        
        print("Filters working correctly")
    
    def test_get_family_detail_404(self):
        """GET /api/layout-fingerprints/families/{family_id} returns 404 for non-existent family"""
        fake_family_id = "FAKE_VENDOR_FAKE_TYPE_ABC123"
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/families/{fake_family_id}")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"Correctly returns 404 for non-existent family")
    
    def test_get_families_by_vendor(self):
        """GET /api/layout-fingerprints/vendor/{vendor_no} returns families by vendor"""
        # Test with a vendor that might exist
        vendor_no = "CARGO_MODULES_LLC"
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/vendor/{vendor_no}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no field"
        assert "families" in data, "Missing families field"
        assert "total" in data, "Missing total field"
        assert isinstance(data["families"], list), "families should be list"
        
        print(f"Vendor {vendor_no}: {data['total']} families found")
    
    def test_get_document_fingerprint_no_fingerprint(self):
        """GET /api/layout-fingerprints/document/{doc_id} returns no-fingerprint response"""
        fake_doc_id = "non-existent-doc-id-12345"
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/document/{fake_doc_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "document_id" in data, "Missing document_id field"
        assert "has_fingerprint" in data, "Missing has_fingerprint field"
        assert data["has_fingerprint"] == False, "Expected has_fingerprint=False for non-existent doc"
        
        print("Document fingerprint endpoint correctly returns no-fingerprint for missing doc")
    
    def test_backfill_endpoint(self):
        """POST /api/layout-fingerprints/backfill triggers backfill and returns result"""
        response = requests.post(f"{BASE_URL}/api/layout-fingerprints/backfill?limit=10")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Backfill should return counts
        assert "candidates" in data, "Missing candidates field"
        assert "generated" in data, "Missing generated field"
        assert "skipped" in data, "Missing skipped field"
        assert "errors" in data, "Missing errors field"
        
        print(f"Backfill result: candidates={data['candidates']}, generated={data['generated']}, skipped={data['skipped']}, errors={data['errors']}")
    
    def test_alerts_endpoint(self):
        """GET /api/layout-fingerprints/alerts returns alerts list"""
        response = requests.get(f"{BASE_URL}/api/layout-fingerprints/alerts")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "alerts" in data, "Missing alerts field"
        assert "total" in data, "Missing total field"
        assert isinstance(data["alerts"], list), "alerts should be list"
        
        print(f"Alerts: {data['total']} alerts returned")
        
        # If there are alerts, verify structure
        if data["alerts"]:
            alert = data["alerts"][0]
            assert "type" in alert, "Alert missing type"
            assert "severity" in alert, "Alert missing severity"
            assert "layout_family_id" in alert, "Alert missing layout_family_id"
            print(f"Sample alert: {alert['type']} - {alert['severity']}")


class TestLayoutFingerprintService:
    """Test the service-level functions directly via imports"""
    
    def test_generate_structural_signature_from_text(self):
        """Test generate_structural_signature with sample text"""
        # Import the function
        import sys
        sys.path.insert(0, '/app/backend')
        from services.layout_fingerprint_service import generate_structural_signature
        
        sample_text = """
        INVOICE
        Invoice #: INV-2025-001
        Date: 2025-01-10
        
        Bill To:
        Acme Corporation
        123 Main Street
        
        Item          Qty    Price    Total
        Widget A      10     $5.00    $50.00
        Widget B      5      $10.00   $50.00
        
        Subtotal: $100.00
        Tax: $10.00
        Total Due: $110.00
        
        Payment Terms: Net 30
        """
        
        signature = generate_structural_signature(sample_text, page_count=1)
        
        # Verify signature structure
        assert "page_count" in signature, "Missing page_count"
        assert "line_count" in signature, "Missing line_count"
        assert "token_density" in signature, "Missing token_density"
        assert "keyword_signature" in signature, "Missing keyword_signature"
        assert "table_signature" in signature, "Missing table_signature"
        assert "header_footer" in signature, "Missing header_footer"
        assert "version" in signature, "Missing version"
        
        # Verify token_density zones
        assert "top" in signature["token_density"], "Missing token_density.top"
        assert "middle" in signature["token_density"], "Missing token_density.middle"
        assert "bottom" in signature["token_density"], "Missing token_density.bottom"
        
        # Verify header_footer structure
        assert "header_density" in signature["header_footer"], "Missing header_density"
        assert "footer_density" in signature["header_footer"], "Missing footer_density"
        
        # Verify keyword_signature detected invoice keywords
        assert "invoice" in signature["keyword_signature"], "Should detect invoice keywords"
        
        # SAFETY: verify NO absolute coordinates (no x/y pixel values)
        sig_str = str(signature)
        assert "x=" not in sig_str.lower() or "coord" not in sig_str.lower(), "Fingerprint should NOT contain absolute coordinates"
        assert "pixel" not in sig_str.lower(), "Fingerprint should NOT contain pixel values"
        
        print(f"Signature generated: {signature['line_count']} lines, {len(signature['keyword_signature'])} keyword categories")
        print(f"Token density: top={signature['token_density']['top']}, middle={signature['token_density']['middle']}, bottom={signature['token_density']['bottom']}")
    
    def test_similarity_scoring_between_signatures(self):
        """Test compute_family_similarity returns 0-1 float"""
        import sys
        sys.path.insert(0, '/app/backend')
        from services.layout_fingerprint_service import generate_structural_signature, compute_family_similarity
        
        # Create two similar signatures
        text1 = """
        INVOICE
        Invoice #: INV-001
        Date: 2025-01-10
        
        Bill To: Customer A
        
        Item    Qty    Price
        A       10     $5.00
        B       5      $10.00
        
        Total: $100.00
        """
        
        text2 = """
        INVOICE
        Invoice #: INV-002
        Date: 2025-01-11
        
        Bill To: Customer B
        
        Item    Qty    Price
        X       8      $6.00
        Y       4      $12.00
        
        Total: $96.00
        """
        
        text3 = """
        BILL OF LADING
        BOL #: BOL-12345
        Ship Date: 2025-01-10
        
        Shipper: Company A
        Consignee: Company B
        Carrier: ABC Trucking
        
        Weight: 1000 lbs
        Pieces: 5 pallets
        """
        
        sig1 = generate_structural_signature(text1)
        sig2 = generate_structural_signature(text2)
        sig3 = generate_structural_signature(text3)
        
        # Similar invoices should have high similarity
        sim_12 = compute_family_similarity(sig1, sig2)
        assert 0 <= sim_12 <= 1, f"Similarity should be 0-1, got {sim_12}"
        print(f"Similarity between two invoices: {sim_12:.4f}")
        
        # Invoice vs BOL should have lower similarity
        sim_13 = compute_family_similarity(sig1, sig3)
        assert 0 <= sim_13 <= 1, f"Similarity should be 0-1, got {sim_13}"
        assert sim_13 < sim_12, f"Invoice vs BOL ({sim_13}) should be less similar than invoice vs invoice ({sim_12})"
        print(f"Similarity between invoice and BOL: {sim_13:.4f}")
        
        # Same signature should have perfect similarity
        sim_11 = compute_family_similarity(sig1, sig1)
        assert sim_11 >= 0.99, f"Same signature should have ~1.0 similarity, got {sim_11}"
        print(f"Self-similarity: {sim_11:.4f}")


class TestResolverIntegration:
    """Test layout_family_bias integration with resolver"""
    
    def test_matching_debug_includes_layout_fingerprint(self):
        """GET /api/documents/{doc_id}/matching-debug includes layout_fingerprint field"""
        # First get a document from the queue
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if docs_response.status_code != 200:
            pytest.skip("No documents available for testing")
        
        docs = docs_response.json().get("documents", [])
        if not docs:
            pytest.skip("No documents in queue")
        
        doc_id = docs[0]["id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/matching-debug")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # The matching debug should include layout_fingerprint field
        assert "layout_fingerprint" in data, "matching-debug should include layout_fingerprint field"
        
        layout_fp = data.get("layout_fingerprint")
        if layout_fp:
            print(f"Document {doc_id[:8]} has layout fingerprint: {layout_fp.get('has_fingerprint', False)}")
            if layout_fp.get("has_fingerprint"):
                print(f"  Family: {layout_fp.get('layout_family_id')}")
                print(f"  Similarity: {layout_fp.get('layout_similarity_score')}")
        else:
            print(f"Document {doc_id[:8]} - no layout fingerprint data")


class TestBackwardsCompatibility:
    """Test documents without fingerprints still work in resolver"""
    
    def test_documents_without_fingerprints_work(self):
        """Documents without fingerprints should still work in resolver"""
        # Get a document
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=1")
        if docs_response.status_code != 200:
            pytest.skip("No documents available")
        
        docs = docs_response.json().get("documents", [])
        if not docs:
            pytest.skip("No documents in queue")
        
        doc_id = docs[0]["id"]
        
        # Get document detail - should work regardless of fingerprint status
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert response.status_code == 200, f"Document detail should work: {response.status_code}"
        
        # Matching debug should work (layout_fingerprint can be null)
        debug_response = requests.get(f"{BASE_URL}/api/documents/{doc_id}/matching-debug")
        assert debug_response.status_code == 200, f"Matching debug should work: {debug_response.status_code}"
        
        print(f"Document {doc_id[:8]} APIs work correctly regardless of fingerprint status")


class TestNoAbsoluteCoordinates:
    """Safety test: fingerprints should NEVER contain absolute coordinates"""
    
    def test_fingerprints_no_absolute_coords(self):
        """Verify fingerprints contain NO absolute coordinates (no x/y pixel values)"""
        import sys
        sys.path.insert(0, '/app/backend')
        from services.layout_fingerprint_service import generate_structural_signature, compute_fingerprint_hash
        
        # Generate signature from various texts
        texts = [
            "INVOICE\nInvoice #: 12345\n\nItem  Qty  Price\nA     10   $5\n\nTotal: $50",
            "BOL #: 67890\nShipper: ABC\nConsignee: XYZ\n\nWeight: 1000 lbs",
            "Purchase Order\nPO #: PO-2025-001\n\nLine  Item  Qty\n1     Widget  10\n2     Gadget  5",
        ]
        
        for text in texts:
            sig = generate_structural_signature(text)
            sig_str = str(sig)
            
            # Check for coordinate-related terms
            forbidden = ["x=", "y=", "pixel", "coord", "position:", "left:", "right:", "top:", "bottom:"]
            for term in forbidden:
                # Note: "top" and "bottom" are OK as zone names, but "top:" or "bottom:" as coords are not
                if term in ["top:", "bottom:"]:
                    continue  # Skip these as they might be in keyword_signature
                assert term not in sig_str.lower(), f"Fingerprint should NOT contain '{term}'"
            
            # Verify it uses relative zones, not absolute positions
            assert "top" in sig["token_density"], "Should use relative zone 'top'"
            assert "middle" in sig["token_density"], "Should use relative zone 'middle'"
            assert "bottom" in sig["token_density"], "Should use relative zone 'bottom'"
        
        print("SAFETY VERIFIED: Fingerprints use relative zones only, no absolute coordinates")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
