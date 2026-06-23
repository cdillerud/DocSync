from services.sales_order_source_inference import infer_sales_order_reference


def test_reference_is_inferred_from_email_subject():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "FW: Gamer Packaging Purchase Order Number: 111169",
        "file_name": "Purchase-Order 111169.pdf",
        "extracted_fields": {},
    }

    inferred, evidence = infer_sales_order_reference(document)

    assert evidence == {
        "inferred": True,
        "reference": "111169",
        "source": "email_subject",
        "confidence": 0.95,
    }
    assert inferred["customer_po_number"] == "111169"
    assert inferred["order_number_extracted"] == "111169"
    assert inferred["extracted_fields"]["customer_po_no"] == "111169"
    assert inferred["normalized_fields"]["po_number"] == "111169"


def test_reference_is_inferred_from_filename_when_subject_has_none():
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "email_subject": "Customer order attached",
        "file_name": "Purchase-Order 111169.pdf",
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
    assert inferred["extracted_fields"]["customer_po_no"] == "CUSTOMER-PO-77"
