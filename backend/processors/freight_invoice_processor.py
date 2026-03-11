"""
GPI Document Hub — Freight Invoice Processor

Recognizes freight invoice layouts and extracts:
    BOL number, shipment number, carrier, invoice number, freight amount,
    weight, class, pieces/pallets
"""

import re
from typing import Optional, Dict, List, Any
from processors.document_processor import DocumentProcessor


# Detection keywords (case-insensitive)
_FREIGHT_KEYWORDS = [
    "freight charge", "freight invoice", "freight bill",
    "weight", "class", "nmfc", "pieces", "pallets",
    "pro number", "pro #", "pro no",
    "bill of lading", "bol",
]

_CARRIER_KEYWORDS = [
    "carrier", "trucking", "transport", "logistics",
    "freight line", "express", "shipping",
]

# Patterns
_BOL_PATTERN = re.compile(
    r"(?:BOL|B/?L|Bill\s+of\s+Lading|Pro\s*(?:Number|No|#)?)\s*[:#]?\s*([A-Z0-9][\w\-]{4,20})",
    re.IGNORECASE,
)
_SHIPMENT_PATTERN = re.compile(
    r"(?:Ship(?:ment)?|Shp)\s*(?:Number|No|#|Ref)?\s*[:#]?\s*([A-Z0-9][\w\-]{4,20})",
    re.IGNORECASE,
)
_INVOICE_PATTERN = re.compile(
    r"(?:^|(?<=\n))(?:Invoice|Inv)\s*(?:Number|No|#)?\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE | re.MULTILINE,
)
_AMOUNT_PATTERN = re.compile(
    r"(?:Total|Amount\s+Due|Freight\s+Charge[s]?|Net\s+Amount)\s*[:#]?\s*\$?\s*([\d,]+\.?\d{0,2})",
    re.IGNORECASE,
)
_WEIGHT_PATTERN = re.compile(
    r"(?:Weight|Wt)\s*[:#]?\s*([\d,]+\.?\d{0,2})\s*(?:lbs?|pounds?|kg)?",
    re.IGNORECASE,
)
_PO_PATTERN = re.compile(
    r"(?<![A-Z])(?:PO|Purchase\s+Order)\s*(?:Number|No|#)?\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE,
)
_CARRIER_NAME_PATTERN = re.compile(
    r"(?:Carrier|Shipped\s+(?:Via|By))\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40}?)(?:\n|$)",
    re.IGNORECASE,
)


class FreightInvoiceProcessor(DocumentProcessor):
    name = "FreightInvoiceProcessor"
    priority = 100

    def detect(self, document_text: str, layout_fingerprint=None, ai_classification=None) -> bool:
        if not document_text:
            return False
        text_lower = document_text.lower()

        # Check AI classification hint
        if ai_classification:
            doc_type = (ai_classification.get("suggested_job_type") or "").lower()
            if "freight" in doc_type:
                return True

        # Check layout family
        if layout_fingerprint:
            family = (layout_fingerprint.get("family_id") or "").lower()
            if "freight" in family:
                return True

        # Keyword detection: need "freight" context + at least one structural keyword
        has_freight = "freight" in text_lower
        keyword_hits = sum(1 for kw in _FREIGHT_KEYWORDS if kw in text_lower)
        return has_freight and keyword_hits >= 2

    def extract(self, document_text: str, layout_fingerprint=None) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}

        m = _BOL_PATTERN.search(document_text)
        if m:
            fields["bol_number"] = m.group(1).strip()

        m = _SHIPMENT_PATTERN.search(document_text)
        if m:
            fields["shipment_number"] = m.group(1).strip()

        m = _INVOICE_PATTERN.search(document_text)
        if m:
            fields["invoice_number"] = m.group(1).strip()

        m = _AMOUNT_PATTERN.search(document_text)
        if m:
            fields["freight_amount"] = m.group(1).replace(",", "")

        m = _WEIGHT_PATTERN.search(document_text)
        if m:
            fields["weight"] = m.group(1).replace(",", "")

        m = _PO_PATTERN.search(document_text)
        if m:
            fields["po_number"] = m.group(1).strip()

        m = _CARRIER_NAME_PATTERN.search(document_text)
        if m:
            fields["carrier"] = m.group(1).strip().rstrip(".,")

        return fields

    def suggest_vendor(self, extracted_fields: Dict[str, Any]) -> Optional[str]:
        return extracted_fields.get("carrier")

    def suggest_references(self, extracted_fields: Dict[str, Any]) -> List[Dict[str, str]]:
        refs = []
        if extracted_fields.get("bol_number"):
            refs.append({"label": "BOL", "value": extracted_fields["bol_number"], "source": "processor"})
        if extracted_fields.get("shipment_number"):
            refs.append({"label": "Shipment", "value": extracted_fields["shipment_number"], "source": "processor"})
        if extracted_fields.get("po_number"):
            refs.append({"label": "PO", "value": extracted_fields["po_number"], "source": "processor"})
        if extracted_fields.get("invoice_number"):
            refs.append({"label": "Invoice", "value": extracted_fields["invoice_number"], "source": "processor"})
        return refs
