from services.sales_order_source_inference import assess_sales_order_source


def test_gamer_vendor_po_subject_is_excluded():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "source": "backfill",
        "email_subject": "FW: Gamer Packaging Purchase Order Number: 111169",
        "file_name": "Purchase-Order 111169.pdf",
        "extracted_fields": {},
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is True
    assert assessment["reason_code"] == "GAMER_VENDOR_PURCHASE_ORDER"


def test_purchase_order_type_needs_bc_customer_evidence():
    document = {"document_id": "doc-2", "doc_type": "PurchaseOrder", "extracted_fields": {}}

    assert assess_sales_order_source(document)["reason_code"] == "VENDOR_PURCHASE_ORDER_TYPE"
    assert assess_sales_order_source(document, bc_customer_no="C10000")["excluded"] is False


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


def test_repeated_scheduled_lines_alone_do_not_imply_recursive_split():
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
                "requestedDeliveryDate": "2026-08-03",
            },
            {
                "description": "CAN UNIVERSAL",
                "quantity": 202400,
                "unitPrice": 0.15206,
                "requestedDeliveryDate": "2026-08-06",
            },
        ],
    }

    assessment = assess_sales_order_source(document)

    assert assessment["excluded"] is False
    assert assessment["reason_code"] is None
