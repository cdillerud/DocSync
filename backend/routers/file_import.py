"""GPI Document Hub - File Import Router (Domain 4)

Extracted from server.py. Handles Excel/CSV file import for sales orders and inventory.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query

from deps import get_db
from services.file_ingestion_service import (
    file_ingestion_service, COLUMN_MAPPINGS
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales/file-import", tags=["File Import"])


@router.post("/parse")
async def parse_sales_file(
    file: UploadFile = File(...),
    ingestion_type: str = Form("sales_order"),
    sheet_name: Optional[str] = Form(None)
):
    """
    Parse an Excel/CSV file and return preview data with validation.

    Supported ingestion types:
    - sales_order: Parse customer POs into order headers and lines
    - inventory_position: Parse inventory snapshot data
    - customer_item: Parse customer SKU mappings
    """
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    try:
        result = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type=ingestion_type,
            sheet_name=sheet_name
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error parsing file: %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Error parsing file: {str(e)}")


@router.post("/import-orders")
async def import_sales_orders_from_file(
    file: UploadFile = File(...),
    customer_id: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    dry_run: bool = Form(True)
):
    """
    Import sales orders from an Excel/CSV file.

    Groups order lines by customer_po into order headers and lines.
    Use dry_run=True to preview without saving to database.
    """
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    try:
        parsed = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type="sales_order",
            sheet_name=sheet_name
        )

        if not parsed.success:
            return {
                "success": False,
                "error": parsed.error,
                "validation_errors": parsed.validation_errors,
                "warnings": parsed.warnings
            }

        result = await file_ingestion_service.import_sales_orders(
            parsed_result=parsed,
            customer_id=customer_id,
            source="file_import",
            dry_run=dry_run
        )

        result["file_name"] = file.filename
        result["ingestion_id"] = parsed.ingestion_id
        result["rows_parsed"] = parsed.rows_parsed
        result["rows_valid"] = parsed.rows_valid
        result["rows_invalid"] = parsed.rows_invalid
        result["validation_errors"] = parsed.validation_errors

        return result

    except Exception as e:
        logger.exception("Error importing sales orders from file")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import-inventory")
async def import_inventory_from_file(
    file: UploadFile = File(...),
    customer_id: Optional[str] = Form(None),
    warehouse_id: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    dry_run: bool = Form(True)
):
    """
    Import inventory positions from an Excel/CSV file.

    Use dry_run=True to preview without saving to database.
    """
    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    try:
        parsed = file_ingestion_service.parse_file(
            content=content,
            file_name=file.filename,
            ingestion_type="inventory_position",
            sheet_name=sheet_name
        )

        if not parsed.success:
            return {
                "success": False,
                "error": parsed.error,
                "validation_errors": parsed.validation_errors,
                "warnings": parsed.warnings
            }

        result = await file_ingestion_service.import_inventory_positions(
            parsed_result=parsed,
            customer_id=customer_id,
            warehouse_id=warehouse_id,
            dry_run=dry_run
        )

        result["file_name"] = file.filename
        result["ingestion_id"] = parsed.ingestion_id
        result["rows_parsed"] = parsed.rows_parsed
        result["rows_valid"] = parsed.rows_valid
        result["rows_invalid"] = parsed.rows_invalid
        result["validation_errors"] = parsed.validation_errors

        return result

    except Exception as e:
        logger.exception("Error importing inventory from file")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/excel-sheets")
async def get_excel_sheets(file: UploadFile = File(...)):
    """Get list of sheet names from an Excel file."""
    content = await file.read()

    try:
        sheets = file_ingestion_service.get_excel_sheets(content)
        return {"sheets": sheets, "file_name": file.filename}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/column-mappings")
async def get_column_mappings(ingestion_type: str = Query("sales_order")):
    """Get the expected column mappings for a given ingestion type."""
    if ingestion_type not in COLUMN_MAPPINGS:
        raise HTTPException(status_code=400, detail=f"Unknown ingestion type: {ingestion_type}")

    config = COLUMN_MAPPINGS[ingestion_type]
    return {
        "ingestion_type": ingestion_type,
        "required_columns": config.get("required_columns", []),
        "optional_columns": config.get("optional_columns", []),
        "known_column_aliases": config.get("known_columns", {})
    }


@router.get("/history")
async def get_import_history(
    ingestion_type: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50)
):
    """Get history of file imports."""
    db = get_db()
    query = {}
    if ingestion_type:
        query["ingestion_type"] = ingestion_type
    if customer_id:
        query["customer_id"] = customer_id

    total = await db.file_ingestion_log.count_documents(query)
    history = await db.file_ingestion_log.find(
        query, {"_id": 0}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)

    return {"history": history, "total": total}
