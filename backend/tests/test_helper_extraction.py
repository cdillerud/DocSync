"""
GPI Document Hub - Shared Helper Extraction Tests

Validates:
  1. Vendor name helpers importable from services.vendor_name_helpers
  2. Dashboard helpers importable from services.dashboard_helpers
  3. BC API helpers importable from services.bc_api_helpers
  4. Router consumers rewired away from server.py
  5. Route count stable at 427
  6. Affected endpoints still respond correctly
  7. Thin compatibility wrappers in server.py still functional
"""

import os
import sys
import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestVendorNameHelpers:
    """services.vendor_name_helpers is the authoritative source."""

    def test_normalize_vendor_name_importable(self):
        from services.vendor_name_helpers import normalize_vendor_name
        assert callable(normalize_vendor_name)

    def test_normalize_basic(self):
        from services.vendor_name_helpers import normalize_vendor_name
        assert normalize_vendor_name("Acme Corp") == "acme"
        assert normalize_vendor_name("Widget LLC") == "widget"
        assert normalize_vendor_name("") == ""
        assert normalize_vendor_name("Foo, Inc.") == "foo"
        assert normalize_vendor_name("Siemens GmbH") == "siemens"

    def test_normalize_whitespace(self):
        from services.vendor_name_helpers import normalize_vendor_name
        assert normalize_vendor_name("  Foo   Bar  ") == "foo bar"

    def test_calculate_fuzzy_score_importable(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        assert callable(calculate_fuzzy_score)

    def test_fuzzy_exact_match(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        assert calculate_fuzzy_score("Acme Corp", "Acme Corp") == 1.0

    def test_fuzzy_no_match(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        assert calculate_fuzzy_score("Acme", "Zebra") == 0.0

    def test_fuzzy_bc_code_prefix(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        score = calculate_fuzzy_score("Tumalo Creek", "TUMALOC - Tumalo Creek")
        assert score >= 0.5

    def test_fuzzy_empty(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        assert calculate_fuzzy_score("", "Acme") == 0.0
        assert calculate_fuzzy_score("Acme", "") == 0.0

    def test_vendor_alias_map_importable(self):
        from services.vendor_name_helpers import VENDOR_ALIAS_MAP
        assert isinstance(VENDOR_ALIAS_MAP, dict)


class TestDashboardHelpers:
    """services.dashboard_helpers is the authoritative source."""

    def test_aggregate_importable(self):
        from services.dashboard_helpers import aggregate_document_types_data
        assert callable(aggregate_document_types_data)

    def test_dashboard_endpoint_json(self):
        resp = requests.get(f"{API_BASE}/api/dashboard/document-types")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_type" in data
        assert "grand_total" in data or "source_systems" in data

    def test_dashboard_endpoint_with_filter(self):
        resp = requests.get(
            f"{API_BASE}/api/dashboard/document-types",
            params={"classification": "ai"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "by_type" in data


class TestBCApiHelpers:
    """services.bc_api_helpers is the authoritative source."""

    def test_get_bc_companies_importable(self):
        from services.bc_api_helpers import get_bc_companies
        assert callable(get_bc_companies)

    def test_get_bc_sales_orders_importable(self):
        from services.bc_api_helpers import get_bc_sales_orders
        assert callable(get_bc_sales_orders)

    def test_mock_data_present(self):
        from services.bc_api_helpers import MOCK_COMPANIES, MOCK_SALES_ORDERS
        assert len(MOCK_COMPANIES) == 2
        assert len(MOCK_SALES_ORDERS) == 7

    def test_sales_orders_endpoint(self):
        """GET /api/bc/sales-orders returns 200 (has error handling)."""
        resp = requests.get(f"{API_BASE}/api/bc/sales-orders")
        assert resp.status_code == 200


class TestBCSandboxServiceFix:
    """bc_sandbox_service no longer imports BC_CLIENT_SECRET from server."""

    def test_no_server_import(self):
        import inspect
        import services.bc_sandbox_service as svc
        source = inspect.getsource(svc)
        assert "from server import BC_CLIENT_SECRET" not in source


class TestRouterDecoupling:
    """Router modules rewired away from server.py for helper functions."""

    def test_aliases_uses_vendor_name_helpers(self):
        import inspect
        from routers.aliases import create_vendor_alias
        source = inspect.getsource(create_vendor_alias)
        assert "from services.vendor_name_helpers import" in source
        assert "from server import" not in source

    def test_aliases_suggest_uses_vendor_name_helpers(self):
        import inspect
        from routers.aliases import suggest_alias_creation
        source = inspect.getsource(suggest_alias_creation)
        assert "from services.vendor_name_helpers import" in source
        assert "from server import" not in source

    def test_bc_integration_uses_bc_api_helpers(self):
        import inspect
        from routers.bc_integration import list_bc_companies, list_bc_sales_orders
        companies_src = inspect.getsource(list_bc_companies)
        assert "from services.bc_api_helpers import" in companies_src
        assert "from server import" not in companies_src
        orders_src = inspect.getsource(list_bc_sales_orders)
        assert "from services.bc_api_helpers import" in orders_src
        assert "from server import" not in orders_src

    def test_dashboard_uses_dashboard_helpers(self):
        import inspect
        from routers.dashboard import get_document_types_dashboard
        source = inspect.getsource(get_document_types_dashboard)
        assert "from services.dashboard_helpers import" in source
        assert "from server import" not in source

    def test_workflow_handlers_uses_vendor_name_helpers(self):
        import inspect
        from services.workflow_handlers import _normalize_vendor_name
        source = inspect.getsource(_normalize_vendor_name)
        assert "from services.vendor_name_helpers import" in source
        assert "from server import" not in source

    def test_metrics_has_normalize_import(self):
        """metrics.py now has explicit import (was a latent NameError before)."""
        import inspect
        import routers.metrics
        source = inspect.getsource(routers.metrics)
        assert "from services.vendor_name_helpers import normalize_vendor_name" in source

    def test_pilot_has_normalize_import(self):
        """pilot.py now has explicit import (was a latent NameError before)."""
        import inspect
        import routers.pilot
        source = inspect.getsource(routers.pilot)
        assert "from services.vendor_name_helpers import normalize_vendor_name" in source


class TestServerCompatibilityWrappers:
    """Thin wrappers in server.py still resolve to authoritative implementations."""

    def test_normalize_vendor_name_wrapper(self):
        import server
        assert server.normalize_vendor_name("Acme Corp") == "acme"

    def test_calculate_fuzzy_score_wrapper(self):
        import server
        assert server.calculate_fuzzy_score("Acme", "Acme") == 1.0


class TestExistingEndpointsUnaffected:
    """Non-affected endpoints still respond correctly."""

    def test_health(self):
        resp = requests.get(f"{API_BASE}/api/health")
        assert resp.status_code == 200

    def test_documents_list(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200

    def test_workflows_list(self):
        resp = requests.get(f"{API_BASE}/api/workflows")
        assert resp.status_code == 200

    def test_aliases_list(self):
        resp = requests.get(f"{API_BASE}/api/aliases/vendors")
        assert resp.status_code == 200

    def test_workflow_mutation_still_works(self):
        resp = requests.post(
            f"{API_BASE}/api/workflows/ap_invoice/NONEXISTENT/set-vendor",
            json={"vendor_id": "V001"},
        )
        assert resp.status_code == 404

    def test_ref_intel_still_works(self):
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
