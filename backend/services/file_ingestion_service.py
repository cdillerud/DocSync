"""
GPI Document Hub - Excel/CSV File Ingestion Service

This service handles parsing and ingestion of Excel/CSV files for:
- Sales Orders (customer POs)
- Inventory Positions
- Customer Items/SKU mappings
- Open Order Lines

Supports file formats:
- CSV (.csv)
- Excel (.xlsx, .xls)
"""

import csv
import io
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class IngestionType(str, Enum):
    """Types of data that can be ingested from files."""
    SALES_ORDER = "sales_order"
    INVENTORY_POSITION = "inventory_position"
    CUSTOMER_ITEM = "customer_item"
    OPEN_ORDER_LINE = "open_order_line"


class IngestionResult(BaseModel):
    """Result of a file ingestion operation."""
    success: bool
    ingestion_id: str
    ingestion_type: str
    file_name: str
    rows_parsed: int
    rows_valid: int
    rows_invalid: int
    rows_imported: int = 0
    validation_errors: List[Dict[str, Any]] = []
    preview_data: List[Dict[str, Any]] = []
    column_mapping: Dict[str, str] = {}
    warnings: List[str] = []
    error: Optional[str] = None


# Column mapping presets for common file formats
COLUMN_MAPPINGS = {
    # Sales Order file mappings
    "sales_order": {
        "known_columns": {
            "customer_po": ["customer_po", "customer_po_no", "po_number", "po", "purchase_order", "po_no", "customer po", "customer po no"],
            "customer_id": ["customer_id", "customer", "customer_no", "customer_number", "cust_id"],
            "customer_name": ["customer_name", "customer name", "cust_name", "name"],
            "order_date": ["order_date", "date", "po_date", "order date"],
            "requested_ship_date": ["requested_ship_date", "ship_date", "required_date", "ship date", "required date", "delivery_date"],
            "item_no": ["item_no", "item", "sku", "item_number", "part_number", "product_code", "item no", "item number", "part number"],
            "customer_sku": ["customer_sku", "customer_item", "customer item", "cust_sku", "customer sku"],
            "quantity": ["quantity", "qty", "ordered_qty", "order_qty", "ordered qty", "amount"],
            "uom": ["uom", "unit", "unit_of_measure", "unit of measure"],
            "warehouse": ["warehouse", "warehouse_id", "ship_from", "location", "warehouse id"],
            "notes": ["notes", "comments", "remarks", "note"]
        },
        "required_columns": ["customer_po", "item_no", "quantity"],
        "optional_columns": ["customer_id", "customer_name", "order_date", "requested_ship_date", "customer_sku", "uom", "warehouse", "notes"]
    },
    # Inventory Position file mappings
    "inventory_position": {
        "known_columns": {
            "customer_id": ["customer_id", "customer", "customer_no", "customer_number"],
            "customer_name": ["customer_name", "customer name", "cust_name"],
            "item_no": ["item_no", "item", "sku", "item_number", "part_number", "product_code"],
            "customer_sku": ["customer_sku", "customer_item", "cust_sku"],
            "warehouse_id": ["warehouse_id", "warehouse", "location", "wh_code", "warehouse_code"],
            "warehouse_name": ["warehouse_name", "wh_name", "location_name"],
            "qty_on_hand": ["qty_on_hand", "on_hand", "quantity", "stock", "available_qty", "qty"],
            "qty_allocated": ["qty_allocated", "allocated", "reserved", "committed"],
            "qty_available": ["qty_available", "available", "free", "free_stock"],
            "qty_on_water": ["qty_on_water", "in_transit", "on_water", "en_route"],
            "qty_on_order": ["qty_on_order", "on_order", "ordered", "open_order"],
            "snapshot_date": ["snapshot_date", "date", "as_of_date", "report_date"]
        },
        "required_columns": ["item_no", "qty_on_hand"],
        "optional_columns": ["customer_id", "customer_name", "customer_sku", "warehouse_id", "warehouse_name", "qty_allocated", "qty_available", "qty_on_water", "qty_on_order", "snapshot_date"]
    },
    # Customer Item mappings
    "customer_item": {
        "known_columns": {
            "customer_id": ["customer_id", "customer", "customer_no"],
            "customer_name": ["customer_name", "customer name"],
            "item_no": ["item_no", "item", "gpi_sku", "internal_sku"],
            "customer_sku": ["customer_sku", "customer_item", "cust_sku", "external_sku"],
            "customer_description": ["customer_description", "description", "item_description", "product_name"],
            "min_order_qty": ["min_order_qty", "moq", "minimum_order"],
            "lead_time_days": ["lead_time_days", "lead_time", "lt_days"]
        },
        "required_columns": ["customer_sku", "item_no"],
        "optional_columns": ["customer_id", "customer_name", "customer_description", "min_order_qty", "lead_time_days"]
    }
}


