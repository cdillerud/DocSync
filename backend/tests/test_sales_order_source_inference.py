from services.sales_order_source_inference import (
    assess_sales_order_source,
    infer_sales_order_reference,
)


def test_gamer_vendor_po_subject_is_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "source": "backfill",
        "email_subject": "FW: Gamer Packaging Purchase Order Number: 111169",
        "file_name": "Purchase-Order 111169.pdf",
        "extracted_fields": {},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence["inferred"] is False
    assert evidence["reference"] is None
    assert evidence["excluded_from_sales_order"] is True
    assert evidence["exclusion_reason_code"] == "GAMER_VENDOR_PURCHASE_ORDER"
    assert "customer_po_number" not in inferred


def test_explicit_customer_po_is_inferred_from_subject():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "FW: Customer PO Number: 111169",
        "file_name": "Customer-PO 111169.pdf",
        "extracted_fields": {},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence["reference"] == "111169"
    assert evidence["source"] == "email_subject"
    assert evidence["confidence"] == 0.95
    assert evidence["excluded_from_sales_order"] is False
    assert inferred["customer_po_number"] == "111169"
    assert inferred["extracted_fields"]["customer_po_no"] == "111169"
    assert inferred["normalized_fields"]["customer_po"] == "111169"


def test_generic_purchase_order_filename_requires_customer_context():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "Order attached",
        "file_name": "Purchase-Order 111169.pdf",
        "extracted_fields": {},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence["inferred"] is False
    assert evidence["reference"] is None
    assert evidence["excluded_from_sales_order"] is False
    assert "customer_po_number" not in inferred


def test_generic_filename_can_use_resolved_customer_context():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "Order attached",
        "file_name": "Purchase-Order 111169.pdf",
        "bc_customer_no": "C10000",
        "extracted_fields": {},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence["reference"] == "111169"
    assert evidence["source"] == "file_name"
    assert evidence["confidence"] == 0.90
    assert inferred["customer_po_number"] == "111169"


def test_existing_extracted_reference_is_not_replaced():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "Purchase Order Number: 111169",
        "extracted_fields": {"customer_po_no": "CUSTOMER-PO-77"},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence["inferred"] is False
    assert evidence["reference"] == "CUSTOMER-PO-77"
    assert evidence["excluded_from_sales_order"] is False
    assert inferred["extracted_fields"]["customer_po_no"] == "CUSTOMER-PO-77"


def test_vendor_po_document_content_is_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "document_text": (
            "Purchase Order\n"
            "Gamer Packaging, Inc.\n"
            "Vendor:\nAnchor Glass\n"
            "Customer PO 02052026CA-03"
        ),
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is True
    assert assessment["reason_code"] == "GAMER_VENDOR_PO_DOCUMENT_CONTENT"


def test_recursive_split_artifact_is_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "source": "auto_split",
        "file_name": "PurchPurchaseOrder.Report_doc1_doc1_doc1.pdf",
        "email_subject": (
            "New Purchase Order - Horseshoe Beverage Company "
            "[Pages 1-2/5] [Pages 1-2/2] [Pages 1-2/2]"
        ),
        "extracted_fields": {
            "line_items": [
                {
                    "description": "CAN UNIVERSAL",
                    "quantity": 202400,
                    "unit_price": 0.15206,
                },
                {
                    "description": "CAN UNIVERSAL",
                    "quantity": 202400,
                    "unit_price": 0.15206,
                },
            ]
        },
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is True
    assert assessment["reason_code"] == "RECURSIVE_SPLIT_ARTIFACT"
    assert "recursively generated split artifact" in assessment["reason"]


def test_single_valid_split_is_not_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "source": "auto_split",
        "file_name": "PurchPurchaseOrder.Report_doc1.pdf",
        "email_subject": (
            "New Purchase Order - Horseshoe Beverage Company [Pages 1/2]"
        ),
        "extracted_fields": {
            "line_items": [
                {
                    "description": "CAN UNIVERSAL",
                    "quantity": 202400,
                    "unit_price": 0.15206,
                }
            ]
        },
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is False
    assert assessment["reason_code"] is None


def test_identical_lines_on_auto_split_are_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "source": "auto_split",
        "file_name": "PurchPurchaseOrder.Report_doc1.pdf",
        "email_subject": "New Purchase Order [Pages 1/2]",
        "sales_order_lines": [
            {
                "description": "CAN UNIVERSAL",
                "quantity": 202400,
                "unitPrice": 0.15206,
            },
            {
                "description": "CAN UNIVERSAL",
                "quantity": 202400,
                "unitPrice": 0.15206,
            },
        ],
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is True
    assert assessment["reason_code"] == "RECURSIVE_SPLIT_ARTIFACT"
