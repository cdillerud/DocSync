"""
GPI Document Hub — Customs Entry Summary Processor

Detects CBP Entry Summaries (CF 7501) and extracts:
    entry number, broker file number, customer reference,
    invoice reference, invoice value, carrier, broker/importer
"""

import re
from typing import Optional, Dict, List, Any
from processors.document_processor import DocumentProcessor


_CUSTOMS_KEYWORDS = [
    "entry summary", "u.s. customs", "cbp form", "cbp 7501",
    "cf 7501", "customs and border", "entry number",
    "broker file", "importer of record", "consignee",
    "port of entry", "entry date", "duty",
]

_ENTRY_NUMBER_PATTERN = re.compile(
    r"Entry\s*(?:Number|No|#)\s*[:#]?\s*([A-Z0-9][\w\-]{6,15})",
    re.IGNORECASE,
)
_BROKER_FILE_PATTERN = re.compile(
    r"(?:Broker\s*File\s*(?:Number|No|#)?|File\s*(?:Number|No|#))\s*[:#]?\s*([A-Z0-9][\w\-]{4,20})",
    re.IGNORECASE,
)
_CUSTOMER_REF_PATTERN = re.compile(
    r"(?:Customer\s*(?:Ref(?:erence)?|Order))\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE,
)
_INVOICE_REF_PATTERN = re.compile(
    r"(?:^|(?<=\n))(?:Invoice)\s*(?:Ref(?:erence)?|Number|No|#)\s*[:#]?\s*([A-Z0-9][\w\-]{3,20})",
    re.IGNORECASE | re.MULTILINE,
)
_INVOICE_VALUE_PATTERN = re.compile(
    r"(?:Invoice\s*Value|Entered\s*Value|Total\s*Value)\s*[:#]?\s*\$?\s*([\d,]+\.?\d{0,2})",
    re.IGNORECASE,
)
_CARRIER_PATTERN = re.compile(
    r"(?:Carrier|Importing\s*Carrier)\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40}?)(?:\n|$)",
    re.IGNORECASE,
)
_BROKER_PATTERN = re.compile(
    r"(?:Broker|Licensed\s*Broker|Customs\s*Broker)\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40}?)(?:\n|$)",
    re.IGNORECASE,
)
_IMPORTER_PATTERN = re.compile(
    r"(?:Importer(?:\s+of\s+Record)?|Consignee)\s*[:#]?\s*([A-Za-z][A-Za-z0-9\s&,\.]{3,40}?)(?:\n|$)",
    re.IGNORECASE,
)
_PORT_PATTERN = re.compile(
    r"(?:Port\s*(?:of\s*Entry)?|Port\s*Code)\s*[:#]?\s*([A-Z0-9][\w\-\s]{2,20})",
    re.IGNORECASE,
)


class CustomsEntryProcessor(DocumentProcessor):
    name = "CustomsEntryProcessor"
    priority = 110

    def detect(self, document_text: str, layout_fingerprint=None, ai_classification=None) -> bool:
        if not document_text:
            return False
        text_lower = document_text.lower()

        if layout_fingerprint:
            family = (layout_fingerprint.get("family_id") or "").lower()
            if "customs" in family or "entry_summary" in family:
                return True

        keyword_hits = sum(1 for kw in _CUSTOMS_KEYWORDS if kw in text_lower)
        return keyword_hits >= 3

    def extract(self, document_text: str, layout_fingerprint=None) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}

        m = _ENTRY_NUMBER_PATTERN.search(document_text)
        if m:
            fields["entry_number"] = m.group(1).strip()

        m = _BROKER_FILE_PATTERN.search(document_text)
        if m:
            fields["broker_file_number"] = m.group(1).strip()

        m = _CUSTOMER_REF_PATTERN.search(document_text)
        if m:
            fields["customer_reference"] = m.group(1).strip()

        m = _INVOICE_REF_PATTERN.search(document_text)
        if m:
            fields["invoice_reference"] = m.group(1).strip()

        m = _INVOICE_VALUE_PATTERN.search(document_text)
        if m:
            fields["invoice_value"] = m.group(1).replace(",", "")

        m = _CARRIER_PATTERN.search(document_text)
        if m:
            fields["carrier"] = m.group(1).strip().rstrip(".,")

        m = _BROKER_PATTERN.search(document_text)
        if m:
            fields["broker"] = m.group(1).strip().rstrip(".,")

        m = _IMPORTER_PATTERN.search(document_text)
        if m:
            fields["importer"] = m.group(1).strip().rstrip(".,")

        m = _PORT_PATTERN.search(document_text)
        if m:
            fields["port_of_entry"] = m.group(1).strip()

        return fields

    def suggest_vendor(self, extracted_fields: Dict[str, Any]) -> Optional[str]:
        return extracted_fields.get("broker") or extracted_fields.get("carrier")

    def suggest_references(self, extracted_fields: Dict[str, Any]) -> List[Dict[str, str]]:
        refs = []
        if extracted_fields.get("entry_number"):
            refs.append({"label": "Entry Number", "value": extracted_fields["entry_number"], "source": "processor"})
        if extracted_fields.get("broker_file_number"):
            refs.append({"label": "Broker File", "value": extracted_fields["broker_file_number"], "source": "processor"})
        if extracted_fields.get("customer_reference"):
            refs.append({"label": "Customer Ref", "value": extracted_fields["customer_reference"], "source": "processor"})
        if extracted_fields.get("invoice_reference"):
            refs.append({"label": "Invoice Ref", "value": extracted_fields["invoice_reference"], "source": "processor"})
        return refs
