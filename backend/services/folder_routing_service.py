"""
Folder Routing Service - Routes documents to SharePoint folders based on accounting structure.

Mirrors the accounting department's folder structure from "Temp Folder Structure 9.15.25.docx"

Key routing rules:
- All Canpack shipment docs → Dropship Not International → Canpack
- Dunnage return freight → Canpack → Dunnage return freight
- Freight issues needing logistics approval → Freight Issues
- S&H invoices split by approved/waiting and processor (Andy/Ellie)
- Credit memos routed by vendor (Anchor/Ball/OI dunnage, Aaron, Quality, Unclaimed)
- Warehouse docs split by international/domestic and order type
"""

import logging
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Legacy all-caps DocType values stored on some auto-split pages.
_LEGACY_DOC_TYPES = {"AP_INVOICE": "AP_Invoice", "SALES_INVOICE": "AR_Invoice",
                     "PURCHASE_ORDER": "Purchase_Order", "SALES_CREDIT_MEMO": "Credit_Memo",
                     "PURCHASE_CREDIT_MEMO": "Credit_Memo", "STATEMENT": "Statement"}
# =============================================================================
# VENDOR ROUTING RULES
# =============================================================================

VENDOR_FOLDER_MAPPING = {
    # Ball vendors
    "ball": "Ball",
    "ball corporation": "Ball",
    "ball container": "Ball",
    "ball metal": "Ball",
    # Canpack vendors
    "canpack": "Canpack",
    "canpack group": "Canpack",
    "canpack usa": "Canpack",
    # Anchor vendors
    "anchor": "Anchor",
    "anchor glass": "Anchor",
    "anchor packaging": "Anchor",
    # OI vendors
    "oi": "OI",
    "o-i": "OI",
    "owens illinois": "OI",
    "owens-illinois": "OI",
    # Freight carriers
    "ups": "Freight",
    "fedex": "Freight",
    "usps": "Freight",
    "dhl": "Freight",
    "xpo": "Freight",
    "old dominion": "Freight",
    "estes": "Freight",
    "saia": "Freight",
    "yrc": "Freight",
    "abf": "Freight",
    "r+l carriers": "Freight",
    "southeastern freight": "Freight",
    "averitt": "Freight",
    "dayton freight": "Freight",
    "central transport": "Freight",
    "pitt ohio": "Freight",
    "tumalo creek": "Freight",
    "tumalo creek transportation": "Freight",
    "tumaloc": "Freight",
}

# =============================================================================
# FOLDER STRUCTURE (for backward compat / summary views)
# =============================================================================

FOLDER_STRUCTURE = {
    "DO_NOT_PAY": {
        "path": "DO NOT PAY",
        "description": "Vendor invoices authorized not to pay",
        "subfolders": ["by_year"],
    },
    "DROPSHIP_INTERNATIONAL": {
        "path": "Dropship International",
        "description": "International vendor invoices for drop ship orders",
        "subfolders": ["by_order"],
    },
    "DROPSHIP_DOMESTIC": {
        "path": "Dropship Not International",
        "description": "Domestic vendor invoices for drop ship orders",
        "subfolders": {
            "Canpack": "All Canpack shipment documents",
            "Canpack/Dunnage return freight": "Canpack dunnage return freight invoices",
        },
    },
    "FREIGHT_ISSUES": {
        "path": "Freight Issues",
        "description": "Freight invoices needing logistics approval",
        "subfolders": {},
    },
    "READY_TO_PROCESS": {
        "path": "Ready to process",
        "description": "Documents ready for processing",
        "subfolders": {
            "Purch Inv": "Invoices with cost verified, purchase invoice only",
        },
    },
    "MEG_TO_PROCESS": {
        "path": "Meg to Process",
        "description": "Documents for Meg to process",
        "subfolders": {},
    },
    "MISCELLANEOUS": {
        "path": "Miscellaneous",
        "description": "Miscellaneous office invoices",
        "subfolders": {
            "Misc Invoices - approved": "Approved miscellaneous invoices",
            "Misc Invoices - need approval": "Miscellaneous invoices needing approval",
        },
    },
    "RHONDA_ISSUES": {
        "path": "Rhonda - Issues",
        "description": "Documents for Rhonda to process",
        "subfolders": {},
    },
    "SH_APPROVED": {
        "path": "S&H Invoices Approved",
        "description": "Warehouse S&H invoices ready to process as cost only",
        "subfolders": {
            "Andy to Process": "S&H approved - Andy to process",
            "Ellie to Process": "S&H approved - Ellie to process",
        },
    },
    "SH_WAITING_APPROVAL": {
        "path": "S&H Invoices waiting for approval",
        "description": "Warehouse S&H invoices needing approval",
        "subfolders": {
            "Andy to Process": "S&H waiting approval - Andy to process",
        },
    },
    "MONTH_REC_TEMPLATES": {
        "path": "Month Rec & Templates",
        "description": "Monthly reconciliation and templates",
        "subfolders": {},
    },
    "TOOLING": {
        "path": "Tooling Invoices",
        "description": "Invoices for tooling charges",
        "subfolders": {},
    },
    "VENDOR_CREDITS": {
        "path": "Vendor Credit Memos",
        "description": "Vendor credit memos",
        "subfolders": {
            "Anchor Dunnage": "Anchor dunnage credits",
            "Ball Dunnage": "Ball dunnage credits",
            "OI Dunnage": "OI dunnage credits",
            "Processed Credit Memo - Aaron": "Processed credit memos by Aaron",
            "Sent to Quality": "Credits sent to quality",
            "Unclaimed credits posted": "Unclaimed posted credits",
        },
    },
    "WAREHOUSE_INTERNATIONAL": {
        "path": "Warehouse International",
        "description": "International vendor invoices for warehouse orders",
        "subfolders": ["by_order"],
    },
    "WAREHOUSE_DOMESTIC": {
        "path": "Warehouse Not International",
        "description": "Domestic vendor invoices for warehouse orders",
        "subfolders": {
            "Assembly": "Assembly paperwork and invoices",
            "GT's": "GT's inbound paperwork",
            "Sort and Stack": "Sort and Stack inbound/assembly",
            "Assembly Kent": "Assembly Kent inbound paperwork, freight, invoices",
            "Assembly GT B&B": "B&B warehouse-assembly paperwork (WA#### files)",
            "Ball Orders": "Ball inbound/outbound paperwork and freight",
            "GT's Orders": "GT's outbound paperwork from Sort and Stack",
            "Transfer Orders": "Transfer orders outbound paperwork",
            "UPS Orders": "UPS shipped orders outbound paperwork",
        },
    },
}


# Document type indicators for special routing
CREDIT_MEMO_INDICATORS = [
    "credit memo", "credit note", "cm", "credit", "refund",
    "adjustment", "rebate", "allowance"
]

TOOLING_INDICATORS = [
    "tooling", "mold", "die", "fixture", "tool charge"
]

DUNNAGE_INDICATORS = [
    "dunnage", "pallet", "return freight", "empty return"
]

# =============================================================================
# AP STAGING / REVIEW DESTINATIONS (Square9 parity, fallback-only)
# =============================================================================
# The locked production AP destination per cutover readiness lock-in:
#   /sites/GamerAccounting/Shared Documents/General/Accounting/Accounts Payable/Temp Folder
# This is now applied ONCE, as SHAREPOINT_BASE_FOLDER in sharepoint_service.py,
# at the point where a routed path is handed off to the actual upload call.
# Every path in this file (including these two) is relative to that base -
# do not bake any part of the locked path into folder strings here, or it
# will be double-prefixed. See MIGRATION_PROGRESS-equivalent notes: this was
# fixed alongside the SharePoint site switch from the /GPI-DocumentHub-Test
# site to the real /GamerAccounting site.
#
# Hub's job is to *automate* AP routing, not to dump every AP invoice into
# the Temp Folder for accountants to manually re-route. Temp Folder (the
# base itself, i.e. AP_STAGING_FOLDER = "") is a **fallback** destination
# used only when:
#   (a) automation cannot determine a final folder with sufficient evidence
#       (weak / ambiguous / contradictory signals), OR
#   (b) the document was flagged `mailbox_lane_needs_review=True` by
#       classification (e.g. non-invoice mistakenly sent to billing@).
# High-confidence AP invoices route directly to their final accounting
# folder (Canpack / Dropship / Warehouse / Vendor Credit Memos / Freight
# / etc.) via the deterministic rule chain below — no override needed.
AP_STAGING_FOLDER = ""
AP_LANE_REVIEW_FOLDER = "_NeedsReview"

# Doc-type strings that count as AP-lane invoices (uppercase from
# DocType.AP_INVOICE.value, plus the suggested_job_type variants).
_AP_INVOICE_DOC_TYPES = {"AP_INVOICE", "AP_Invoice", "AP Invoice"}


def _is_ap_lane_doc(doc: Dict[str, Any]) -> bool:
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    doc_type = _LEGACY_DOC_TYPES.get(doc_type, doc_type)
    if doc_type in _AP_INVOICE_DOC_TYPES:
        return True
    if (doc.get("doc_type") or "") in _AP_INVOICE_DOC_TYPES:
        return True
    return False


def _accounting_override_set(doc: Dict[str, Any]) -> bool:
    """True when accounting has explicitly opted this document out of the
    AP-lane weak-fallback guard (so the document keeps whatever destination
    the rule chain produced, even if that destination is the generic Misc
    bucket). Two signals are accepted: ``accounting_routing_override=True``
    or ``approved=True`` / ``status="Approved"``. Almost never needed in
    practice — the rule chain itself produces the correct final folder for
    high-confidence AP invoices.
    """
    if doc.get("accounting_routing_override") is True:
        return True
    if doc.get("approved") is True:
        return True
    if (doc.get("status") or "") == "Approved":
        return True
    return False


