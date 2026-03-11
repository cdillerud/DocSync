"""
GPI Document Hub — Document Processor Registry

Detects which processor matches a document, runs it, and merges output
with existing AI extraction results.

Selection order:
    1. AI classification hint
    2. Layout fingerprint family
    3. Processor detect() logic
    4. Vendor pattern hint

If no processor matches, returns None and the pipeline continues normally.
"""

import logging
from typing import Optional, Dict, Any, List

from processors.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

# Global registry of processor instances (populated at startup)
_processors: List[DocumentProcessor] = []


def register_processor(processor: DocumentProcessor):
    """Add a processor to the registry."""
    _processors.append(processor)
    _processors.sort(key=lambda p: p.priority)
    logger.info("[ProcessorRegistry] Registered: %s (priority %d)", processor.name, processor.priority)


def get_registered_processors() -> List[Dict[str, Any]]:
    """Return info about all registered processors."""
    return [{"name": p.name, "priority": p.priority} for p in _processors]


def detect_processor(
    document_text: str,
    layout_fingerprint: Optional[Dict] = None,
    ai_classification: Optional[Dict] = None,
    vendor_name: Optional[str] = None,
) -> Optional[DocumentProcessor]:
    """
    Detect which processor should handle a document.
    Returns the first matching processor, or None.
    """
    for proc in _processors:
        try:
            if proc.detect(document_text, layout_fingerprint, ai_classification):
                logger.info("[ProcessorRegistry] Matched: %s", proc.name)
                return proc
        except Exception as e:
            logger.warning("[ProcessorRegistry] Error in %s.detect(): %s", proc.name, str(e))
    return None


def run_processor(
    processor: DocumentProcessor,
    document_text: str,
    layout_fingerprint: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Run a matched processor and return its full output.

    Returns:
        {
            "processor_name": str,
            "extracted_fields": dict,
            "suggested_vendor": str | None,
            "suggested_references": list,
            "diagnostics": dict,
        }
    """
    try:
        extracted = processor.extract(document_text, layout_fingerprint)
        vendor = processor.suggest_vendor(extracted)
        references = processor.suggest_references(extracted)
        diagnostics = processor.get_diagnostics(extracted)

        return {
            "processor_name": processor.name,
            "extracted_fields": extracted,
            "suggested_vendor": vendor,
            "suggested_references": references,
            "diagnostics": diagnostics,
        }
    except Exception as e:
        logger.error("[ProcessorRegistry] Error running %s: %s", processor.name, str(e))
        return {
            "processor_name": processor.name,
            "extracted_fields": {},
            "suggested_vendor": None,
            "suggested_references": [],
            "diagnostics": {"error": str(e)},
        }


def merge_processor_output(
    ai_extracted_fields: Dict[str, Any],
    processor_output: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge processor-extracted fields with AI extraction results.

    Strategy: processor fields AUGMENT, never replace, AI fields.
    - New keys from processor are added directly.
    - Existing keys are preserved from AI (processor can't overwrite).
    - Processor references are appended.
    """
    merged = dict(ai_extracted_fields)

    proc_fields = processor_output.get("extracted_fields", {})

    for key, value in proc_fields.items():
        if value and not merged.get(key):
            merged[key] = value

    # Tag the merge
    merged["_processor_name"] = processor_output.get("processor_name")
    merged["_processor_fields"] = list(proc_fields.keys())
    merged["_processor_references"] = processor_output.get("suggested_references", [])

    # If processor suggests a vendor and AI didn't find one
    proc_vendor = processor_output.get("suggested_vendor")
    if proc_vendor and not merged.get("vendor"):
        merged["vendor"] = proc_vendor
        merged["_vendor_source"] = "processor"

    return merged


def initialize_default_processors():
    """Register built-in processors. Called at startup."""
    from processors.freight_invoice_processor import FreightInvoiceProcessor
    from processors.customs_entry_processor import CustomsEntryProcessor
    from processors.bill_of_lading_processor import BillOfLadingProcessor

    register_processor(FreightInvoiceProcessor())
    register_processor(CustomsEntryProcessor())
    register_processor(BillOfLadingProcessor())

    logger.info("[ProcessorRegistry] %d default processors registered", len(_processors))
