"""Offline regressions for profiled customer-PDF purchase-order formats and mappings."""

from datetime import date

import pytest

from order_intake import apply_profiled_customer_pdf_mapping
from order_intake.parsers import (
    BernerPdfEvidenceParser,
    CustomerPoEvidence,
    CustomerPoLineEvidence,
    HerdezCoupaPdfTextParser,
)


def _herdez_text(*, po: str = "4500063632", qty: str = "195,888", total: str = "44,221.72") -> str:
    return f"""Herdez Group
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
PO Number {po}
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
09/01/2026 {qty} THOUSAND 225.75 {total}
$ {total}
"""


def _berner_evidence(*, po: str = "241355", qty: float = 68000) -> CustomerPoEvidence:
    return CustomerPoEvidence(
        source_format="BERNER_PDF",
        extraction_method="MANUAL_FIXTURE",
        customer_name="Berner Food & Beverage LLC",
        customer_order_reference=po,
        order_date=date(2026, 5, 14),
        currency="USD",
        ship_to="Berner Foods, Inc. | 5778 Baxter Road | Rockford, IL 61109",
        vendor_reference="7050",
        lines=[
            CustomerPoLineEvidence(
                line_number="1",
                customer_item_reference="811476",
                description="Scround Jar 13.7oz 48mm Beverage Jar 21579-858231",
                quantity=qty,
                uom="EA",
                requested_delivery_date=date(2026, 7, 20),
                source_quantity_text=f"{qty:,.0f}",
                source_uom_text="EA",
                source_unit_price=243.43,
                source_price_uom="THOU",
                source_line_total=16553.24 if qty == 68000 else None,
                source_coordinates=["page:1", "line:1"],
            )
        ],
    )


def test_herdez_coupa_pdf_text_preserves_source_and_normalizes_decimal_comma_quantity():
    result = HerdezCoupaPdfTextParser().parse_text(
        _herdez_text(),
        attachment_name="Purchase Order-4500063632.pdf",
    )

    assert result.source.source_format == "HERDEZ_COUPA_PDF_TEXT"
    assert result.source.source_party_role == "CUSTOMER"
    assert result.customer.candidate_customer_name == "Herdez Group"
    assert result.document.document_type.value == "STANDARD_PO"
    assert result.document.customer_order_reference == "4500063632"
    assert result.document.order_date == date(2026, 7, 30)
    assert result.document.currency == "USD"
    assert result.document.source_vendor_reference == "50001644"
    assert result.validation is not None
    assert result.validation.proposed_action.value == "REVIEW"
    assert result.validation.quantity_status == "SOURCE_STATED_BC_TRANSACTION_UNRESOLVED"
    assert result.validation.price_status == "SOURCE_STATED_EVIDENCE_NOT_AUTHORITY"

    assert len(result.releases) == 1
    release = result.releases[0]
    assert release.source_line_number == "0001"
    assert release.customer_item_reference == "000000000004003467"
    assert release.source_quantity_text == "195,888"
    assert release.source_uom_text == "THOUSAND"
    assert release.physical_quantity == pytest.approx(195.888)
    assert release.physical_uom == "M"
    assert release.quantity is None
    assert release.uom is None
    assert release.quantity_resolution_method is None
    assert release.source_unit_price == pytest.approx(225.75)
    assert release.source_price_uom == "THOUSAND"
    assert release.source_line_total == pytest.approx(44221.72)
    assert release.requested_delivery_date == date(2026, 9, 1)
    assert "SLP INDUSTRIES PLANT" in (release.ship_to_candidate or "")
    assert "BC transaction equivalence still requires" in " | ".join(release.parser_review_reasons)

    # Arithmetic corroborates the format-specific source decimal-comma interpretation.
    assert release.physical_quantity * release.source_unit_price == pytest.approx(44221.72, abs=0.01)


def test_berner_image_pdf_evidence_preserves_customer_quantity_and_price_as_source_evidence():
    result = BernerPdfEvidenceParser().parse_evidence(
        _berner_evidence(),
        attachment_name="AP - Purchase Order 241355.pdf",
    )

    assert result.source.source_format == "BERNER_PDF"
    assert result.source.source_party_role == "CUSTOMER"
    assert result.customer.candidate_customer_name == "Berner Food & Beverage LLC"
    assert result.document.customer_order_reference == "241355"
    assert result.document.order_date == date(2026, 5, 14)
    assert result.document.currency == "USD"
    assert result.document.source_vendor_reference == "7050"
    assert result.validation is not None
    assert result.validation.proposed_action.value == "REVIEW"
    assert result.validation.quantity_status == "SOURCE_STATED_BC_TRANSACTION_UNRESOLVED"
    assert result.validation.price_status == "SOURCE_STATED_EVIDENCE_NOT_AUTHORITY"

    release = result.releases[0]
    assert release.source_line_number == "1"
    assert release.customer_item_reference == "811476"
    assert release.physical_quantity == 68000
    assert release.physical_uom == "EA"
    assert release.quantity is None
    assert release.uom is None
    assert release.resolved_item_no is None
    assert release.resolved_ship_to_code is None
    assert release.source_quantity_text == "68,000"
    assert release.source_uom_text == "EA"
    assert release.source_unit_price == pytest.approx(243.43)
    assert release.source_price_uom == "THOU"
    assert release.source_line_total == pytest.approx(16553.24)
    assert release.requested_delivery_date == date(2026, 7, 20)
    assert release.quantity_source == "customer_purchase_order"
    assert release.quantity_resolution_method is None
    assert "BC transaction quantity/UOM unresolved" in " | ".join(release.parser_review_reasons)


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


