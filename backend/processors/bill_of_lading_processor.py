"""
GPI Document Hub — Bill of Lading Processor

Detects BOL documents and extracts:
    BOL number, carrier, shipper, consignee, shipment reference, PO number,
    weight, pieces
"""

import re
from typing import Optional, Dict, List, Any
from processors.document_processor import DocumentProcessor


_BOL_KEYWORDS = [
    "bill of lading", "b/l", "bol", "straight bill",
    "shipper", "consignee", "carrier", "notify party",
    "port of loading", "port of discharge",
    "pro number", "pro #", "seal number",
]

_BOL_NUMBER_PATTERN = re.compile(
    r"(?:B/?(?:O/?)?L|Bill\s+of\s+Lading|Pro)\s*(?:Number|No|#)?\s*[:#]?\s*([A-Z0-9][\w\-]{4,20})",
    re.IGNORECASE,
)
_CARRIER_PATTERN = re.compile(
    r"(?:Carrier|Trucking\s*(?:Company|Co)?|Transport(?:er)?)\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40}?)(?:\n|$)",
    re.IGNORECASE,
)
_SHIPPER_PATTERN = re.compile(
    r"(?:Shipper|Ship(?:ped)?\s*(?:From|By))\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40})",
    re.IGNORECASE,
)
_CONSIGNEE_PATTERN = re.compile(
    r"(?:Consignee|Ship\s*(?:To)|Deliver\s*To)\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40})",
    re.IGNORECASE,
)
_SHIPMENT_REF_PATTERN = re.compile(
    r"(?:Ship(?:ment)?\s*(?:Ref(?:erence)?|Number|No|#)?|Tracking)\s*[:#]?\s*([A-Z0-9][\w\-]{4,20})",
    re.IGNORECASE,
)
_PO_PATTERN = re.compile(
    r"(?<![A-Z])(?:PO|Purchase\s+Order)\s*(?:Number|No|#)?\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE,
)
_WEIGHT_PATTERN = re.compile(
    r"(?:Weight|Gross\s*Weight|Net\s*Weight)\s*[:#]?\s*([\d,]+\.?\d{0,2})\s*(?:lbs?|kg)?",
    re.IGNORECASE,
)
_SEAL_PATTERN = re.compile(
    r"(?:Seal)\s*(?:Number|No|#)?\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE,
)


class BillOfLadingProcessor(DocumentProcessor):
    name = "BillOfLadingProcessor"
    priority = 105

    def detect(self, document_text: str, layout_fingerprint=None, ai_classification=None) -> bool:
        if not document_text:
            return False
        text_lower = document_text.lower()

        if ai_classification:
            doc_type = (ai_classification.get("suggested_job_type") or "").lower()
            if "bol" in doc_type or "bill of lading" in doc_type or "lading" in doc_type:
                return True

        if layout_fingerprint:
            family = (layout_fingerprint.get("family_id") or "").lower()
            if "bol" in family or "lading" in family:
                return True

        keyword_hits = sum(1 for kw in _BOL_KEYWORDS if kw in text_lower)
        return keyword_hits >= 3

    def extract(self, document_text: str, layout_fingerprint=None) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}

        m = _BOL_NUMBER_PATTERN.search(document_text)
        if m:
            fields["bol_number"] = m.group(1).strip()

        m = _CARRIER_PATTERN.search(document_text)
        if m:
            fields["carrier"] = m.group(1).strip().rstrip(".,")

        m = _SHIPPER_PATTERN.search(document_text)
        if m:
            fields["shipper"] = m.group(1).strip().rstrip(".,")

        m = _CONSIGNEE_PATTERN.search(document_text)
        if m:
            fields["consignee"] = m.group(1).strip().rstrip(".,")

        m = _SHIPMENT_REF_PATTERN.search(document_text)
        if m:
            fields["shipment_reference"] = m.group(1).strip()

        m = _PO_PATTERN.search(document_text)
        if m:
            fields["po_number"] = m.group(1).strip()

        m = _WEIGHT_PATTERN.search(document_text)
        if m:
            fields["weight"] = m.group(1).replace(",", "")

        m = _SEAL_PATTERN.search(document_text)
        if m:
            fields["seal_number"] = m.group(1).strip()

        return fields

    def suggest_vendor(self, extracted_fields: Dict[str, Any]) -> Optional[str]:
        return extracted_fields.get("carrier") or extracted_fields.get("shipper")

    def suggest_references(self, extracted_fields: Dict[str, Any]) -> List[Dict[str, str]]:
        refs = []
        if extracted_fields.get("bol_number"):
            refs.append({"label": "BOL", "value": extracted_fields["bol_number"], "source": "processor"})
        if extracted_fields.get("shipment_reference"):
            refs.append({"label": "Shipment", "value": extracted_fields["shipment_reference"], "source": "processor"})
        if extracted_fields.get("po_number"):
            refs.append({"label": "PO", "value": extracted_fields["po_number"], "source": "processor"})
        if extracted_fields.get("seal_number"):
            refs.append({"label": "Seal", "value": extracted_fields["seal_number"], "source": "processor"})
        return refs
