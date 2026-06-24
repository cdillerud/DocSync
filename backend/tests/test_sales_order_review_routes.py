import pytest


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


@pytest.mark.asyncio
async def test_vendor_purchase_order_is_filtered_from_review_queue(monkeypatch):
    import routes.sales_order_review as route_module

    async def fake_assessment(document_id):
        if document_id == "vendor-po":
            return {
                "excluded": True,
                "reason_code": "GAMER_VENDOR_PURCHASE_ORDER",
                "reason": "Gamer-issued vendor PO",
            }
        return {
            "excluded": False,
            "reason_code": None,
            "reason": None,
        }

    monkeypatch.setattr(route_module, "_source_assessment", fake_assessment)

    documents = [
        {"document_id": "customer-po", "file_name": "Customer PO.pdf"},
        {"document_id": "vendor-po", "file_name": "Purchase Order.pdf"},
    ]

    filtered = await route_module._filter_review_queue(documents)

    assert filtered == [documents[0]]


@pytest.mark.asyncio
async def test_vendor_purchase_order_cannot_be_approved(monkeypatch):
    import routes.sales_order_review as route_module

    async def fake_assessment(document_id):
        return {
            "excluded": True,
            "reason_code": "GAMER_VENDOR_PURCHASE_ORDER",
            "reason": "Gamer-issued vendor PO",
        }

    monkeypatch.setattr(route_module, "_source_assessment", fake_assessment)

    with pytest.raises(Exception) as exc_info:
        await route_module._require_customer_sales_order("vendor-po")

    error = exc_info.value
    assert getattr(error, "status_code", None) == 409
    assert error.detail["reason_code"] == "GAMER_VENDOR_PURCHASE_ORDER"
