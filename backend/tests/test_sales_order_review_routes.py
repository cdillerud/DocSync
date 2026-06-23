def test_sales_order_review_routes_are_registered():
    import routes.sales_order_review  # noqa: F401
    from sales_module import sales_router

    paths = {route.path for route in sales_router.routes}

    assert "/api/sales/order-intake/status" in paths
    assert "/api/sales/order-intake/review" in paths
    assert "/api/sales/order-intake/preflight-pending" in paths
    assert "/api/sales/order-intake/{document_id}/preflight" in paths
    assert "/api/sales/order-intake/{document_id}/approve" in paths
    assert "/api/sales/order-intake/{document_id}/reject" in paths
    assert "/api/sales/order-intake/{document_id}/create-draft" in paths
