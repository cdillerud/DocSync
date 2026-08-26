from services.parity_scope_guard import (
    ADMIN_ONLY_PREFIXES,
    AUTHENTICATED_ONLY_PREFIXES,
    M2M_OR_USER_PREFIXES,
    OUT_OF_SCOPE_SALES_PREFIXES,
    is_admin_only_path,
    is_authenticated_only_path,
    is_m2m_or_user_path,
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
        "/api/gpi-integration/sales-orders",
        "/api/gpi-integration/sales-orders/preflight/doc1",
        "/api/gpi-integration/sales-orders/from-document/doc1",
        "/api/gpi-integration/ds-purchase-orders/auto-create/doc1",
        "/api/gpi-integration/order-patterns/learn/C100",
        "/api/gpi-integration/document-links/salesOrders/SO100",
        "/api/gpi-integration/document-links/salesInvoices/SI100",
        "/api/gpi-integration/factbox-ui/salesOrders/SO100",
    )
    for path in samples:
        assert is_out_of_scope_sales_path(path) is True, path


def test_ap_and_warehouse_paths_are_not_sales_blocked():
    samples = (
        "/api/gpi-integration/document-links/purchaseInvoices/PI100",
        "/api/gpi-integration/document-links/purchaseOrders/PO100",
        "/api/gpi-integration/document-links/postedSalesShipments/S100",
        "/api/gpi-integration/purchase-invoices/preflight/doc1",
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
        "/api/settings/config",
        "/api/settings/mailbox-sources",
        "/api/admin/eod/run",
        "/api/dev/bakeoff",
        "/api/migration/run",
        "/api/sharepoint/initialize-folders",
        "/api/sharepoint-routing/rules",
        "/api/email-polling/poll-now",
        "/api/vendor-reprocess/run",
        "/api/auto-clear-reprocess/force-clear-all-remaining",
        "/api/workflow-fix/run",
        "/api/dedup/run",
        "/api/vendor-profiles/rebuild/run",
        "/api/auto-approve/run",
        "/api/file-integrity/scan",
        "/api/gpi-integration/status",
        "/api/gpi-integration/item-mappings",
        "/api/gpi-integration/catalog/sync",
        "/api/gpi-integration/customers",
        "/api/gpi-integration/vendors",
        "/api/gpi-integration/document-links/migrate-from-zetadocs",
        "/api/gpi-integration/purchase-invoices/retry-lines/doc1",
    )
    for path in samples:
        assert is_admin_only_path(path) is True, path

    for path in (
        "/api/health",
        "/api/documents/abc",
        "/api/gpi-integration/document-links/purchaseInvoices/PI100",
    ):
        assert is_admin_only_path(path) is False, path


def test_operator_document_and_ap_surfaces_require_login():
    samples = (
        "/api/documents/upload",
        "/api/documents/abc/retry",
        "/api/workflows/abc/approve",
        "/api/ap-review/documents/abc/save",
        "/api/human-routing-review/document/abc/assign",
        "/api/gpi-integration/purchase-invoices",
        "/api/gpi-integration/purchase-invoices/preflight/doc1",
        "/api/gpi-integration/purchase-invoices/from-document/doc1",
        "/api/gpi-integration/factbox-ui/purchaseInvoices/PI100",
    )
    for path in samples:
        assert is_authenticated_only_path(path) is True, path


def test_factbox_document_links_accept_machine_or_user_auth_class():
    samples = (
        "/api/gpi-integration/document-links/purchaseInvoices/PI100",
        "/api/gpi-integration/document-links/purchaseOrders/PO100/upload-raw",
        "/api/gpi-integration/document-links/postedSalesShipments/S100",
        "/api/gpi-integration/document-links/recover/doc1",
    )
    for path in samples:
        assert is_m2m_or_user_path(path) is True, path

    assert is_m2m_or_user_path("/api/gpi-integration/factbox-ui/purchaseInvoices/PI100") is False


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
    assert "/api" not in AUTHENTICATED_ONLY_PREFIXES
    assert "/api" not in M2M_OR_USER_PREFIXES
