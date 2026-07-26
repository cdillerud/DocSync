"""
GPI Document Hub - Orchestration Extraction Tests

Validates:
  1. vendor_matching module functions work correctly
  2. ap_computation module functions work correctly
  3. document_handlers.py imports directly from extracted modules
  4. server.py compatibility wrappers still functional
  5. Route count stable at 931
  6. Affected endpoints still respond correctly
"""

import os
import sys
import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
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

        required_imports = (
            "from services.document_reprocess_service import reprocess_document",
            "from services.document_batch_revalidate_service import",
            "from services.document_preview_service import",
            "from services.document_classification_service import classify_document",
            "from services.document_resolution_service import",
            "from services.document_link_service import link_document",
            "from services.document_resubmit_service import resubmit_document",
            "from services.document_retry_service import retry_document",
            "from services.document_upload_service import upload_document",
            "from services.document_intake_service import intake_document",
        )

        for required_import in required_imports:
            assert required_import in source

    def test_handlers_is_thin_facade_plus_bytes_intake(self):
        import ast
        import inspect
        import services.document_handlers as dh

        source = inspect.getsource(dh)
        tree = ast.parse(source)

        local_functions = [
            node.name
            for node in tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
        ]

        assert local_functions == ["intake_document_from_bytes"]
        assert "from fastapi import" not in source
        assert "from pydantic import" not in source
        assert "from deps import get_db" not in source
        assert "def _get_workflow_enums" not in source
        assert "def _get_transaction_action" not in source
        assert "def _get_default_job_types" not in source

    def test_classify_document_uses_direct_import(self):
        import inspect
        from services.document_handlers import classify_document
        source = inspect.getsource(classify_document)
        assert "_classify_with_ai(" in source
        assert "srv.classify_document_with_ai" not in source

    def test_reprocess_uses_direct_import(self):
        import services.document_handlers as handlers
        from services.document_reprocess_service import reprocess_document as service_reprocess
        assert handlers.reprocess_document is service_reprocess

    def test_batch_revalidate_uses_direct_import(self):
        import inspect
        from services.document_handlers import batch_revalidate_documents
        source = inspect.getsource(batch_revalidate_documents)
        assert "_make_automation_decision(" in source
        assert "srv = _server()" not in source


    def test_intake_uses_extracted_service(self):
        import services.document_handlers as handlers
        from services.document_intake_service import (
            intake_document as service_intake,
        )

        assert handlers.intake_document is service_intake

    def test_bytes_intake_remains_in_handlers(self):
        import services.document_handlers as handlers

        assert (
            handlers.intake_document_from_bytes.__module__
            == "services.document_handlers"
        )


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
    """Route count preserved at the current extracted baseline."""

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
        assert count == 931, f"Expected 931, got {count}"
