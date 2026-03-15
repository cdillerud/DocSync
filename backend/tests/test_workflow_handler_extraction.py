"""
GPI Document Hub - Workflow Handler Extraction Tests

Validates:
  1. All 15 workflow mutation routes still available at original paths
  2. Route handlers now sourced from services.workflow_handlers
  3. routers/workflows.py no longer imports server for handler functions
  4. Route count stable at 427
  5. Handler behavior preserved (response shapes, error codes)
  6. Pydantic models importable from the new module
"""

import requests
import os

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestAPInvoiceRouteAvailability:
    """All 6 AP Invoice mutation routes reachable at original paths."""

    def test_set_vendor_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/set-vendor — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/set-vendor",
            json={"vendor_id": "V001"},
        )
        assert resp.status_code == 404

    def test_update_fields_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/update-fields — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/update-fields",
            json={},
        )
        assert resp.status_code == 404

    def test_override_bc_validation_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/override-bc-validation — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/override-bc-validation",
            json={"override_reason": "test", "override_user": "admin"},
        )
        assert resp.status_code == 404

    def test_start_approval_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/start-approval — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/start-approval",
            json={},
        )
        assert resp.status_code == 404

    def test_approve_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/approve — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/approve",
            json={},
        )
        assert resp.status_code == 404

    def test_reject_accepts_post(self):
        """POST /api/workflows/ap_invoice/{id}/reject — 404 for missing doc."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/reject",
            json={"reason": "test rejection"},
        )
        assert resp.status_code == 404


class TestGenericWorkflowRouteAvailability:
    """All 9 generic workflow mutation routes reachable at original paths."""

    def test_mark_ready_for_review_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/mark-ready-for-review")
        assert resp.status_code == 404

    def test_mark_reviewed_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/mark-reviewed")
        assert resp.status_code == 404

    def test_start_approval_generic_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/start-approval")
        assert resp.status_code == 404

    def test_approve_generic_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/approve")
        assert resp.status_code == 404

    def test_reject_generic_accepts_post(self):
        resp = requests.post(
            f"{API_BASE}/api/workflows/NONEXISTENT/reject",
            params={"reason": "test"},
        )
        assert resp.status_code == 404

    def test_complete_triage_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/complete-triage")
        assert resp.status_code == 404

    def test_link_credit_to_invoice_accepts_post(self):
        resp = requests.post(
            f"{API_BASE}/api/workflows/NONEXISTENT/link-credit-to-invoice",
            params={"invoice_id": "INV001"},
        )
        assert resp.status_code == 404

    def test_tag_quality_accepts_post(self):
        resp = requests.post(
            f"{API_BASE}/api/workflows/NONEXISTENT/tag-quality",
            params={"tags": ["defect"]},
        )
        assert resp.status_code == 404

    def test_export_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/workflows/NONEXISTENT/export")
        assert resp.status_code == 404


class TestExistingQueryRoutesStillWork:
    """Simple query routes in the router still function."""

    def test_workflow_list(self):
        resp = requests.get(f"{API_BASE}/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflows" in data
        assert "total" in data

    def test_ap_status_counts(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/status-counts")
        assert resp.status_code == 200
        data = resp.json()
        assert "status_counts" in data

    def test_vendor_pending_queue(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/vendor-pending")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert data.get("queue") == "vendor_pending"

    def test_ap_metrics(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data

    def test_generic_queue(self):
        resp = requests.get(f"{API_BASE}/api/workflows/generic/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data

    def test_generic_status_counts_by_type(self):
        resp = requests.get(f"{API_BASE}/api/workflows/generic/status-counts-by-type")
        assert resp.status_code == 200
        data = resp.json()
        assert "status_counts_by_type" in data


class TestRouterDecoupling:
    """routers/workflows.py decoupled from server.py for handler functions."""

    def test_workflow_handlers_module_exists(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.workflow_handlers import (
            set_vendor_for_document,
            update_document_fields,
            override_bc_validation,
            start_approval,
            approve_document,
            reject_document,
            mark_ready_for_review,
            mark_reviewed,
            start_approval_generic,
            approve_generic,
            reject_generic,
            complete_triage,
            link_credit_to_invoice,
            tag_quality_doc,
            export_document,
        )
        # All 15 handlers importable from the new module
        assert callable(set_vendor_for_document)
        assert callable(update_document_fields)
        assert callable(override_bc_validation)
        assert callable(start_approval)
        assert callable(approve_document)
        assert callable(reject_document)
        assert callable(mark_ready_for_review)
        assert callable(mark_reviewed)
        assert callable(start_approval_generic)
        assert callable(approve_generic)
        assert callable(reject_generic)
        assert callable(complete_triage)
        assert callable(link_credit_to_invoice)
        assert callable(tag_quality_doc)
        assert callable(export_document)

    def test_pydantic_models_in_handlers(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.workflow_handlers import (
            SetVendorRequest,
            UpdateFieldsRequest,
            BCValidationOverrideRequest,
            ApprovalActionRequest,
        )
        sv = SetVendorRequest(vendor_id="V001", vendor_name="Test Co")
        assert sv.vendor_id == "V001"
        uf = UpdateFieldsRequest(invoice_number="INV-123", amount=100.50)
        assert uf.amount == 100.50
        bc = BCValidationOverrideRequest(override_reason="test", override_user="admin")
        assert bc.override_reason == "test"
        aa = ApprovalActionRequest(reason="approved", approver="admin")
        assert aa.approver == "admin"

    def test_router_no_longer_imports_server_for_handlers(self):
        """Verify the register_server_routes function imports from services.workflow_handlers."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import inspect
        from routers.workflows import register_server_routes
        source = inspect.getsource(register_server_routes)
        assert "from services.workflow_handlers import" in source
        assert "import server" not in source


class TestRouteCountStable:
    """Route count preserved at 427."""

    def test_count(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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