class FileIngestionService:
    """Service for parsing and validating Excel/CSV files."""
    
    def __init__(self, db=None):
        self.db = db
    
    def set_db(self, db):
        """Set database reference."""
        self.db = db
    
    def _normalize_column_name(self, col: str) -> str:
        """Normalize column name for matching."""
        return col.lower().strip().replace("-", "_").replace(" ", "_")
    
    def _detect_column_mapping(self, columns: List[str], ingestion_type: str) -> Dict[str, str]:
        """
        Auto-detect column mapping based on column names.
        Returns a dict mapping internal field names to actual column names.
        """
        mapping = {}
        type_config = COLUMN_MAPPINGS.get(ingestion_type, {})
        known_columns = type_config.get("known_columns", {})
        
        for field_name, possible_names in known_columns.items():
            for col in columns:
                normalized = self._normalize_column_name(col)
                if normalized in [self._normalize_column_name(p) for p in possible_names]:
                    mapping[field_name] = col
                    break
        
        return mapping
    
    def _validate_required_columns(self, mapping: Dict[str, str], ingestion_type: str) -> List[str]:
        """Validate that all required columns are present."""
        type_config = COLUMN_MAPPINGS.get(ingestion_type, {})
        required = type_config.get("required_columns", [])
        
        missing = []
        for req in required:
            if req not in mapping:
                missing.append(req)
        
        return missing
    
    def parse_csv(self, content: bytes, file_name: str) -> Tuple[List[str], List[Dict[str, str]]]:
        """Parse CSV file content into headers and rows."""
        try:
            # Try UTF-8 first, then fallback to latin-1
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                text = content.decode('latin-1')
            
            reader = csv.DictReader(io.StringIO(text))
            headers = reader.fieldnames or []
            rows = list(reader)
            
            return headers, rows
        except Exception as e:
            logger.error("Error parsing CSV: %s", str(e))
            raise ValueError(f"Failed to parse CSV file: {str(e)}")
    
    def parse_excel(self, content: bytes, file_name: str, sheet_name: str = None) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Parse Excel file content into headers and rows."""
        try:
            import pandas as pd
            from io import BytesIO
            
            # Read Excel file
            excel_file = BytesIO(content)
            
            if sheet_name:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
            else:
                # Read first sheet
                df = pd.read_excel(excel_file)
            
            # Handle empty DataFrame
            if df.empty:
                return [], []
            
            # Clean column names
            df.columns = [str(col).strip() for col in df.columns]
            headers = list(df.columns)
            
            # Convert to list of dicts, handling NaN values
            df = df.fillna('')
            rows = df.to_dict('records')
            
            return headers, rows
        except Exception as e:
            logger.error("Error parsing Excel: %s", str(e))
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
    
    def get_excel_sheets(self, content: bytes) -> List[str]:
        """Get list of sheet names from Excel file."""
        try:
            import pandas as pd
            from io import BytesIO
            
            excel_file = BytesIO(content)
            xl = pd.ExcelFile(excel_file)
            return xl.sheet_names
        except Exception as e:
            logger.error("Error reading Excel sheets: %s", str(e))
            return []
    
    def parse_file(
        self,
        content: bytes,
        file_name: str,
        ingestion_type: str,
        sheet_name: str = None,
        custom_mapping: Dict[str, str] = None
    ) -> IngestionResult:
        """
        Parse a file and return structured data with validation.
        
        Args:
            content: File content as bytes
            file_name: Original filename
            ingestion_type: Type of data to expect (sales_order, inventory_position, etc.)
            sheet_name: Optional sheet name for Excel files
            custom_mapping: Optional custom column mapping to override auto-detection
        
        Returns:
            IngestionResult with parsed data and validation status
        """
        ingestion_id = str(uuid.uuid4())
        file_ext = Path(file_name).suffix.lower()
        
        result = IngestionResult(
            success=False,
            ingestion_id=ingestion_id,
            ingestion_type=ingestion_type,
            file_name=file_name,
            rows_parsed=0,
            rows_valid=0,
            rows_invalid=0
        )
        
        try:
            # Parse file based on extension
            if file_ext == '.csv':
                headers, rows = self.parse_csv(content, file_name)
            elif file_ext in ['.xlsx', '.xls']:
                headers, rows = self.parse_excel(content, file_name, sheet_name)
            else:
                result.error = f"Unsupported file format: {file_ext}. Supported: .csv, .xlsx, .xls"
                return result
            
            if not headers:
                result.error = "No headers found in file"
                return result
            
            if not rows:
                result.error = "No data rows found in file"
                return result
            
            result.rows_parsed = len(rows)
            
            # Detect column mapping
            if custom_mapping:
                column_mapping = custom_mapping
            else:
                column_mapping = self._detect_column_mapping(headers, ingestion_type)
            
            result.column_mapping = column_mapping
            
            # Validate required columns
            missing_columns = self._validate_required_columns(column_mapping, ingestion_type)
            if missing_columns:
                result.error = f"Missing required columns: {', '.join(missing_columns)}"
                result.warnings.append(f"Detected columns: {headers}")
                result.warnings.append(f"Auto-mapped: {column_mapping}")
                return result
            
            # Validate and transform rows
            valid_rows = []
            validation_errors = []
            
            for idx, row in enumerate(rows):
                row_num = idx + 2  # Excel row number (1-indexed + header row)
                row_errors = []
                transformed = {}
                
                # Map columns to internal field names
                for field_name, col_name in column_mapping.items():
                    value = row.get(col_name, '')
                    # Convert to string and strip whitespace
                    if value is not None:
                        value = str(value).strip()
                    transformed[field_name] = value
                
                # Validate based on ingestion type
                if ingestion_type == "sales_order":
                    row_errors = self._validate_sales_order_row(transformed, row_num)
                elif ingestion_type == "inventory_position":
                    row_errors = self._validate_inventory_row(transformed, row_num)
                elif ingestion_type == "customer_item":
                    row_errors = self._validate_customer_item_row(transformed, row_num)
                
                if row_errors:
                    validation_errors.extend(row_errors)
                    result.rows_invalid += 1
                else:
                    valid_rows.append(transformed)
                    result.rows_valid += 1
            
            result.validation_errors = validation_errors
            result.preview_data = valid_rows[:100]  # Limit preview to 100 rows
            result.success = result.rows_valid > 0
            
            if result.rows_invalid > 0:
                result.warnings.append(f"{result.rows_invalid} rows had validation errors")
            
            return result
            
        except Exception as e:
            logger.exception("Error parsing file: %s", file_name)
            result.error = str(e)
            return result
    
    def _validate_sales_order_row(self, row: Dict[str, str], row_num: int) -> List[Dict[str, Any]]:
        """Validate a sales order row."""
        errors = []
        
        # Check required fields
        if not row.get("customer_po"):
            errors.append({"row": row_num, "field": "customer_po", "error": "Customer PO is required"})
        
        if not row.get("item_no"):
            errors.append({"row": row_num, "field": "item_no", "error": "Item number is required"})
        
        qty = row.get("quantity", "")
        if not qty:
            errors.append({"row": row_num, "field": "quantity", "error": "Quantity is required"})
        else:
            try:
                qty_val = float(str(qty).replace(",", ""))
                if qty_val <= 0:
                    errors.append({"row": row_num, "field": "quantity", "error": "Quantity must be positive"})
            except ValueError:
                errors.append({"row": row_num, "field": "quantity", "error": f"Invalid quantity: {qty}"})
        
        return errors
    
    def _validate_inventory_row(self, row: Dict[str, str], row_num: int) -> List[Dict[str, Any]]:
        """Validate an inventory position row."""
        errors = []
        
        if not row.get("item_no"):
            errors.append({"row": row_num, "field": "item_no", "error": "Item number is required"})
        
        qty = row.get("qty_on_hand", "")
        if qty == "":
            errors.append({"row": row_num, "field": "qty_on_hand", "error": "Quantity on hand is required"})
        else:
            try:
                float(str(qty).replace(",", ""))
            except ValueError:
                errors.append({"row": row_num, "field": "qty_on_hand", "error": f"Invalid quantity: {qty}"})
        
        return errors
    
    def _validate_customer_item_row(self, row: Dict[str, str], row_num: int) -> List[Dict[str, Any]]:
        """Validate a customer item row."""
        errors = []
        
        if not row.get("customer_sku"):
            errors.append({"row": row_num, "field": "customer_sku", "error": "Customer SKU is required"})
        
        if not row.get("item_no"):
            errors.append({"row": row_num, "field": "item_no", "error": "GPI item number is required"})
        
        return errors
    
    async def import_sales_orders(
        self,
        parsed_result: IngestionResult,
        customer_id: str = None,
        source: str = "file_import",
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Import sales orders from parsed file data into the database.
        
        Groups order lines by customer_po into order headers and lines.
        """
        if self.db is None:
            return {"success": False, "error": "Database not configured"}
        
        if not parsed_result.success:
            return {"success": False, "error": "Cannot import invalid parsed data"}
        
        now = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        # Group rows by customer_po
        orders_by_po = {}
        for row in parsed_result.preview_data:
            po = row.get("customer_po", "")
            if po not in orders_by_po:
                orders_by_po[po] = {
                    "lines": [],
                    "customer_id": row.get("customer_id") or customer_id,
                    "order_date": row.get("order_date") or today,
                    "requested_ship_date": row.get("requested_ship_date"),
                    "notes": row.get("notes", "")
                }
            orders_by_po[po]["lines"].append(row)
        
        created_orders = []
        created_lines = []
        
        for po_no, order_data in orders_by_po.items():
            order_id = f"ord_{uuid.uuid4().hex[:8]}"
            
            # Create order header
            order_header = {
                "order_id": order_id,
                "customer_id": order_data["customer_id"] or "unknown",
                "bc_sales_order_no": None,
                "customer_po_no": po_no,
                "order_date": order_data["order_date"],
                "requested_ship_date": order_data["requested_ship_date"],
                "status": "planned",
                "source": source,
                "total_qty": 0,
                "line_count": 0,
                "created_utc": now,
                "updated_utc": now,
                "ingestion_id": parsed_result.ingestion_id,
                "notes": order_data["notes"]
            }
            
            # Create order lines
            line_num = 0
            for line_data in order_data["lines"]:
                line_num += 1
                line_id = f"line_{uuid.uuid4().hex[:8]}"
                
                try:
                    qty = float(str(line_data.get("quantity", "0")).replace(",", ""))
                except ValueError:
                    qty = 0
                
                order_line = {
                    "order_line_id": line_id,
                    "order_id": order_id,
                    "line_number": line_num,
                    "item_no": line_data.get("item_no"),
                    "customer_sku": line_data.get("customer_sku"),
                    "ordered_qty": qty,
                    "uom": line_data.get("uom", "EA"),
                    "ship_from_warehouse_id": line_data.get("warehouse"),
                    "requested_ship_date": line_data.get("requested_ship_date") or order_data["requested_ship_date"],
                    "promised_ship_date": None,
                    "line_status": "open",
                    "created_utc": now
                }
                
                order_header["total_qty"] += qty
                order_header["line_count"] += 1
                created_lines.append(order_line)
            
            created_orders.append(order_header)
        
        if not dry_run:
            try:
                # Insert into database
                if created_orders:
                    await self.db.sales_open_order_headers.insert_many(created_orders)
                if created_lines:
                    await self.db.sales_open_order_lines.insert_many(created_lines)
                
                # Log the import
                await self.db.file_ingestion_log.insert_one({
                    "ingestion_id": parsed_result.ingestion_id,
                    "ingestion_type": "sales_order",
                    "file_name": parsed_result.file_name,
                    "rows_parsed": parsed_result.rows_parsed,
                    "rows_imported": len(created_lines),
                    "orders_created": len(created_orders),
                    "created_utc": now,
                    "customer_id": customer_id,
                    "source": source
                })
                
            except Exception as e:
                logger.exception("Error importing sales orders")
                return {"success": False, "error": str(e)}
        
        return {
            "success": True,
            "dry_run": dry_run,
            "orders_created": len(created_orders),
            "lines_created": len(created_lines),
            "total_quantity": sum(o["total_qty"] for o in created_orders),
            "order_ids": [o["order_id"] for o in created_orders],
            "preview": created_orders[:5] if dry_run else None
        }
    
    async def import_inventory_positions(
        self,
        parsed_result: IngestionResult,
        customer_id: str = None,
        warehouse_id: str = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Import inventory positions from parsed file data."""
        if self.db is None:
            return {"success": False, "error": "Database not configured"}
        
        if not parsed_result.success:
            return {"success": False, "error": "Cannot import invalid parsed data"}
        
        now = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        created_positions = []
        
        for row in parsed_result.preview_data:
            position_id = f"inv_{uuid.uuid4().hex[:8]}"
            
            def parse_qty(val):
                try:
                    return float(str(val).replace(",", "")) if val else 0.0
                except ValueError:
                    return 0.0
            
            position = {
                "inventory_id": position_id,
                "customer_id": row.get("customer_id") or customer_id or "unknown",
                "item_no": row.get("item_no"),
                "customer_sku": row.get("customer_sku"),
                "warehouse_id": row.get("warehouse_id") or warehouse_id or "unknown",
                "snapshot_date": row.get("snapshot_date") or today,
                "qty_on_hand": parse_qty(row.get("qty_on_hand")),
                "qty_allocated": parse_qty(row.get("qty_allocated")),
                "qty_available": parse_qty(row.get("qty_available")),
                "qty_on_water": parse_qty(row.get("qty_on_water")),
                "qty_on_order": parse_qty(row.get("qty_on_order")),
                "created_utc": now,
                "ingestion_id": parsed_result.ingestion_id
            }
            
            # Calculate available if not provided
            if position["qty_available"] == 0 and position["qty_on_hand"] > 0:
                position["qty_available"] = position["qty_on_hand"] - position["qty_allocated"]
            
            created_positions.append(position)
        
        if not dry_run:
            try:
                if created_positions:
                    await self.db.sales_inventory_positions.insert_many(created_positions)
                
                await self.db.file_ingestion_log.insert_one({
                    "ingestion_id": parsed_result.ingestion_id,
                    "ingestion_type": "inventory_position",
                    "file_name": parsed_result.file_name,
                    "rows_parsed": parsed_result.rows_parsed,
                    "rows_imported": len(created_positions),
                    "created_utc": now,
                    "customer_id": customer_id,
                    "warehouse_id": warehouse_id
                })
                
            except Exception as e:
                logger.exception("Error importing inventory positions")
                return {"success": False, "error": str(e)}
        
        return {
            "success": True,
            "dry_run": dry_run,
            "positions_created": len(created_positions),
            "total_on_hand": sum(p["qty_on_hand"] for p in created_positions),
            "preview": created_positions[:5] if dry_run else None
        }


# Singleton instance
file_ingestion_service = FileIngestionService()


def set_file_ingestion_db(db):
    """Set database reference for the file ingestion service."""
    file_ingestion_service.set_db(db)
