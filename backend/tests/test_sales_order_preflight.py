import pytest

from services.sales_order_preflight import (
    build_bc_sales_order_payload,
    build_sales_order_candidate,
    preflight_sales_order,
)


def valid_doc():
    return {
        "id": "doc-1",
        "doc_type": "SALES_ORDER",
        "ai_confidence": 0.98,
        "bc_customer_number": "C10000",
        "customer_extracted": "Example Customer",
        "order_number_extracted": "PO-45001",
        "sharepoint_web_url": "https://example.sharepoint.com/doc.pdf",
        "review_status": "approved",
        "workflow_status": "validated",
        "line_items": [
            {
                "bc_item_number": "ITEM-100",
                "customer_sku": "CUSTOMER-ABC",
                "quantity": "12",
                "uom": "CASE",
                "unit_price": "14.25",
                "mapping_status": "approved",
                "item_match_confidence": 0.99,
            }
        ],
    }


def issue_codes(result):
    return {issue.code for issue in result.errors}


def test_valid_approved_candidate_passes():
    result = preflight_sales_order(valid_doc())

    assert result.can_create is True
    assert result.errors == []
    assert result.candidate["customerNumber"] == "C10000"
    assert result.candidate["externalDocumentNumber"] == "PO-45001"
    assert result.candidate["lines"][0]["itemNumber"] == "ITEM-100"


def test_customer_name_is_not_a_resolved_customer():
    doc = valid_doc()
    doc.pop("bc_customer_number")

    result = preflight_sales_order(doc)

    assert "CUSTOMER_NOT_RESOLVED" in issue_codes(result)


def test_sales_invoice_is_not_accepted_as_sales_order():
    doc = valid_doc()
    doc["doc_type"] = "SALES_INVOICE"

    result = preflight_sales_order(doc)

    assert "UNSUPPORTED_DOCUMENT_TYPE" in issue_codes(result)


def test_order_requires_lines():
    doc = valid_doc()
    doc["line_items"] = []

    result = preflight_sales_order(doc)

    assert "ORDER_LINES_REQUIRED" in issue_codes(result)


def test_customer_sku_without_bc_item_is_rejected():
    doc = valid_doc()
    doc["line_items"][0].pop("bc_item_number")

    result = preflight_sales_order(doc)

    assert "ITEM_NOT_RESOLVED" in issue_codes(result)


@pytest.mark.parametrize("quantity", [None, "", "not-a-number"])
def test_invalid_quantity_is_rejected(quantity):
    doc = valid_doc()
    doc["line_items"][0]["quantity"] = quantity

    result = preflight_sales_order(doc)

    assert "QUANTITY_INVALID" in issue_codes(result)


@pytest.mark.parametrize("quantity", [0, -1, "-4"])
def test_non_positive_quantity_is_rejected(quantity):
    doc = valid_doc()
    doc["line_items"][0]["quantity"] = quantity

    result = preflight_sales_order(doc)

    assert "QUANTITY_NOT_POSITIVE" in issue_codes(result)


def test_missing_uom_is_rejected():
    doc = valid_doc()
    doc["line_items"][0].pop("uom")

    result = preflight_sales_order(doc)

    assert "UOM_NOT_RESOLVED" in issue_codes(result)


def test_low_item_match_requires_manual_mapping_approval():
    doc = valid_doc()
    doc["line_items"][0]["item_match_confidence"] = 0.70
    doc["line_items"][0]["mapping_approved"] = False

    result = preflight_sales_order(doc)

    assert "ITEM_MATCH_CONFIDENCE_LOW" in issue_codes(result)


def test_manual_mapping_approval_allows_low_match_confidence():
    doc = valid_doc()
    doc["line_items"][0]["item_match_confidence"] = 0.70
    doc["line_items"][0]["mapping_approved"] = True

    result = preflight_sales_order(doc)

    assert "ITEM_MATCH_CONFIDENCE_LOW" not in issue_codes(result)


def test_review_approval_is_required():
    doc = valid_doc()
    doc["review_status"] = "needs_review"

    result = preflight_sales_order(doc)

    assert "REVIEW_APPROVAL_REQUIRED" in issue_codes(result)


def test_low_document_confidence_is_rejected():
    doc = valid_doc()
    doc["ai_confidence"] = 0.40

    result = preflight_sales_order(doc)

    assert "LOW_CLASSIFICATION_CONFIDENCE" in issue_codes(result)


def test_payload_is_built_only_from_normalized_candidate():
    candidate = build_sales_order_candidate(valid_doc())
    payload = build_bc_sales_order_payload(candidate)

    assert payload["customerNumber"] == "C10000"
    assert payload["externalDocumentNumber"] == "PO-45001"
    assert payload["lines"] == [
        {
            "itemNumber": "ITEM-100",
            "quantity": 12.0,
            "unitOfMeasureCode": "CASE",
            "unitPrice": 14.25,
        }
    ]


def test_upstream_validation_errors_block_creation():
    doc = valid_doc()
    doc["validation_errors"] = [{"message": "Ship-to address is ambiguous"}]

    result = preflight_sales_order(doc)

    assert "UPSTREAM_VALIDATION_ERROR" in issue_codes(result)