def _is_weak_fallback_routing(path: str, reason: str) -> bool:
    """A 'weak fallback' is when the rule chain produced a destination by
    hitting the bottom-of-chain default ("Default routing for ...") or by
    landing in Misc/need-approval through an uncertain / contradictory
    signal (e.g. PO not found in BC). For AP-lane documents we redirect
    these to the AP Temp Folder so the AP team can review them rather than
    letting them sit unstructured in Misc.

    Specific named rules with strong evidence (Canpack vendor → Dropship/
    Canpack, credit-memo keywords → Vendor Credit Memos, file pattern →
    Warehouse, freight vendor → Freight, LocationCode=MSC → Misc,
    DO NOT PAY status → DO NOT PAY/<year>, etc.) are NOT considered weak
    fallbacks because they are evidence-based routings to the correct
    final destination.
    """
    r = reason or ""
    p = path or ""
    # Strong-signal reasons override the weak-fallback heuristic even when
    # they happen to land in Misc/need-approval (LocationCode=MSC is the
    # canonical case — accounting explicitly tags those for Misc).
    strong_prefixes = (
        "LocationCode=",
        "Document marked Do Not Pay",
        "No order number on domestic invoice",
        "Suspected payment fraud",
    )
    if any(r.startswith(prefix) for prefix in strong_prefixes):
        return False
    if r.startswith("Default routing for"):
        return True
    if "Misc Invoices - need approval" in p:
        return True
    return False


# =============================================================================
# FOLDER ROUTING LOGIC
# =============================================================================

# Operations-style folder roots that may *only* receive an AP-lane document
# when a specific evidence-backed rule explicitly placed it there (e.g.
# Canpack vendor → Dropship/Canpack, freight vendor + resolved PO →
# Freight Issues, credit-memo description → Vendor Credit Memos). The
# scatter guard below treats a landing in one of these roots as suspicious
# unless the routing reason matches a known strong-AP signal.
_OPERATIONS_FOLDER_ROOTS = (
    "Warehouse Reports",
    "Dropship Not International",
    "Dropship International",
    "Warehouse Not International",
    "Warehouse International",
    "Freight Issues",
    "Vendor Credit Memos",
    "Miscellaneous",
)

# Reason-string fragments that mark an AP-lane Operations-folder landing
# as suspicious (defense-in-depth scatter guard). The weak-fallback wrapper
# in `determine_folder_path` should already redirect these for AP-lane
# documents, so this list is intentionally narrow — anything matching a
# named rule (Canpack vendor, credit-memo description, WH_ pattern, freight
# vendor, resolved BC PO, "All Others" domestic, LocationCode=, etc.) is
# treated as strong evidence and allowed to land in Operations roots.
_WEAK_SCATTER_REASON_FRAGMENTS = (
    "Default routing for",
    "Misc Invoices - need approval",
)


def _path_in_operations_root(path: str) -> bool:
    if not path:
        return False
    return any(path.startswith(root) for root in _OPERATIONS_FOLDER_ROOTS)


def _reason_is_weak_for_scatter_guard(reason: str) -> bool:
    """True only when the reason matches a known weak / catch-all signal.
    Named-rule reasons are *not* weak; the rule chain has already produced
    the documented final destination."""
    if not reason:
        return True
    return any(frag in reason for frag in _WEAK_SCATTER_REASON_FRAGMENTS)


