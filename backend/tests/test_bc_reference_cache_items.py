from types import SimpleNamespace

from services.bc_reference_cache_service import (
    BCReferenceCacheService,
    ENTITY_CONFIGS,
)


def _service():
    return BCReferenceCacheService(
        SimpleNamespace(
            bc_reference_cache=None,
            bc_cache_metadata=None,
        )
    )


def test_items_entity_is_registered_for_cache_sync():
    config = ENTITY_CONFIGS["items"]

    assert config["entity_type"] == "item"
    assert config["domain"] == "master"
    assert config["number_field"] == "number"
    assert config["external_ref_field"] is None

    selected = set(config["select_fields"].split(","))

    assert {
        "id",
        "number",
        "displayName",
        "itemCategoryCode",
        "baseUnitOfMeasureCode",
        "unitPrice",
        "lastModifiedDateTime",
    } <= selected


def test_item_record_builds_searchable_cache_document():
    config = ENTITY_CONFIGS["items"]

    result = _service()._build_cache_document(
        {
            "id": "item-record-id",
            "number": "OIPALLET",
            "displayName": "O-I Pallet",
            "itemCategoryCode": "PALLET",
            "baseUnitOfMeasureCode": "EA",
            "unitPrice": 12.5,
            "lastModifiedDateTime": "2026-07-21T01:00:00Z",
        },
        config,
    )

    assert result["bc_entity_type"] == "item"
    assert result["bc_domain"] == "master"
    assert result["bc_record_id"] == "item-record-id"
    assert result["bc_document_no"] == "OIPALLET"
    assert result["normalized_document_no"] == "OIPALLET"
    assert result["displayName"] == "O-I Pallet"
    assert result["description"] == "O-I Pallet"
    assert result["item_category_code"] == "PALLET"
    assert result["base_uom"] == "EA"
    assert result["unit_price"] == 12.5


def test_item_without_record_id_is_not_cached():
    config = ENTITY_CONFIGS["items"]

    result = _service()._build_cache_document(
        {
            "number": "ITEM-1",
            "displayName": "Missing ID",
        },
        config,
    )

    assert result is None
