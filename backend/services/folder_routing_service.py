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
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

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
        "path": "DO NOT PAY Documents",
        "description": "Vendor invoices authorized not to pay",
        "subfolders": ["by_year"],
    },
    "DROPSHIP_INTERNATIONAL": {
        "path": "Dropship International Documents",
        "description": "International vendor invoices for drop ship orders",
        "subfolders": ["by_order"],
    },
    "DROPSHIP_DOMESTIC": {
        "path": "Dropship Not International Documents",
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
        "path": "Miscellaneous Documents",
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
        "path": "S&H Invoices Approved Documents",
        "description": "Warehouse S&H invoices ready to process as cost only",
        "subfolders": {
            "Andy to Process": "S&H approved - Andy to process",
            "Ellie to Process": "S&H approved - Ellie to process",
        },
    },
    "SH_WAITING_APPROVAL": {
        "path": "S&H Invoices waiting for approval Documents",
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
        "path": "Warehouse International Documents",
        "description": "International vendor invoices for warehouse orders",
        "subfolders": ["by_order"],
    },
    "WAREHOUSE_DOMESTIC": {
        "path": "Warehouse Not International Documents",
        "description": "Domestic vendor invoices for warehouse orders",
        "subfolders": {
            "Assembly": "Assembly paperwork and invoices",
            "GT's": "GT's inbound paperwork",
            "Sort and Stack": "Sort and Stack inbound/assembly",
            "Assembly Kent": "Assembly Kent inbound paperwork, freight, invoices",
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
# FOLDER ROUTING LOGIC
# =============================================================================

def determine_folder_path(
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
    }

    # RULE -1: LocationCode = MSC → Miscellaneous (matches S9 workflow)
    if location_code and location_code.upper() == "MSC":
        return (
            "Miscellaneous Documents/Misc Invoices - need approval",
            f"LocationCode=MSC → Miscellaneous (vendor={vendor_name})",
            routing_details,
        )

    # Auto-detect international from vendor name if not explicitly set
    if not is_international:
        is_international = _detect_international_vendor(vendor_name, extracted, doc)

    # =================================================================
    # ROUTING RULES (in priority order per accounting document)
    # =================================================================

    # RULE 0: All Canpack documents → Dropship Not International → Canpack
    # This is a high-level directive that overrides other paths for Canpack
    if _is_canpack_vendor(vendor_name):
        if _is_dunnage_related(invoice_description):
            return (
                "Dropship Not International Documents/Canpack/Dunnage return freight",
                "Canpack dunnage return freight",
                routing_details,
            )
        return (
            "Dropship Not International Documents/Canpack",
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
    if doc.get("needs_logistics_approval") or doc.get("has_freight_issue"):
        return ("Freight Issues", "Freight invoice needing logistics approval", routing_details)

    # RULE 5: S&H (Storage & Handling) Invoices
    if doc_type in ("S&H_Invoice", "SH_Invoice") or _is_storage_handling(invoice_description):
        if doc.get("approved") or doc.get("status") == "Approved":
            return (
                "S&H Invoices Approved Documents",
                "Approved S&H invoice",
                routing_details,
            )
        return (
            "S&H Invoices Approved Documents",
            "S&H invoice",
            routing_details,
        )

    # RULE 6: Shipping/Freight documents based on direction & international
    if doc_type in ("Shipping_Document", "Freight_Document", "SHIPMENT", "RECEIPT"):
        if _is_freight_vendor(vendor_name) and doc_type == "Freight_Document":
            return ("Freight Issues", "Freight invoice from carrier", routing_details)

        if is_international or doc.get("is_international"):
            if freight_direction == "outbound":
                path = f"Warehouse International Documents/{order_number}" if order_number else "Warehouse International Documents"
                return (path, "Outbound international shipment", routing_details)
            path = f"Dropship International Documents/{order_number}" if order_number else "Dropship International Documents"
            return (path, "International shipment document", routing_details)

        # Domestic
        if freight_direction == "outbound":
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International Documents/{subfolder}",
                f"Outbound domestic → {subfolder}",
                routing_details,
            )

        if freight_direction == "inbound":
            vendor_folder = _get_vendor_subfolder(vendor_name)
            return (
                f"Dropship Not International Documents/{order_number}" if order_number else f"Dropship Not International Documents",
                f"Inbound domestic from {vendor_folder}",
                routing_details,
            )

        # Unknown direction — default based on vendor
        vendor_folder = _get_vendor_subfolder(vendor_name)
        if vendor_folder == "Freight":
            return ("Freight Issues", "Freight document (direction unknown)", routing_details)
        return (
            f"Dropship Not International Documents/{order_number}" if order_number else "Dropship Not International Documents",
            "Shipping document (domestic default)",
            routing_details,
        )

    # RULE 7: AP Invoices
    if doc_type in ("AP_Invoice", "AP Invoice"):
        # Freight vendors
        if _is_freight_vendor(vendor_name):
            return ("Freight Issues", "Freight invoice from carrier", routing_details)

        # International
        if is_international or doc.get("is_international"):
            if _is_warehouse_order(doc):
                path = f"Warehouse International Documents/{order_number}" if order_number else "Warehouse International Documents"
                return (path, "International warehouse invoice", routing_details)
            path = f"Dropship International Documents/{order_number}" if order_number else "Dropship International Documents"
            return (path, "International vendor invoice", routing_details)

        # Domestic warehouse
        if _is_warehouse_order(doc):
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International Documents/{subfolder}",
                f"Domestic warehouse invoice → {subfolder}",
                routing_details,
            )

        # Regular domestic invoice → Dropship Not International by order
        vendor_folder = _get_vendor_subfolder(vendor_name)
        if order_number:
            return (
                f"Dropship Not International Documents/{order_number}",
                f"Domestic vendor invoice ({vendor_folder}) → order {order_number}",
                routing_details,
            )
        return (
            "Dropship Not International Documents",
            f"Domestic vendor invoice ({vendor_folder})",
            routing_details,
        )

    # RULE 8: Sales Orders / Order Confirmations
    if doc_type in ("Sales_Order", "Order_Confirmation", "Sales_Quote"):
        if is_international or doc.get("is_international"):
            if _is_warehouse_order(doc):
                path = f"Warehouse International Documents/{order_number}" if order_number else "Warehouse International Documents"
                return (path, "International warehouse sales doc", routing_details)
            path = f"Dropship International Documents/{order_number}" if order_number else "Dropship International Documents"
            return (path, "International sales document", routing_details)

        if _is_warehouse_order(doc):
            subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
            return (
                f"Warehouse Not International Documents/{subfolder}",
                f"Domestic warehouse sales doc → {subfolder}",
                routing_details,
            )

        if order_number:
            return (
                f"Dropship Not International Documents/{order_number}",
                "Domestic sales document with order",
                routing_details,
            )
        return (
            "Dropship Not International Documents",
            "Domestic sales document",
            routing_details,
        )

    # RULE 9: Miscellaneous / Unknown
    if doc_type in ("OTHER", "Unknown", "Unknown_Document"):
        if doc.get("approved") or doc.get("status") == "Approved":
            return (
                "Miscellaneous Documents/Misc Invoices - approved",
                "Approved miscellaneous document",
                routing_details,
            )
        return (
            "Miscellaneous Documents/Misc Invoices - need approval",
            "Miscellaneous document needing approval",
            routing_details,
        )

    # RULE 10: DO NOT PAY
    if doc.get("do_not_pay") or doc.get("status") == "DO_NOT_PAY":
        year = datetime.now().year
        return (
            f"DO NOT PAY Documents/{year}",
            "Document marked Do Not Pay",
            routing_details,
        )

    # FALLBACK
    current_year = datetime.now().year
    return (
        f"Miscellaneous Documents/Misc Invoices - need approval",
        f"Default routing for {doc_type}",
        routing_details,
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_canpack_vendor(vendor_name: str) -> bool:
    """Check if the vendor is Canpack (overrides other routing)."""
    return "canpack" in vendor_name.lower()


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
    vendor_lower = vendor_name.lower()
    freight_keywords = [
        "freight", "trucking", "logistics", "transport", "shipping",
        "carrier", "express", "delivery", "ltl", "truckload"
    ]
    for key, folder in VENDOR_FOLDER_MAPPING.items():
        if folder == "Freight" and key in vendor_lower:
            return True
    return any(kw in vendor_lower for kw in freight_keywords)


def _is_warehouse_order(doc: Dict) -> bool:
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


def _is_dunnage_related(description: str) -> bool:
    """Check if document is dunnage-related."""
    return any(indicator in description.lower() for indicator in DUNNAGE_INDICATORS)


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
