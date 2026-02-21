"""
GPI Document Hub - Sales Inventory & Orders Module (Phase 0)

This module provides:
- Data models for Sales customers, items, inventory, and orders
- API endpoints for viewing sales data
- Seed data for testing

Phase 0 is BC-disconnected. No Business Central calls are made.
BC-related fields (bc_customer_no, bc_sales_order_no) are placeholders.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import uuid

# Create Sales API router
sales_router = APIRouter(prefix="/api/sales", tags=["Sales"])


# ==================== PYDANTIC MODELS ====================

class CustomerBase(BaseModel):
    name: str
    bc_customer_no: Optional[str] = None
    default_warehouse_id: Optional[str] = None
    default_terms: Optional[str] = None
    account_manager: Optional[str] = None


class CustomerResponse(CustomerBase):
    customer_id: str
    created_utc: str
    updated_utc: str


class ItemBase(BaseModel):
    item_no: str
    description: str
    uom_base: str = "EA"
    pack_config: Optional[Dict[str, Any]] = None
    active_flag: bool = True


class ItemResponse(ItemBase):
    item_id: str


class WarehouseBase(BaseModel):
    code: str
    name: str
    location_type: str = "internal"  # internal, third_party, customer


class WarehouseResponse(WarehouseBase):
    warehouse_id: str


class InventoryPositionResponse(BaseModel):
    inventory_id: str
    customer_id: str
    item_id: str
    warehouse_id: str
    snapshot_date: str
    qty_on_hand: float
    qty_allocated: float
    qty_available: float
    qty_on_water: float = 0.0
    qty_on_order: float = 0.0
    # Joined fields for display
    item_no: Optional[str] = None
    item_description: Optional[str] = None
    customer_sku: Optional[str] = None
    warehouse_code: Optional[str] = None


class OpenOrderHeaderResponse(BaseModel):
    order_id: str
    customer_id: str
    bc_sales_order_no: Optional[str] = None
    customer_po_no: str
    order_date: str
    requested_ship_date: Optional[str] = None
    status: str  # planned, in_draft, released, shipped, closed
    source: str  # email, portal, manual, file_import, api
    total_qty: float = 0.0
    line_count: int = 0


class OpenOrderLineResponse(BaseModel):
    order_line_id: str
    order_id: str
    item_id: str
    customer_item_id: Optional[str] = None
    ordered_qty: float
    uom: str
    ship_from_warehouse_id: Optional[str] = None
    requested_ship_date: Optional[str] = None
    promised_ship_date: Optional[str] = None
    line_status: str  # open, allocated, shipped, backordered
    # Joined fields
    item_no: Optional[str] = None
    item_description: Optional[str] = None
    warehouse_code: Optional[str] = None


class DraftCandidateResponse(BaseModel):
    candidate_id: str
    customer_id: str
    source_document_id: Optional[str] = None
    header_confidence: float
    lines_confidence: float
    mapped_customer_po_no: Optional[str] = None
    mapped_lines: List[Dict[str, Any]] = []
    validation_errors: List[str] = []
    ready_for_bc_draft: bool = False
    created_utc: str
    customer_name: Optional[str] = None


class AlertItem(BaseModel):
    alert_type: str  # low_stock, at_risk_order, lost_business
    severity: str  # warning, critical
    message: str
    item_id: Optional[str] = None
    order_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class CustomerDashboardResponse(BaseModel):
    customer_id: str
    customer_name: str
    account_manager: Optional[str]
    # Summary totals
    summary: Dict[str, float]
    # Detailed inventory rows
    inventory_positions: List[InventoryPositionResponse]
    # Open orders summary
    open_orders: List[OpenOrderHeaderResponse]
    # Alerts
    alerts: List[AlertItem]


# ==================== SEED DATA ====================

def generate_seed_data():
    """Generate seed data mimicking real customer spreadsheets."""
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # Customers
    customers = [
        {
            "customer_id": "cust_etbrowne",
            "name": "ET Browne",
            "bc_customer_no": None,  # Placeholder for BC mapping
            "default_warehouse_id": "wh_fastlane",
            "default_terms": "Net 30",
            "account_manager": "Sales Team",
            "created_utc": now,
            "updated_utc": now
        },
        {
            "customer_id": "cust_how",
            "name": "HOW (House of Wines)",
            "bc_customer_no": None,
            "default_warehouse_id": "wh_glassocean",
            "default_terms": "Net 45",
            "account_manager": "Sales Team",
            "created_utc": now,
            "updated_utc": now
        },
        {
            "customer_id": "cust_karlin",
            "name": "Karlin",
            "bc_customer_no": None,
            "default_warehouse_id": "wh_fastlane",
            "default_terms": "Net 30",
            "account_manager": "Sales Team",
            "created_utc": now,
            "updated_utc": now
        },
        {
            "customer_id": "cust_wingnien",
            "name": "Wing Nien",
            "bc_customer_no": None,
            "default_warehouse_id": "wh_wing",
            "default_terms": "Net 30",
            "account_manager": "Sales Team",
            "created_utc": now,
            "updated_utc": now
        }
    ]
    
    # Warehouses
    warehouses = [
        {"warehouse_id": "wh_fastlane", "code": "FASTLANE", "name": "Fastlane Fulfillment", "location_type": "third_party"},
        {"warehouse_id": "wh_glassocean", "code": "GLASSOCEAN", "name": "Glass Ocean Logistics", "location_type": "third_party"},
        {"warehouse_id": "wh_wing", "code": "WING", "name": "Wing Nien Warehouse", "location_type": "customer"},
        {"warehouse_id": "wh_gpi", "code": "GPI", "name": "GPI Main Warehouse", "location_type": "internal"},
        {"warehouse_id": "wh_onwater", "code": "ONWATER", "name": "In Transit (Ocean)", "location_type": "internal"}
    ]
    
    # Items
    items = [
        {"item_id": "item_001", "item_no": "PKG-BTL-8OZ", "description": "8oz Amber Glass Bottle", "uom_base": "EA", "pack_config": {"units_per_case": 24, "cases_per_pallet": 84}, "active_flag": True},
        {"item_id": "item_002", "item_no": "PKG-BTL-16OZ", "description": "16oz Amber Glass Bottle", "uom_base": "EA", "pack_config": {"units_per_case": 12, "cases_per_pallet": 72}, "active_flag": True},
        {"item_id": "item_003", "item_no": "PKG-JAR-4OZ", "description": "4oz Clear Glass Jar", "uom_base": "EA", "pack_config": {"units_per_case": 48, "cases_per_pallet": 96}, "active_flag": True},
        {"item_id": "item_004", "item_no": "PKG-CAP-BLK", "description": "Black Polypropylene Cap 28-400", "uom_base": "EA", "pack_config": {"units_per_case": 1000, "cases_per_pallet": 40}, "active_flag": True},
        {"item_id": "item_005", "item_no": "PKG-LBL-ETB", "description": "ET Browne Label Roll", "uom_base": "ROLL", "pack_config": {"labels_per_roll": 2500}, "active_flag": True},
        {"item_id": "item_006", "item_no": "PKG-BTL-12OZ", "description": "12oz Green Glass Bottle", "uom_base": "EA", "pack_config": {"units_per_case": 12, "cases_per_pallet": 80}, "active_flag": True},
        {"item_id": "item_007", "item_no": "PKG-PUMP-WHT", "description": "White Lotion Pump 28-410", "uom_base": "EA", "pack_config": {"units_per_case": 500, "cases_per_pallet": 48}, "active_flag": True},
        {"item_id": "item_008", "item_no": "PKG-BOX-GIFT", "description": "Gift Box Set", "uom_base": "EA", "pack_config": {"units_per_case": 25, "cases_per_pallet": 60}, "active_flag": True}
    ]
    
    # Customer Items (customer-specific SKU mappings)
    customer_items = [
        # ET Browne items
        {"customer_item_id": "ci_001", "customer_id": "cust_etbrowne", "item_id": "item_001", "customer_sku": "ETB-8OZ-AMB", "customer_description": "Palmer's 8oz Bottle", "min_order_qty": 5000, "lead_time_days": 14},
        {"customer_item_id": "ci_002", "customer_id": "cust_etbrowne", "item_id": "item_002", "customer_sku": "ETB-16OZ-AMB", "customer_description": "Palmer's 16oz Bottle", "min_order_qty": 3000, "lead_time_days": 14},
        {"customer_item_id": "ci_003", "customer_id": "cust_etbrowne", "item_id": "item_004", "customer_sku": "ETB-CAP-BLK", "customer_description": "Palmer's Black Cap", "min_order_qty": 10000, "lead_time_days": 7},
        # Karlin items
        {"customer_item_id": "ci_004", "customer_id": "cust_karlin", "item_id": "item_003", "customer_sku": "KAR-JAR-4", "customer_description": "Karlin 4oz Jar", "min_order_qty": 2000, "lead_time_days": 21},
        {"customer_item_id": "ci_005", "customer_id": "cust_karlin", "item_id": "item_007", "customer_sku": "KAR-PUMP", "customer_description": "Karlin Pump Dispenser", "min_order_qty": 5000, "lead_time_days": 14},
        # HOW items
        {"customer_item_id": "ci_006", "customer_id": "cust_how", "item_id": "item_006", "customer_sku": "HOW-12GRN", "customer_description": "HOW 12oz Green", "min_order_qty": 1000, "lead_time_days": 28},
        # Wing Nien items
        {"customer_item_id": "ci_007", "customer_id": "cust_wingnien", "item_id": "item_008", "customer_sku": "WN-GIFT-SET", "customer_description": "Wing Nien Gift Box", "min_order_qty": 500, "lead_time_days": 30}
    ]
    
    # Inventory Positions
    inventory_positions = [
        # ET Browne inventory at Fastlane
        {"inventory_id": "inv_001", "customer_id": "cust_etbrowne", "item_id": "item_001", "warehouse_id": "wh_fastlane", "snapshot_date": today, "qty_on_hand": 45000, "qty_allocated": 12000, "qty_available": 33000, "qty_on_water": 50000, "qty_on_order": 25000},
        {"inventory_id": "inv_002", "customer_id": "cust_etbrowne", "item_id": "item_002", "warehouse_id": "wh_fastlane", "snapshot_date": today, "qty_on_hand": 18000, "qty_allocated": 8000, "qty_available": 10000, "qty_on_water": 0, "qty_on_order": 15000},
        {"inventory_id": "inv_003", "customer_id": "cust_etbrowne", "item_id": "item_004", "warehouse_id": "wh_fastlane", "snapshot_date": today, "qty_on_hand": 85000, "qty_allocated": 20000, "qty_available": 65000, "qty_on_water": 100000, "qty_on_order": 0},
        # Karlin inventory
        {"inventory_id": "inv_004", "customer_id": "cust_karlin", "item_id": "item_003", "warehouse_id": "wh_fastlane", "snapshot_date": today, "qty_on_hand": 12000, "qty_allocated": 5000, "qty_available": 7000, "qty_on_water": 20000, "qty_on_order": 10000},
        {"inventory_id": "inv_005", "customer_id": "cust_karlin", "item_id": "item_007", "warehouse_id": "wh_fastlane", "snapshot_date": today, "qty_on_hand": 3500, "qty_allocated": 3000, "qty_available": 500, "qty_on_water": 0, "qty_on_order": 8000},
        # HOW inventory at Glass Ocean
        {"inventory_id": "inv_006", "customer_id": "cust_how", "item_id": "item_006", "warehouse_id": "wh_glassocean", "snapshot_date": today, "qty_on_hand": 8000, "qty_allocated": 2000, "qty_available": 6000, "qty_on_water": 15000, "qty_on_order": 5000},
        # Wing Nien inventory
        {"inventory_id": "inv_007", "customer_id": "cust_wingnien", "item_id": "item_008", "warehouse_id": "wh_wing", "snapshot_date": today, "qty_on_hand": 2500, "qty_allocated": 500, "qty_available": 2000, "qty_on_water": 3000, "qty_on_order": 1000}
    ]
    
    # Open Order Headers
    open_orders = [
        # ET Browne orders
        {"order_id": "ord_001", "customer_id": "cust_etbrowne", "bc_sales_order_no": None, "customer_po_no": "ETB-PO-2024-0042", "order_date": "2024-02-10", "requested_ship_date": "2024-03-01", "status": "released", "source": "email"},
        {"order_id": "ord_002", "customer_id": "cust_etbrowne", "bc_sales_order_no": None, "customer_po_no": "ETB-PO-2024-0043", "order_date": "2024-02-15", "requested_ship_date": "2024-03-15", "status": "planned", "source": "email"},
        # Karlin orders
        {"order_id": "ord_003", "customer_id": "cust_karlin", "bc_sales_order_no": None, "customer_po_no": "KAR-2024-112", "order_date": "2024-02-08", "requested_ship_date": "2024-02-28", "status": "released", "source": "portal"},
        {"order_id": "ord_004", "customer_id": "cust_karlin", "bc_sales_order_no": None, "customer_po_no": "KAR-2024-113", "order_date": "2024-02-18", "requested_ship_date": "2024-03-10", "status": "in_draft", "source": "manual"},
        # HOW orders
        {"order_id": "ord_005", "customer_id": "cust_how", "bc_sales_order_no": None, "customer_po_no": "HOW-FEB-001", "order_date": "2024-02-12", "requested_ship_date": "2024-03-20", "status": "planned", "source": "file_import"},
        # Wing Nien orders
        {"order_id": "ord_006", "customer_id": "cust_wingnien", "bc_sales_order_no": None, "customer_po_no": "WN-2024-Q1-005", "order_date": "2024-02-01", "requested_ship_date": "2024-04-01", "status": "released", "source": "email"}
    ]
    
    # Open Order Lines
    order_lines = [
        # ETB-PO-2024-0042 lines
        {"order_line_id": "line_001", "order_id": "ord_001", "item_id": "item_001", "customer_item_id": "ci_001", "ordered_qty": 12000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-03-01", "promised_ship_date": "2024-03-01", "line_status": "allocated"},
        {"order_line_id": "line_002", "order_id": "ord_001", "item_id": "item_004", "customer_item_id": "ci_003", "ordered_qty": 15000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-03-01", "promised_ship_date": "2024-03-01", "line_status": "allocated"},
        # ETB-PO-2024-0043 lines
        {"order_line_id": "line_003", "order_id": "ord_002", "item_id": "item_002", "customer_item_id": "ci_002", "ordered_qty": 8000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-03-15", "promised_ship_date": None, "line_status": "open"},
        # KAR-2024-112 lines
        {"order_line_id": "line_004", "order_id": "ord_003", "item_id": "item_003", "customer_item_id": "ci_004", "ordered_qty": 5000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-02-28", "promised_ship_date": "2024-02-28", "line_status": "allocated"},
        {"order_line_id": "line_005", "order_id": "ord_003", "item_id": "item_007", "customer_item_id": "ci_005", "ordered_qty": 3000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-02-28", "promised_ship_date": "2024-03-05", "line_status": "backordered"},
        # KAR-2024-113 lines
        {"order_line_id": "line_006", "order_id": "ord_004", "item_id": "item_003", "customer_item_id": "ci_004", "ordered_qty": 10000, "uom": "EA", "ship_from_warehouse_id": "wh_fastlane", "requested_ship_date": "2024-03-10", "promised_ship_date": None, "line_status": "open"},
        # HOW-FEB-001 lines
        {"order_line_id": "line_007", "order_id": "ord_005", "item_id": "item_006", "customer_item_id": "ci_006", "ordered_qty": 2000, "uom": "EA", "ship_from_warehouse_id": "wh_glassocean", "requested_ship_date": "2024-03-20", "promised_ship_date": None, "line_status": "open"},
        # WN-2024-Q1-005 lines
        {"order_line_id": "line_008", "order_id": "ord_006", "item_id": "item_008", "customer_item_id": "ci_007", "ordered_qty": 500, "uom": "EA", "ship_from_warehouse_id": "wh_wing", "requested_ship_date": "2024-04-01", "promised_ship_date": "2024-04-01", "line_status": "allocated"}
    ]
    
    # Lost Business Records (Karlin-style tracking)
    lost_business = [
        {"lost_id": "lost_001", "customer_id": "cust_karlin", "item_id": "item_007", "date": "2024-02-05", "qty_lost": 5000, "reason": "no_stock", "comments": "Customer needed pumps urgently, none available"},
        {"lost_id": "lost_002", "customer_id": "cust_karlin", "item_id": "item_003", "date": "2024-01-28", "qty_lost": 2000, "reason": "lead_time", "comments": "Lead time too long for customer timeline"},
        {"lost_id": "lost_003", "customer_id": "cust_etbrowne", "item_id": "item_002", "date": "2024-02-10", "qty_lost": 3000, "reason": "price", "comments": "Competitor offered lower price"}
    ]
    
    # Pricing Tiers
    pricing_tiers = [
        {"pricing_id": "price_001", "customer_id": "cust_etbrowne", "item_id": "item_001", "effective_date": "2024-01-01", "unit_price": 0.42, "currency": "USD", "notes": "Volume tier 1"},
        {"pricing_id": "price_002", "customer_id": "cust_etbrowne", "item_id": "item_002", "effective_date": "2024-01-01", "unit_price": 0.68, "currency": "USD", "notes": "Volume tier 1"},
        {"pricing_id": "price_003", "customer_id": "cust_karlin", "item_id": "item_003", "effective_date": "2024-01-01", "unit_price": 0.35, "currency": "USD", "notes": "Standard"},
        {"pricing_id": "price_004", "customer_id": "cust_karlin", "item_id": "item_007", "effective_date": "2024-01-01", "unit_price": 0.28, "currency": "USD", "notes": "Bulk rate"}
    ]
    
    # Sales Order Draft Candidates (pattern like AP draft_candidate)
    draft_candidates = [
        {
            "candidate_id": "draft_001",
            "customer_id": "cust_etbrowne",
            "source_document_id": None,
            "header_confidence": 0.95,
            "lines_confidence": 0.88,
            "mapped_customer_po_no": "ETB-PO-2024-0044",
            "mapped_lines": [
                {"item_no": "PKG-BTL-8OZ", "qty": 10000, "confidence": 0.92},
                {"item_no": "PKG-CAP-BLK", "qty": 10000, "confidence": 0.85}
            ],
            "validation_errors": [],
            "ready_for_bc_draft": True,
            "created_utc": now
        },
        {
            "candidate_id": "draft_002",
            "customer_id": "cust_karlin",
            "source_document_id": None,
            "header_confidence": 0.78,
            "lines_confidence": 0.65,
            "mapped_customer_po_no": "KAR-2024-???",
            "mapped_lines": [
                {"item_no": "PKG-JAR-4OZ", "qty": 5000, "confidence": 0.72},
                {"item_no": "UNKNOWN", "qty": 2000, "confidence": 0.45}
            ],
            "validation_errors": ["unknown_item", "low_confidence"],
            "ready_for_bc_draft": False,
            "created_utc": now
        }
    ]
    
    return {
        "customers": customers,
        "warehouses": warehouses,
        "items": items,
        "customer_items": customer_items,
        "inventory_positions": inventory_positions,
        "open_orders": open_orders,
        "order_lines": order_lines,
        "lost_business": lost_business,
        "pricing_tiers": pricing_tiers,
        "draft_candidates": draft_candidates
    }


# ==================== API ENDPOINTS ====================

# Database reference will be set by main server
_db = None

def set_db(database):
    """Set the database reference from the main server."""
    global _db
    _db = database


@sales_router.get("/customers", response_model=List[CustomerResponse])
async def get_customers():
    """Get list of all Sales customers."""
    customers = await _db.sales_customers.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    return customers


@sales_router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Get a single customer by ID."""
    customer = await _db.sales_customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@sales_router.get("/customers/{customer_id}/dashboard")
