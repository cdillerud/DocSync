"""GPI Document Hub - SharePoint Admin Router"""

import logging
from fastapi import APIRouter, HTTPException, Body, BackgroundTasks, Form
from deps import get_db
from services.folder_routing_service import (
    determine_folder_path, get_all_folder_paths, get_folder_structure_summary,
    FOLDER_STRUCTURE, VENDOR_FOLDER_MAPPING
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sharepoint", tags=["SharePoint"])


@router.get("/folder-structure")
async def get_sharepoint_folder_structure():
    """
    Get the accounting folder structure configuration.
    Shows how documents will be routed to SharePoint folders.
    """
    return {
        "structure": FOLDER_STRUCTURE,
        "vendor_mapping": VENDOR_FOLDER_MAPPING,
        "all_folders": get_all_folder_paths(),
        "total_folders": len(get_all_folder_paths()),
        "summary": get_folder_structure_summary()
    }


@router.post("/initialize-folders")
async def initialize_sharepoint_folders(background_tasks: BackgroundTasks):
    """
    Initialize all SharePoint folders according to accounting structure.
    Creates folders if they don't exist.
    """
    from server import ensure_sharepoint_folder_exists

    folders = get_all_folder_paths()

    results = {
        "total": len(folders),
        "created": [],
        "existing": [],
        "failed": []
    }

    for folder in folders:
        try:
            success = await ensure_sharepoint_folder_exists(folder)
            if success:
                results["created"].append(folder)
            else:
                results["failed"].append({"folder": folder, "error": "Unknown error"})
        except Exception as e:
            results["failed"].append({"folder": folder, "error": str(e)})

    return {
        "message": f"Initialized {len(results['created'])} folders",
        "results": results
    }


@router.post("/test-routing")
async def test_folder_routing(
    doc_type: str = Form("AP_Invoice"),
    vendor: str = Form(""),
    order_number: str = Form(""),
    freight_direction: str = Form(""),
    is_international: bool = Form(False),
    description: str = Form("")
):
    """Test how a document would be routed to a SharePoint folder."""
    folder = determine_folder_path(
        doc_type=doc_type,
        vendor=vendor,
        order_number=order_number
    )
    return {
        "input": {
            "doc_type": doc_type,
            "vendor": vendor,
            "order_number": order_number,
            "freight_direction": freight_direction,
            "is_international": is_international,
            "description": description
        },
        "routed_folder": folder
    }
