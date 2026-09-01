"""Deterministic parser for Giovanni monthly blanket OOR workbooks."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import load_workbook

from ..models import (
    DocumentType,
    NormalizedInboundOrder,
    NormalizedRelease,
    OrderCustomer,
    OrderDocument,
    OrderSource,
)
from ..utils import clean_text, excel_serial_to_datetime, numeric_reference, sha256_file


@dataclass(frozen=True)
class GiovanniQuantityProfile:
    product_context: str
    full_tl_quantity: Optional[float]
    customer_item_reference: Optional[str] = None
    uom: Optional[str] = None
    source: Optional[str] = None


class GiovanniOorParser:
    SOURCE_FORMAT = "GIOVANNI_OOR_XLSX"
    PRODUCTS = ("24oz Pasta", "24oz Salsa", "16oz Vinegar", "14oz Pizza", "16oz Salsa")

    def __init__(
        self,
        quantity_profiles: Optional[Dict[str, GiovanniQuantityProfile]] = None,
        sheet_name: str = "Orders",
    ):
        self.quantity_profiles = quantity_profiles or {}
        self.sheet_name = sheet_name

    @staticmethod
    def _period_parts(period: str) -> Tuple[int, int]:
        match = re.fullmatch(r"(\d{4})-(\d{2})", period.strip())
        if not match:
            raise ValueError("Giovanni period must be YYYY-MM")
        year, month = int(match.group(1)), int(match.group(2))
        if month not in range(1, 13):
            raise ValueError("Giovanni period month must be 01-12")
        return year, month

    @staticmethod
    def _norm(value) -> str:
        return " ".join(str(value or "").strip().split())

    def _section_product(self, value, month: int) -> Optional[str]:
        text = self._norm(value).lower()
        month_name = calendar.month_name[month].lower()
        for product in self.PRODUCTS:
            if text == f"{month_name} {product.lower()}":
                return product
        return None

    def _find_sections(self, ws, month: int) -> List[Tuple[int, int, str]]:
        """Find monthly product block anchors.

        Giovanni does not repeat field headers under every month. Each monthly
        product title anchors a fixed six-column block:
        Load, Gamer PO, Gio PO, Delivery Date, BOL, Notes.
        """
        sections: List[Tuple[int, int, str]] = []
        for row in ws.iter_rows():
            for cell in row:
                product = self._section_product(cell.value, month)
                if product:
                    sections.append((cell.row, cell.column, product))
        return sections

    @staticmethod
    def _semantic_note(bol_value, notes_value) -> Optional[str]:
        parts: List[str] = []
        bol = clean_text(bol_value)
        if bol:
            plain = bol.replace("-", "").replace(" ", "")
            if not plain.isdigit():
                parts.append(bol)
        notes = clean_text(notes_value)
        if notes:
            parts.append(notes)
        return " | ".join(parts) or None

    def _resolve_test_quantity(
        self, product: str, note: Optional[str]
    ) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str], List[str]]:
        profile = self.quantity_profiles.get(product)
        review: List[str] = []
        text = (note or "").lower()
        exception_tokens = ("pallet", "mixed", "32oz", "partial", "split", "cancel", "reroute")

        if any(token in text for token in exception_tokens):
            review.append("Nonstandard/mixed/cancel/reroute note requires quantity/order review")
            return (
                None,
                profile.customer_item_reference if profile else None,
                profile.uom if profile else None,
                profile.source if profile else None,
                review,
            )

        if not profile or profile.full_tl_quantity is None:
            review.append("No authoritative Giovanni full-TL quantity profile supplied")
            return (
                None,
                profile.customer_item_reference if profile else None,
                profile.uom if profile else None,
                profile.source if profile else None,
                review,
            )

        return (
            float(profile.full_tl_quantity),
            profile.customer_item_reference,
            profile.uom,
            profile.source,
            review,
        )

    def parse(
        self,
        path: str | Path,
        *,
        period: str,
        include_existing: bool = False,
    ) -> NormalizedInboundOrder:
        """Parse one Giovanni blanket-release period.

        A numeric Gio PO plus numeric load and blank Gamer PO is only a candidate.
        Business Central duplicate validation remains mandatory before creation.
        """
        path = Path(path)
        target_year, target_month = self._period_parts(period)

        # Normal mode is intentional. This historical sheet requires random access;
        # repeated ws.cell() in openpyxl read-only mode is prohibitively slow.
        wb = load_workbook(path, data_only=True, read_only=False)
        if self.sheet_name not in wb.sheetnames:
            raise ValueError(f"Giovanni workbook does not contain sheet '{self.sheet_name}'")
        ws = wb[self.sheet_name]
        sections = self._find_sections(ws, target_month)

        releases: List[NormalizedRelease] = []
        seen = set()
        month_names = tuple(name.lower() for name in calendar.month_name[1:])

        for section_row, start_col, product in sections:
            for row_idx in range(section_row + 1, min(section_row + 100, ws.max_row) + 1):
                first = self._norm(ws.cell(row_idx, start_col).value)
                if row_idx > section_row + 1 and any(first.lower().startswith(f"{m} ") for m in month_names):
                    break

                load_ref = numeric_reference(ws.cell(row_idx, start_col).value)
                gamer_po = clean_text(ws.cell(row_idx, start_col + 1).value)
                gio_ref = numeric_reference(ws.cell(row_idx, start_col + 2).value)
                delivery = excel_serial_to_datetime(ws.cell(row_idx, start_col + 3).value)
                if not load_ref or not gio_ref or not delivery:
                    continue  # skips SS and other non-release rows
                if delivery.year != target_year or delivery.month != target_month:
                    continue
                if gamer_po and not include_existing:
                    continue

                coord = f"{ws.title}!{ws.cell(row_idx, start_col).coordinate}:{ws.cell(row_idx, start_col + 5).coordinate}"
                if coord in seen:
                    continue
                seen.add(coord)

                note = self._semantic_note(
                    ws.cell(row_idx, start_col + 4).value,
                    ws.cell(row_idx, start_col + 5).value,
                )
                quantity, item_ref, uom, qty_source, review = self._resolve_test_quantity(product, note)
                if "montreal" in (note or "").lower():
                    review.append("Ship-to/location needs BC resolution")

                releases.append(
                    NormalizedRelease(
                        customer_release_reference=gio_ref,
                        load_number=int(load_ref),
                        product_context=product,
                        customer_item_reference=item_ref,
                        description=f"{calendar.month_name[target_month]} {product}",
                        quantity=quantity,
                        uom=uom,
                        requested_delivery_date=delivery.date(),
                        existing_gamer_order=gamer_po,
                        notes=note,
                        source_coordinates=[coord],
                        quantity_source=qty_source,
                        extraction_confidence=1.0,
                        parser_review_reasons=list(dict.fromkeys(review)),
                    )
                )

        return NormalizedInboundOrder(
            source=OrderSource(
                attachment_name=path.name,
                attachment_sha256=sha256_file(path),
                source_format=self.SOURCE_FORMAT,
                source_sheet=ws.title,
            ),
            customer=OrderCustomer(
                candidate_customer_name="Giovanni",
                resolution_method="known_format",
                resolution_confidence=1.0,
                evidence=[f"Known Giovanni monthly OOR format; period={period}"],
            ),
            document=OrderDocument(
                document_type=DocumentType.BLANKET_RELEASE_BATCH,
                period=period,
            ),
            releases=releases,
        )
