import pytest

from services.document_link_visibility_service import (
    build_bc_document_link_filter,
    build_hub_document_link_query,
)


def test_ap_hub_query_requires_number_type_and_system_id_when_supplied():
    query = build_hub_document_link_query(
        "purchaseInvoices",
        "PI-1001",
        "11111111-1111-1111-1111-111111111111",
    )

    assert query["bc_document_no"] == "PI-1001"
    assert query["sharepoint_web_url"] == {"$nin": [None, ""]}
    clauses = query["$and"]
    identity_clause = next(
        clause for clause in clauses
        if isinstance(clause, dict)
        and "$or" in clause
        and any("GPI_SourceSystemId" in option for option in clause["$or"])
    )
    assert {"bc_record_id": "11111111-1111-1111-1111-111111111111"} in identity_clause["$or"]
    assert {"bc_system_id": "11111111-1111-1111-1111-111111111111"} in identity_clause["$or"]
    assert {"GPI_SourceSystemId": "11111111-1111-1111-1111-111111111111"} in identity_clause["$or"]


def test_same_number_different_system_id_builds_different_queries():
    first = build_hub_document_link_query(
        "purchaseInvoices", "PI-1001", "11111111-1111-1111-1111-111111111111"
    )
    second = build_hub_document_link_query(
        "purchaseInvoices", "PI-1001", "22222222-2222-2222-2222-222222222222"
    )
    assert first != second


def test_bc_document_link_filter_includes_target_system_id_when_supplied():
    result = build_bc_document_link_filter(
        "purchaseInvoices",
        "PI-1001",
        "11111111-1111-1111-1111-111111111111",
    )
    assert "bcDocumentNo eq 'PI-1001'" in result
    assert "documentType eq 'AP_Invoice'" in result
    assert "targetSystemId eq 11111111-1111-1111-1111-111111111111" in result


def test_invalid_system_id_fails_closed():
    with pytest.raises(ValueError, match="SystemId"):
        build_hub_document_link_query("purchaseInvoices", "PI-1001", "not-a-guid")
    with pytest.raises(ValueError, match="SystemId"):
        build_bc_document_link_filter("purchaseInvoices", "PI-1001", "not-a-guid")


def test_omitted_system_id_preserves_legacy_number_typed_selector():
    query = build_hub_document_link_query("purchaseInvoices", "PI-1001")
    assert query["bc_document_no"] == "PI-1001"
    assert all(
        not (
            isinstance(clause, dict)
            and "$or" in clause
            and any("GPI_SourceSystemId" in option for option in clause["$or"])
        )
        for clause in query["$and"]
    )
    result = build_bc_document_link_filter("purchaseInvoices", "PI-1001")
    assert "targetSystemId" not in result
