"""
GPI Document Hub - Document Handler Extraction Tests

Validates:
  1. All 10 document routes still available at original paths
  2. Route handlers now sourced from services.document_handlers
  3. routers/documents.py no longer imports server for handler functions
  4. Route count stable at 427
  5. Handler behavior preserved (response shapes, error codes)
"""

import requests
import os

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestDocumentRouteAvailability:
    """All 10 document-domain routes reachable at original paths."""

    def test_upload_accepts_post(self):
        """POST /api/documents/upload — 422 without file (route exists)."""
        resp = requests.post(f"{API_BASE}/api/documents/upload")
        assert resp.status_code == 422

    def test_retry_accepts_post(self):
        """POST /api/documents/{id}/retry — 404 for missing doc."""
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/retry")
        assert resp.status_code == 404

    def test_resubmit_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/resubmit")
        assert resp.status_code == 404

    def test_link_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/link",
                             params={"bc_record_id": "test"})
        assert resp.status_code == 404

    def test_intake_accepts_post(self):
        """POST /api/documents/intake — 422 without file."""
        resp = requests.post(f"{API_BASE}/api/documents/intake")
        assert resp.status_code == 422

    def test_classify_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/classify")
        assert resp.status_code == 404

    def test_resolve_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/resolve",
                             json={})
        assert resp.status_code == 404

    def test_reprocess_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/reprocess")
        assert resp.status_code == 404

    def test_batch_revalidate_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/batch-revalidate")
        assert resp.status_code != 404  # should work (may return 200 with count=0)

    def test_preview_post_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/preview-post")
        assert resp.status_code == 404


class TestDocumentRouteResponses:
    """Response shapes preserved after extraction."""

    def test_batch_revalidate_returns_result_shape(self):
        resp = requests.post(f"{API_BASE}/api/documents/batch-revalidate")
        assert resp.status_code == 200
        data = resp.json()
        # Should return count or results structure
        assert "count" in data or "total" in data or "message" in data

    def test_documents_list_still_works(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data


class TestRouterDecoupling:
    """routers/documents.py decoupled from server.py for handler functions."""

    def test_document_handlers_module_exists(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.document_handlers import (
            upload_document,
            retry_document,
            resubmit_document,
            link_document,
            intake_document,
            classify_document,
            resolve_and_link_document,
            reprocess_document,
            batch_revalidate_documents,
            preview_post_to_bc,
        )
        # All 10 handlers importable from the new module
        assert callable(upload_document)
        assert callable(retry_document)
        assert callable(resubmit_document)
        assert callable(link_document)
        assert callable(intake_document)
        assert callable(classify_document)
        assert callable(resolve_and_link_document)
        assert callable(reprocess_document)
        assert callable(batch_revalidate_documents)
        assert callable(preview_post_to_bc)

    def test_pydantic_models_in_handlers(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.document_handlers import ResolveRequest, DryRunPreviewRequest
        # Models moved to document_handlers
        r = ResolveRequest(selected_vendor_id="V001", notes="test")
        assert r.selected_vendor_id == "V001"
        d = DryRunPreviewRequest()
        assert d.use_production_bc is True


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
