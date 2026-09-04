"""Deterministic normalization for known customer-PDF purchase-order formats.

PDF byte/text extraction is intentionally outside this module.

- Digital PDFs may supply extracted text to a format-specific parser.
- Image/scanned PDFs may supply structured evidence from a document-vision/OCR layer.

Both paths end in the same normalized order contract. The parser preserves source
quantity/UOM/price evidence but does not make Business Central pricing or item-resolution
decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Iterable, List, Optional

from ..models import (
    DocumentType,
    NormalizedInboundOrder,
    NormalizedRelease,
    OrderCustomer,
    OrderDocument,
    OrderSource,
    OrderValidation,
    ProposedAction,
)


@dataclass
class CustomerPoLineEvidence:
    line_number: str
    customer_item_reference: Optional[str]
    description: Optional[str]
    quantity: float
    uom: str
    requested_delivery_date: Optional[date] = None
    source_quantity_text: Optional[str] = None
    source_uom_text: Optional[str] = None
    source_unit_price: Optional[float] = None
    source_price_uom: Optional[str] = None
    source_line_total: Optional[float] = None
    source_coordinates: List[str] = field(default_factory=list)


@dataclass
class CustomerPoEvidence:
    source_format: str
    extraction_method: str
    customer_name: str
    customer_order_reference: str
    order_date: Optional[date]
    currency: Optional[str]
    ship_to: Optional[str]
    vendor_reference: Optional[str]
    lines: List[CustomerPoLineEvidence]


class CustomerPoEvidenceNormalizer:
    """Convert extracted customer-PO evidence into the normalized order contract."""

    def normalize(
        self,
        evidence: CustomerPoEvidence,
        *,
        attachment_name: str,
        attachment_sha256: Optional[str] = None,
    ) -> NormalizedInboundOrder:
        if not evidence.customer_name.strip():
            raise ValueError("Customer PO evidence must include customer_name.")
        if not evidence.customer_order_reference.strip():
            raise ValueError("Customer PO evidence must include customer_order_reference.")
        if not evidence.lines:
            raise ValueError("Customer PO evidence must include at least one line.")

        if not attachment_sha256:
            serialized = json.dumps(
                {
                    "source_format": evidence.source_format,
                    "extraction_method": evidence.extraction_method,
                    "customer_name": evidence.customer_name,
                    "customer_order_reference": evidence.customer_order_reference,
                    "order_date": evidence.order_date.isoformat() if evidence.order_date else None,
                    "currency": evidence.currency,
                    "ship_to": evidence.ship_to,
                    "vendor_reference": evidence.vendor_reference,
                    "lines": [line.__dict__ for line in evidence.lines],
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
            attachment_sha256 = hashlib.sha256(serialized).hexdigest()

        releases: List[NormalizedRelease] = []
        for line in evidence.lines:
            if line.quantity <= 0:
                raise ValueError(f"Customer PO line {line.line_number} quantity must be positive.")
            if not line.uom.strip():
                raise ValueError(f"Customer PO line {line.line_number} UOM is required.")

            releases.append(
                NormalizedRelease(
                    customer_release_reference=evidence.customer_order_reference,
                    source_line_number=line.line_number,
                    customer_item_reference=line.customer_item_reference,
                    description=line.description,
                    quantity=float(line.quantity),
                    uom=line.uom,
                    source_quantity_text=line.source_quantity_text,
                    source_uom_text=line.source_uom_text,
                    source_unit_price=line.source_unit_price,
                    source_price_uom=line.source_price_uom,
                    source_line_total=line.source_line_total,
                    requested_delivery_date=line.requested_delivery_date,
                    ship_to_candidate=evidence.ship_to,
                    source_coordinates=list(line.source_coordinates),
                    quantity_source="customer_purchase_order",
                    quantity_resolution_method="source_customer_po",
                    extraction_confidence=1.0,
                )
            )

        return NormalizedInboundOrder(
            source=OrderSource(
                attachment_name=attachment_name,
                attachment_sha256=attachment_sha256,
                source_format=evidence.source_format,
                source_party_role="CUSTOMER",
            ),
            customer=OrderCustomer(
                candidate_customer_name=evidence.customer_name,
                evidence=[
                    f"Customer identity stated on {evidence.source_format}",
                    f"Extraction method: {evidence.extraction_method}",
                ],
            ),
            document=OrderDocument(
                document_type=DocumentType.STANDARD_PO,
                customer_order_reference=evidence.customer_order_reference,
                order_date=evidence.order_date,
                currency=evidence.currency,
                source_revision_key=evidence.customer_order_reference,
            ),
            releases=releases,
            validation=OrderValidation(
                customer_status="CANDIDATE_FROM_CUSTOMER_PO",
                item_status="UNRESOLVED_CUSTOMER_ITEM",
                quantity_status="SOURCE_STATED",
                ship_to_status="SOURCE_STATED" if evidence.ship_to else "UNRESOLVED",
                date_status="SOURCE_STATED",
                price_status="SOURCE_STATED_EVIDENCE_NOT_AUTHORITY",
                exceptions=[
                    "Business Central customer/item/UOM/ship-to/price validation is still required before order creation."
                ],
                proposed_action=ProposedAction.REVIEW,
            ),
        )


class BernerPdfEvidenceParser:
    """Normalize structured evidence from image/scanned Berner PO PDFs.

    The real profiled Berner PDF is image-only, so extraction belongs to a vision/OCR
    stage. This class intentionally does not pretend raw PDF text extraction exists.
    """

    def parse_evidence(
        self,
        evidence: CustomerPoEvidence,
        *,
        attachment_name: str = "berner-purchase-order.pdf",
        attachment_sha256: Optional[str] = None,
    ) -> NormalizedInboundOrder:
        if evidence.source_format != "BERNER_PDF":
            raise ValueError(f"Expected BERNER_PDF evidence; received {evidence.source_format!r}.")
        if evidence.extraction_method not in {"DOCUMENT_VISION", "OCR", "MANUAL_FIXTURE"}:
            raise ValueError(
                "Berner image-PDF evidence must come from DOCUMENT_VISION, OCR, or a controlled MANUAL_FIXTURE."
            )
        return CustomerPoEvidenceNormalizer().normalize(
            evidence,
            attachment_name=attachment_name,
            attachment_sha256=attachment_sha256,
        )


class HerdezCoupaPdfTextParser:
    """Parse the profiled Herdez Coupa PDF text layout.

    Herdez uses a decimal comma in the displayed quantity while the line total uses
    US-style thousands separators. Example: `195,888 THOUSAND @ 225.75` means
    195.888 thousand, not 195,888 thousand.
    """

    _po_re = re.compile(r"(?mi)^PO Number\s+(?P<po>\S+)\s*$")
    _date_re = re.compile(r"(?mi)^DATE\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$")
    _currency_re = re.compile(r"(?mi)^CURRENCY\s+(?P<currency>[A-Z]{3})\s*$")
    _line_re = re.compile(
        r"(?mi)^(?P<line>\d{4})\s+\S+\s+(?P<item>\d{8,})\s+(?P<description>.+?)\s*$"
    )
    _detail_re = re.compile(
        r"(?mi)^(?P<date>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<qty>[\d.,]+)\s+(?P<uom>[A-Z]+)\s+"
        r"(?P<price>[\d.,]+)\s+(?P<total>[\d.,]+)\s*$"
    )

    def parse_text(
        self,
        text: str,
        *,
        attachment_name: str = "herdez-purchase-order.pdf",
        attachment_sha256: Optional[str] = None,
    ) -> NormalizedInboundOrder:
        if "HERDEZ" not in text.upper() or "PURCHASE ORDER" not in text.upper():
            raise ValueError("Text does not match the profiled Herdez purchase-order format.")
        if "GAMER PACKAGING" not in text.upper():
            raise ValueError("Herdez PO does not identify Gamer Packaging as the supplier/vendor.")

        po_match = self._po_re.search(text)
        date_match = self._date_re.search(text)
        currency_match = self._currency_re.search(text)
        if not po_match:
            raise ValueError("Herdez PO number not found.")
        if not date_match:
            raise ValueError("Herdez PO order date not found.")

        po_number = po_match.group("po")
        order_date = datetime.strptime(date_match.group("date"), "%Y-%m-%d").date()
        currency = currency_match.group("currency") if currency_match else None
        ship_to = self._extract_section(text, "Ship To", "Bill To")

        lines: List[CustomerPoLineEvidence] = []
        line_matches = list(self._line_re.finditer(text))
        detail_matches = list(self._detail_re.finditer(text))
        if not line_matches or not detail_matches:
            raise ValueError("Herdez PO line/detail rows were not found.")

        for index, line_match in enumerate(line_matches):
            detail = detail_matches[index] if index < len(detail_matches) else None
            if detail is None:
                raise ValueError(f"Herdez PO line {line_match.group('line')} has no quantity/detail row.")

            source_uom = detail.group("uom").upper()
            quantity = self._parse_herdez_quantity(detail.group("qty"), source_uom)
            normalized_uom = self._normalize_customer_uom(source_uom)
            lines.append(
                CustomerPoLineEvidence(
                    line_number=line_match.group("line"),
                    customer_item_reference=line_match.group("item"),
                    description=line_match.group("description").strip(),
                    quantity=float(quantity),
                    uom=normalized_uom,
                    requested_delivery_date=datetime.strptime(detail.group("date"), "%m/%d/%Y").date(),
                    source_quantity_text=detail.group("qty"),
                    source_uom_text=source_uom,
                    source_unit_price=float(self._parse_us_decimal(detail.group("price"))),
                    source_price_uom=source_uom,
                    source_line_total=float(self._parse_us_decimal(detail.group("total"))),
                    source_coordinates=[f"line:{line_match.group('line')}"]
                )
            )

        evidence = CustomerPoEvidence(
            source_format="HERDEZ_COUPA_PDF_TEXT",
            extraction_method="PDF_TEXT",
            customer_name="Herdez Group",
            customer_order_reference=po_number,
            order_date=order_date,
            currency=currency,
            ship_to=ship_to,
            vendor_reference=self._extract_vendor_reference(text),
            lines=lines,
        )
        result = CustomerPoEvidenceNormalizer().normalize(
            evidence,
            attachment_name=attachment_name,
            attachment_sha256=attachment_sha256,
        )
        for release in result.releases:
            if release.source_uom_text == "THOUSAND" and release.uom == "M":
                release.quantity_resolution_method = "semantic_customer_uom_alias:THOUSAND->M"
        return result

    @staticmethod
    def _parse_herdez_quantity(value: str, source_uom: str) -> Decimal:
        value = value.strip()
        # Profiled Herdez/Coupa format: `195,888 THOUSAND` is a decimal-comma
        # quantity. Treat comma as decimal separator only for this known format/UOM.
        if source_uom == "THOUSAND" and re.fullmatch(r"\d+,\d{3}", value):
            return Decimal(value.replace(",", "."))
        return HerdezCoupaPdfTextParser._parse_us_decimal(value)

    @staticmethod
    def _parse_us_decimal(value: str) -> Decimal:
        return Decimal(value.replace(",", ""))

    @staticmethod
    def _normalize_customer_uom(source_uom: str) -> str:
        aliases = {
            "THOUSAND": "M",
        }
        return aliases.get(source_uom, source_uom)

    @staticmethod
    def _extract_section(text: str, start_label: str, end_label: str) -> Optional[str]:
        pattern = re.compile(
            rf"(?is){re.escape(start_label)}\s*(?P<body>.+?)\s*{re.escape(end_label)}"
        )
        match = pattern.search(text)
        if not match:
            return None
        body = " | ".join(line.strip() for line in match.group("body").splitlines() if line.strip())
        return body or None

    @staticmethod
    def _extract_vendor_reference(text: str) -> Optional[str]:
        # Herdez displays Gamer's supplier/vendor account immediately after GAMER PACKAGING.
        match = re.search(r"(?mi)^GAMER PACKAGING\s+(?P<vendor>\d+)\s*$", text)
        return match.group("vendor") if match else None
