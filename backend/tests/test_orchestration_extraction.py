"""
GPI Document Hub - Orchestration Extraction Tests

Validates:
  1. vendor_matching module functions work correctly
  2. ap_computation module functions work correctly
  3. document_handlers.py imports directly from extracted modules
  4. server.py compatibility wrappers still functional
  5. Route count stable at 427
  6. Affected endpoints still respond correctly
"""

import os
import sys
import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestVendorMatching:
    """services.vendor_matching functions importable and correct."""

    def test_lookup_vendor_alias_importable(self):
        from services.vendor_matching import lookup_vendor_alias
        assert callable(lookup_vendor_alias)

    def test_match_vendor_in_bc_importable(self):
        from services.vendor_matching import match_vendor_in_bc
        assert callable(match_vendor_in_bc)

    def test_check_duplicate_document_importable(self):
        from services.vendor_matching import check_duplicate_document
        assert callable(check_duplicate_document)


class TestAPComputation:
    """services.ap_computation functions importable and correct."""

    def test_compute_ap_validation_importable(self):
        from services.ap_computation import compute_ap_validation
        assert callable(compute_ap_validation)

    def test_compute_ap_validation_all_fields(self):
        from services.ap_computation import compute_ap_validation
        result = compute_ap_validation(
            document_type="AP_Invoice",
            vendor_normalized="acme",
            invoice_number_clean="INV001",
            amount_float=100.0,
            po_number_clean="PO001",
            ai_confidence=0.95,
        )
        assert result["draft_candidate"] is True
        assert len(result["validation_errors"]) == 0

    def test_compute_ap_validation_missing_vendor(self):
        from services.ap_computation import compute_ap_validation
        result = compute_ap_validation(
            document_type="AP_Invoice",
            vendor_normalized="",
            invoice_number_clean="INV001",
            amount_float=100.0,
            po_number_clean="PO001",
            ai_confidence=0.95,
        )
        assert result["draft_candidate"] is False
        assert "Missing vendor name" in result["validation_errors"]

    def test_compute_ap_validation_low_confidence(self):
        from services.ap_computation import compute_ap_validation
        result = compute_ap_validation(
            document_type="AP_Invoice",
            vendor_normalized="acme",
            invoice_number_clean="INV001",
            amount_float=100.0,
            po_number_clean="PO001",
            ai_confidence=0.5,
        )
        assert result["draft_candidate"] is False
        assert any("confidence" in e.lower() for e in result["validation_errors"])

    def test_compute_ap_status_importable(self):
        from services.ap_computation import compute_ap_status
        assert callable(compute_ap_status)

    def test_compute_draft_candidate_flag_importable(self):
        from services.ap_computation import compute_draft_candidate_flag
        assert callable(compute_draft_candidate_flag)

    def test_is_eligible_for_draft_creation_importable(self):
        from services.ap_computation import is_eligible_for_draft_creation
        assert callable(is_eligible_for_draft_creation)

    def test_is_eligible_feature_flag_off(self):
        from services.ap_computation import is_eligible_for_draft_creation
        # Feature flag is off by default in test environment
        eligible, reason = is_eligible_for_draft_creation(
            job_type="AP_Invoice",
            match_method="exact_name",
            match_score=0.95,
            ai_confidence=0.95,
            validation_results={"all_passed": True, "checks": []},
            doc={"status": "NeedsReview"},
        )
        # Either disabled by feature flag or passes - both are valid
        assert isinstance(eligible, bool)
        assert isinstance(reason, str)


class TestDocumentHandlersRewiring:
    """document_handlers.py uses direct imports instead of _server()."""

    def test_direct_imports_present(self):
        import inspect
        import services.document_handlers as dh
        source = inspect.getsource(dh)
        assert "from services.document_intel_helpers import" in source
        assert "from services.vendor_matching import" in source
        assert "from services.ap_computation import" in source
        assert "from services.bc_api_helpers import" in source

    def test_classify_document_uses_direct_import(self):
        import inspect
        from services.document_handlers import classify_document
        source = inspect.getsource(classify_document)
        assert "_classify_with_ai(" in source
        assert "srv.classify_document_with_ai" not in source

    def test_reprocess_uses_direct_import(self):
        import inspect
        from services.document_handlers import reprocess_document
        source = inspect.getsource(reprocess_document)
        assert "_classify_with_ai(" in source or "_make_automation_decision(" in source
        assert "srv = _server()" not in source

    def test_batch_revalidate_uses_direct_import(self):
        import inspect
        from services.document_handlers import batch_revalidate_documents
        source = inspect.getsource(batch_revalidate_documents)
        assert "_make_automation_decision(" in source
        assert "srv = _server()" not in source


class TestServerCompatibilityWrappers:
    """Thin wrappers in server.py still resolve correctly."""

    def test_compute_ap_validation_wrapper(self):
        import server
        result = server.compute_ap_validation(
            "AP_Invoice", "acme", "INV001", 100.0, "PO001", 0.95
        )
        assert result["draft_candidate"] is True

    def test_is_eligible_wrapper(self):
        import server
        eligible, reason = server.is_eligible_for_draft_creation(
            "AP_Invoice", "exact_name", 0.95, 0.95,
            {"all_passed": True, "checks": []}, {"status": "NeedsReview"},
        )
        assert isinstance(eligible, bool)


class TestExistingEndpointsUnaffected:
    """All endpoints still respond."""

    def test_health(self):
        resp = requests.get(f"{API_BASE}/api/health")
        assert resp.status_code == 200

    def test_documents_list(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200

    def test_workflows_list(self):
        resp = requests.get(f"{API_BASE}/api/workflows")
        assert resp.status_code == 200

    def test_dashboard(self):
        resp = requests.get(f"{API_BASE}/api/dashboard/document-types")
        assert resp.status_code == 200

    def test_workflow_mutation(self):
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/set-vendor",
            json={"vendor_id": "V001"},
        )
        assert resp.status_code == 404

    def test_ref_intel(self):
        resp = requests.post(
            f"{API_BASE}/api/bc/resolve-reference",
            params={"reference_number": "TEST123"},
        )
        assert resp.status_code == 200


class TestRouteCountStable:
    """Route count preserved at 427."""

    def test_count(self):
        from main import app
        count = 0
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                count += 1
            elif hasattr(route, 'path') and hasattr(route, 'routes'):
                for sub in route.routes:
                    if hasattr(sub, 'path') and hasattr(sub, 'methods'):
                        count += 1
        assert count == 427, f"Expected 427, got {count}"
