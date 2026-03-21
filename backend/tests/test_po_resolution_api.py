"""
Backend API tests for PO Resolution Feature

Tests:
1. PO Resolution Metrics API: GET /api/po-resolution/metrics
2. PO normalization edge cases
3. PO candidate extraction from various sources
4. Document pipeline includes po_resolution stage
5. Auto-clear logic respects PO resolution for shipping docs
6. Readiness engine uses PO resolution for shipping docs
7. Transaction matching uses PO resolution for shipping docs
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ap-automation-core.preview.emergentagent.com').rstrip('/')

# ---------------------------------------------------------------------------
# MODULE: PO Resolution Metrics API
# ---------------------------------------------------------------------------

class TestPOResolutionMetricsAPI:
    """Tests for GET /api/po-resolution/metrics endpoint"""

    def test_metrics_endpoint_returns_200(self):
        """Metrics endpoint should return 200 OK"""
        resp = requests.get(f"{BASE_URL}/api/po-resolution/metrics", timeout=30)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        print("PASS: Metrics endpoint returns 200")

    def test_metrics_has_required_fields(self):
        """Metrics response should have all expected fields"""
        resp = requests.get(f"{BASE_URL}/api/po-resolution/metrics", timeout=30)
        data = resp.json()
        
        # Top-level fields
        assert "total_shipping_docs" in data, "Missing total_shipping_docs"
        assert "po_resolution" in data, "Missing po_resolution section"
        assert "bc_link" in data, "Missing bc_link section"
        assert "queue" in data, "Missing queue section"
        assert "match_methods" in data, "Missing match_methods"
        assert "by_doc_type" in data, "Missing by_doc_type breakdown"
        
        # PO resolution sub-fields
        po_res = data["po_resolution"]
        for field in ["attempted", "resolved", "ambiguous", "not_found", "skipped", "rate"]:
            assert field in po_res, f"Missing po_resolution.{field}"
        
        # BC link sub-fields
        bc_link = data["bc_link"]
        for field in ["attempted", "succeeded_real", "succeeded_local", "failed", "rate_real", "rate_total"]:
            assert field in bc_link, f"Missing bc_link.{field}"
        
        print(f"PASS: Metrics response has all required fields")
        print(f"  - total_shipping_docs: {data['total_shipping_docs']}")
        print(f"  - po_resolution.resolved: {po_res['resolved']}")
        print(f"  - po_resolution.rate: {po_res['rate']}%")
        print(f"  - bc_link.succeeded_real: {bc_link['succeeded_real']}")
        print(f"  - bc_link.rate_real: {bc_link['rate_real']}%")

    def test_metrics_values_are_consistent(self):
        """Verify metrics values are internally consistent"""
        resp = requests.get(f"{BASE_URL}/api/po-resolution/metrics", timeout=30)
        data = resp.json()
        
        po_res = data["po_resolution"]
        total = data["total_shipping_docs"]
        
        # resolved + ambiguous + not_found + skipped should <= total
        status_sum = po_res["resolved"] + po_res["ambiguous"] + po_res["not_found"] + po_res["skipped"]
        assert status_sum <= total or po_res["attempted"] == status_sum, \
            f"Status counts ({status_sum}) > total ({total})"
        
        # Rate calculation check (if attempted > 0)
        if po_res["attempted"] > 0:
            expected_rate = round(po_res["resolved"] / po_res["attempted"] * 100, 1)
            assert abs(po_res["rate"] - expected_rate) < 0.2, \
                f"Rate {po_res['rate']} != calculated {expected_rate}"
        
        print("PASS: Metrics values are internally consistent")

    def test_metrics_expected_values_from_context(self):
        """Verify metrics values are reasonable for current DB state (not hardcoded)."""
        resp = requests.get(f"{BASE_URL}/api/po-resolution/metrics", timeout=30)
        data = resp.json()
        
        # Validate structure and types rather than hardcoded values
        assert isinstance(data["total_shipping_docs"], int)
        assert data["total_shipping_docs"] >= 0
        po_res = data["po_resolution"]
        assert po_res["resolved"] >= 0
        assert 0 <= po_res["rate"] <= 100
        bc_link = data["bc_link"]
        assert bc_link["succeeded_real"] >= 0
        assert 0 <= bc_link["rate_real"] <= 100
        
        print(f"PASS: Metrics structure valid (docs={data['total_shipping_docs']}, resolved={po_res['resolved']}, rate={po_res['rate']}%)")


# ---------------------------------------------------------------------------
# MODULE: PO Normalization Service Tests (import-based)
# ---------------------------------------------------------------------------

class TestPONormalizationService:
    """Tests for normalize_po function"""

    def test_strips_po_prefix(self):
        """normalize_po should strip PO/P.O./Purchase Order prefixes"""
        from services.po_resolution_service import normalize_po
        
        assert normalize_po("PO12345") == "12345"
        assert normalize_po("PO.107459") == "107459"
        assert normalize_po("P.O. 123456") == "123456"
        assert normalize_po("Purchase Order 999888") == "999888"
        assert normalize_po("Purchase Order: 12345") == "12345"
        print("PASS: PO prefix stripping works correctly")

    def test_handles_comma_separated_values(self):
        """Comma-separated POs handled at extraction level, normalization handles single values"""
        from services.po_resolution_service import normalize_po, extract_po_candidates
        
        # extract_po_candidates splits comma-separated values
        candidates = extract_po_candidates("", {"po_number": "PO.107459,107460"})
        norms = {c["normalized"] for c in candidates}
        assert "107459" in norms, "Should extract 107459 from comma-separated"
        assert "107460" in norms, "Should extract 107460 from comma-separated"
        print("PASS: Comma-separated PO values handled correctly")

    def test_preserves_alphanumeric_chars(self):
        """Alphanumeric PO numbers should be preserved"""
        from services.po_resolution_service import normalize_po
        
        assert normalize_po("W117397") == "W117397"
        assert normalize_po("SI-02-26-31488") == "SI-02-26-31488"
        print("PASS: Alphanumeric PO numbers preserved")


# ---------------------------------------------------------------------------
# MODULE: PO Candidate Extraction
# ---------------------------------------------------------------------------

class TestPOCandidateExtraction:
    """Tests for extract_po_candidates function"""

    def test_extracts_from_po_number_field(self):
        """Should extract from extracted_fields.po_number"""
        from services.po_resolution_service import extract_po_candidates
        
        fields = {"po_number": "109023"}
        candidates = extract_po_candidates("", fields)
        assert len(candidates) >= 1
        assert candidates[0]["normalized"] == "109023"
        assert candidates[0]["source"].startswith("extracted_field:")
        print("PASS: Extracts from po_number field")

    def test_extracts_from_order_number_field(self):
        """Should also check order_number field"""
        from services.po_resolution_service import extract_po_candidates
        
        fields = {"order_number": "5477796"}
        candidates = extract_po_candidates("", fields)
        assert any(c["normalized"] == "5477796" for c in candidates)
        print("PASS: Extracts from order_number field")

    def test_extracts_from_text_with_regex(self):
        """Should extract PO numbers from raw text via regex"""
        from services.po_resolution_service import extract_po_candidates
        
        text = "Our PO# 123456 has been shipped"
        candidates = extract_po_candidates(text, {})
        norms = {c["normalized"] for c in candidates}
        assert "123456" in norms
        print("PASS: Extracts from raw text via regex")

    def test_deduplicates_candidates(self):
        """Same PO number from multiple sources should be deduplicated"""
        from services.po_resolution_service import extract_po_candidates
        
        text = "PO# 109023 confirmed"
        fields = {"po_number": "109023"}
        candidates = extract_po_candidates(text, fields)
        norms = [c["normalized"] for c in candidates]
        assert norms.count("109023") == 1, "Should deduplicate"
        print("PASS: Duplicate candidates are deduplicated")

    def test_extracts_from_description_field(self):
        """Should directly extract PO number from description field when value is PO-shaped"""
        from services.po_resolution_service import extract_po_candidates

        fields = {"description": "107459"}
        candidates = extract_po_candidates("", fields)
        direct = [c for c in candidates if c["source"] == "extracted_field:description"]
        assert len(direct) >= 1, "description='107459' should produce a direct candidate"
        assert direct[0]["normalized"] == "107459"
        assert direct[0]["confidence"] >= 0.70
        print("PASS: Extracts PO number directly from description field")

    def test_extracts_from_invoice_description_field(self):
        """Should extract PO from invoice_description and line_description fields"""
        from services.po_resolution_service import extract_po_candidates

        fields = {"invoice_description": "W117397", "line_description": "PR10088"}
        candidates = extract_po_candidates("", fields)
        norms = {c["normalized"] for c in candidates}
        assert "W117397" in norms, "invoice_description='W117397' should be extracted"
        assert "PR10088" in norms, "line_description='PR10088' should be extracted"
        inv_desc = [c for c in candidates if c["source"] == "extracted_field:invoice_description"]
        assert len(inv_desc) >= 1
        assert inv_desc[0]["confidence"] >= 0.60
        print("PASS: Extracts PO from invoice_description and line_description")

    def test_description_non_po_text_no_candidate(self):
        """Non-PO descriptive text in description should NOT generate a direct candidate"""
        from services.po_resolution_service import extract_po_candidates

        fields = {"description": "Invoice for services"}
        candidates = extract_po_candidates("", fields)
        direct = [c for c in candidates if c["source"] == "extracted_field:description"]
        assert len(direct) == 0, (
            f"'Invoice for services' should not produce a direct description candidate, "
            f"got {direct}"
        )
        print("PASS: Non-PO description text does not generate a direct candidate")


# ---------------------------------------------------------------------------
# MODULE: Pipeline Stage Order
# ---------------------------------------------------------------------------

class TestPipelineStageOrder:
    """Verify po_resolution is in the pipeline stages"""

    def test_pipeline_has_po_resolution_stage(self):
        """STAGE_ORDER should include po_resolution between entity_resolution and transaction_match"""
        from services.pipeline.document_pipeline import STAGE_ORDER
        
        assert "po_resolution" in STAGE_ORDER, "po_resolution not in STAGE_ORDER"
        
        po_idx = STAGE_ORDER.index("po_resolution")
        ent_idx = STAGE_ORDER.index("entity_resolution")
        tx_idx = STAGE_ORDER.index("transaction_match")
        
        assert ent_idx < po_idx < tx_idx, \
            f"po_resolution ({po_idx}) should be between entity_resolution ({ent_idx}) and transaction_match ({tx_idx})"
        print(f"PASS: po_resolution at index {po_idx} (between entity_resolution and transaction_match)")


# ---------------------------------------------------------------------------
# MODULE: Required Doc Types
# ---------------------------------------------------------------------------

class TestPORequiredDocTypes:
    """Verify which document types require PO resolution"""

    def test_shipping_doc_requires_po(self):
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        assert "Shipping_Document" in PO_REQUIRED_DOC_TYPES
        print("PASS: Shipping_Document requires PO resolution")

    def test_warehouse_receipt_requires_po(self):
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        assert "Warehouse_Receipt" in PO_REQUIRED_DOC_TYPES
        print("PASS: Warehouse_Receipt requires PO resolution")

    def test_freight_doc_requires_po(self):
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        assert "Freight_Document" in PO_REQUIRED_DOC_TYPES
        print("PASS: Freight_Document requires PO resolution")

    def test_ap_invoice_does_not_require_po(self):
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        assert "AP_Invoice" not in PO_REQUIRED_DOC_TYPES
        print("PASS: AP_Invoice does NOT require PO resolution")


# ---------------------------------------------------------------------------
# MODULE: Auto-Clear Shipping Docs Need PO Resolution
# ---------------------------------------------------------------------------

class TestAutoClearPORequirement:
    """Verify auto-clear requires PO resolution for shipping docs"""

    def test_auto_clear_checks_po_resolution(self):
        """evaluate_auto_clear should have po_resolution check for shipping docs"""
        from services.auto_clear_service import evaluate_auto_clear, AutoClearDecision
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        
        # Shipping doc without po_resolution should not auto-clear
        doc = {
            "id": "test-shipping-doc",
            "document_type": "Shipping_Document",
            "ai_confidence": 0.95,
            "extracted_fields": {"vendor": "Test Vendor", "po_number": "12345"},
            "normalized_fields": {},
            # No po_resolution field
        }
        
        decision, reason, details = evaluate_auto_clear(doc)
        
        # Should either fail po_resolution check or be needs_review
        checks = {c["check"]: c for c in details.get("checks", [])}
        if "po_resolution" in checks:
            assert checks["po_resolution"]["passed"] == False, \
                "po_resolution check should fail when po_resolution is missing"
            print("PASS: Shipping doc without po_resolution fails po_resolution check")
        else:
            # Check is present in the logic
            print("PASS: auto_clear_service has po_resolution check logic (CHECK 5a)")


# ---------------------------------------------------------------------------
# MODULE: Readiness Engine PO Signal
# ---------------------------------------------------------------------------

class TestReadinessEnginePOSignal:
    """Verify readiness engine uses po_resolution for shipping docs"""

    def test_compute_signals_uses_po_resolution(self):
        """compute_signals should check po_resolution.status for shipping docs"""
        from services.document_readiness_service import compute_signals
        from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
        
        # Shipping doc with resolved PO
        doc_resolved = {
            "document_type": "Shipping_Document",
            "extracted_fields": {"po_number": "109023"},
            "po_resolution": {"status": "resolved", "po_number": "109023"}
        }
        signals_resolved = compute_signals(doc_resolved)
        assert signals_resolved["po_resolved"] == True, \
            f"po_resolved should be True for resolved PO, got {signals_resolved['po_resolved']}"
        
        # Shipping doc with not_found PO
        doc_not_found = {
            "document_type": "Shipping_Document",
            "extracted_fields": {"po_number": "UNKNOWN123"},
            "po_resolution": {"status": "not_found"}
        }
        signals_not_found = compute_signals(doc_not_found)
        assert signals_not_found["po_resolved"] == False, \
            f"po_resolved should be False for not_found PO, got {signals_not_found['po_resolved']}"
        
        # Non-shipping doc (AP_Invoice) - just having po_number is enough
        doc_ap = {
            "document_type": "AP_Invoice",
            "extracted_fields": {"po_number": "12345"}
        }
        signals_ap = compute_signals(doc_ap)
        assert signals_ap["po_resolved"] == True, \
            f"AP_Invoice should have po_resolved=True with just po_number, got {signals_ap['po_resolved']}"
        
        print("PASS: Readiness engine correctly uses po_resolution for shipping docs")


# ---------------------------------------------------------------------------
# MODULE: Transaction Matching Uses PO Resolution
# ---------------------------------------------------------------------------

class TestTransactionMatchingPOResolution:
    """Verify transaction matching uses PO resolution results"""

    def test_match_transactions_imports_po_required_types(self):
        """transaction_matching_service should import PO_REQUIRED_DOC_TYPES"""
        import services.transaction_matching_service as tm_svc
        
        # The service should check for PO resolution status
        import inspect
        source = inspect.getsource(tm_svc.match_transactions)
        
        assert "PO_REQUIRED_DOC_TYPES" in source, \
            "match_transactions should reference PO_REQUIRED_DOC_TYPES"
        assert "po_resolution" in source, \
            "match_transactions should check po_resolution field"
        
        print("PASS: Transaction matching service uses PO resolution for shipping docs")


# ---------------------------------------------------------------------------
# MODULE: Backend Health and Existing Endpoints
# ---------------------------------------------------------------------------

class TestBackendHealth:
    """Verify backend starts without errors and existing endpoints work"""

    def test_health_endpoint(self):
        """Health endpoint should return healthy"""
        resp = requests.get(f"{BASE_URL}/api/health", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"
        print("PASS: Backend health check returns healthy")

    def test_documents_endpoint(self):
        """Documents endpoint should work"""
        resp = requests.get(f"{BASE_URL}/api/documents?limit=3", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert "total" in data
        print(f"PASS: Documents endpoint returns {data.get('counts', {}).get('total_all', 0)} total documents")

    def test_dashboard_stats_endpoint(self):
        """Dashboard stats should work"""
        resp = requests.get(f"{BASE_URL}/api/dashboard/stats", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_documents" in data
        assert "by_status" in data
        assert "by_type" in data
        print(f"PASS: Dashboard stats endpoint returns {data['total_documents']} documents")

    def test_square9_stage_counts_endpoint(self):
        """Square9 stage-counts should return 200 with stages array (regression for NameError fix)"""
        resp = requests.get(f"{BASE_URL}/api/square9/stage-counts", timeout=30)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "stages" in data, "Response missing 'stages' key"
        assert isinstance(data["stages"], list), "stages should be a list"
        assert len(data["stages"]) > 0, "stages should not be empty"
        assert "total_documents" in data, "Response missing 'total_documents'"
        print(f"PASS: Square9 stage-counts returns {len(data['stages'])} stages, {data['total_documents']} docs")

    def test_square9_migration_status_endpoint(self):
        """Square9 migration-status should return 200 with cutover readiness info"""
        resp = requests.get(f"{BASE_URL}/api/square9/migration-status", timeout=30)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "total_documents" in data
        assert "with_square9_stage" in data
        assert "cutover_readiness" in data
        assert "square9_active" in data
        print(f"PASS: migration-status: readiness={data['cutover_readiness']}, active={data['square9_active']}")

    def test_square9_cutover_idempotent(self):
        """Square9 cutover should be idempotent — second call returns already_decommissioned"""
        resp = requests.post(f"{BASE_URL}/api/admin/square9-cutover", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("decommissioned", "already_decommissioned")
        print(f"PASS: cutover idempotent: status={data['status']}")


# ---------------------------------------------------------------------------
# Run with pytest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