def determine_folder_path(
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False,
    location_code: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """Top-level routing entry point.

    Runs the deterministic rule chain in :func:`_determine_folder_path_core`
    and applies a thin **AP-lane weak-fallback guard** afterward: if the
    chosen destination is a generic catch-all (the bottom-of-chain
    ``"Default routing for ..."`` path or ``Miscellaneous/Misc Invoices -
    need approval``) for an AP-lane document and accounting has not
    explicitly overridden, redirect to the AP Temp Folder so the AP team
    can review rather than letting the doc sit unstructured in Misc.

    High-confidence AP invoices (Canpack vendor / credit memo / WH_ pattern
    / freight vendor / resolved BC PO / etc.) auto-route to their final
    folder via the rule chain — no override needed.
    """
    path, reason, details = _determine_folder_path_core(
        doc, freight_direction=freight_direction,
        is_international=is_international, location_code=location_code,
    )
    if _is_ap_lane_doc(doc) and not _accounting_override_set(doc):
        if _is_weak_fallback_routing(path, reason):
            details = dict(details)
            details["weak_fallback_redirect_from"] = path
            details["weak_fallback_redirect_reason"] = reason
            return (
                AP_STAGING_FOLDER,
                f"AP-lane weak-fallback redirect (was: {reason}); staged for AP review",
                details,
            )
    return path, reason, details


# =============================================================================
# Structured AP routing decision (mission-aligned, auditable contract)
# =============================================================================

# Routing status taxonomy.
ROUTING_STATUS_AUTO_ROUTED = "auto_routed"        # final destination chosen by evidence
ROUTING_STATUS_NEEDS_REVIEW = "needs_review"      # weak-evidence / lane-review fallback
ROUTING_STATUS_EXCEPTION = "exception"            # hard block (forbidden scatter)
ROUTING_STATUS_MANUAL_OVERRIDE = "manual_override"  # operator opted out of guard


def determine_ap_routing_decision(
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False,
    location_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Evidence-based AP-lane routing decision.

    Wraps the deterministic rule chain (`determine_folder_path`) in a
    structured contract aligned with the GPI Hub mission: auto-classify
    and auto-route AP documents using evidence, and only route to review
    when evidence is insufficient or contradictory.

    Returns a dict with::

        {
            "folder_path": str,
            "routing_status": "auto_routed" | "needs_review" | "exception" | "manual_override",
            "routing_reason": str,
            "routing_details": {
                # full routing details dict from the rule chain plus:
                "mailbox_category": ...,
                "doc_type": ...,
                "suggested_job_type": ...,
                "classification_method": ...,
                "ai_confidence": ...,
                "vendor_canonical": ...,
                "vendor_match_method": ...,
                "po_number_clean": ...,
                "invoice_number_clean": ...,
                "amount_float": ...,
                "validation_results": ...,
                "possible_duplicate": ...,
                "manual_override_applied": bool,
                "evidence_signals_used": [...],
                "scatter_guard_blocked_destination": optional str,
            },
        }
    """
    folder_path, reason, details = determine_folder_path(
        doc, freight_direction=freight_direction,
        is_international=is_international, location_code=location_code,
    )

    is_ap = _is_ap_lane_doc(doc)
    override = _accounting_override_set(doc)
    needs_review_lane = bool(doc.get("mailbox_lane_needs_review"))

    # Defense-in-depth scatter guard for AP-lane docs.
    scatter_blocked: Optional[Tuple[str, str]] = None
    if (
        is_ap
        and not override
        and _path_in_operations_root(folder_path)
        and _reason_is_weak_for_scatter_guard(reason)
    ):
        scatter_blocked = (folder_path, reason)
        folder_path = AP_LANE_REVIEW_FOLDER
        reason = (
            f"AP-lane scatter guard: blocked landing in Operations folder "
            f"({scatter_blocked[0]}) without strong AP evidence; held for review"
        )

    # Decide routing_status.
    if override:
        routing_status = ROUTING_STATUS_MANUAL_OVERRIDE
    elif scatter_blocked:
        routing_status = ROUTING_STATUS_EXCEPTION
    elif folder_path in (AP_STAGING_FOLDER, AP_LANE_REVIEW_FOLDER):
        routing_status = ROUTING_STATUS_NEEDS_REVIEW
    elif folder_path.startswith(AP_LANE_REVIEW_FOLDER):
        routing_status = ROUTING_STATUS_NEEDS_REVIEW
    else:
        routing_status = ROUTING_STATUS_AUTO_ROUTED

    # Evidence signals captured by the rule chain (best-effort summary).
    evidence_signals: list = []
    if doc.get("vendor_canonical"):
        evidence_signals.append("vendor_canonical")
    if doc.get("po_number_clean") or doc.get("po_number_extracted"):
        evidence_signals.append("po_number")
    if doc.get("invoice_number_clean"):
        evidence_signals.append("invoice_number")
    if doc.get("bc_po_resolved") is True:
        evidence_signals.append("bc_po_resolved")
    if doc.get("amount_float") is not None:
        evidence_signals.append("amount")
    if (doc.get("file_name") or "").upper().startswith(("WH_", "AS_", "ML_")):
        evidence_signals.append("filename_pattern")
    if needs_review_lane:
        evidence_signals.append("mailbox_lane_needs_review")

    enriched_details = dict(details)
    enriched_details.update({
        "mailbox_category": doc.get("mailbox_category"),
        "mailbox_lane_needs_review": needs_review_lane,
        "doc_type": doc.get("doc_type") or doc.get("document_type"),
        "suggested_job_type": doc.get("suggested_job_type"),
        "classification_method": doc.get("classification_method"),
        "ai_confidence": doc.get("ai_confidence") or doc.get("confidence"),
        "vendor_canonical": doc.get("vendor_canonical"),
        "vendor_match_method": doc.get("vendor_match_method"),
        "po_number_clean": doc.get("po_number_clean") or doc.get("po_number_extracted"),
        "invoice_number_clean": doc.get("invoice_number_clean"),
        "amount_float": doc.get("amount_float"),
        "validation_results": doc.get("validation_results"),
        "possible_duplicate": doc.get("possible_duplicate"),
        "manual_override_applied": override,
        "evidence_signals_used": evidence_signals,
    })
    if scatter_blocked:
        enriched_details["scatter_guard_blocked_destination"] = scatter_blocked[0]
        enriched_details["scatter_guard_blocked_reason"] = scatter_blocked[1]

    return {
        "folder_path": folder_path,
        "routing_status": routing_status,
        "routing_reason": reason,
        "routing_details": enriched_details,
    }


# B&B sends warehouse-assembly paperwork as WA####*.pdf. Staff file all of it in
# Square9 under "Warehouse Not International/Assembly GT B&B"; Hub was treating
# it as inbound shipping and filing it under Dropship Not International.
# Approved 2026-10-01.
BB_ASSEMBLY_SENDERS = {"justin_bandb@yahoo.com", "bandbwarehouse@yahoo.com"}
BB_ASSEMBLY_FOLDER = "Warehouse Not International/Assembly GT B&B"
_WA_ASSEMBLY_FILE = re.compile(r"^WA\d{4}", re.I)


def _determine_folder_path_core(
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False,
    location_code: Optional[str] = None
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Determine the SharePoint folder path for a document based on accounting rules.

    Returns:
        Tuple of (folder_path, routing_reason, routing_details)
    """
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
    doc_type = _LEGACY_DOC_TYPES.get(doc_type, doc_type)
    extracted = doc.get("extracted_fields") or {}
    normalized = doc.get("normalized_fields", {})
    ai_extraction = doc.get("ai_extraction", {})

    # Get key fields
    vendor_name = (
        doc.get("vendor_canonical") or
        normalized.get("vendor") or
        extracted.get("vendor") or
        ai_extraction.get("vendor") or
        ""
    ).lower()

    order_number = (
        doc.get("po_number_extracted") or
        doc.get("bol_number_extracted") or
        normalized.get("po_number") or
        normalized.get("bol_number") or
        extracted.get("po_number") or
        extracted.get("bol_number") or
        extracted.get("order_number") or
        ""
    )

    invoice_description = (
        extracted.get("description") or
        ai_extraction.get("description") or
        doc.get("file_name") or
        ""
    ).lower()

    routing_details = {
        "doc_type": doc_type,
        "vendor": vendor_name,
        "order_number": order_number,
        "freight_direction": freight_direction,
        "is_international": is_international,
        "location_code": location_code,
        "mailbox_category": doc.get("mailbox_category"),
        "mailbox_lane_needs_review": bool(doc.get("mailbox_lane_needs_review")),
        "accounting_routing_override": _accounting_override_set(doc),
    }

    # =========================================================================
    # SQUARE9-PARITY STAGING (mailbox-lane review only — fallback-only)
    # =========================================================================
    #
    # Hub auto-classifies and auto-routes. Temp Folder is NOT the default
    # destination for AP invoices; it is the safe fallback for documents
    # that classification could not place with sufficient evidence
    # (mailbox_lane_needs_review=True), and the wrapper below catches
    # weak-fallback routing for AP-lane docs and redirects there too.
    #
    # PRIORITY 1: mailbox-lane needs-review hint set by classification
    # (e.g., non-invoice mistakenly sent to billing@) — keep on AP review
    # desk rather than letting it leak into a generic Operations folder.
    if doc.get("mailbox_lane_needs_review"):
        mc = (doc.get("mailbox_category") or "").upper()
        if mc == "AP":
            return (
                AP_LANE_REVIEW_FOLDER,
                "AP-lane document not definitively classified; staged for AP review",
                routing_details,
            )
        if mc in ("SALES", "PURCHASE"):
            return (
                AP_LANE_REVIEW_FOLDER,
                f"{mc} lane document not definitively classified; staged for review",
                routing_details,
            )

    # =================================================================
    # ROUTING RULES (in priority order per accounting document)
    # =================================================================

    # RULE -1: LocationCode = MSC → Miscellaneous (matches S9 workflow)
    if location_code and location_code.upper() == "MSC":
        return (
            "Miscellaneous/Misc Invoices - need approval",
            f"LocationCode=MSC → Miscellaneous (vendor={vendor_name})",
            routing_details,
        )

    # RULE -0.5: B&B warehouse-assembly paperwork (see BB_ASSEMBLY_SENDERS).
    sender = (doc.get("email_sender") or "").strip().lower()
    if sender in BB_ASSEMBLY_SENDERS and _WA_ASSEMBLY_FILE.match(doc.get("file_name") or ""):
        return (
            BB_ASSEMBLY_FOLDER,
            f"B&B warehouse-assembly paperwork ({doc.get('file_name')}) -> Assembly GT B&B",
            routing_details,
        )

    # Auto-detect international from vendor name if not explicitly set
    if not is_international:
        is_international = _detect_international_vendor(vendor_name, extracted, doc)

    # Learned vendor lane profile (staff filings): a vendor staff file as
    # domestic 90%+ of the time is domestic, whatever the extraction said
    # (US carriers and US branches of foreign vendors: Anchor, Quarterback,
    # Swift, Massilly ... were flagged international by extraction).
    lane = _lane_profile(doc)
    if lane:
        if lane["intl_share"] <= LANE_PROFILE_INTL_MINORITY:
            is_international = False
        elif lane["intl_share"] >= 1 - LANE_PROFILE_MINORITY:
            is_international = True

    # An ocean bill of lading / container number (Evergreen EGLV..., MSC
    # MEDU..., Yang Ming YMJA...) on the invoice is an import: staff filed
    # 15 of 16 such invoices (mostly Tumalo drayage) as International, the
    # extraction and vendor profile had all 16 domestic.
    if _is_ocean_import(doc):
        is_international = True
        doc["_ocean_import"] = True

    # =================================================================
    # ROUTING RULES (in priority order per accounting document)
    # =================================================================

    # RULE -0.5f: suspected payment fraud (see fraud_signal_service) goes to
    # DO NOT PAY for a person to check, before any vendor or invoice rule.
    fraud = doc.get("fraud_risk") or {}
    if isinstance(fraud, dict) and fraud.get("flagged"):
        return (
            f"DO NOT PAY/{datetime.now().year}",
            "Suspected payment fraud: " + "; ".join(fraud.get("reasons") or []),
            routing_details,
        )

    # RULE -0.25: definite credits (Credit_Memo type or negative total) go to
    # Vendor Credit Memos before any vendor-specific rule (see _is_definite_credit).
    if _is_definite_credit(doc, doc_type):
        vendor_folder = _get_credit_vendor_subfolder(vendor_name, invoice_description)
        if vendor_folder:
            return (f"Vendor Credit Memos/{vendor_folder}", f"Credit memo → {vendor_folder}", routing_details)
        return ("Vendor Credit Memos", "Vendor credit memo (credit type or negative total)", routing_details)

    # RULE 0: All Canpack documents → Dropship Not International → Canpack
    # This is a high-level directive that overrides other paths for Canpack
    if _is_canpack_vendor(vendor_name):
        if _is_dunnage_related(invoice_description):
            return (
                "Dropship Not International/Canpack/Dunnage return freight",
                "Canpack dunnage return freight",
                routing_details,
            )
        return (
            "Dropship Not International/Canpack",
            "All Canpack shipment documents route here",
            routing_details,
        )

    # RULE 1: Credit Memos → Vendor Credit Memos
    if _is_credit_memo(doc_type, invoice_description):
        vendor_folder = _get_credit_vendor_subfolder(vendor_name, invoice_description)
        if vendor_folder:
            return (
                f"Vendor Credit Memos/{vendor_folder}",
                f"Credit memo → {vendor_folder}",
                routing_details,
            )
        return (
            "Vendor Credit Memos",
            "Vendor credit memo (general)",
            routing_details,
        )

    # RULE 2: Quality Issues → Vendor Credit Memos / Sent to Quality
    if doc_type == "Quality_Issue":
        return (
            "Vendor Credit Memos/Sent to Quality",
            "Quality issue document",
            routing_details,
        )

    # RULE 3: Tooling Invoices
    if any(indicator in invoice_description for indicator in TOOLING_INDICATORS):
        return ("Tooling Invoices", "Tooling invoice detected", routing_details)

    # RULE 4: Freight Issues (needing logistics approval)
    # Exception disposition must be supported by an explicit issue signal.
    if (
        doc.get("needs_logistics_approval")
        or doc.get("has_freight_issue")
        or doc.get("freight_issues")
    ):
        return (
            "Dropship Not International/Freight/Freight Issues",
            "Freight invoice needing logistics approval",
            routing_details,
        )

    # RULE 5: S&H (Storage & Handling) Invoices
    if doc_type in ("S&H_Invoice", "SH_Invoice") or _is_storage_handling(invoice_description)             or (doc_type in ("AP_Invoice", "AP Invoice", "Warehouse_Receipt", "Inspection_Form") and _vendor_files_sh(doc))             or (doc_type in ("AP_Invoice", "AP Invoice") and _is_sh_invoice_evidence(doc, order_number)):
        if doc.get("approved") or doc.get("status") == "Approved":
            return (
                "S&H Invoices Approved",
                "Approved S&H invoice",
                routing_details,
            )
        # Unapproved S&H invoices wait for approval (staff filings: 17 waiting
        # vs 2 approved, week of 2026-09-28); this branch used to say Approved.
        return (
            "S&H Invoices waiting for approval",
            "S&H invoice awaiting approval",
            routing_details,
        )

    # RULE 5.5: Inspection Forms → Vendor Credit Memos / Sent to Quality,
    # unless the vendor has a decisive lane: staff filed 0 of 10 inspection
    # forms (Citi Cargo shipping/dunnage reports) in Sent to Quality and 9
    # under Warehouse Not International (45 days to 2026-10-05).
    if doc_type == "Inspection_Form":
        _ilane = _lane_profile(doc)
        if _ilane and _ilane.get("warehouse_share", 0.5) >= 1 - LANE_PROFILE_MINORITY:
            _intl = _ilane.get("intl_share", 0.0) >= 1 - LANE_PROFILE_MINORITY
            return (
                "Warehouse International" if _intl else
                f"Warehouse Not International/{_get_warehouse_subfolder(vendor_name, order_number, doc)}",
                "Inspection form from a warehouse-lane vendor (staff file these in the lane)",
                routing_details,
            )
        return (
            "Vendor Credit Memos/Sent to Quality",
            "Inspection form → Sent to Quality",
            routing_details,
        )

    # GPI-SQUARE9-WAREHOUSE-RECEIPT-V28: warehouse receipts are warehouse-lane documents, not Misc fallback.
    if doc_type in ("Warehouse_Receipt", "Warehouse Receipt"):
        _wr_direction = str(freight_direction or extracted.get("freight_direction") or normalized.get("freight_direction") or "").strip().lower()
        _wr_international = bool(is_international or doc.get("is_international") or extracted.get("is_international") or normalized.get("is_international"))
        routing_details["freight_direction"] = _wr_direction or None
        routing_details["is_international"] = _wr_international
        if _wr_international:
            return ("Warehouse International", "Warehouse receipt (international)", routing_details)
        if _wr_direction == "outbound":
            _wr_subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (f"Warehouse Not International/{_wr_subfolder}", f"Warehouse receipt outbound domestic -> {_wr_subfolder}", routing_details)
        return ("Warehouse Not International", "Warehouse receipt (domestic inbound)", routing_details)

    # RULE 6: Shipping/Freight documents based on direction & international
    if doc_type in ("Shipping_Document", "Freight_Document", "SHIPMENT", "RECEIPT"):
        # Hydrate direction from persisted validation context when callers do not
        # pass freight_direction explicitly. Strong resolved shipment evidence
        # must outrank carrier identity.
        if not freight_direction and doc_type == "Shipping_Document":
            _persisted_routing_details = doc.get("routing_details") or {}
            if not isinstance(_persisted_routing_details, dict):
                _persisted_routing_details = {}

            _shipping_validation = (
                _persisted_routing_details.get("validation_results")
                or doc.get("validation_results")
                or {}
            )
            if not isinstance(_shipping_validation, dict):
                _shipping_validation = {}

            _shipping_normalized = (
                _shipping_validation.get("normalized_fields")
                or doc.get("normalized_fields")
                or {}
            )
            if not isinstance(_shipping_normalized, dict):
                _shipping_normalized = {}

            freight_direction = (
                doc.get("freight_direction")
                or _persisted_routing_details.get("freight_direction")
                or _shipping_normalized.get("freight_direction")
            )
            if freight_direction:
                freight_direction = str(freight_direction).strip().casefold()

        # S9 Workflow: If PO not in BC → Miscellaneous (applies to shipping docs too)
        bc_po_resolved = doc.get("bc_po_resolved")
        if order_number and bc_po_resolved is False and not _po_not_found_is_moot(doc, order_number):
            return (
                "Miscellaneous/Misc Invoices - need approval",
                f"PO {order_number} not found as BC purchase order — shipping doc → Misc (S9)",
                routing_details,
            )

        if is_international or doc.get("is_international"):
            if freight_direction == "outbound":
                path = "Warehouse International"
                return (path, "Outbound international shipment", routing_details)
            if _is_warehouse_order(doc):
                return ("Warehouse International", "International warehouse shipment document", routing_details)
            path = "Dropship International"
            return (path, "International shipment document", routing_details)

        # Domestic
        if freight_direction == "outbound":
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International/{subfolder}",
                f"Outbound domestic → {subfolder}",
                routing_details,
            )

        # A shipping document for a warehouse order (Rotondo inbound
        # receipt for W118811) belongs to the warehouse lane.
        if _is_warehouse_order(doc):
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International/{subfolder}",
                f"Domestic shipping document for a warehouse order → {subfolder}",
                routing_details,
            )

        if freight_direction == "inbound":
            vendor_folder = _get_vendor_subfolder(vendor_name)
            return (
                "Dropship Not International",
                f"Inbound domestic from {vendor_folder}",
                routing_details,
            )

        # Unknown direction — default based on vendor
        vendor_folder = _get_vendor_subfolder(vendor_name)
        if vendor_folder == "Freight":
            return (
                "Dropship Not International/Freight",
                "Freight document (direction unknown; no exception signal)",
                routing_details,
            )
        return (
            "Dropship Not International",
            "Shipping document (domestic default)",
            routing_details,
        )

    # RULE 7: AP Invoices
    if doc_type in ("AP_Invoice", "AP Invoice"):
        # S9 Workflow: If PO is NOT a valid internal BC purchase order → Miscellaneous
        # This check comes FIRST, before vendor-specific routing (mirrors S9)
        bc_po_resolved = doc.get("bc_po_resolved")
        if order_number and bc_po_resolved is False and not _po_not_found_is_moot(doc, order_number):
            return (
                "Miscellaneous/Misc Invoices - need approval",
                f"PO {order_number} not found as internal BC purchase order (S9 workflow)",
                routing_details,
            )

        # International disposition outranks carrier identity.
        if is_international or doc.get("is_international"):
            if _is_warehouse_order(doc):
                path = "Warehouse International"
                return (path, "International warehouse invoice", routing_details)
            path = "Dropship International"
            return (path, "International vendor invoice", routing_details)

        # Domestic warehouse disposition outranks carrier identity.
        if _is_warehouse_order(doc):
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International/{subfolder}",
                f"Domestic warehouse invoice → {subfolder}",
                routing_details,
            )

        # A freight carrier is a business-lane signal, not an exception signal.
        if _is_freight_vendor(vendor_name):
            return (
                "Dropship Not International/Freight",
                "Freight invoice from carrier (normal disposition)",
                routing_details,
            )

        # No Gamer order anywhere (fields, PO list, PDF text) from a vendor
        # that rarely bills against orders (set by route_with_feedback): a
        # non-trade invoice (awards, printing, rent) that staff file under
        # Misc for approval, not a dropship order.
        if (doc.get("_non_trade_vendor") is True
                and not order_number and not _order_numbers_of(doc, {}, doc.get("routing_details") or {})
                and not _text_order_refs(doc) and not _TEXT_GAMER_NUMERIC_ORDER.search(_pdf_text(doc))):
            return (
                "Miscellaneous/Misc Invoices - need approval",
                "No order number on domestic invoice (non-trade, needs approval)",
                routing_details,
            )

        # Regular domestic invoice → Dropship Not International by order
        vendor_folder = _get_vendor_subfolder(vendor_name)
        if order_number:
            return (
                "Dropship Not International",
                f"Domestic vendor invoice ({vendor_folder}) → order {order_number}",
                routing_details,
            )
        return (
            "Dropship Not International",
            f"Domestic vendor invoice ({vendor_folder})",
            routing_details,
        )

    # RULE 8: Sales Orders / Order Confirmations
    if doc_type in ("Sales_Order", "Order_Confirmation", "Sales_Quote"):
        if is_international or doc.get("is_international"):
            if _is_warehouse_order(doc):
                path = "Warehouse International"
                return (path, "International warehouse sales doc", routing_details)
            path = "Dropship International"
            return (path, "International sales document", routing_details)

        if _is_warehouse_order(doc):
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International/{subfolder}",
                f"Domestic warehouse sales doc → {subfolder}",
                routing_details,
            )

        if order_number:
            return (
                "Dropship Not International",
                "Domestic sales document with order",
                routing_details,
            )
        return (
            "Dropship Not International",
            "Domestic sales document",
            routing_details,
        )

    # RULE 9: Remittance / Statement → Remittance Advices
    if doc_type in ("Remittance", "Statement", "Account_Statement", "REMINDER"):
        vendor_folder = _get_vendor_subfolder(vendor_name) if vendor_name else "Unmatched"
        return (
            f"Remittance Advices/{vendor_folder}",
            f"Remittance/statement from {vendor_name or 'unknown vendor'}",
            routing_details,
        )

    # RULE 9b: Inventory Reports → Warehouse Reports
    if doc_type in ("Inventory_Report", "Warehouse"):
        vendor_folder = _get_vendor_subfolder(vendor_name) if vendor_name else "General"
        return (
            f"Warehouse Reports/{vendor_folder}",
            f"Inventory/warehouse report from {vendor_name or 'unknown'}",
            routing_details,
        )

    # RULE 9c: Bill of Lading (standalone, not part of a shipment flow)
    if doc_type in ("Bill_of_Lading", "BOL"):
        if order_number:
            return (
                "Dropship Not International",
                f"Bill of Lading for order {order_number}",
                routing_details,
            )
        return (
            "Miscellaneous/Shipping Documents - Unmatched",
            "Bill of Lading with no order reference",
            routing_details,
        )

    # RULE 10c: Miscellaneous / Unknown
    if doc_type in ("OTHER", "Unknown", "Unknown_Document"):
        if doc.get("approved") or doc.get("status") == "Approved":
            return (
                "Miscellaneous/Misc Invoices - approved",
                "Approved miscellaneous document",
                routing_details,
            )
        return (
            "Miscellaneous/Misc Invoices - need approval",
            "Miscellaneous document needing approval",
            routing_details,
        )

    # RULE 11: DO NOT PAY
    if doc.get("do_not_pay") or doc.get("status") == "DO_NOT_PAY":
        year = datetime.now().year
        return (
            f"DO NOT PAY/{year}",
            "Document marked Do Not Pay",
            routing_details,
        )

    # FALLBACK
    current_year = datetime.now().year
    return (
        f"Miscellaneous/Misc Invoices - need approval",
        f"Default routing for {doc_type}",
        routing_details,
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_canpack_vendor(vendor_name: str) -> bool:
    """Check if the vendor is Canpack (overrides other routing)."""
    return "canpack" in vendor_name.lower()




# Square9's live working folders (Accounts Payable/Temp Folder, read from
# SharePoint 2026-10-01). Learned routing feedback may only point here: older
# rules learned from Square9's archive ("Paid Invoices - by Check Date",
# "Dropship Not International Documents/<PO>", "Miscellaneous Documents/...")
# sent every later invoice from a vendor into a payment archive or one old
# PO's folder.
SQUARE9_WORKING_ROOTS = {
    "do not pay", "dropship international", "dropship not international",
    "meg to process", "miscellaneous", "rhonda - issues",
    "s&h invoices approved", "s&h invoices waiting for approval",
    "tooling invoices", "vendor credit memos",
    "warehouse international", "warehouse not international",
}


_LANE_ROOTS = {"dropship international", "dropship not international",
               "warehouse international", "warehouse not international"}


def _lane_root(path: Optional[str]) -> str:
    p = (path or "").strip("/")
    if p.lower().startswith("temp folder/"):
        p = p[12:]
    return p.split("/")[0].strip().lower()


def _is_working_folder(path: Optional[str]) -> bool:
    p = (path or "").strip("/")
    if p.lower().startswith("temp folder/"):
        p = p[12:]
    return p.split("/")[0].strip().lower() in SQUARE9_WORKING_ROOTS

# Vendors whose credit memos have their own number series and print no
# "credit" wording. Canpack: invoices 1101/1102xxxxxx (787 since 2026-07),
# credits 1111/1112xxxxxx (staff filed 6 of 6 under Vendor Credit Memos).
_CANPACK_CREDIT = re.compile(r"^11[1-2][1-9]\d{6}$")
# CANPUSA is the BC vendor for CanPack US (Olyphant/Muncie); CANPACK the older code.
_VENDOR_CREDIT_SERIES = {"CANPACK": _CANPACK_CREDIT, "CANPUSA": _CANPACK_CREDIT}


def _is_definite_credit(doc: Dict[str, Any], doc_type: str) -> bool:
    """A document that is unambiguously a vendor credit: typed Credit_Memo, or
    a negative total. Staff file these under Vendor Credit Memos whatever the
    vendor, so this outranks vendor-specific rules and learned feedback (found
    2026-10-05: Ball credits of -5,020/-1,905/-1,670 and Canpack credit memos
    went to the vendors' invoice folders). Narrower than _is_credit_memo, whose
    keyword scan also matches remittances and stray "cm" substrings.
    """
    # BC is the truth: a document AP booked as a positive purchase invoice
    # is not a credit (Canpack 1111600287/88: credit series, BC +18,519.01,
    # staff filed under dropship).
    bc_link = doc.get("bc_link") if isinstance(doc.get("bc_link"), dict) else {}
    if bc_link.get("bc_entity") == "purchase_credit_memo":
        return True
    if bc_link.get("bc_amount") is not None and float(bc_link["bc_amount"]) > 0:
        return False
    if doc_type in ("Credit_Memo", "credit_memo"):
        return True
    # (A "credit memo/note" wording trigger was removed 2026-10-05: on 2,077
    # staff filings it was right 0 of 1 times.)
    vendor = str(doc.get("vendor_canonical") or "").upper()
    series = _VENDOR_CREDIT_SERIES.get(vendor)
    if series:
        nf, ef = doc.get("normalized_fields") or {}, doc.get("extracted_fields") or {}
        inv = str(doc.get("invoice_number_clean") or nf.get("invoice_number") or ef.get("invoice_number") or "").strip()
        if series.match(inv):
            return True
    amount = doc.get("amount_float")
    try:
        return amount is not None and float(amount) < 0
    except (TypeError, ValueError):
        return False

def _is_credit_memo(doc_type: str, description: str) -> bool:
    """Check if document is a credit memo."""
    if doc_type in ("Return_Request", "Remittance", "Credit_Memo", "credit_memo"):
        return True
    return any(indicator in description for indicator in CREDIT_MEMO_INDICATORS)


# International vendor indicators — vendor names/patterns that are known international suppliers
INTERNATIONAL_VENDOR_PATTERNS = [
    "s.a. de c.v.", "sa de cv", "s.a.de c.v",  # Mexican companies
    "de mexico", "de méxico",  # Literally "of Mexico"
    "fevisa", "canpack", "envases",
    "gmbh",  # German
    "s.r.l", "srl",  # Italian/Latin American
    "ltd.",  # Could be intl
    "b.v.",  # Dutch
    "s.a.s", "sarl",  # French
    "pty ltd",  # Australian
    "pte ltd",  # Singaporean
    "co., ltd", "co.,ltd",  # Asian
    "kabushiki", "k.k.",  # Japanese
    "a.s.",  # Turkish/Nordic
    "int'l",  # International abbreviation (e.g., MKC CUSTOMS BROKERS INT'L INC.)
    "intl",  # Alternative intl abbreviation
    "customs broker",  # Customs brokers handle international shipments
]

# Short patterns that need word-boundary checks to avoid false positives
# e.g., "ag" matching inside "packaging"
INTERNATIONAL_VENDOR_WORD_PATTERNS = [
    "ag",  # Swiss/German — must be standalone word
]


def _detect_international_vendor(vendor_name: str, extracted: Dict, doc: Dict) -> bool:
    """Auto-detect if vendor/order is international from vendor name patterns."""
    import re
    v = vendor_name.lower()
    # Check substring patterns
    if any(pat in v for pat in INTERNATIONAL_VENDOR_PATTERNS):
        return True
    # Check word-boundary patterns (avoid "ag" matching "packaging")
    for pat in INTERNATIONAL_VENDOR_WORD_PATTERNS:
        if re.search(rf'\b{re.escape(pat)}\b', v):
            return True
    # Check if doc itself has is_international flag
    if doc.get("is_international"):
        return True
    # Check extracted fields
    if (extracted.get("is_international") is True or
            str(extracted.get("is_international", "")).lower() == "true"):
        return True
    return False


def _get_credit_vendor_subfolder(vendor_name: str, description: str) -> Optional[str]:
    """Get credit memo subfolder based on vendor."""
    vl = vendor_name.lower()
    dl = description.lower()

    if "anchor" in vl:
        if _is_dunnage_related(dl):
            return "Anchor Dunnage"
        return None
    if "ball" in vl:
        if _is_dunnage_related(dl):
            return "Ball Dunnage"
        return None
    if "oi" in vl or "owens" in vl or "o-i" in vl:
        if _is_dunnage_related(dl):
            return "OI Dunnage"
        return None
    if "quality" in dl:
        return "Sent to Quality"
    return None


def _get_vendor_subfolder(vendor_name: str) -> str:
    """Get the appropriate subfolder for a vendor."""
    vendor_lower = vendor_name.lower().strip()
    # GPI-SQUARE9-RL-ROUTING-AUTHORITY-V23: normalize R&L carrier aliases at folder-routing authority.
    _rl_vendor_alias = " ".join(str(vendor_name or "").strip().casefold().split())
    if _rl_vendor_alias in ("r & l", "r&l", "r and l", "r+l", "r + l", "r l", "rl"):
        return "Freight"
    for key, folder in VENDOR_FOLDER_MAPPING.items():
        if key in vendor_lower:
            return folder
    return "All Others"


def _get_warehouse_subfolder(vendor_name: str, order_number: str, doc: Dict) -> str:
    """Determine warehouse subfolder based on order type."""
    vendor_lower = vendor_name.lower()
    file_name = (doc.get("file_name") or "").lower()
    desc = ((doc.get("extracted_fields") or {}).get("description") or "").lower()

    if "ball" in vendor_lower:
        return "Ball Orders"
    if "gt" in vendor_lower or "gt's" in file_name or "gt's" in desc:
        return "GT's Orders"
    if "transfer" in file_name or "transfer" in desc:
        return "Transfer Orders"
    if "ups" in vendor_lower or ("ups" in file_name and "ups" not in vendor_lower):
        return "UPS Orders"
    if "kent" in file_name or "kent" in desc:
        return "Assembly Kent"
    if "sort" in file_name or "stack" in file_name or "sort" in desc or "stack" in desc:
        return "Sort and Stack"
    if "assembly" in file_name or "assembly" in desc:
        return "Assembly"
    if "gt" in file_name or "gt" in desc:
        return "GT's"

    return "Assembly"  # Default warehouse subfolder


def _is_freight_vendor(vendor_name: str) -> bool:
    """Check if vendor is a freight carrier."""
    # GPI-SQUARE9-RL-FREIGHT-ALIAS-V20: normalize R&L carrier naming only.
    _rl_vendor_alias = " ".join(str(vendor_name or "").strip().casefold().split())
    if _rl_vendor_alias in ("r & l", "r&l", "r and l", "r+l", "r + l", "r l", "rl"):
        return True
    vendor_lower = vendor_name.lower()
    freight_keywords = [
        "freight", "trucking", "logistics", "transport", "shipping",
        "carrier", "express", "delivery", "ltl", "truckload"
    ]
    for key, folder in VENDOR_FOLDER_MAPPING.items():
        if folder == "Freight" and key in vendor_lower:
            return True
    return any(kw in vendor_lower for kw in freight_keywords)


def _is_warehouse_order_legacy(doc: Dict) -> bool:
    """Check if document is related to a warehouse order."""
    file_name = (doc.get("file_name") or "").lower()
    desc = ((doc.get("extracted_fields") or {}).get("description") or "").lower()
    tags = doc.get("tags", [])

    warehouse_keywords = ["warehouse", "wh_", "wh-", "wh ", "assembly", "storage", "inventory"]
    if any(kw in file_name for kw in warehouse_keywords):
        return True
    # Also check if filename starts with "wh" followed by separator
    if file_name.startswith("wh_") or file_name.startswith("wh-") or file_name.startswith("wh "):
        return True
    if any(kw in desc for kw in warehouse_keywords):
        return True
    if "warehouse" in [t.lower() for t in tags]:
        return True
    return False


def _is_warehouse_order(doc: dict) -> bool:
    if not isinstance(doc, dict):
        return _is_warehouse_order_legacy(doc)

    doc_type = str(
        doc.get("document_type")
        or doc.get("suggested_job_type")
        or doc.get("doc_type")
        or ""
    ).strip().casefold()

    mailbox = str(doc.get("mailbox_category") or "").strip().casefold()

    routing_details = doc.get("routing_details") or {}
    if not isinstance(routing_details, dict):
        routing_details = {}

    validation = (
        routing_details.get("validation_results")
        or doc.get("validation_results")
        or {}
    )
    if not isinstance(validation, dict):
        validation = {}

    normalized = (
        validation.get("normalized_fields")
        or doc.get("normalized_fields")
        or {}
    )
    if not isinstance(normalized, dict):
        normalized = {}

    direction = str(
        normalized.get("freight_direction")
        or doc.get("freight_direction")
        or routing_details.get("freight_direction")
        or ""
    ).strip().casefold()

    is_international = bool(
        normalized.get("is_international")
        or doc.get("is_international")
        or routing_details.get("is_international")
    )

    match_method = str(validation.get("match_method") or "").strip().casefold()

    checks = validation.get("checks") or []
    passed_sales_order_match = any(
        isinstance(check, dict)
        and str(check.get("check_name") or "").strip().casefold() == "sales_order_match"
        and bool(check.get("passed"))
        for check in checks
    )

    strong_outbound_warehouse_evidence = (
        doc_type == "shipping_document"
        and mailbox == "operations"
        and not is_international
        and direction == "outbound"
        and match_method == "sales_order_number"
        and passed_sales_order_match
    )

    if strong_outbound_warehouse_evidence:
        return True

    # Gamer order numbers carry the disposition in their prefix. In staff
    # Square9 filings (2026-09-28..10-05): WA (warehouse/assembly) 11/11 and
    # WR (warehouse receipt) 4/4 filed under Warehouse, plain W purchase
    # orders 50/68 Warehouse, while plain numeric orders were 46/60 Dropship.
    # BC location code on the invoice lines is the lane (AP: "00" = dropship,
    # any other location = warehouse); filled by bc_reconciliation_service
    # once AP enters the invoice. Agreed with staff on 708 of 712 filings.
    bc_lane = (doc.get("bc_link") or {}).get("bc_location_lane") if isinstance(doc.get("bc_link"), dict) else ""
    if bc_lane == "warehouse":
        return True
    if bc_lane == "dropship":
        return False

    # Other documents of the same order that AP entered in BC (their line
    # location codes), excluding this document: majority lane decides.
    votes = doc.get("_order_lane_votes") or {}
    if votes and len(votes) == 1 and not any(_WAREHOUSE_ORDER_PREFIX.match(o)
                                              for o in _order_numbers_of(doc, {}, doc.get("routing_details") or {})):
        return "warehouse" in votes

    # A freight bill delivered to a customer (consignee is neither Gamer nor
    # a warehouse) is dropship freight, whatever the order prefix: staff
    # agreed on 195 of 202 carrier invoices (Tumalo hauling Canpack cans
    # to a customer on a W-order went to Warehouse).
    if not doc.get("_ocean_import") and _consignee_is_customer(doc):
        return False

    # Ocean imports land at a Gamer warehouse (staff: 12 of 15 Warehouse
    # International) unless a Gamer order says otherwise.
    if doc.get("_ocean_import") and not any(_WAREHOUSE_ORDER_PREFIX.match(o) or re.fullmatch(r"1\d{5}", o)
                                            for o in _order_numbers_of(doc, {}, doc.get("routing_details") or {})):
        return True

    # Learned vendor lane profile: freight carriers that bill W-orders but
    # that staff file under Dropship/Freight 90%+ of the time stay dropship.
    lane = _lane_profile(doc)
    if lane and lane["warehouse_share"] <= LANE_PROFILE_MINORITY:
        return False
    if lane and lane["warehouse_share"] >= 1 - LANE_PROFILE_MINORITY:
        return True

    orders = _order_numbers_of(doc, normalized, routing_details)
    numeric = {o for o in orders if re.fullmatch(r"1\d{5}", o)}
    # The same order in both forms ("118078" and "W118078") is a dropship
    # order in staff filings 18 of 22 times: the numeric form wins.
    if any(re.fullmatch(r"W(1\d{5})", o) and o[1:] in numeric for o in orders):
        return _is_warehouse_order_legacy(doc)
    if any(_WAREHOUSE_ORDER_PREFIX.match(o) for o in orders):
        return True
    # Extraction often leaves the Gamer order out of the PO field even when it
    # is printed on the invoice (a reference line, the bill-to block); in the
    # week of 2026-09-28 that hid 10 of 17 warehouse misroutes.
    if _text_order_refs(doc):
        return True

    return _is_warehouse_order_legacy(doc)


_WAREHOUSE_ORDER_PREFIX = re.compile(r"^(?:WA|WR|WTR|W)-?\d{4,}", re.I)


_TEXT_ORDER_REF = re.compile(r"(?<![A-Z0-9])(?:WA|WR|WTR|W)-?\d{4,6}(?![0-9])")
_TEXT_REF_MAX_B64 = 8_000_000


def _text_order_refs(doc: dict) -> list:
    """Gamer warehouse order numbers (W/WA/WR/WTR + digits) printed in the
    first pages of the PDF. Read once per routing call and cached on the
    dict; any failure means no evidence, never an error."""
    if "_text_order_refs" in doc:
        return doc["_text_order_refs"]
    stored = doc.get("gamer_order_refs")
    if isinstance(stored, list):
        refs = stored
    else:
        text = _pdf_text(doc).upper()
        refs = sorted(set(m.replace("-", "") for m in _TEXT_ORDER_REF.findall(text)))
    doc["_text_order_refs"] = refs
    return refs


def _pdf_text(doc: dict) -> str:
    """Text of the first three pages of the stored PDF, cached on the dict;
    empty when unavailable (no bytes, not a PDF, too large, unreadable)."""
    if "_pdf_text" in doc:
        return doc["_pdf_text"]
    text = ""
    b64 = doc.get("file_content_b64")
    name = str(doc.get("file_name") or "").lower()
    if isinstance(b64, str) and b64 and len(b64) <= _TEXT_REF_MAX_B64 and (name.endswith(".pdf") or b64.startswith("JVBER")):
        try:
            import base64
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(base64.b64decode(b64)))
            text = " ".join((pg.extract_text() or "") for pg in reader.pages[:3])
        except Exception:
            text = ""
    doc["_pdf_text"] = text
    return text