async def get_customer_dashboard(
    customer_id: str,
    warehouse: Optional[str] = Query(None, description="Filter by warehouse_id"),
    days: int = Query(30, description="Days to look back for alerts")
):
    """
    Get comprehensive dashboard data for a customer.
    
    Returns:
    - Summary totals (on_hand, available, open_orders, on_water, on_order)
    - Detailed inventory positions
    - Open orders list
    - Alerts (low stock, at-risk orders, lost business)
    """
    # Get customer
    customer = await _db.sales_customers.find_one({"customer_id": customer_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Build inventory query
    inv_query = {"customer_id": customer_id}
    if warehouse:
        inv_query["warehouse_id"] = warehouse
    
    # Get inventory positions
    inventory_docs = await _db.sales_inventory_positions.find(inv_query, {"_id": 0}).to_list(500)
    
    # Get items and warehouses for joining
    items = {i["item_id"]: i for i in await _db.sales_items.find({}, {"_id": 0}).to_list(500)}
    warehouses = {w["warehouse_id"]: w for w in await _db.sales_warehouses.find({}, {"_id": 0}).to_list(100)}
    customer_items = {ci["item_id"]: ci for ci in await _db.sales_customer_items.find({"customer_id": customer_id}, {"_id": 0}).to_list(500)}
    
    # Enrich inventory positions with item/warehouse data
    inventory_positions = []
    summary = {"on_hand": 0, "allocated": 0, "available": 0, "on_water": 0, "on_order": 0}
    
    for inv in inventory_docs:
        item = items.get(inv["item_id"], {})
        wh = warehouses.get(inv["warehouse_id"], {})
        ci = customer_items.get(inv["item_id"], {})
        
        enriched = {
            **inv,
            "item_no": item.get("item_no"),
            "item_description": item.get("description"),
            "customer_sku": ci.get("customer_sku"),
            "warehouse_code": wh.get("code")
        }
        inventory_positions.append(enriched)
        
        # Accumulate summary
        summary["on_hand"] += inv.get("qty_on_hand", 0)
        summary["allocated"] += inv.get("qty_allocated", 0)
        summary["available"] += inv.get("qty_available", 0)
        summary["on_water"] += inv.get("qty_on_water", 0)
        summary["on_order"] += inv.get("qty_on_order", 0)
    
    # Get open orders
    order_query = {"customer_id": customer_id, "status": {"$nin": ["shipped", "closed"]}}
    order_docs = await _db.sales_open_order_headers.find(order_query, {"_id": 0}).sort("order_date", -1).to_list(100)
    
    # Get order lines for totals
    order_ids = [o["order_id"] for o in order_docs]
    order_lines = await _db.sales_open_order_lines.find({"order_id": {"$in": order_ids}}, {"_id": 0}).to_list(1000)
    
    # Compute totals per order
    order_totals = {}
    for line in order_lines:
        oid = line["order_id"]
        if oid not in order_totals:
            order_totals[oid] = {"total_qty": 0, "line_count": 0}
        order_totals[oid]["total_qty"] += line.get("ordered_qty", 0)
        order_totals[oid]["line_count"] += 1
    
    open_orders = []
    for order in order_docs:
        totals = order_totals.get(order["order_id"], {"total_qty": 0, "line_count": 0})
        open_orders.append({
            **order,
            "total_qty": totals["total_qty"],
            "line_count": totals["line_count"]
        })
    
    # Generate alerts
    alerts = []
    
    # Alert: Low stock (available < 20% of on_hand)
    for inv in inventory_positions:
        on_hand = inv.get("qty_on_hand", 0)
        available = inv.get("qty_available", 0)
        if on_hand > 0 and available < (on_hand * 0.2):
            alerts.append({
                "alert_type": "low_stock",
                "severity": "warning" if available > 0 else "critical",
                "message": f"Low stock: {inv.get('item_no', 'Unknown')} at {inv.get('warehouse_code', 'Unknown')} - {available:,.0f} available",
                "item_id": inv["item_id"],
                "details": {"available": available, "on_hand": on_hand}
            })
    
    # Alert: At-risk orders (backordered lines)
    backordered_lines = [ol for ol in order_lines if ol.get("line_status") == "backordered"]
    for line in backordered_lines:
        item = items.get(line["item_id"], {})
        alerts.append({
            "alert_type": "at_risk_order",
            "severity": "warning",
            "message": f"Backordered: {item.get('item_no', 'Unknown')} qty {line.get('ordered_qty', 0):,.0f}",
            "order_id": line["order_id"],
            "item_id": line["item_id"],
            "details": {"line_id": line["order_line_id"], "qty": line.get("ordered_qty", 0)}
        })
    
    # Alert: Recent lost business
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    lost_count = await _db.sales_lost_business.count_documents({
        "customer_id": customer_id,
        "date": {"$gte": cutoff_date}
    })
    if lost_count > 0:
        alerts.append({
            "alert_type": "lost_business",
            "severity": "warning",
            "message": f"{lost_count} lost business record(s) in last {days} days",
            "details": {"count": lost_count, "days": days}
        })
    
    return {
        "customer_id": customer_id,
        "customer_name": customer.get("name"),
        "account_manager": customer.get("account_manager"),
        "summary": summary,
        "inventory_positions": inventory_positions,
        "open_orders": open_orders,
        "alerts": alerts
    }


@sales_router.get("/customers/{customer_id}/open-orders")
async def get_customer_open_orders(
    customer_id: str,
    status: Optional[str] = Query(None, description="Filter by status")
):
    """
    Get open orders for a customer with line-level detail.
    """
    # Build query
    query = {"customer_id": customer_id}
    if status:
        query["status"] = status
    else:
        query["status"] = {"$nin": ["shipped", "closed"]}
    
    orders = await _db.sales_open_order_headers.find(query, {"_id": 0}).sort("order_date", -1).to_list(100)
    
    if not orders:
        return []
    
    # Get all lines for these orders
    order_ids = [o["order_id"] for o in orders]
    lines = await _db.sales_open_order_lines.find({"order_id": {"$in": order_ids}}, {"_id": 0}).to_list(1000)
    
    # Get items and warehouses for joining
    items = {i["item_id"]: i for i in await _db.sales_items.find({}, {"_id": 0}).to_list(500)}
    warehouses = {w["warehouse_id"]: w for w in await _db.sales_warehouses.find({}, {"_id": 0}).to_list(100)}
    
    # Group lines by order
    lines_by_order = {}
    for line in lines:
        oid = line["order_id"]
        if oid not in lines_by_order:
            lines_by_order[oid] = []
        
        item = items.get(line["item_id"], {})
        wh = warehouses.get(line.get("ship_from_warehouse_id"), {})
        
        enriched_line = {
            **line,
            "item_no": item.get("item_no"),
            "item_description": item.get("description"),
            "warehouse_code": wh.get("code")
        }
        lines_by_order[oid].append(enriched_line)
    
    # Attach lines to orders
    result = []
    for order in orders:
        order_with_lines = {
            **order,
            "lines": lines_by_order.get(order["order_id"], []),
            "total_qty": sum(ol.get("ordered_qty", 0) for ol in lines_by_order.get(order["order_id"], [])),
            "line_count": len(lines_by_order.get(order["order_id"], []))
        }
        result.append(order_with_lines)
    
    return result


@sales_router.get("/order-drafts")
async def get_order_drafts(
    customer_id: Optional[str] = Query(None),
    ready_only: bool = Query(False, description="Only return ready_for_bc_draft=true"),
    limit: int = Query(50)
):
    """
    Get sales order draft candidates.
    
    These are extracted/parsed orders not yet pushed to BC.
    """
    query = {}
    if customer_id:
        query["customer_id"] = customer_id
    if ready_only:
        query["ready_for_bc_draft"] = True
    
    drafts = await _db.sales_order_draft_candidates.find(query, {"_id": 0}).sort("created_utc", -1).to_list(limit)
    
    # Get customer names for display
    customer_ids = list(set(d.get("customer_id") for d in drafts if d.get("customer_id")))
    customers = {c["customer_id"]: c for c in await _db.sales_customers.find({"customer_id": {"$in": customer_ids}}, {"_id": 0}).to_list(100)}
    
    # Enrich with customer names
    for draft in drafts:
        cust = customers.get(draft.get("customer_id"), {})
        draft["customer_name"] = cust.get("name")
    
    return drafts


@sales_router.get("/order-drafts/{candidate_id}")
async def get_order_draft_detail(candidate_id: str):
    """Get detailed view of a single draft candidate."""
    draft = await _db.sales_order_draft_candidates.find_one({"candidate_id": candidate_id}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft candidate not found")
    
    # Get customer info
    customer = await _db.sales_customers.find_one({"customer_id": draft.get("customer_id")}, {"_id": 0})
    draft["customer_name"] = customer.get("name") if customer else None
    
    return draft


@sales_router.get("/warehouses")
async def get_warehouses():
    """Get list of all warehouses."""
    warehouses = await _db.sales_warehouses.find({}, {"_id": 0}).sort("code", 1).to_list(100)
    return warehouses


@sales_router.get("/items")
async def get_items(active_only: bool = Query(True)):
    """Get list of all items."""
    query = {"active_flag": True} if active_only else {}
    items = await _db.sales_items.find(query, {"_id": 0}).sort("item_no", 1).to_list(1000)
    return items


@sales_router.post("/seed-data")
async def seed_sales_data():
    """
    Initialize seed data for testing.
    
    WARNING: This will clear and recreate all sales_* collections.
    For development/testing only.
    """
    seed = generate_seed_data()
    
    # Clear existing data
    await _db.sales_customers.delete_many({})
    await _db.sales_items.delete_many({})
    await _db.sales_customer_items.delete_many({})
    await _db.sales_warehouses.delete_many({})
    await _db.sales_inventory_positions.delete_many({})
    await _db.sales_open_order_headers.delete_many({})
    await _db.sales_open_order_lines.delete_many({})
    await _db.sales_lost_business.delete_many({})
    await _db.sales_pricing_tiers.delete_many({})
    await _db.sales_order_draft_candidates.delete_many({})
    
    # Insert seed data
    if seed["customers"]:
        await _db.sales_customers.insert_many(seed["customers"])
    if seed["items"]:
        await _db.sales_items.insert_many(seed["items"])
    if seed["customer_items"]:
        await _db.sales_customer_items.insert_many(seed["customer_items"])
    if seed["warehouses"]:
        await _db.sales_warehouses.insert_many(seed["warehouses"])
    if seed["inventory_positions"]:
        await _db.sales_inventory_positions.insert_many(seed["inventory_positions"])
    if seed["open_orders"]:
        await _db.sales_open_order_headers.insert_many(seed["open_orders"])
    if seed["order_lines"]:
        await _db.sales_open_order_lines.insert_many(seed["order_lines"])
    if seed["lost_business"]:
        await _db.sales_lost_business.insert_many(seed["lost_business"])
    if seed["pricing_tiers"]:
        await _db.sales_pricing_tiers.insert_many(seed["pricing_tiers"])
    if seed["draft_candidates"]:
        await _db.sales_order_draft_candidates.insert_many(seed["draft_candidates"])
    
    return {
        "status": "success",
        "seeded": {
            "customers": len(seed["customers"]),
            "items": len(seed["items"]),
            "customer_items": len(seed["customer_items"]),
            "warehouses": len(seed["warehouses"]),
            "inventory_positions": len(seed["inventory_positions"]),
            "open_orders": len(seed["open_orders"]),
            "order_lines": len(seed["order_lines"]),
            "lost_business": len(seed["lost_business"]),
            "pricing_tiers": len(seed["pricing_tiers"]),
            "draft_candidates": len(seed["draft_candidates"])
        }
    }


async def initialize_sales_indexes(database):
    """Create indexes for sales collections."""
    db = database
    
    # Customers
    await db.sales_customers.create_index("customer_id", unique=True)
    await db.sales_customers.create_index("name")
    await db.sales_customers.create_index("bc_customer_no")
    
    # Items
    await db.sales_items.create_index("item_id", unique=True)
    await db.sales_items.create_index("item_no")
    await db.sales_items.create_index("active_flag")
    
    # Customer Items
    await db.sales_customer_items.create_index("customer_item_id", unique=True)
    await db.sales_customer_items.create_index("customer_id")
    await db.sales_customer_items.create_index("item_id")
    await db.sales_customer_items.create_index([("customer_id", 1), ("item_id", 1)])
    
    # Warehouses
    await db.sales_warehouses.create_index("warehouse_id", unique=True)
    await db.sales_warehouses.create_index("code", unique=True)
    
    # Inventory Positions
    await db.sales_inventory_positions.create_index("inventory_id", unique=True)
    await db.sales_inventory_positions.create_index("customer_id")
    await db.sales_inventory_positions.create_index("item_id")
    await db.sales_inventory_positions.create_index("warehouse_id")
    await db.sales_inventory_positions.create_index([("customer_id", 1), ("item_id", 1), ("warehouse_id", 1)])
    
    # Open Order Headers
    await db.sales_open_order_headers.create_index("order_id", unique=True)
    await db.sales_open_order_headers.create_index("customer_id")
    await db.sales_open_order_headers.create_index("status")
    await db.sales_open_order_headers.create_index("customer_po_no")
    
    # Open Order Lines
    await db.sales_open_order_lines.create_index("order_line_id", unique=True)
    await db.sales_open_order_lines.create_index("order_id")
    await db.sales_open_order_lines.create_index("item_id")
    
    # Lost Business
    await db.sales_lost_business.create_index("lost_id", unique=True)
    await db.sales_lost_business.create_index("customer_id")
    await db.sales_lost_business.create_index("date")
    
    # Pricing Tiers
    await db.sales_pricing_tiers.create_index("pricing_id", unique=True)
    await db.sales_pricing_tiers.create_index([("customer_id", 1), ("item_id", 1)])
    
    # Draft Candidates
    await db.sales_order_draft_candidates.create_index("candidate_id", unique=True)
    await db.sales_order_draft_candidates.create_index("customer_id")
    await db.sales_order_draft_candidates.create_index("ready_for_bc_draft")
    
    # Sales Documents (ingested from email)
    await db.sales_documents.create_index("document_id", unique=True)
    await db.sales_documents.create_index("document_type")
    await db.sales_documents.create_index("status")
    await db.sales_documents.create_index("created_utc")
    await db.sales_documents.create_index("customer_id")
    await db.sales_documents.create_index("email_sender")
    
    # Sales Mail Intake Log (idempotency)
    await db.sales_mail_intake_log.create_index("internet_message_id")
    await db.sales_mail_intake_log.create_index("attachment_hash")
    await db.sales_mail_intake_log.create_index([("internet_message_id", 1), ("attachment_hash", 1)])
    
    # Sales Mail Poll Runs
    await db.sales_mail_poll_runs.create_index("started_at")


# ==================== SALES DOCUMENT TYPES ====================

SALES_DOCUMENT_TYPES = {
    # Core order documents
    "Sales_Order": {
        "description": "Customer purchase order or sales order",
        "keywords": ["purchase order", "po", "order", "buy", "quantity", "ship to", "bill to"],
        "priority": "high",
        "action": "create_order_candidate"
    },
    "Sales_Quote": {
        "description": "Price quote or proposal to customer",
        "keywords": ["quote", "quotation", "proposal", "estimate", "pricing", "valid until"],
        "priority": "medium",
        "action": "log_only"
    },
    "Order_Confirmation": {
        "description": "Confirmation of order received/accepted",
        "keywords": ["confirmation", "confirmed", "order acknowledgment", "acknowledge"],
        "priority": "medium",
        "action": "link_to_order"
    },
    "Order_Change": {
        "description": "Request to modify existing order",
        "keywords": ["change order", "revision", "amendment", "modify", "cancel line", "add line"],
        "priority": "high",
        "action": "flag_for_review"
    },
    
    # Shipping & logistics
    "Shipping_Request": {
        "description": "Request for shipment or delivery",
        "keywords": ["ship", "shipping", "delivery", "dispatch", "release", "pick up"],
        "priority": "high",
        "action": "flag_for_review"
    },
    "Shipping_Schedule": {
        "description": "Scheduled shipment or delivery date",
        "keywords": ["schedule", "eta", "arrival", "vessel", "container", "tracking"],
        "priority": "medium",
        "action": "log_only"
    },
    "Bill_of_Lading": {
        "description": "Bill of lading or shipping document",
        "keywords": ["bill of lading", "bol", "b/l", "consignment", "freight"],
        "priority": "medium",
        "action": "log_only"
    },
    "Packing_List": {
        "description": "Packing list or shipment contents",
        "keywords": ["packing list", "pack list", "contents", "cartons", "pallets"],
        "priority": "low",
        "action": "log_only"
    },
    
    # Commercial documents
    "Price_Inquiry": {
        "description": "Customer asking about pricing",
        "keywords": ["price", "pricing", "cost", "rate", "discount", "how much"],
        "priority": "medium",
        "action": "log_only"
    },
    "Price_List": {
        "description": "Price list or catalog",
        "keywords": ["price list", "catalog", "catalogue", "pricing sheet"],
        "priority": "low",
        "action": "log_only"
    },
    
    # Inventory related
    "Inventory_Report": {
        "description": "Inventory status or report",
        "keywords": ["inventory", "stock", "on hand", "available", "warehouse"],
        "priority": "medium",
        "action": "log_only"
    },
    "Forecast": {
        "description": "Sales or demand forecast",
        "keywords": ["forecast", "projection", "demand", "planning", "outlook"],
        "priority": "medium",
        "action": "log_only"
    },
    
    # Quality & returns
    "Quality_Issue": {
        "description": "Quality complaint or issue report",
        "keywords": ["quality", "defect", "damage", "complaint", "issue", "problem"],
        "priority": "high",
        "action": "flag_for_review"
    },
    "Return_Request": {
        "description": "Request to return goods",
        "keywords": ["return", "rma", "credit", "refund", "send back"],
        "priority": "high",
        "action": "flag_for_review"
    },
    
    # General
    "Customer_Inquiry": {
        "description": "General customer question or inquiry",
        "keywords": ["question", "inquiry", "asking", "wondering", "information"],
        "priority": "low",
        "action": "log_only"
    },
    "Meeting_Notes": {
        "description": "Notes from customer meeting or call",
        "keywords": ["meeting", "call", "discussion", "notes", "recap"],
        "priority": "low",
        "action": "log_only"
    },
    "Contract": {
        "description": "Contract or agreement document",
        "keywords": ["contract", "agreement", "terms", "conditions", "signed"],
        "priority": "medium",
        "action": "log_only"
    },
    "Unknown_Sales": {
        "description": "Unclassified sales-related document",
        "keywords": [],
        "priority": "low",
        "action": "log_only"
    }
}


# ==================== SALES EMAIL POLLING ====================

# Configuration (will be set from environment)
_sales_email_config = {
    "enabled": False,
    "mailbox": "",
    "interval_minutes": 5,
    "lookback_minutes": 60,
    "max_messages": 25,
    "max_attachment_size_mb": 25
}

_sales_polling_task = None


def configure_sales_email_polling(
    enabled: bool,
    mailbox: str,
    interval_minutes: int = 5,
    lookback_minutes: int = 60
):
    """Configure sales email polling settings."""
    global _sales_email_config
    _sales_email_config["enabled"] = enabled
    _sales_email_config["mailbox"] = mailbox
    _sales_email_config["interval_minutes"] = interval_minutes
    _sales_email_config["lookback_minutes"] = lookback_minutes


async def classify_sales_document_with_ai(file_path: str, filename: str, email_subject: str = "", email_body: str = "") -> Dict[str, Any]:
    """
    Classify a sales document using AI.
    
    Returns:
    - document_type: One of SALES_DOCUMENT_TYPES keys
    - confidence: 0.0 to 1.0
    - extracted_fields: Dict of extracted data
    - reasoning: Why this classification was chosen
    """
    import os
    import base64
    
    # Check for Emergent LLM key
    llm_key = os.environ.get("EMERGENT_LLM_KEY")
    if not llm_key:
        # Fallback to keyword-based classification
        return _keyword_classify_sales_document(filename, email_subject, email_body)
    
    try:
        from emergentintegrations.llm.gemini import GeminiChat
        
        # Read file content for context
        file_context = ""
        if file_path and os.path.exists(file_path):
            try:
                # For PDFs, we'd need OCR - for now just use filename + email context
                with open(file_path, 'rb') as f:
                    content = f.read()
                    if len(content) < 1000:  # Small text file
                        try:
                            file_context = content.decode('utf-8')[:2000]
                        except:
                            pass
            except:
                pass
        
        # Build classification prompt
        doc_types_list = "\n".join([
            f"- {dtype}: {info['description']}"
            for dtype, info in SALES_DOCUMENT_TYPES.items()
        ])
        
        prompt = f"""You are a document classifier for a packaging company's Sales department.

Classify this document into ONE of the following types:

{doc_types_list}

Document Information:
- Filename: {filename}
- Email Subject: {email_subject}
- Email Preview: {email_body[:500] if email_body else 'N/A'}

Additionally, extract any relevant fields you can identify:
- customer_name: The customer or company name
- customer_po_no: Customer's PO number if present
- order_date: Date of order/request
- requested_ship_date: When they want it shipped
- items: List of items/SKUs mentioned (if any)
- quantities: Quantities mentioned (if any)
- ship_to_address: Shipping destination
- contact_person: Contact name
- contact_email: Contact email
- urgency: urgent, normal, or low

Respond in this exact JSON format:
{{
    "document_type": "TYPE_FROM_LIST",
    "confidence": 0.85,
    "reasoning": "Brief explanation of why this classification",
    "extracted_fields": {{
        "customer_name": "...",
        "customer_po_no": "...",
        ...
    }}
}}
"""
        
        chat = GeminiChat(emergent_api_key=llm_key)
        response = await chat.send_message_async(prompt=prompt, model="gemini-2.5-flash")
        
        # Parse response
        import json
        import re
        
        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
            # Validate document type
            if result.get("document_type") not in SALES_DOCUMENT_TYPES:
                result["document_type"] = "Unknown_Sales"
            return result
        else:
            return _keyword_classify_sales_document(filename, email_subject, email_body)
            
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI classification failed: {e}")
        return _keyword_classify_sales_document(filename, email_subject, email_body)


def _keyword_classify_sales_document(filename: str, email_subject: str = "", email_body: str = "") -> Dict[str, Any]:
    """Fallback keyword-based classification for sales documents."""
    combined_text = f"{filename} {email_subject} {email_body}".lower()
    
    best_match = "Unknown_Sales"
    best_score = 0
    
    for doc_type, info in SALES_DOCUMENT_TYPES.items():
        if doc_type == "Unknown_Sales":
            continue
        score = sum(1 for kw in info["keywords"] if kw.lower() in combined_text)
        if score > best_score:
            best_score = score
            best_match = doc_type
    
    confidence = min(0.5 + (best_score * 0.1), 0.85) if best_score > 0 else 0.3
    
    return {
        "document_type": best_match,
        "confidence": confidence,
        "reasoning": f"Keyword match (score: {best_score})",
        "extracted_fields": {}
    }


async def ingest_sales_document(
    file_content: bytes,
    filename: str,
    source: str = "email",
    email_sender: str = None,
    email_subject: str = None,
    email_body: str = None,
    email_message_id: str = None,
    correlation_id: str = None
) -> Dict[str, Any]:
    """
    Ingest a sales document into the Hub.
    
    This is the main entry point for sales document ingestion.
    All documents land in NeedsReview status (shadow mode).
    """
    import hashlib
    import os
    from pathlib import Path
    
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Save file temporarily for classification
    upload_dir = Path("/app/uploads/sales")
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / doc_id
    
    with open(file_path, 'wb') as f:
        f.write(file_content)
    
    # Classify document with AI
    classification = await classify_sales_document_with_ai(
        str(file_path), 
        filename, 
        email_subject or "", 
        email_body or ""
    )
    
    doc_type = classification.get("document_type", "Unknown_Sales")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    reasoning = classification.get("reasoning", "")
    
    # Get document type config
    type_config = SALES_DOCUMENT_TYPES.get(doc_type, SALES_DOCUMENT_TYPES["Unknown_Sales"])
    
    # Try to match to a customer
    customer_id = None
    customer_name = extracted_fields.get("customer_name")
    if customer_name:
        # Try to find matching customer
        customer = await _db.sales_customers.find_one(
            {"name": {"$regex": customer_name, "$options": "i"}},
            {"customer_id": 1, "_id": 0}
        )
        if customer:
            customer_id = customer["customer_id"]
    
    # Determine action based on document type
    action = type_config.get("action", "log_only")
    priority = type_config.get("priority", "low")
    
    # All documents start as NeedsReview in shadow mode
    status = "NeedsReview"
    
    # Build document record
    document = {
        "document_id": doc_id,
        "file_name": filename,
        "file_size": len(file_content),
        "file_hash": hashlib.sha256(file_content).hexdigest(),
        "source": source,
        "document_type": doc_type,
        "ai_confidence": confidence,
        "classification_reasoning": reasoning,
        "extracted_fields": extracted_fields,
        "type_config": {
            "priority": priority,
            "action": action,
            "description": type_config.get("description", "")
        },
        "customer_id": customer_id,
        "customer_name_extracted": customer_name,
        "email_sender": email_sender,
        "email_subject": email_subject,
        "email_message_id": email_message_id,
        "status": status,
        "workflow_state": "Classified",
        "validation_errors": [],
        "validation_warnings": [],
        "created_utc": now,
        "updated_utc": now,
        "correlation_id": correlation_id or str(uuid.uuid4())
    }
    
    # Insert into database
    await _db.sales_documents.insert_one(document)
    
    # Clean up temp file
    try:
        os.remove(file_path)
    except:
        pass
    
    return {
        "document_id": doc_id,
        "document_type": doc_type,
        "confidence": confidence,
        "status": status,
        "customer_id": customer_id,
        "priority": priority,
        "action": action
    }


async def check_sales_duplicate(internet_message_id: str, attachment_hash: str) -> bool:
    """Check if this attachment was already processed."""
    existing = await _db.sales_mail_intake_log.find_one({
        "internet_message_id": internet_message_id,
        "attachment_hash": attachment_hash,
        "status": {"$in": ["Ingested", "SkippedInline"]}
    })
    return existing is not None


async def record_sales_mail_log(
    message_id: str,
    internet_message_id: str,
    attachment_id: str,
    attachment_hash: str,
    filename: str,
    status: str,
    document_id: str = None,
    error: str = None
):
    """Record mail intake processing result."""
    await _db.sales_mail_intake_log.insert_one({
        "log_id": str(uuid.uuid4()),
        "message_id": message_id,
        "internet_message_id": internet_message_id,
        "attachment_id": attachment_id,
        "attachment_hash": attachment_hash,
        "filename": filename,
        "status": status,
        "document_id": document_id,
        "error": error,
        "processed_at": datetime.now(timezone.utc).isoformat()
    })


# ==================== SALES EMAIL POLLING ENDPOINTS ====================

@sales_router.get("/email-polling/status")
async def get_sales_email_polling_status():
    """Get current sales email polling configuration and stats."""
    # Get last 24h stats
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    runs = await _db.sales_mail_poll_runs.find(
        {"started_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("started_at", -1).to_list(100)
    
    total_detected = sum(r.get("messages_detected", 0) for r in runs)
    total_ingested = sum(r.get("attachments_ingested", 0) for r in runs)
    total_skipped = sum(r.get("attachments_skipped_dup", 0) + r.get("attachments_skipped_inline", 0) for r in runs)
    
    return {
        "config": {
            "enabled": _sales_email_config["enabled"],
            "mailbox": _sales_email_config["mailbox"],
            "interval_minutes": _sales_email_config["interval_minutes"],
            "lookback_minutes": _sales_email_config["lookback_minutes"]
        },
        "stats_24h": {
            "poll_runs": len(runs),
            "messages_detected": total_detected,
            "attachments_ingested": total_ingested,
            "attachments_skipped": total_skipped
        },
        "recent_runs": runs[:10],
        "document_types": list(SALES_DOCUMENT_TYPES.keys())
    }


@sales_router.post("/email-polling/trigger")
async def trigger_sales_email_poll():
    """Manually trigger a sales email poll run (for testing)."""
    if not _sales_email_config["mailbox"]:
        raise HTTPException(status_code=400, detail="Sales email polling not configured. Set SALES_EMAIL_POLLING_USER in .env")
    
    # Import the polling function from main server
    try:
        from server import run_sales_email_poll
        result = await run_sales_email_poll()
        return result
    except ImportError:
        raise HTTPException(status_code=500, detail="Sales email polling not initialized")


@sales_router.get("/documents")
async def get_sales_documents(
    skip: int = Query(0),
    limit: int = Query(20),
    document_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    days: int = Query(30)
):
    """Get list of ingested sales documents."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    query = {"created_utc": {"$gte": cutoff}}
    if document_type:
        query["document_type"] = document_type
    if status:
        query["status"] = status
    if customer_id:
        query["customer_id"] = customer_id
    
    total = await _db.sales_documents.count_documents(query)
    docs = await _db.sales_documents.find(
        query,
        {"_id": 0}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "documents": docs
    }


@sales_router.get("/documents/{document_id}")
async def get_sales_document(document_id: str):
    """Get details of a single sales document."""
    doc = await _db.sales_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@sales_router.get("/documents/stats/by-type")
async def get_sales_document_stats_by_type(days: int = Query(30)):
    """Get document counts grouped by type."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    pipeline = [
        {"$match": {"created_utc": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$document_type",
            "count": {"$sum": 1},
            "avg_confidence": {"$avg": "$ai_confidence"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    results = await _db.sales_documents.aggregate(pipeline).to_list(100)
    
    # Add metadata from type config
    stats = []
    for r in results:
        doc_type = r["_id"]
        type_config = SALES_DOCUMENT_TYPES.get(doc_type, {})
        stats.append({
            "document_type": doc_type,
            "count": r["count"],
            "avg_confidence": round(r.get("avg_confidence", 0), 2),
            "priority": type_config.get("priority", "unknown"),
            "action": type_config.get("action", "unknown"),
            "description": type_config.get("description", "")
        })
    
    return {
        "period_days": days,
        "total_documents": sum(s["count"] for s in stats),
        "by_type": stats
    }


@sales_router.get("/documents/stats/by-customer")
async def get_sales_document_stats_by_customer(days: int = Query(30)):
    """Get document counts grouped by customer."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    pipeline = [
        {"$match": {"created_utc": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$customer_id",
            "customer_name": {"$first": "$customer_name_extracted"},
            "count": {"$sum": 1},
            "types": {"$addToSet": "$document_type"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    results = await _db.sales_documents.aggregate(pipeline).to_list(100)
    
    return {
        "period_days": days,
        "by_customer": [
            {
                "customer_id": r["_id"],
                "customer_name": r.get("customer_name") or "Unknown",
                "document_count": r["count"],
                "document_types": r["types"]
            }
            for r in results
        ]
    }


@sales_router.get("/email-polling/logs")
async def get_sales_email_logs(
    skip: int = Query(0),
    limit: int = Query(50),
    status: Optional[str] = Query(None)
):
    """Get sales mail intake logs."""
    query = {}
    if status:
        query["status"] = status
    
    logs = await _db.sales_mail_intake_log.find(
        query,
        {"_id": 0}
    ).sort("processed_at", -1).skip(skip).limit(limit).to_list(limit)
    
    return logs