def test_berner_profile_resolves_only_the_exact_repeated_packout_pattern():
    parsed = BernerPdfEvidenceParser().parse_evidence(_berner_evidence(po="241999"))
    mapped = apply_profiled_customer_pdf_mapping(parsed)

    assert mapped.customer.resolved_customer_no == "BERNER"
    assert mapped.validation is not None
    assert mapped.validation.proposed_action.value == "PASS"
    assert mapped.validation.item_status == "RESOLVED_PROFILED_CUSTOMER_ITEM_ALIAS"
    assert mapped.validation.quantity_status == "RESOLVED_EXACT_PROFILED_PACKOUT"
    assert mapped.validation.price_status == "SOURCE_CORROBORATION_ONLY_BC_AUTHORITY_REQUIRED"

    release = mapped.releases[0]
    assert release.customer_item_reference == "811476"  # source fact remains untouched
    assert "21579-858231" in (release.description or "")  # source alias remains untouched
    assert release.resolved_item_no == "21759-858231"
    assert release.resolved_ship_to_code == "78899028"
    assert release.resolved_location_code == "00"
    assert release.physical_quantity == 68000
    assert release.physical_uom == "EA"
    assert release.quantity == pytest.approx(72.2)
    assert release.uom == "M"
    assert release.quantity_resolution_method == "berner_exact_68000_ea_to_72_2_m_profile"


def test_berner_profile_does_not_turn_72_2_m_into_a_universal_quantity_template():
    parsed = BernerPdfEvidenceParser().parse_evidence(_berner_evidence(po="241999", qty=70000))
    mapped = apply_profiled_customer_pdf_mapping(parsed)

    assert mapped.validation is not None
    assert mapped.validation.proposed_action.value == "REVIEW"
    assert mapped.validation.quantity_status == "REVIEW_BERNER_PACKOUT_NOT_PROFILED"
    release = mapped.releases[0]
    assert release.physical_quantity == 70000
    assert release.quantity is None
    assert release.uom is None
    assert release.resolved_item_no is None
    assert "different quantity/UOM must not inherit" in " | ".join(mapped.validation.exceptions)


def test_herdez_profile_carries_incoming_positive_m_quantity_instead_of_using_history_as_template():
    parsed = HerdezCoupaPdfTextParser().parse_text(
        _herdez_text(po="4500099999", qty="123,456", total="27,870.19")
    )
    mapped = apply_profiled_customer_pdf_mapping(parsed)

    assert mapped.customer.resolved_customer_no == "HERDEZ"
    assert mapped.validation is not None
    assert mapped.validation.proposed_action.value == "PASS"
    assert mapped.validation.quantity_status == "RESOLVED_DIRECT_INCOMING_QUANTITY"
    assert mapped.validation.price_status == "SOURCE_CORROBORATION_ONLY_BC_AUTHORITY_REQUIRED"

    release = mapped.releases[0]
    assert release.customer_item_reference == "000000000004003467"
    assert release.resolved_item_no == "20113526"
    assert release.resolved_ship_to_code == "001"
    assert release.resolved_location_code == "00"
    assert release.physical_quantity == pytest.approx(123.456)
    assert release.quantity == pytest.approx(123.456)
    assert release.uom == "M"
    assert release.quantity_resolution_method == "direct_incoming_quantity_after_profiled_thousand_to_m_equivalence"


def test_exact_existing_customer_po_overrides_valid_mapping_to_duplicate():
    herdez = HerdezCoupaPdfTextParser().parse_text(_herdez_text())
    mapped_herdez = apply_profiled_customer_pdf_mapping(
        herdez,
        existing_customer_po_orders={"4500063632": "117357"},
    )
    assert mapped_herdez.validation is not None
    assert mapped_herdez.validation.proposed_action.value == "DUPLICATE"
    assert mapped_herdez.validation.duplicate_status == "DUPLICATE_EXISTING_GAMER_ORDER"
    assert mapped_herdez.releases[0].existing_gamer_order == "117357"
    assert mapped_herdez.releases[0].resolved_item_no == "20113526"
    assert mapped_herdez.releases[0].quantity == pytest.approx(195.888)

    berner = BernerPdfEvidenceParser().parse_evidence(_berner_evidence())
    mapped_berner = apply_profiled_customer_pdf_mapping(
        berner,
        existing_customer_po_orders={"241355": "114600"},
    )
    assert mapped_berner.validation is not None
    assert mapped_berner.validation.proposed_action.value == "DUPLICATE"
    assert mapped_berner.releases[0].existing_gamer_order == "114600"
    assert mapped_berner.releases[0].resolved_item_no == "21759-858231"
    assert mapped_berner.releases[0].quantity == pytest.approx(72.2)