_TEXT_CREDIT_DOC = re.compile(r"\bcredit\s+(?:memo|note|invoice)\b", re.I)
_TEXT_GAMER_NUMERIC_ORDER = re.compile(r"(?<![0-9])1[0-2]\d{4}(?![0-9])")
LANE_PROFILE_MIN_FILINGS = 3
LANE_PROFILE_INTL_MINORITY = 0.10
LANE_PROFILE_MINORITY = 0.05


def _lane_profile(doc: dict):
    """The vendor lane profile attached by route_with_feedback (None when the
    vendor has fewer than LANE_PROFILE_MIN_FILINGS lane filings)."""
    prof = doc.get("_vendor_lane_profile")
    if isinstance(prof, dict) and int(prof.get("n") or 0) >= LANE_PROFILE_MIN_FILINGS:
        return prof
    return None


_GAMER_PO_SHAPE = re.compile(r"^(?:1\d{5}|(?:W|WR|WTR)-?1?\d{5}|PR\d{5}|WA\d{4})[A-Z]?$")

_OCEAN_BL = re.compile(
    r"\b(?:EGLV|MEDU|MSCU|MAEU|MAEI|COSU|YMJA|YMLU|OOLU|HLCU|HLXU|CMDU|ONEY|ZIMU|SUDU|HDMU|EVER|APLU|WHLC"
    r"|SMLM|TGHU|TCNU|MRKU|MSKU|CSNU|TEMU|FCIU|SEGU|BEAU|TRHU|GESU|CAIU|DFSU|TLLU|EMCU|EISU|MATS|SEAU|BMOU)"
    r"(?=[A-Z0-9]*(?:\d[A-Z]*){4})[A-Z0-9]{6,14}\b")


