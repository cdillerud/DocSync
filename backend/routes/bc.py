"""
BC company/sales-order lookup proxy endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 7). No logic changed.
"""
import logging
from fastapi import APIRouter, Query

from core.legacy_hub_helpers import get_bc_companies, get_bc_sales_orders

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


@router.get("/bc/companies")
async def list_bc_companies():
    companies = await get_bc_companies()
    return {"companies": companies}


@router.get("/bc/sales-orders")
async def list_bc_sales_orders(search: str = Query(None)):
    try:
        orders = await get_bc_sales_orders(order_no=search)
        return {"orders": orders}
    except Exception as e:
        logger.warning("BC sales orders search failed: %s", str(e))
        return {"orders": [], "warning": str(e)}
