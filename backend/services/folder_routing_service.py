"""
Folder Routing Service - Routes documents to SharePoint folders based on accounting structure.

Mirrors the accounting department's folder structure from "Temp Folder Structure 9.15.25.docx"
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# =============================================================================
# ACCOUNTING FOLDER STRUCTURE CONFIGURATION
# =============================================================================

# Main folder categories matching accounting's structure
FOLDER_STRUCTURE = {
    # DO NOT PAY - Vendor invoices authorized not to pay (organized by year)
    "DO_NOT_PAY": {
        "path": "DO NOT PAY Documents",
        "description": "Vendor invoices and supporting documents for invoices authorized not to pay",
        "subfolders": ["by_year"],  # Dynamic: creates year subfolders
    },
    
    # DROPSHIP INTERNATIONAL - International vendor invoices for drop ship orders
    "DROPSHIP_INTERNATIONAL": {
        "path": "Dropship International Documents",
        "description": "International vendor invoices, freight bills, and shipping docs for drop ship orders",
        "subfolders": ["by_order"],  # Dynamic: creates order number subfolders
    },
    
    # DROPSHIP NOT INTERNATIONAL - Domestic vendor invoices for drop ship orders
    "DROPSHIP_DOMESTIC": {
        "path": "Dropship Not International",
        "description": "Domestic vendor invoices, freight bills, and shipping docs for drop ship orders",
        "subfolders": {
            "Ball": "Ball vendor documents",
            "Canpack": "Canpack vendor documents",
            "Canpack/Dunnage return freight": "Canpack dunnage return freight invoices",
            "All Others": "Other vendor documents",
            "Freight": "Freight invoices",
            "Freight Issues": "Freight invoices needing logistics approval",
            "Ready to process": "Documents ready for processing",
            "Purch Inv": "Invoices with cost verified, ready for purchase invoice",
            "Meg to Process": "Documents for Meg to process",
        }
    },
    
    # MISCELLANEOUS - Office invoices
    "MISCELLANEOUS": {
        "path": "Miscellaneous Documents",
        "description": "Miscellaneous office invoices",
        "subfolders": {
            "Misc Invoices - approved": "Approved miscellaneous invoices",
            "Misc Invoices - need approval": "Miscellaneous invoices needing approval",
            "Rhonda - Issues": "Documents for Rhonda to process",
            "S&H Invoices": "Storage and handling invoices",
        }
    },
    
    # APPROVED DOCUMENTS - Warehouse invoices ready to process
    "APPROVED_WAREHOUSE": {
        "path": "Approved Documents",
        "description": "Warehouse invoices for storage and handling charges ready to be processed",
        "subfolders": {
            "Andy to Process": "Documents for Andy to process",
            "Ellie to Process": "Documents for Ellie to process",
        }
    },
    
    # S&H WAITING APPROVAL - Warehouse invoices needing approval
    "SH_WAITING_APPROVAL": {
        "path": "S&H Invoices waiting for approval Documents",
        "description": "Warehouse invoices for storage and handling charges needing approval",
        "subfolders": {
            "Andy to Process": "Documents for Andy to process",
        }
    },
    
    # MONTH REC & TEMPLATES
    "MONTH_REC_TEMPLATES": {
        "path": "Month Rec & Templates",
        "description": "Monthly reconciliation and templates",
        "subfolders": {}
    },
    
    # TOOLING INVOICES
    "TOOLING": {
        "path": "Tooling Invoices Documents",
        "description": "Invoices for tooling charges",
        "subfolders": {}
    },
    
    # VENDOR CREDIT MEMOS
    "VENDOR_CREDITS": {
        "path": "Vendor Credit Memos Documents",
        "description": "Vendor credits",
        "subfolders": {
            "Anchor": "Anchor vendor credits",
            "Anchor/Dunnage": "Anchor dunnage credits",
            "Ball": "Ball vendor credits",
            "Ball/Dunnage": "Ball dunnage credits",
            "OI": "OI vendor credits",
            "OI/Dunnage": "OI dunnage credits",
            "Processed Credit Memo - Aaron": "Processed credit memos by Aaron",
            "Sent to Quality": "Credits sent to quality",
            "Unclaimed credits posted": "Unclaimed posted credits",
        }
    },
    
    # WAREHOUSE INTERNATIONAL - International vendor invoices for warehouse orders
    "WAREHOUSE_INTERNATIONAL": {
        "path": "Warehouse International Documents",
        "description": "International vendor invoices, freight bills, and inbound paperwork for warehouse orders",
        "subfolders": ["by_order"],  # Dynamic: creates order number subfolders
    },
    
    # WAREHOUSE NOT INTERNATIONAL - Domestic warehouse orders
    "WAREHOUSE_DOMESTIC": {
        "path": "Warehouse Not International Documents",
        "description": "Domestic vendor invoices, freight bills, and paperwork for warehouse orders",
        "subfolders": {
            "Assembly/GT's/Sort and Stack": "GT's Sort and Stack inbound paperwork and assembly invoices",
            "Assembly/Assembly Kent": "Assembly Kent inbound paperwork, freight, invoices",
            "Ball Orders": "Ball inbound/outbound paperwork and freight",
            "GT's Orders": "GT's outbound paperwork from Sort and Stack",
            "Transfer Orders": "Transfer orders outbound paperwork",
            "UPS Orders": "UPS shipped orders outbound paperwork",
        }
    },
}

# =============================================================================
# VENDOR ROUTING RULES
# =============================================================================

# Known vendors and their folder mappings
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
    
    # Freight carriers (common ones)
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
    is_international: bool = False
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Determine the SharePoint folder path for a document based on accounting rules.
    
    Args:
        doc: Document dictionary with extracted fields
        freight_direction: "inbound", "outbound", or None
        is_international: Whether the document is for international shipment
        
    Returns:
        Tuple of (folder_path, routing_reason, routing_details)
    """
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
    extracted = doc.get("extracted_fields", {})
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
    
    # Get document amount for potential routing
    amount = doc.get("amount_float") or extracted.get("amount") or 0
    
    routing_details = {
        "doc_type": doc_type,
        "vendor": vendor_name,
        "order_number": order_number,
        "freight_direction": freight_direction,
        "is_international": is_international,
    }
    
    # =================================================================
    # ROUTING RULES (in priority order)
    # =================================================================
    
    # 1. Credit Memos -> Vendor Credit Memos folder
    if any(indicator in invoice_description for indicator in CREDIT_MEMO_INDICATORS):
        vendor_folder = _get_vendor_subfolder(vendor_name, for_credits=True)
        if _is_dunnage_related(invoice_description):
            folder_path = f"Vendor Credit Memos Documents/{vendor_folder}/Dunnage"
            reason = f"Credit memo with dunnage for {vendor_folder}"
        else:
            folder_path = f"Vendor Credit Memos Documents/{vendor_folder}"
            reason = f"Credit memo for vendor {vendor_folder}"
        return folder_path, reason, routing_details
    
    # 2. Tooling Invoices
    if any(indicator in invoice_description for indicator in TOOLING_INDICATORS):
        folder_path = "Tooling Invoices Documents"
        reason = "Tooling invoice detected"
        return folder_path, reason, routing_details
    
    # 3. Shipping/Warehouse Documents based on freight direction
    if doc_type in ("Shipping_Document", "Warehouse_Document", "SHIPMENT", "RECEIPT", "Freight_Document"):
        
        # Outbound freight -> Warehouse folders
        if freight_direction == "outbound":
            if is_international:
                # International outbound -> Warehouse International by order
                folder_path = f"Warehouse International Documents/{order_number}" if order_number else "Warehouse International Documents"
                reason = "Outbound international shipment"
            else:
                # Domestic outbound -> Warehouse Not International
                subfolder = _get_warehouse_subfolder(vendor_name, order_number, doc)
                folder_path = f"Warehouse Not International Documents/{subfolder}"
                reason = f"Outbound domestic shipment - {subfolder}"
            return folder_path, reason, routing_details
        
        # Inbound freight -> Dropship folders
        elif freight_direction == "inbound":
            if is_international:
                # International inbound -> Dropship International by order
                folder_path = f"Dropship International Documents/{order_number}" if order_number else "Dropship International Documents"
                reason = "Inbound international shipment"
            else:
                # Domestic inbound -> Dropship Not International
                vendor_folder = _get_vendor_subfolder(vendor_name)
                
                # Check for dunnage return freight
                if _is_dunnage_related(invoice_description) and vendor_folder == "Canpack":
                    folder_path = "Dropship Not International/Canpack/Dunnage return freight"
                    reason = "Canpack dunnage return freight"
                else:
                    folder_path = f"Dropship Not International/{vendor_folder}"
                    reason = f"Inbound domestic from {vendor_folder}"
            return folder_path, reason, routing_details
        
        # Unknown freight direction -> default to Freight folder
        else:
            folder_path = "Dropship Not International/Freight"
            reason = "Freight document (direction unknown)"
            return folder_path, reason, routing_details
    
    # 4. AP Invoices - Route based on vendor and type
    if doc_type in ("AP_Invoice", "AP Invoice"):
        vendor_folder = _get_vendor_subfolder(vendor_name)
        
        # Check if it's a freight invoice
        if _is_freight_vendor(vendor_name):
            # Freight invoice - check for issues flag
            if doc.get("needs_logistics_approval") or doc.get("has_freight_issue"):
                folder_path = "Dropship Not International/Freight Issues"
                reason = "Freight invoice needing logistics approval"
            else:
                folder_path = "Dropship Not International/Freight"
                reason = "Freight invoice"
            return folder_path, reason, routing_details
        
        # Check if it's S&H (storage and handling)
        if _is_storage_handling(invoice_description):
            if doc.get("approved") or doc.get("status") == "Approved":
                folder_path = "Approved Documents/Andy to Process"
                reason = "Approved S&H invoice"
            else:
                folder_path = "S&H Invoices waiting for approval Documents/Andy to Process"
                reason = "S&H invoice awaiting approval"
            return folder_path, reason, routing_details
        
        # Regular vendor invoice
        if is_international:
            folder_path = f"Dropship International Documents/{order_number}" if order_number else "Dropship International Documents"
            reason = "International vendor invoice"
        else:
            folder_path = f"Dropship Not International/{vendor_folder}"
            reason = f"Domestic vendor invoice - {vendor_folder}"
        return folder_path, reason, routing_details
    
    # 5. Miscellaneous documents
    if doc_type in ("OTHER", "Unknown", "Unknown_Document", "QUALITY_DOC"):
        if doc.get("approved") or doc.get("status") == "Approved":
            folder_path = "Miscellaneous Documents/Misc Invoices - approved"
            reason = "Approved miscellaneous document"
        else:
            folder_path = "Miscellaneous Documents/Misc Invoices - need approval"
            reason = "Miscellaneous document needing approval"
        return folder_path, reason, routing_details
    
    # 6. Default fallback
    current_year = datetime.now().year
    folder_path = f"Uncategorized/{current_year}"
    reason = f"Default routing for {doc_type}"
    return folder_path, reason, routing_details