def _is_ocean_import(doc: dict) -> bool:
    import json
    for k in ("extracted_fields", "normalized_fields", "po_number_extracted", "po_number_clean"):
        v = doc.get(k)
        if v and _OCEAN_BL.search(json.dumps(v, default=str).upper()):
            return True
    return False


_WH_PARTY = re.compile(r"gamer|warehouse|whse|consign|buske|rotondo|horseshoe|strategic"
                       r"|valley dist|citi.?cargo|yandell|group wa|alpha wh", re.I)


def _consignee_is_customer(doc: dict) -> bool:
    ef = doc.get("extracted_fields") or {}
    con = str(ef.get("consignee") or ef.get("ship_to") or "").strip()
    if not con or _WH_PARTY.search(con):
        return False
    return _is_freight_vendor(str(doc.get("vendor_canonical") or ef.get("vendor") or doc.get("vendor_raw") or ""))


SH_PROFILE_MIN_FILINGS = 3
SH_PROFILE_SHARE = 0.8


def _vendor_files_sh(doc: dict) -> bool:
    """A 3PL warehouse whose invoices staff file under S&H 80%+ of the time
    (Valley Distributing, Citi Cargo allocations; learned from filings)."""
    prof = doc.get("_vendor_lane_profile")
    return (isinstance(prof, dict) and int(prof.get("n_all") or 0) >= SH_PROFILE_MIN_FILINGS
            and float(prof.get("sh_share") or 0) >= SH_PROFILE_SHARE)


