from services.resolved_bc_identity_persistence_service import build_resolved_bc_identity_update


def test_resolved_purchase_order_promotes_exact_identity():
    update = build_resolved_bc_identity_update({
        "status": "resolved",
        "bc_entity_type": "purchase_order",
        "bc_record_id": "11111111-2222-3333-4444-555555555555",
        "po_number": "109204",
        "match_method": "bc_cache_exact",
        "confidence": 0.95,
    })

    assert update["bc_document_no"] == "109204"
    assert update["bc_record_id"] == "11111111-2222-3333-4444-555555555555"
    assert update["bc_system_id"] == update["bc_record_id"]
    assert update["bc_entity"] == "purchaseOrders"
    assert update["bc_entity_type"] == "purchase_order"
    assert update["bc_record_type"] == "purchaseOrder"


def test_resolved_shipment_promotes_factbox_visible_identity():
    update = build_resolved_bc_identity_update({
        "status": "resolved_shipment",
        "bc_entity_type": "posted_sales_shipment",
        "bc_record_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "po_number": "S-105012",
        "match_method": "bc_cache_shipment_exact",
        "confidence": 0.85,
    })

    assert update["bc_document_no"] == "S-105012"
    assert update["bc_record_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert update["bc_entity"] == "postedSalesShipments"
    assert update["bc_entity_type"] == "posted_sales_shipment"
    assert update["bc_record_type"] == "posted_sales_shipment"


def test_resolved_without_system_id_fails_closed():
    assert build_resolved_bc_identity_update({
        "status": "resolved_shipment",
        "bc_entity_type": "posted_sales_shipment",
        "bc_record_id": "",
        "po_number": "S-105012",
    }) == {}


def test_ambiguous_result_never_promotes_identity():
    assert build_resolved_bc_identity_update({
        "status": "ambiguous",
        "bc_entity_type": "posted_sales_shipment",
        "bc_record_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "po_number": "S-105012",
    }) == {}


def test_unknown_entity_fails_closed():
    assert build_resolved_bc_identity_update({
        "status": "resolved",
        "bc_entity_type": "mystery_record",
        "bc_record_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "po_number": "100",
    }) == {}
