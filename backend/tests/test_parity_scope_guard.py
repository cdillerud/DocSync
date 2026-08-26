from services.parity_scope_guard import (
    ADMIN_ONLY_PREFIXES,
    OUT_OF_SCOPE_SALES_PREFIXES,
    is_admin_only_path,
    is_out_of_scope_sales_path,
    sales_routes_enabled,
)


def test_sales_route_families_are_blocked_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", raising=False)
    assert sales_routes_enabled() is False

    samples = (
        "/api/sales",
        "/api/sales/customers",
        "/api/sales-dashboard/queue",
        "/api/sales-dashboard/demo/run",
        "/api/salesperson-dashboard/overview",
        "/api/inside-sales-pilot/poll-now",
        "/api/inside-sales-pilot/smart-reclassify",
        "/api/bc/sales-orders/create",
    )
    for path in samples:
        assert is_out_of_scope_sales_path(path) is True, path


def test_ap_and_warehouse_paths_are_not_blocked():
    samples = (
        "/api/gpi-integration/document-links/purchaseInvoices/PI100",
        "/api/gpi-integration/document-links/postedSalesShipments/S100",
        "/api/email-polling/status",
        "/api/documents/abc",
        "/api/health",
        "/api/bc/companies",
        "/api/bc/sales-orders",
    )
    for path in samples:
        assert is_out_of_scope_sales_path(path) is False, path


def test_operational_control_plane_is_admin_only():
    samples = (
        "/api/settings",
        "/api/settings/status",
        "/api/settings/config",
        "/api/settings/test-connection",
        "/api/settings/features/create-draft-header",
        "/api/settings/job-types/AP_Invoice",
        "/api/settings/email-watcher",
        "/api/settings/email-watcher/subscribe",
        "/api/settings/mailbox-sources",
        "/api/settings/mailbox-sources/mailbox_123",
        "/api/admin",
        "/api/admin/migrate-sales-to-unified",
        "/api/admin/eod/run",
        "/api/dev",
        "/api/dev/bakeoff",
        "/api/migration",
        "/api/migration/run",
        "/api/migration/generate-sample",
        "/api/sharepoint",
        "/api/sharepoint/initialize-folders",
    )
    for path in samples:
        assert is_admin_only_path(path) is True, path

    for path in (
        "/api/health",
        "/api/documents/abc",
        "/api/gpi-integration/document-links/purchaseInvoices/PI100",
    ):
        assert is_admin_only_path(path) is False, path


def test_sales_route_activation_requires_explicit_true(monkeypatch):
    for value in ("", "false", "0", "no", "off"):
        monkeypatch.setenv("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", value)
        assert sales_routes_enabled() is False

    for value in ("true", "1", "yes", "on"):
        monkeypatch.setenv("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", value)
        assert sales_routes_enabled() is True


def test_prefix_lists_have_no_broad_api_catchall():
    assert "/api" not in OUT_OF_SCOPE_SALES_PREFIXES
    assert "/api" not in ADMIN_ONLY_PREFIXES