def _po_not_found_is_moot(doc: dict, order_number: str) -> bool:
    """"PO not found as an internal BC purchase order" sends an invoice to
    Misc/AP staging. It is no evidence when AP has entered the invoice in BC
    (bc_link from bc_reconciliation_service) or when the "PO" is a label
    with no digit ("MULTI-TRUCKS"): 56 of 2,077 staff filings in 45 days
    were dropship invoices parked this way."""
    if isinstance(doc.get("bc_link"), dict) and doc["bc_link"].get("bc_document_no"):
        return True
    # Only a value shaped like a Gamer PO (1xxxxx, W/WA/WR/WTR/PR + digits)
    # can be "not found" meaningfully; a customer PO (P0028017-40) or a
    # vendor reference (45034416) is no evidence (29 parked filings / 45d).
    return not _GAMER_PO_SHAPE.match(str(order_number or "").strip().upper())


def _order_numbers_of(doc: dict, normalized: dict, routing_details: dict) -> list:
    """Every order/PO value on the document, first PO of any list, uppercased."""
    from services.po_resolution_service import normalize_po
    ef = doc.get("extracted_fields") or {}
    out = []
    # The Gamer order on the BC purchase invoice this document became
    # (bc_reconciliation_service) is ground truth when extraction missed it.
    bc_order = (doc.get("bc_link") or {}).get("bc_order_number") if isinstance(doc.get("bc_link"), dict) else None
    for v in (doc.get("po_number_clean"), doc.get("po_number_extracted"), normalized.get("po_number"),
              ef.get("po_number"), ef.get("order_number"), routing_details.get("order_number"), bc_order):
        n = normalize_po(str(v)) if v and str(v).strip() else ""
        if n and n not in out:
            out.append(n)
    return out


