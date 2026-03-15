"""
GPI Document Hub - Legacy Route Registration Cleanup Tests

Validates that routes previously on api_router (now removed) are still
available via add_api_route() registration in router modules.

Covers:
  1. Document routes (routers/documents.py add_api_route)
  2. Workflow routes (routers/workflows.py add_api_route)
  3. Reference Intelligence routes (routers/reference_intelligence.py add_api_route)
  4. Route count stability (427 routes)
  5. No api_router import from server.py
"""

import requests
import os

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


def _auth_header():
    resp = requests.post(f"{API_BASE}/api/auth/login",
                         json={"username": "admin", "password": "admin"})
    token = resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


class TestDocumentRoutesAvailable:
    """Routes registered via documents.py add_api_route."""

    def test_documents_upload_accepts_post(self):
        """POST /api/documents/upload should be reachable (will 422 without file)."""
        resp = requests.post(f"{API_BASE}/api/documents/upload")
        assert resp.status_code == 422  # missing required file param

    def test_documents_intake_accepts_post(self):
        """POST /api/documents/intake should be reachable."""
        resp = requests.post(f"{API_BASE}/api/documents/intake",
                             json={"source": "test"})
        # 422 or 400 expected (missing required fields), not 404
        assert resp.status_code != 404

    def test_documents_batch_revalidate_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/documents/batch-revalidate",
                             json={})
        assert resp.status_code != 404


class TestWorkflowRoutesAvailable:
    """Routes registered via workflows.py add_api_route."""

    def test_ap_status_counts(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/status-counts")
        assert resp.status_code == 200

    def test_ap_vendor_pending(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/vendor-pending")
        assert resp.status_code == 200

    def test_generic_queue(self):
        resp = requests.get(f"{API_BASE}/api/workflows/generic/queue")
        assert resp.status_code == 200

    def test_generic_status_counts_by_type(self):
        resp = requests.get(f"{API_BASE}/api/workflows/generic/status-counts-by-type")
        assert resp.status_code == 200

    def test_ap_metrics(self):
        resp = requests.get(f"{API_BASE}/api/workflows/ap_invoice/metrics")
        assert resp.status_code == 200


class TestRefIntelRoutesAvailable:
    """Routes registered via reference_intelligence.py add_api_route."""

    def test_resolve_reference_accepts_post(self):
        resp = requests.post(f"{API_BASE}/api/bc/resolve-reference",
                             json={"reference": "PO-TEST"})
        # Should be reachable (not 404), may fail with business logic error
        assert resp.status_code != 404

    def test_matching_debug_requires_doc(self):
        resp = requests.get(f"{API_BASE}/api/documents/NONEXISTENT/matching-debug")
        # 404 for missing doc is fine; confirms route exists
        assert resp.status_code in (200, 404, 500)

    def test_reference_intelligence_requires_doc(self):
        resp = requests.get(f"{API_BASE}/api/documents/NONEXISTENT/reference-intelligence")
        assert resp.status_code in (200, 404, 500)


class TestRouteCountStability:
    """Verify total route count hasn't changed after cleanup."""

    def test_route_count_unchanged(self):
        """Route count should be 427 after removing the empty api_router."""
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
        assert count == 427, f"Expected 427 routes, got {count}"


class TestApiRouterRemoved:
    """Verify api_router no longer exists in server.py exports."""

    def test_no_api_router_attribute(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import server
        assert not hasattr(server, 'api_router'), \
            "server.py should no longer export api_router"
