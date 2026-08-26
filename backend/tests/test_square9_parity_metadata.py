"""Focused parity tests for SharePoint metadata and BC SystemId readiness."""

from services.sharepoint_service import build_square9_parity_metadata


def _build(doc, resolution):
    return build_square9_parity_metadata(
        routing_doc=doc,
        po_result=resolution,
        original_file_name="invoice-original.pdf",
        sharepoint_file_name="109204 Vendor 08252026.pdf",
        sharepoint_path="Accounting/AP/Invoices",
        sharepoint_url="https://example.sharepoint.com/invoice.pdf",
    )


def test_resolved_purchase_order_with_system_id_is_import_ready():
    metadata = _build(
        {
            "document_type": "AP_INVOICE",
            "po_number_clean": "109204",
            "extracted_fields": {"vendor_no": "V100"},
        },
        {
            "status": "resolved",
            "po_number": "109204",
            "bc_record_id": "11111111-2222-3333-4444-555555555555",
            "bc_entity_type": "purchase_order",
            "bc_vendor_no": "V100",
            "confidence": 0.98,
            "match_method": "exact_po",
            "candidates_raw": ["109204"],
        },
    )

    assert metadata["GPI_SourceTableID"] == 38
    assert metadata["GPI_SourceSystemId"] == "11111111-2222-3333-4444-555555555555"
    assert metadata["GPI_SourceDocumentType"] == "Purchase Order"
    assert metadata["GPI_SourceDocumentNo"] == "109204"
    assert metadata["GPI_SourcePartyType"] == "Vendor"
    assert metadata["GPI_SourcePartyNo"] == "V100"
    assert metadata["GPI_OriginalFileName"] == "invoice-original.pdf"
    assert metadata["GPI_SharePointFileName"] == "109204 Vendor 08252026.pdf"
    assert metadata["ImportReady"] is True
    assert metadata["GPI_Status"] == "ImportReady"


def test_resolved_purchase_order_without_system_id_is_not_import_ready():
    metadata = _build(
        {"document_type": "WAREHOUSE_RECEIPT", "po_number_clean": "109204"},
        {
            "status": "resolved",
            "po_number": "109204",
            "bc_record_id": "",
            "bc_entity_type": "purchase_order",
            "confidence": 0.98,
            "match_method": "exact_po",
        },
    )

    assert metadata["GPI_SourceDocumentNo"] == "109204"
    assert metadata["GPI_SourceSystemId"] == ""
    assert metadata["ImportReady"] is False
    assert metadata["GPI_Status"] == "NeedsSystemId"


def test_ambiguous_match_is_not_import_ready_even_with_candidate_data():
    metadata = _build(
        {"document_type": "WAREHOUSE_RECEIPT", "po_number_clean": "109204"},
        {
            "status": "ambiguous",
            "po_number": "109204",
            "bc_record_id": "",
            "bc_entity_type": "purchase_order",
            "candidates_raw": ["109204", "109240"],
            "confidence": 0.81,
            "match_method": "candidate_rank",
        },
    )

    assert metadata["ImportReady"] is False
    assert metadata["GPI_Status"] == "NeedsMatchReview"
    assert metadata["GPI_Candidates"] == "109204, 109240"
    assert metadata["GPI_MatchConfidence"] == 0.81


def test_not_found_match_is_explicitly_not_import_ready():
    metadata = _build(
        {"document_type": "AP_INVOICE", "po_number_clean": "109204"},
        {
            "status": "not_found",
            "candidates_raw": ["109204"],
            "confidence": 0.0,
        },
    )

    assert metadata["ImportReady"] is False
    assert metadata["GPI_Status"] == "NeedsResolution"
    assert metadata["GPI_MatchStatus"] == "not_found"


def test_filename_path_url_and_match_evidence_are_preserved():
    metadata = _build(
        {"document_type": "AP_INVOICE", "po_number_clean": "109204"},
        {
            "status": "resolved",
            "po_number": "109204",
            "bc_record_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "bc_entity_type": "purchase_order",
            "confidence": 0.95,
            "match_method": "bc_cache_exact",
            "candidates_raw": ["109204"],
        },
    )

    assert metadata["GPI_OriginalFileName"] == "invoice-original.pdf"
    assert metadata["GPI_SharePointFileName"] == "109204 Vendor 08252026.pdf"
    assert metadata["GPI_SharePointPath"] == "Accounting/AP/Invoices"
    assert metadata["GPI_SharePointURL"] == "https://example.sharepoint.com/invoice.pdf"
    assert metadata["GPI_MatchStatus"] == "resolved"
    assert metadata["GPI_MatchMethod"] == "bc_cache_exact"
    assert metadata["GPI_Candidates"] == "109204"


def test_absent_bc_table_id_is_null_not_blank_text():
    metadata = _build(
        {"document_type": "STATEMENT"},
        {"status": "not_run"},
    )

    assert metadata["GPI_SourceTableID"] is None
    assert metadata["GPI_SourceSystemId"] == ""
    assert metadata["ImportReady"] is True
