"""GPI Document Hub - BC Integration Router (Domain 5)

Extracted from server.py. Business Central company and sales order lookups.
"""

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bc", tags=["Business Central"])


@router.get("/companies")
async def list_bc_companies():
    """List available Business Central companies."""
    from server import get_bc_companies
    companies = await get_bc_companies()
    return {"companies": companies}


@router.get("/sales-orders")
async def list_bc_sales_orders(search: str = Query(None)):
    """Search Business Central sales orders."""
    from server import get_bc_sales_orders
    try:
        orders = await get_bc_sales_orders(order_no=search)
        return {"orders": orders}
    except Exception as e:
        logger.warning("BC sales orders search failed: %s", str(e))
        return {"orders": [], "warning": str(e)}