def _order_number_of(doc: dict, normalized: dict, routing_details: dict) -> str:
    found = _order_numbers_of(doc, normalized, routing_details)
    return found[0] if found else ""


def _is_dunnage_related(description: str) -> bool:
    """Check if document is dunnage-related."""
    return any(indicator in description.lower() for indicator in DUNNAGE_INDICATORS)


_TEXT_SH = re.compile(r"storage.{0,40}handling|handling.{0,40}storage|storage (?:charge|fee)s?|pallet storage"
                      r"|handling (?:in|out)\b|in/out handling|inbound handling|outbound handling")
_SH_VENDOR_WORDS = re.compile(r"\b(?:warehous\w*|storage)\b", re.I)


def _is_sh_invoice_evidence(doc: dict, order_number: str) -> bool:
    """Storage & handling evidence beyond the description: S&H wording on the
    PDF (no false positives on 3 weeks of staff filings), or a 3PL warehouse
    vendor (Rotondo Warehouse, Valley Distributing and Storage) billing with
    no order number; with an order it is freight/warehouse work, not S&H."""
    if _TEXT_SH.search(_pdf_text(doc)[:4000].lower()):
        return True
    ef = doc.get("extracted_fields") or {}
    raw = " ".join(str(v) for v in (doc.get("vendor_raw"), ef.get("vendor")) if v)
    return bool(_SH_VENDOR_WORDS.search(raw)) and not order_number and not _text_order_refs(doc)


def _is_storage_handling(description: str) -> bool:
    """Check if document is for storage and handling charges."""
    sh_keywords = ["storage", "handling", "s&h", "warehouse fee", "storage fee", "handling fee"]
    return any(kw in description.lower() for kw in sh_keywords)


# =============================================================================
# FOLDER CREATION HELPER
# =============================================================================

def get_all_folder_paths() -> list:
    """Get all folder paths that should exist in SharePoint."""
    paths = []
    for category, config in FOLDER_STRUCTURE.items():
        base_path = config["path"]
        paths.append(base_path)
        subfolders = config.get("subfolders", {})
        if isinstance(subfolders, dict):
            for subfolder in subfolders.keys():
                paths.append(f"{base_path}/{subfolder}")
        # Dynamic subfolders (by_year, by_order) - just create base
    return paths


def get_folder_structure_summary() -> Dict[str, Any]:
    """Get a summary of the folder structure for display."""
    return {
        "structure": FOLDER_STRUCTURE,
        "vendor_mapping": VENDOR_FOLDER_MAPPING,
        "total_folders": len(get_all_folder_paths()),
    }


_TRADE_HISTORY_MIN_PO_DOCS = 10
_TRADE_CACHE: Dict[str, Tuple[float, bool]] = {}


async def _is_non_trade_vendor(vendor: Any) -> bool:
    """True when the vendor has fewer than 10 Hub documents carrying a PO:
    trade vendors had 28-219 (Rotondo, Berry, Ardagh), the Misc vendors staff
    approve by hand 0-5 (Boyer, Broadway Awards, Contemporary Images)."""
    import time
    key = str(vendor or "").strip()
    if not key:
        return True
    hit = _TRADE_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 3600:
        return hit[1]
    try:
        from deps import get_db
        n = await get_db().hub_documents.count_documents(
            {"vendor_canonical": key, "po_number_clean": {"$nin": [None, ""]}},
            limit=_TRADE_HISTORY_MIN_PO_DOCS, maxTimeMS=3000)
    except Exception:
        return False
    result = n < _TRADE_HISTORY_MIN_PO_DOCS
    if len(_TRADE_CACHE) > 5000:
        _TRADE_CACHE.clear()
    _TRADE_CACHE[key] = (time.monotonic(), result)
    return result


