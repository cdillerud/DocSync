"""
GPI Document Hub - Architecture Guardrail Tests

Prevents regression toward monolithic dependency patterns.
Verifies the intended dependency direction:
  main.py -> routers -> handlers -> services -> helpers

Tests:
  1. No router imports server.py (except documented exceptions)
  2. No service imports server.py (except documented exceptions)
  3. Newly extracted modules are importable
  4. Settings router uses deps, not server, for config
  5. Route count stable
  6. Affected endpoints still respond
"""

import os
import sys
import inspect
import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Allowed exceptions: files that may still import from server.py, with reason
# ---------------------------------------------------------------------------
ALLOWED_ROUTER_SERVER_IMPORTS = {
    "routers/mailbox_sources.py",  # Background task state (lifecycle: _dynamic_mailbox_polling_task, _mailbox_last_poll_times)
}

ALLOWED_SERVICE_SERVER_IMPORTS = {
    "services/mailbox_polling.py",  # Calls server._internal_intake_document (next extraction target)
}


class TestNoRouterImportsServer:
    """Routers must not import from server.py (except documented exceptions)."""

    def test_no_undocumented_router_server_imports(self):
        import pathlib
        routers_dir = pathlib.Path(__file__).parent.parent / "routers"
        violations = []
        for py_file in sorted(routers_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            rel_path = f"routers/{py_file.name}"
            content = py_file.read_text()
            has_server_import = (
                "from server import" in content
                or "import server" in content
            )
            if has_server_import and rel_path not in ALLOWED_ROUTER_SERVER_IMPORTS:
                violations.append(rel_path)
        assert violations == [], (
            f"Routers importing server.py without allowlist entry: {violations}. "
            f"Move the needed symbol into deps, a helper module, or the allowlist."
        )


class TestNoServiceImportsServer:
    """Services must not import from server.py (except documented exceptions)."""

    def test_no_undocumented_service_server_imports(self):
        import pathlib
        services_dir = pathlib.Path(__file__).parent.parent / "services"
        violations = []
        for py_file in sorted(services_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            rel_path = f"services/{py_file.name}"
            content = py_file.read_text()
            has_server_import = (
                "from server import" in content
                or "import server" in content
            )
            if has_server_import and rel_path not in ALLOWED_SERVICE_SERVER_IMPORTS:
                violations.append(rel_path)
        assert violations == [], (
            f"Services importing server.py without allowlist entry: {violations}. "
            f"Move the needed symbol into the appropriate service module or the allowlist."
        )


class TestNewModulesImportable:
    """Newly extracted modules are importable and contain expected symbols."""

    def test_settings_helpers(self):
        from services.settings_helpers import SECRET_KEYS, mask_secret, current_config
        assert callable(mask_secret)
        assert callable(current_config)
        assert isinstance(SECRET_KEYS, set)

    def test_graph_access(self):
        from services.graph_access import get_graph_token, get_email_token
        assert callable(get_graph_token)
        assert callable(get_email_token)

    def test_sharepoint_helpers(self):
        from services.sharepoint_helpers import (
            upload_to_sharepoint, create_sharing_link, ensure_sharepoint_folder_exists,
        )
        assert callable(upload_to_sharepoint)
        assert callable(create_sharing_link)
        assert callable(ensure_sharepoint_folder_exists)

    def test_bc_draft_service(self):
        from services.bc_draft_service import (
            check_duplicate_purchase_invoice, create_purchase_invoice_header,
        )
        assert callable(check_duplicate_purchase_invoice)
        assert callable(create_purchase_invoice_header)

    def test_document_linking(self):
        from services.document_linking import link_document_to_bc, link_document
        assert callable(link_document_to_bc)
        assert callable(link_document)

    def test_email_helpers(self):
        from services.email_helpers import (
            get_email_watcher_config, subscribe_to_mailbox_notifications,
        )
        assert callable(get_email_watcher_config)
        assert callable(subscribe_to_mailbox_notifications)


    def test_document_classification(self):
        from services.document_classification import classify_document_type, get_category_for_doc_type
        assert callable(classify_document_type)
        assert callable(get_category_for_doc_type)

    def test_mailbox_polling(self):
        from services.mailbox_polling import poll_mailbox_for_documents
        assert callable(poll_mailbox_for_documents)

    def test_document_linking_workflow(self):
        from services.document_linking import run_upload_and_link_workflow
        assert callable(run_upload_and_link_workflow)


class TestSettingsUsesDepNotServer:
    """settings.py imports config from deps, not from server."""

    def test_settings_no_server_import(self):
        import pathlib
        settings_path = pathlib.Path(__file__).parent.parent / "routers" / "settings.py"
        content = settings_path.read_text()
        assert "from server import" not in content, "settings.py still imports from server"
        assert "import server" not in content, "settings.py still imports server"

    def test_settings_imports_deps(self):
        import pathlib
        settings_path = pathlib.Path(__file__).parent.parent / "routers" / "settings.py"
        content = settings_path.read_text()
        assert "import deps" in content

    def test_settings_imports_settings_helpers(self):
        import pathlib
        settings_path = pathlib.Path(__file__).parent.parent / "routers" / "settings.py"
        content = settings_path.read_text()
        assert "from services.settings_helpers import" in content


class TestDocumentHandlersFullyDecoupled:
    """document_handlers.py is fully decoupled from server.py."""

    def test_no_server_import(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "import server" not in content, "document_handlers.py still imports server"
        assert "_server()" not in content, "document_handlers.py still uses _server() lazy import"

    def test_uses_sharepoint_helpers(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "from services.sharepoint_helpers import" in content

    def test_uses_document_linking(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "from services.document_linking import" in content
        assert "run_upload_and_link_workflow" in content

    def test_uses_document_classification(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "from services.document_classification import" in content

    def test_uses_bc_draft_service(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "from services.bc_draft_service import" in content

    def test_no_srv_calls_remain(self):
        import pathlib
        dh_path = pathlib.Path(__file__).parent.parent / "services" / "document_handlers.py"
        content = dh_path.read_text()
        assert "srv.upload_to_sharepoint" not in content
        assert "srv.create_sharing_link" not in content
        assert "srv.link_document_to_bc" not in content
        assert "srv.check_duplicate_purchase_invoice" not in content
        assert "srv.create_purchase_invoice_header" not in content
        assert "srv.get_bc_token" not in content
        assert "srv.run_upload_and_link_workflow" not in content
        assert "srv.classify_document_type" not in content


class TestVendorMatchingUsesDepNotServer:
    """vendor_matching.py imports config from deps, not from server."""

    def test_no_server_import(self):
        import pathlib
        vm_path = pathlib.Path(__file__).parent.parent / "services" / "vendor_matching.py"
        content = vm_path.read_text()
        assert "import server" not in content, "vendor_matching.py still imports server"


class TestEndpointsStillWork:
    """All key endpoints respond after hardening."""

    def test_health(self):
        resp = requests.get(f"{API_BASE}/api/health")
        assert resp.status_code == 200

    def test_settings_status(self):
        resp = requests.get(f"{API_BASE}/api/settings/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "connections" in data
        assert "features" in data

    def test_settings_config(self):
        resp = requests.get(f"{API_BASE}/api/settings/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data

    def test_documents_list(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200

    def test_workflows_list(self):
        resp = requests.get(f"{API_BASE}/api/workflows")
        assert resp.status_code == 200

    def test_dashboard(self):
        resp = requests.get(f"{API_BASE}/api/dashboard/document-types")
        assert resp.status_code == 200

    def test_mailbox_sources(self):
        resp = requests.get(f"{API_BASE}/api/settings/mailbox-sources")
        assert resp.status_code == 200

    def test_email_watcher(self):
        resp = requests.get(f"{API_BASE}/api/settings/email-watcher")
        assert resp.status_code == 200


class TestRouteCountStable:
    """Route count preserved at 427."""

    def test_count(self):
        from main import app
        count = 0
        for route in app.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                count += 1
            elif hasattr(route, "path") and hasattr(route, "routes"):
                for sub in route.routes:
                    if hasattr(sub, "path") and hasattr(sub, "methods"):
                        count += 1
        assert count == 427, f"Expected 427, got {count}"