def _get_vendor_subfolder(vendor_name: str, for_credits: bool = False) -> str:
    """Get the appropriate subfolder for a vendor."""
    vendor_lower = vendor_name.lower().strip()
    
    for key, folder in VENDOR_FOLDER_MAPPING.items():
        if key in vendor_lower:
            return folder
    
    # For credits, default to a catch-all
    if for_credits:
        return "Other"
    
    return "All Others"


def _get_warehouse_subfolder(vendor_name: str, order_number: str, doc: Dict) -> str:
    """Determine warehouse subfolder based on order type."""
    vendor_lower = vendor_name.lower()
    file_name = (doc.get("file_name") or "").lower()
    
    # Check for specific warehouse operations
    if "ball" in vendor_lower:
        return "Ball Orders"
    
    if "gt" in vendor_lower or "gt's" in file_name:
        return "GT's Orders"
    
    if "transfer" in file_name:
        return "Transfer Orders"
    
    if "ups" in vendor_lower or "ups" in file_name:
        return "UPS Orders"
    
    if "assembly" in file_name or "kent" in file_name:
        return "Assembly/Assembly Kent"
    
    if "sort" in file_name or "stack" in file_name:
        return "Assembly/GT's/Sort and Stack"
    
    # Default
    return "General"


def _is_freight_vendor(vendor_name: str) -> bool:
    """Check if vendor is a freight carrier."""
    vendor_lower = vendor_name.lower()
    freight_keywords = [
        "freight", "trucking", "logistics", "transport", "shipping",
        "carrier", "express", "delivery", "ltl", "truckload"
    ]
    
    # Check against known freight carriers
    for key, folder in VENDOR_FOLDER_MAPPING.items():
        if folder == "Freight" and key in vendor_lower:
            return True
    
    # Check for freight keywords
    return any(kw in vendor_lower for kw in freight_keywords)


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
        elif isinstance(subfolders, list):
            # Dynamic subfolders (by_year, by_order) - just create base
            pass
    
    return paths


def get_folder_structure_summary() -> Dict[str, Any]:
    """Get a summary of the folder structure for display."""
    return {
        "structure": FOLDER_STRUCTURE,
        "vendor_mapping": VENDOR_FOLDER_MAPPING,
        "total_folders": len(get_all_folder_paths()),
    }
