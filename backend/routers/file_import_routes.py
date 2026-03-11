"""
GPI Document Hub — File Import Router (Thin Wrapper)

Extracts /sales/file-import/* routes from server.py during modular refactor.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/sales/file-import", tags=["File Import"])

# POST /sales/file-import/parse
router.add_api_route("/parse", server.parse_sales_file, methods=["POST"])

# POST /sales/file-import/import-orders
router.add_api_route("/import-orders", server.import_sales_orders_from_file, methods=["POST"])

# POST /sales/file-import/import-inventory
router.add_api_route("/import-inventory", server.import_inventory_from_file, methods=["POST"])

# GET /sales/file-import/excel-sheets
router.add_api_route("/excel-sheets", server.get_excel_sheets, methods=["GET"])

# GET /sales/file-import/column-mappings
router.add_api_route("/column-mappings", server.get_column_mappings, methods=["GET"])

# GET /sales/file-import/history
router.add_api_route("/history", server.get_import_history, methods=["GET"])
