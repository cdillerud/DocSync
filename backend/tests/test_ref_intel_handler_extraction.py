"""
GPI Document Hub - Reference Intelligence Handler Extraction Tests

Validates:
  1. All 7 reference intelligence routes still available at original paths
  2. Route handlers now sourced from services.reference_intelligence_handlers
  3. routers/reference_intelligence.py no longer imports server for handler functions
  4. Route count stable at 427
  5. Handler behavior preserved (response shapes, error codes)
"""

import requests
import os

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestRefIntelRouteAvailability:
    """All 7 reference intelligence routes reachable at original paths."""

    def test_resolve_bc_reference_accepts_post(self):
        """POST /api/bc/resolve-reference — 200 with reference_number param."""
        resp = requests.post(
            f"{API_BASE}/api/bc/resolve-reference",
            params={"reference_number": "TEST-REF-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_resolve_bc_reference_requires_param(self):
        """POST /api/bc/resolve-reference — 422 without required param."""
        resp = requests.post(f"{API_BASE}/api/bc/resolve-reference")
        assert resp.status_code == 422

    def test_resolve_document_reference_accepts_post(self):
        """POST /api/documents/{id}/resolve-reference — 404 for missing doc."""
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/resolve-reference")
        assert resp.status_code == 404

    def test_resolve_document_intelligence_accepts_post(self):
        """POST /api/documents/{id}/resolve-intelligence — 404 for missing doc."""
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/resolve-intelligence")
        assert resp.status_code == 404

    def test_get_reference_intelligence_accepts_get(self):
        """GET /api/documents/{id}/reference-intelligence — 404 for missing doc."""
        resp = requests.get(f"{API_BASE}/api/documents/NONEXISTENT/reference-intelligence")
        assert resp.status_code == 404

    def test_auto_resolve_accepts_post(self):
        """POST /api/documents/{id}/auto-resolve — 404 for missing doc."""
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/auto-resolve")
        assert resp.status_code == 404

    def test_matching_debug_accepts_get(self):
        """GET /api/documents/{id}/matching-debug — 404 for missing doc."""
        resp = requests.get(f"{API_BASE}/api/documents/NONEXISTENT/matching-debug")
        assert resp.status_code == 404

    def test_matching_debug_rerun_accepts_post(self):
        """POST /api/documents/{id}/matching-debug/rerun — 404 for missing doc."""
        resp = requests.post(f"{API_BASE}/api/documents/NONEXISTENT/matching-debug/rerun")
        assert resp.status_code == 404


class TestRefIntelResponseShapes:
    """Response shapes preserved after extraction."""

    def test_resolve_bc_reference_response_shape(self):
        resp = requests.post(
            f"{API_BASE}/api/bc/resolve-reference",
            params={"reference_number": "SO-999999"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "reference_number" in data or "query" in data or "matches" in data or "tables_checked" in data

    def test_resolve_bc_reference_with_tables_filter(self):
        resp = requests.post(
            f"{API_BASE}/api/bc/resolve-reference",
            params={"reference_number": "PO-12345", "tables": "purchaseOrders,salesOrders"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


class TestRefIntelRouterDecoupling:
    """routers/reference_intelligence.py decoupled from server.py for handler functions."""

    def test_handler_module_exists(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from services.reference_intelligence_handlers import (
            resolve_bc_reference,
            resolve_document_reference,
            resolve_document_intelligence,
            get_document_reference_intelligence,
            trigger_auto_resolve,
            get_matching_debug,
            rerun_matching_with_diagnostics,
        )
        assert callable(resolve_bc_reference)
        assert callable(resolve_document_reference)
        assert callable(resolve_document_intelligence)
        assert callable(get_document_reference_intelligence)
        assert callable(trigger_auto_resolve)
        assert callable(get_matching_debug)
        assert callable(rerun_matching_with_diagnostics)

    def test_router_no_longer_imports_server_for_handlers(self):
        """Verify the register_server_routes function imports from services.reference_intelligence_handlers."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import inspect
        from routers.reference_intelligence import register_server_routes
        source = inspect.getsource(register_server_routes)
        assert "from services.reference_intelligence_handlers import" in source
        assert "import server" not in source


class TestExistingEndpointsStillWork:
    """Verify non-reference-intelligence endpoints are unaffected."""

    def test_health(self):
        resp = requests.get(f"{API_BASE}/api/health")
        assert resp.status_code == 200

    def test_documents_list(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data

    def test_workflows_list(self):
        resp = requests.get(f"{API_BASE}/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflows" in data

    def test_workflow_mutation_still_works(self):
        """A workflow mutation route (from prior extraction) still returns expected error."""
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/set-vendor",
            json={"vendor_id": "V001"},
        )
        assert resp.status_code == 404


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
