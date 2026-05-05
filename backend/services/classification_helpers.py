"""
GPI Document Hub - Classification Helpers

Extracted from server.py — authoritative implementations of:
  - classify_document_type: Deterministic-first classification pipeline
  - get_category_for_doc_type: Map doc_type to category
  - derive_workflow_status: Map processing result to workflow_status
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from workflows.core.engine import DocType, DocumentClassifier
from services.ai_classifier import classify_doc_type_with_ai

logger = logging.getLogger(__name__)

# Config from environment
AI_CLASSIFICATION_ENABLED = os.environ.get('AI_CLASSIFICATION_ENABLED', 'true').lower() == 'true'
AI_CLASSIFICATION_THRESHOLD = float(os.environ.get('AI_CLASSIFICATION_THRESHOLD', '0.8'))


async def classify_document_type(
    document: Dict,
    extracted_fields: Dict,
    suggested_type: str,
    confidence: float,
    metadata: Optional[Dict] = None,
) -> Dict:
    """
    Deterministic-first document type classification pipeline.

    Step 1: Run deterministic rules (Zetadocs codes, Square9 workflows, mailbox category)
    Step 2: If doc_type is not OTHER, keep it and skip AI
    Step 3: If doc_type is OTHER and AI classification is enabled, try AI
    Step 4: Apply AI result if confidence >= threshold
    """
    metadata = metadata or {}
    result = {
        "doc_type": DocType.OTHER.value,
        "category": "Other",
        "ai_classification": None,
        "classification_method": "default",
    }

    # Step 1a: Check Zetadocs set code
    zetadocs_set = metadata.get("zetadocs_set") or document.get("zetadocs_set_code")
    if zetadocs_set:
        doc_type, capture_channel = DocumentClassifier.classify_from_zetadocs_set(zetadocs_set)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"zetadocs:{zetadocs_set}"
            logger.info("Deterministic classification: Zetadocs set %s -> %s", zetadocs_set, doc_type.value)

    # Step 1b: Check Square9 workflow name
    if result["doc_type"] == DocType.OTHER.value:
        square9_workflow = metadata.get("square9_workflow") or document.get("square9_workflow_name")
        if square9_workflow:
            doc_type = DocumentClassifier.classify_from_square9_workflow(square9_workflow)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"square9:{square9_workflow}"
                logger.info("Deterministic classification: Square9 workflow %s -> %s", square9_workflow, doc_type.value)

    # Step 1c: Check mailbox category (source-lane context, requires evidence)
    # Mailbox category is *intake context*, not absolute proof of doc type.
    # We only let it deterministically classify when the extracted fields show
    # invoice/order-like evidence consistent with the mailbox lane. Without
    # evidence, we leave doc_type=OTHER and let AI run; if AI also says OTHER,
    # the AP-lane fallback below will route the document to NeedsReview rather
    # than letting it land in a non-AP folder.
    if result["doc_type"] == DocType.OTHER.value:
        mailbox_category = metadata.get("mailbox_category") or document.get("mailbox_category")
        if mailbox_category:
            evidence = _has_lane_evidence(mailbox_category, extracted_fields)
            doc_type = DocumentClassifier.classify_from_mailbox_category(mailbox_category, evidence=evidence)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"mailbox:{mailbox_category}+evidence"
                logger.info(
                    "Deterministic classification: Mailbox category %s + evidence -> %s",
                    mailbox_category, doc_type.value,
                )
            else:
                logger.info(
                    "Mailbox category %s noted as source context only (no invoice-like evidence yet); "
                    "deferring to AI / review",
                    mailbox_category,
                )

    # Step 1d: Check legacy suggested_job_type
    if result["doc_type"] == DocType.OTHER.value and suggested_type and suggested_type != "Unknown":
        doc_type = DocumentClassifier.classify_from_ai_result(suggested_type)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"legacy_ai:{suggested_type}"
            logger.info("Classification from legacy AI: %s -> %s", suggested_type, doc_type.value)

    # Step 2: If definitive type, set category and return
    if result["doc_type"] != DocType.OTHER.value:
        result["category"] = get_category_for_doc_type(result["doc_type"])
        return result

    # Step 3: Try AI classification if enabled
    if AI_CLASSIFICATION_ENABLED and os.environ.get("EMERGENT_LLM_KEY"):
        logger.info("Deterministic classification returned OTHER, invoking AI classifier for doc %s", document.get("id"))
        try:
            ai_result = await classify_doc_type_with_ai(
                document=document,
                extracted_text=extracted_fields.get("raw_text"),
                metadata=metadata,
            )
            result["ai_classification"] = ai_result.to_dict()

            if ai_result.should_accept(AI_CLASSIFICATION_THRESHOLD):
                result["doc_type"] = normalize_doc_type(ai_result.proposed_doc_type)
                result["classification_method"] = f"ai:{ai_result.model_name}:{ai_result.confidence:.2f}"
                logger.info("AI classification accepted for doc %s: %s (confidence: %.2f)",
                            document.get("id"), ai_result.proposed_doc_type, ai_result.confidence)
            else:
                logger.info("AI classification NOT accepted for doc %s: %s (confidence: %.2f, threshold: %.2f)",
                            document.get("id"), ai_result.proposed_doc_type, ai_result.confidence, AI_CLASSIFICATION_THRESHOLD)
        except Exception as e:
            logger.error("AI classification failed for doc %s: %s", document.get("id"), str(e))
            result["ai_classification"] = {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

    result["category"] = get_category_for_doc_type(result["doc_type"])

    # AP-lane review fallback: if the document came in through an AP-style
    # mailbox lane and nothing — neither deterministic rules nor AI — was able
    # to definitively classify it, keep the document inside the AP review lane
    # rather than letting it land in a generic Operations folder. doc_type
    # stays OTHER (we are NOT forcing AP_INVOICE without evidence), but a hint
    # is surfaced so downstream routing/derive_workflow_status can hold it for
    # human review instead of mis-routing.
    if result["doc_type"] == DocType.OTHER.value:
        mailbox_category = (metadata.get("mailbox_category")
                            or document.get("mailbox_category") or "")
        if (mailbox_category or "").upper() in ("AP", "SALES", "PURCHASE"):
            result["mailbox_lane_needs_review"] = True
            result["classification_method"] = f"mailbox_lane:{mailbox_category}:needs_review"
            logger.info(
                "Document on %s mailbox lane could not be definitively classified; "
                "flagging for AP-lane review instead of generic Operations routing",
                mailbox_category,
            )

    return result


# ---------------------------------------------------------------------------
# Lane-evidence helpers
# ---------------------------------------------------------------------------

def _has_lane_evidence(mailbox_category: str, extracted_fields: Dict) -> bool:
    """Return True when extracted fields support the mailbox lane's doc type.

    AP lane: needs at least one of invoice_number, amount/total/subtotal,
    vendor, due_date, bill_to. Sales / Purchase lanes: needs invoice/PO
    number or customer/vendor signal. The bar is intentionally low — this is
    confirming "yes, this looks roughly like the kind of doc this mailbox
    handles" rather than gold-standard validation. Hard validation is the
    job of the dedicated AP/Sales/Purchase services downstream.
    """
    if not extracted_fields or not isinstance(extracted_fields, dict):
        return False
    cat = (mailbox_category or "").upper()
    fields = {k: v for k, v in extracted_fields.items() if v not in (None, "", [], {})}
    if not fields:
        return False
    if cat == "AP":
        signals = (
            "invoice_number", "vendor", "vendor_name", "vendor_raw",
            "amount", "total", "subtotal", "amount_due",
            "due_date", "bill_to", "invoice_date",
        )
        return any(k in fields for k in signals)
    if cat == "SALES":
        signals = (
            "invoice_number", "customer", "customer_name", "customer_po",
            "ship_to", "amount", "total", "so_number",
        )
        return any(k in fields for k in signals)
    if cat == "PURCHASE":
        signals = ("po_number", "vendor", "vendor_name", "vendor_raw",
                   "ship_to", "line_items")
        return any(k in fields for k in signals)
    return False


def get_category_for_doc_type(doc_type: str) -> str:
    """Map doc_type to category for backward compatibility."""
    if doc_type == DocType.AP_INVOICE.value:
        return "AP"
    elif doc_type in [DocType.SALES_INVOICE.value, DocType.SALES_CREDIT_MEMO.value]:
        return "Sales"
    elif doc_type == DocType.PURCHASE_ORDER.value:
        return "Purchase"
    elif doc_type in ["SALES_ORDER", "Sales_Order", "DS_SALES_ORDER", "WH_SALES_ORDER", "SH_INVOICE"]:
        return "Sales"
    elif doc_type in ["BILL_OF_LADING", "Shipping_Document", "PACKING_SLIP", "Warehouse_Document"]:
        return "Shipping"
    return "Other"


# Map AI classifier types to system-internal document type strings
_AI_TYPE_TO_SYSTEM_TYPE = {
    "BILL_OF_LADING": "Shipping_Document",
    "PACKING_SLIP": "Packing_Slip",
    "SALES_ORDER": "Sales_Order",
}


def normalize_doc_type(raw_type: str) -> str:
    """Normalize AI-returned doc type to system-expected values."""
    return _AI_TYPE_TO_SYSTEM_TYPE.get(raw_type, raw_type)


def derive_workflow_status(final_status: str, doc_type: str, decision: str) -> str:
    """Map the processing result to a meaningful workflow_status."""
    status_lower = (final_status or "").lower()
    if status_lower in ("completed", "posted", "archived"):
        return "completed"
    if status_lower == "exception":
        return "exception"
    if status_lower in ("readytolink", "linkedtobc"):
        return "ready_for_approval"
    if status_lower in ("storedinsp",):
        return "processed"
    if decision == "auto_link":
        return "validation_passed"
    if status_lower == "needsreview":
        return "needs_review"
    return "classified"
