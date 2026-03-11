"""
GPI Document Hub — BC Integration Router (Thin Wrapper)

Extracts /bc/* routes from server.py during modular refactor.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/bc", tags=["Business Central"])

# POST /bc/resolve-reference
router.add_api_route("/resolve-reference", server.resolve_bc_reference, methods=["POST"])

# GET /bc/companies
router.add_api_route("/companies", server.list_bc_companies, methods=["GET"])

# GET /bc/sales-orders
router.add_api_route("/sales-orders", server.list_bc_sales_orders, methods=["GET"])