async def _route_with_feedback_core(
    doc: Dict[str, Any],
    is_international: bool = False,
    location_code: Optional[str] = None,
    freight_direction: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Async wrapper that checks the feedback/learning layer BEFORE
    falling through to the rule-based determine_folder_path().
    
    Use this in async contexts (API endpoints, document processing)
    to get the benefit of learned routing corrections.
    """
    from services.routing_feedback_service import lookup_feedback

    doc = dict(doc)
    doc["_non_trade_vendor"] = await _is_non_trade_vendor(doc.get("vendor_canonical"))
    if "_vendor_lane_profile" not in doc and doc.get("vendor_canonical"):
        try:
            from deps import get_db
            prof = await get_db().vendor_lane_profiles.find_one(
                {"vendor": str(doc["vendor_canonical"]).upper()}, {"_id": 0})
            if prof:
                doc["_vendor_lane_profile"] = prof
        except Exception:
            pass
    if (doc.get("batch_parent_id") and "_text_order_refs" not in doc
            and not _order_numbers_of(doc, {}, doc.get("routing_details") or {})
            and not doc.get("gamer_order_refs")):
        # A split piece with no order of its own (an invoice's second page)
        # takes the W-orders of its sibling pieces and parent: Evergreen
        # _doc2 pieces of W-order invoices went to Dropship.
        try:
            from deps import get_db
            refs = set()
            pid = doc["batch_parent_id"]
            async for sib in get_db().hub_documents.find(
                    {"$or": [{"batch_parent_id": pid}, {"id": pid}], "id": {"$ne": doc.get("id")}},
                    {"_id": 0, "po_number_clean": 1, "po_number_extracted": 1, "extracted_fields.po_number": 1,
                     "extracted_fields.order_number": 1, "gamer_order_refs": 1, "bc_link.bc_order_number": 1}).limit(50):
                for o in _order_numbers_of(sib, {}, {}) + list(sib.get("gamer_order_refs") or []):
                    if _WAREHOUSE_ORDER_PREFIX.match(str(o)):
                        refs.add(str(o).upper())
            if refs:
                doc["_text_order_refs"] = sorted(refs)
        except Exception:
            pass
    if "_order_lane_votes" not in doc:
        try:
            from deps import get_db
            orders = _order_numbers_of(doc, {}, doc.get("routing_details") or {})
            votes: Dict[str, int] = {}
            if orders:
                async for ol in get_db().order_lanes.find({"order": {"$in": orders}}, {"_id": 0, "docs": 1}):
                    for did, ln in (ol.get("docs") or {}).items():
                        if did != doc.get("id"):
                            votes[ln] = votes.get(ln, 0) + 1
            doc["_order_lane_votes"] = votes
        except Exception:
            pass
    if "fraud_risk" not in doc:
        try:
            from deps import get_db
            from services.fraud_signal_service import assess_fraud_risk
            doc["fraud_risk"] = await assess_fraud_risk(get_db(), doc)
        except Exception:
            pass

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
    doc_type = _LEGACY_DOC_TYPES.get(doc_type, doc_type)
    vendor_name = (
        doc.get("vendor_canonical") or
        (doc.get("normalized_fields") or {}).get("vendor") or
        (doc.get("extracted_fields") or {}).get("vendor") or
        ""
    )
    extracted = doc.get("extracted_fields") or {}
    po = (
        doc.get("po_number_extracted") or
        extracted.get("po_number") or
        extracted.get("order_number") or
        ""
    ).strip()

    # Check learned feedback (not for definite credits: vendor feedback was
    # learned from invoices and would send a credit to the invoice folder).
    _doc_type_for_credit = doc.get("document_type") or doc.get("suggested_job_type") or ""
    feedback_folder = None if _is_definite_credit(doc, _doc_type_for_credit) else await lookup_feedback(
        vendor=vendor_name,
        doc_type=doc_type,
        has_po=bool(po),
        is_international=is_international,
    )

    if feedback_folder and not _is_working_folder(feedback_folder):
        logger.info("[Routing] ignoring learned folder outside Square9 working folders: %r", feedback_folder)
        feedback_folder = None
    if feedback_folder and _lane_root(feedback_folder) in _LANE_ROOTS and _order_number_of(doc, {}, doc.get("routing_details") or {}):
        # Warehouse vs dropship is a property of the order, not the vendor
        # (Ball ships both ways); with an order number the rules decide it.
        logger.info("[Routing] order number present; ignoring vendor-level lane rule %r", feedback_folder)
        feedback_folder = None
    if feedback_folder and _lane_root(feedback_folder) in _LANE_ROOTS:
        # A learned vendor-level lane loses to BC (this invoice's location
        # code, its order's other invoices) and to the vendor's staff-filing
        # profile when they point the other way (O-I: a feedback rule said
        # Warehouse; staff file O-I 88% dropship).
        fb_wh = str(feedback_folder).strip("/").lower().startswith("warehouse")
        bl = doc.get("bc_link") if isinstance(doc.get("bc_link"), dict) else {}
        votes = doc.get("_order_lane_votes") or {}
        prof = _lane_profile(doc)
        other = None
        if bl.get("bc_location_lane"):
            other = bl["bc_location_lane"] == "warehouse"
        elif votes and len(votes) == 1:
            other = "warehouse" in votes
        elif prof and abs(prof.get("warehouse_share", 0.5) - 0.5) >= 0.25:
            other = prof["warehouse_share"] > 0.5
        if other is not None and other != fb_wh:
            logger.info("[Routing] BC/staff lane evidence contradicts learned lane rule %r; ignoring it", feedback_folder)
            feedback_folder = None

    if feedback_folder:
        normalized_feedback = str(feedback_folder).strip("/").casefold()
        freight_issue_targets = {
            "freight issues",
            "dropship not international/freight/freight issues",
        }
        has_explicit_freight_issue = bool(
            doc.get("needs_logistics_approval")
            or doc.get("has_freight_issue")
            or doc.get("freight_issues")
        )

        # Learned vendor feedback may identify a useful bucket, but it may not
        # manufacture an exception state. Unsupported Freight Issues feedback
        # falls through to the deterministic role/lane rules.
        if normalized_feedback not in freight_issue_targets or has_explicit_freight_issue:
            # Canonicalize legacy learned Freight Issues destinations to the
            # Square9-equivalent nested workflow path when an explicit issue
            # signal independently justifies the exception disposition.
            if normalized_feedback in freight_issue_targets and has_explicit_freight_issue:
                feedback_folder = "Dropship Not International/Freight/Freight Issues"

            routing_details = {
                "doc_type": doc_type,
                "vendor": vendor_name.lower(),
                "order_number": po,
                "is_international": is_international,
                "source": "feedback_loop",
            }
            return (
                feedback_folder,
                f"Learned from feedback (vendor={vendor_name}, type={doc_type})",
                routing_details,
            )

    # Fall through to rule-based routing
    return determine_folder_path(
        doc,
        is_international=is_international,
        location_code=location_code,
        freight_direction=freight_direction,
    )


# ---------------------------------------------------------------------------
# Real Square9 subfolders (learned from staff filings)
# ---------------------------------------------------------------------------
# The rule chain decides the top folder well (93% vs staff) but stopped at
# "Dropship Not International" or used folders that do not exist in
# Square9: the full folder matched staff only ~26% of the time (45 days,
# 2026-10-06). AP folders are part of AP's workflow, so the subfolder is
# filled from where staff file this vendor's documents (vendor_subfolder_
# profiles, top_subfolder_defaults; lane_profile_service). Leave-one-out:
# top + second level 26% -> 75.6%.

_SUBFOLDER_DEFAULTS: Dict[str, Any] = {"at": 0.0, "tops": {}}
_EXCEPTION_SUBFOLDER = re.compile(r"hold|issue|quality|missing|not posted|return", re.I)
_DUNNAGE_TEXT = re.compile(r"dunnage|pallet|tier ?sheet|top ?frame|slip ?sheet|divider|layer pad", re.I)


async def _top_defaults(db) -> Dict[str, Any]:
    import time
    if time.monotonic() - _SUBFOLDER_DEFAULTS["at"] > 600:
        tops = {}
        async for t in db.top_subfolder_defaults.find({}, {"_id": 0}):
            tops[t["top_l"]] = t
        _SUBFOLDER_DEFAULTS.update({"at": time.monotonic(), "tops": tops})
    return _SUBFOLDER_DEFAULTS["tops"]


_PO_TOKEN = re.compile(r"(?<![A-Z0-9-])(W?R?1\d{5}|W1\d{5}|WA\d{4,6})(?![0-9])", re.I)   # not HH-150922A
_ORDER_FOLDER = "<per-order>"


def _is_order_folder(name: str) -> bool:
    """International folders hold one subfolder per order, named by its
    Gamer PO numbers ("115179 115180", "W118530")."""
    toks = [t for t in re.split(r"[\s,&]+", str(name or "").strip()) if t]
    return bool(toks) and all(_PO_TOKEN.fullmatch(t) for t in toks)


def _order_folder_for(doc: dict) -> str:
    """This document's own per-order folder name: its Gamer PO numbers
    (file name, subject, PO field), ascending, space-separated; "" when none."""
    text = " ".join(str(doc.get(k) or "") for k in ("file_name", "email_subject", "po_number_clean", "po_number_raw"))
    nums = sorted({m.upper() for m in _PO_TOKEN.findall(text)}, key=lambda x: (len(x), x))
    return " ".join(nums[:6])


def _pick_subfolder(doc: dict, hub_sub: str, vendor_counts: Dict[str, float], top_counts: Dict[str, float],
                    vendor_n: int = 0) -> Optional[str]:
    if hub_sub and _EXCEPTION_SUBFOLDER.search(hub_sub):
        return None  # a deliberate exception folder (Freight Issues, Sent to Quality) stays
    # Per-order folders learned as if fixed ("115179 115180" suggested for
    # every Hwa Hsia invoice): pool them, and build this document's own.
    def pooled(counts):
        out: Dict[str, float] = {}
        for k, n in (counts or {}).items():
            key = _ORDER_FOLDER if _is_order_folder(k) else k
            out[key] = out.get(key, 0) + n
        return out
    vendor_counts, top_counts = pooled(vendor_counts), pooled(top_counts)
    picked = _pick_subfolder_core(doc, hub_sub, vendor_counts, top_counts, vendor_n)
    if picked == _ORDER_FOLDER or (picked is None and _is_order_folder(hub_sub)):
        return _order_folder_for(doc)
    return picked


def _pick_subfolder_core(doc: dict, hub_sub: str, vendor_counts: Dict[str, float], top_counts: Dict[str, float],
                         vendor_n: int = 0) -> Optional[str]:
    vc = {k: n for k, n in (vendor_counts or {}).items() if n > 0}
    tot = sum(vc.values())
    # Recency-weighted vendor history (2+ filings): its dominant folder.
    # (A dunnage-wording split was tried: it added nothing; the O-I / Anchor
    # split was staff moving folders in mid-September, which recency covers.)
    if tot > 0 and (vendor_n or 2) >= 2:
        s1, n1 = max(vc.items(), key=lambda kv: kv[1])
        if n1 / tot >= 0.6:
            return s1
        # Folder families (first segment): ATS files "Freight", "Freight/Ready
        # to process Purch Inv", "Freight/... current month" - 52% for the
        # top folder alone, 97% for the Freight family. A dominant family wins;
        # within it, its most-used folder.
        fam: Dict[str, float] = {}
        for k, n in vc.items():
            f = k.split("/")[0].strip().lower()
            fam[f] = fam.get(f, 0) + n
        f1, fn = max(fam.items(), key=lambda kv: kv[1])
        if f1 and fn / tot >= 0.6:
            return max(((k, n) for k, n in vc.items() if k.split("/")[0].strip().lower() == f1), key=lambda kv: kv[1])[0]
    real = {k for k, n in (top_counts or {}).items() if n > 0}
    if hub_sub and hub_sub in real:
        return None
    if real:
        # No vendor history: stay in the family the rules chose (a carrier's
        # bill -> the most used Freight folder; anything else -> the most used
        # non-freight folder, e.g. "Drop Ship All Others").
        freight = (hub_sub or "").lower().startswith("freight")
        pool = [(k, n) for k, n in top_counts.items() if n > 0 and k.lower().startswith("freight") == freight]
        if pool:
            return max(pool, key=lambda kv: kv[1])[0]
    return None


_VENDOR_TOP_COUNTS: Dict[str, Any] = {"at": 0.0, "by_top": {}}
DEFAULT_BY_VENDORS = True


async def _vendor_weighted_top_counts(db, top_l: str) -> Dict[str, float]:
    """Subfolder -> number of vendors whose usual folder it is, within a
    top folder. A vendor with no filing history goes where most vendors go
    ("Drop Ship All Others": 52 vendors), not where the most documents go
    (a few heavy dunnage vendors made "Drop Ship Dunnage Vendors" the
    document-count leader; replay 2026-10-08)."""
    import time
    if time.time() - _VENDOR_TOP_COUNTS["at"] > 3600:
        by_top: Dict[str, Dict[str, float]] = {}
        async for p in db.vendor_subfolder_profiles.find({}, {"_id": 0, "counts": 1, "top_l": 1}):
            c = {k: v for k, v in (p.get("counts") or {}).items() if v > 0}
            if c:
                k = max(c.items(), key=lambda kv: kv[1])[0]
                t = by_top.setdefault(p.get("top_l") or "", {})
                t[k] = t.get(k, 0) + 1
        _VENDOR_TOP_COUNTS.update(at=time.time(), by_top=by_top)
    return _VENDOR_TOP_COUNTS["by_top"].get(top_l) or {}


async def route_with_feedback(doc: Dict[str, Any], is_international: bool = False, **kwargs):
    path, reason, details = await _route_with_feedback_core(doc, is_international=is_international, **kwargs)
    try:
        parts = [p for p in (path or "").strip("/").split("/") if p]
        if not parts:
            return path, reason, details
        from deps import get_db
        db = get_db()
        tops = await _top_defaults(db)
        t = tops.get(parts[0].lower())
        if not t:
            return path, reason, details
        vendor = str(doc.get("vendor_canonical") or "").upper()
        prof = await db.vendor_subfolder_profiles.find_one({"vendor": vendor, "top_l": parts[0].lower()}, {"_id": 0, "counts": 1, "n": 1}) if vendor else None
        hub_sub = "/".join(parts[1:])
        top_counts = t.get("counts") or {}
        if DEFAULT_BY_VENDORS:
            top_counts = await _vendor_weighted_top_counts(db, parts[0].lower()) or top_counts
        sub = _pick_subfolder(doc, hub_sub, (prof or {}).get("counts") or {}, top_counts, (prof or {}).get("n") or 0)
        if sub is None or sub == hub_sub:
            return path, reason, details
        new_path = t["top"] + ("/" + sub if sub else "")
        details = dict(details or {})
        details["subfolder_from"] = "vendor_profile" if prof else "folder_default"
        details["rule_path"] = path
        return new_path, reason, details
    except Exception:
        return path, reason, details
