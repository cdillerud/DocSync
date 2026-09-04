"""Offline regressions for profiled customer-PDF purchase-order formats."""

from datetime import date

import pytest

from order_intake.parsers import (
    BernerPdfEvidenceParser,
    CustomerPoEvidence,
    CustomerPoLineEvidence,
    HerdezCoupaPdfTextParser,
)


def test_herdez_coupa_pdf_text_preserves_source_and_normalizes_decimal_comma_quantity():
    text = """Herdez Group
PURCHASE ORDER
GAMER PACKAGING 50001644
330 2ND AVENUE SOUTH SUITE 895
Ship To
Herdez Group
SLP INDUSTRIES PLANT
AV. INDUSTRIAS 3815
SLP, SLP 78395
Mexico
Bill To
HERDEZ RFC. HER8301121X4
PO Number 4500063632
DATE 2026-07-30
PAYMENT TERMS Z060
SHIPPING TERMS DAP
CURRENCY USD
Line Clue Description
Delivery
Date
Qty Unit Price Total
0001 None 000000000004003467 EP.HE.PP.80202.9OZ.
Note: SPECIF LEVEL REV 02 JUN 2026
09/01/2026 195,888 THOUSAND 225.75 44,221.72
$ 44,221.72
"""

    result = HerdezCoupaPdfTextParser().parse_text(
        text,
        attachment_name="Purchase Order-4500063632.pdf",
    )

    assert result.source.source_format == "HERDEZ_COUPA_PDF_TEXT"
    assert result.source.source_party_role == "CUSTOMER"
    assert result.customer.candidate_customer_name == "Herdez Group"
    assert result.document.document_type.value == "STANDARD_PO"
    assert result.document.customer_order_reference == "4500063632"
    assert result.document.order_date == date(2026, 7, 30)
    assert result.document.currency == "USD"
    assert result.validation is not None
    assert result.validation.proposed_action.value == "REVIEW"
    assert result.validation.price_status == "SOURCE_STATED_EVIDENCE_NOT_AUTHORITY"

    assert len(result.releases) == 1
    release = result.releases[0]
    assert release.source_line_number == "0001"
    assert release.customer_item_reference == "000000000004003467"
    assert release.source_quantity_text == "195,888"
    assert release.source_uom_text == "THOUSAND"
    assert release.quantity == pytest.approx(195.888)
    assert release.uom == "M"
    assert release.quantity_resolution_method == "semantic_customer_uom_alias:THOUSAND->M"
    assert release.source_unit_price == pytest.approx(225.75)
    assert release.source_price_uom == "THOUSAND"
    assert release.source_line_total == pytest.approx(44221.72)
    assert release.requested_delivery_date == date(2026, 9, 1)
    assert "SLP INDUSTRIES PLANT" in (release.ship_to_candidate or "")

    # Arithmetic corroborates the format-specific decimal-comma interpretation.
    assert release.quantity * release.source_unit_price == pytest.approx(44221.72, abs=0.01)


def test_berner_image_pdf_evidence_preserves_customer_quantity_and_price_as_evidence():
    evidence = CustomerPoEvidence(
        source_format="BERNER_PDF",
        extraction_method="MANUAL_FIXTURE",
        customer_name="Berner Food & Beverage LLC",
        customer_order_reference="241355",
        order_date=date(2026, 5, 14),
        currency="USD",
        ship_to="Berner Food & Beverage LLC | Rockford, IL",
        vendor_reference="7050",
        lines=[
            CustomerPoLineEvidence(
                line_number="1",
                customer_item_reference="811476",
                description="Scround Jar 13.7oz 48mm Beverage Jar 21579-858231",
                quantity=68000,
                uom="EA",
                requested_delivery_date=date(2026, 7, 20),
                source_quantity_text="68,000",
                source_uom_text="EA",
                source_unit_price=243.43,
                source_price_uom="THOU",
                source_line_total=16553.24,
                source_coordinates=["page:1", "line:1"],
            )
        ],
    )

    result = BernerPdfEvidenceParser().parse_evidence(
        evidence,
        attachment_name="AP - Purchase Order 241355.pdf",
    )

    assert result.source.source_format == "BERNER_PDF"
    assert result.source.source_party_role == "CUSTOMER"
    assert result.customer.candidate_customer_name == "Berner Food & Beverage LLC"
    assert result.document.customer_order_reference == "241355"
    assert result.document.order_date == date(2026, 5, 14)
    assert result.document.currency == "USD"
    assert result.validation is not None
    assert result.validation.proposed_action.value == "REVIEW"
    assert result.validation.price_status == "SOURCE_STATED_EVIDENCE_NOT_AUTHORITY"

    release = result.releases[0]
    assert release.source_line_number == "1"
    assert release.customer_item_reference == "811476"
    assert release.quantity == 68000
    assert release.uom == "EA"
    assert release.source_quantity_text == "68,000"
    assert release.source_uom_text == "EA"
    assert release.source_unit_price == pytest.approx(243.43)
    assert release.source_price_uom == "THOU"
    assert release.source_line_total == pytest.approx(16553.24)
    assert release.requested_delivery_date == date(2026, 7, 20)
    assert release.quantity_source == "customer_purchase_order"
    assert release.quantity_resolution_method == "source_customer_po"


def test_berner_image_pdf_parser_rejects_unproven_text_extraction_path():
    evidence = CustomerPoEvidence(
        source_format="BERNER_PDF",
        extraction_method="PDF_TEXT",
        customer_name="Berner Food & Beverage LLC",
        customer_order_reference="241355",
        order_date=date(2026, 5, 14),
        currency="USD",
        ship_to=None,
        vendor_reference="7050",
        lines=[
            CustomerPoLineEvidence(
                line_number="1",
                customer_item_reference="811476",
                description="Scround Jar",
                quantity=68000,
                uom="EA",
            )
        ],
    )

    with pytest.raises(ValueError, match="DOCUMENT_VISION, OCR, or a controlled MANUAL_FIXTURE"):
        BernerPdfEvidenceParser().parse_evidence(evidence)
