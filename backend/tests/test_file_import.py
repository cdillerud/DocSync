"""
Test suite for Excel/CSV File Ingestion API endpoints.

Tests the following endpoints:
- POST /api/sales/file-import/parse - Parse CSV/Excel files
- POST /api/sales/file-import/import-orders - Import sales orders (dry-run & actual)
- POST /api/sales/file-import/import-inventory - Import inventory positions
- GET /api/sales/file-import/column-mappings - Get expected column mappings
- POST /api/sales/file-import/excel-sheets - Get Excel sheet names
- GET /api/sales/file-import/history - Get import history
"""
import pytest
import requests
import os
import io

# Use environment variable for BASE_URL - no defaults
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

if not BASE_URL:
    BASE_URL = "https://migration-workspace.preview.emergentagent.com"


# Test CSV data
TEST_CSV_CONTENT = """customer_po,item_no,quantity,customer_name,ship_date
PO-TEST-001,PKG-BTL-8OZ,5000,ET Browne,2024-03-01
PO-TEST-001,PKG-CAP-BLK,5000,ET Browne,2024-03-01
PO-TEST-002,PKG-BTL-16OZ,3000,Karlin,2024-03-15
PO-TEST-003,PKG-JAR-4OZ,2000,HOW,2024-04-01
"""

# Invalid CSV - missing required columns
INVALID_CSV_CONTENT = """customer_name,ship_date
ET Browne,2024-03-01
Karlin,2024-03-15
"""

# CSV with validation errors
CSV_WITH_ERRORS = """customer_po,item_no,quantity,customer_name,ship_date
PO-ERR-001,PKG-BTL-8OZ,-100,Error Corp,2024-03-01
PO-ERR-002,,5000,No Item,2024-03-15
,PKG-JAR-4OZ,abc,No PO,2024-04-01
"""

# Inventory CSV data
INVENTORY_CSV_CONTENT = """item_no,qty_on_hand,warehouse_id,customer_sku
PKG-BTL-8OZ,10000,WH-001,CUST-8OZ
PKG-BTL-16OZ,5000,WH-001,CUST-16OZ
PKG-JAR-4OZ,8000,WH-002,CUST-4OZ
"""


class TestColumnMappingsAPI:
    """Test GET /api/sales/file-import/column-mappings"""
    
    def test_get_sales_order_mappings(self):
        """Should return column mappings for sales_order type"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/column-mappings?ingestion_type=sales_order")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["ingestion_type"] == "sales_order"
        assert "required_columns" in data
        assert "optional_columns" in data
        assert "known_column_aliases" in data
        
        # Verify required columns
        required = data["required_columns"]
        assert "customer_po" in required
        assert "item_no" in required
        assert "quantity" in required
        
        print(f"Sales order required columns: {required}")
        print(f"Sales order optional columns: {data['optional_columns']}")
    
    def test_get_inventory_position_mappings(self):
        """Should return column mappings for inventory_position type"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/column-mappings?ingestion_type=inventory_position")
        assert response.status_code == 200
        
        data = response.json()
        assert data["ingestion_type"] == "inventory_position"
        assert "item_no" in data["required_columns"]
        assert "qty_on_hand" in data["required_columns"]
    
    def test_get_customer_item_mappings(self):
        """Should return column mappings for customer_item type"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/column-mappings?ingestion_type=customer_item")
        assert response.status_code == 200
        
        data = response.json()
        assert data["ingestion_type"] == "customer_item"
        assert "customer_sku" in data["required_columns"]
        assert "item_no" in data["required_columns"]
    
    def test_invalid_ingestion_type(self):
        """Should return 400 for unknown ingestion type"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/column-mappings?ingestion_type=invalid_type")
        assert response.status_code == 400


class TestParseCSVAPI:
    """Test POST /api/sales/file-import/parse with CSV files"""
    
    def test_parse_valid_csv(self):
        """Should successfully parse valid CSV file"""
        files = {
            'file': ('test_orders.csv', TEST_CSV_CONTENT, 'text/csv')
        }
        data = {
            'ingestion_type': 'sales_order'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/parse", files=files, data=data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["success"] == True
        assert result["rows_parsed"] == 4
        assert result["rows_valid"] == 4
        assert result["rows_invalid"] == 0
        assert "ingestion_id" in result
        assert "column_mapping" in result
        
        # Verify column mapping auto-detection
        mapping = result["column_mapping"]
        assert "customer_po" in mapping
        assert "item_no" in mapping
        assert "quantity" in mapping
        
        # Verify preview data
        assert len(result["preview_data"]) == 4
        first_row = result["preview_data"][0]
        assert first_row["customer_po"] == "PO-TEST-001"
        assert first_row["item_no"] == "PKG-BTL-8OZ"
        
        print(f"Successfully parsed {result['rows_valid']} valid rows")
        print(f"Column mapping: {mapping}")
    
    def test_parse_csv_missing_required_columns(self):
        """Should fail when required columns are missing"""
        files = {
            'file': ('invalid.csv', INVALID_CSV_CONTENT, 'text/csv')
        }
        data = {
            'ingestion_type': 'sales_order'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/parse", files=files, data=data)
        assert response.status_code == 200  # Returns 200 but with success=False
        
        result = response.json()
        assert result["success"] == False
        assert "Missing required columns" in result["error"]
    
    def test_parse_csv_with_validation_errors(self):
        """Should detect validation errors in row data"""
        files = {
            'file': ('errors.csv', CSV_WITH_ERRORS, 'text/csv')
        }
        data = {
            'ingestion_type': 'sales_order'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/parse", files=files, data=data)
        assert response.status_code == 200
        
        result = response.json()
        # File has some invalid rows
        assert result["rows_invalid"] > 0
        assert len(result["validation_errors"]) > 0
        
        print(f"Found {len(result['validation_errors'])} validation errors")


class TestParseInventoryCSV:
    """Test parsing inventory position CSV files"""
    
    def test_parse_inventory_csv(self):
        """Should parse inventory position CSV"""
        files = {
            'file': ('inventory.csv', INVENTORY_CSV_CONTENT, 'text/csv')
        }
        data = {
            'ingestion_type': 'inventory_position'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/parse", files=files, data=data)
        assert response.status_code == 200
        
        result = response.json()
        assert result["success"] == True
        assert result["rows_parsed"] == 3
        assert result["rows_valid"] == 3


class TestImportOrdersDryRun:
    """Test POST /api/sales/file-import/import-orders with dry_run=True"""
    
    def test_import_orders_dry_run(self):
        """Should preview import without saving to database"""
        files = {
            'file': ('test_orders.csv', TEST_CSV_CONTENT, 'text/csv')
        }
        data = {
            'dry_run': 'true'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/import-orders", files=files, data=data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["success"] == True
        assert result["dry_run"] == True
        assert result["orders_created"] == 3  # PO-TEST-001, PO-TEST-002, PO-TEST-003
        assert result["lines_created"] == 4
        assert result["total_quantity"] == 15000  # 5000+5000+3000+2000
        
        # Verify preview data is returned
        assert "preview" in result
        assert len(result["preview"]) > 0
        
        # Verify order_ids are returned
        assert "order_ids" in result
        assert len(result["order_ids"]) == 3
        
        print(f"Dry run: {result['orders_created']} orders, {result['lines_created']} lines would be created")
        print(f"Total quantity: {result['total_quantity']}")


class TestImportOrdersActual:
    """Test POST /api/sales/file-import/import-orders with dry_run=False"""
    
    def test_import_orders_actual(self):
        """Should actually import orders to database"""
        # Use unique PO numbers to avoid conflicts
        import uuid
        unique_suffix = uuid.uuid4().hex[:6]
        actual_csv = f"""customer_po,item_no,quantity,customer_name,ship_date
PO-IMPORT-{unique_suffix}-001,PKG-BTL-8OZ,100,Test Corp,2024-03-01
PO-IMPORT-{unique_suffix}-002,PKG-CAP-BLK,200,Test Corp 2,2024-03-15
"""
        
        files = {
            'file': ('actual_import.csv', actual_csv, 'text/csv')
        }
        data = {
            'dry_run': 'false',
            'customer_id': 'test_customer_001'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/import-orders", files=files, data=data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["success"] == True
        assert result["dry_run"] == False
        assert result["orders_created"] == 2
        assert result["lines_created"] == 2
        
        # Preview should be None for actual import
        assert result.get("preview") is None
        
        # Verify ingestion_id
        assert "ingestion_id" in result
        
        print(f"Actual import: Created {result['orders_created']} orders with {result['lines_created']} lines")
        print(f"Ingestion ID: {result['ingestion_id']}")
        
        return result["ingestion_id"]


class TestImportHistory:
    """Test GET /api/sales/file-import/history"""
    
    def test_get_import_history(self):
        """Should return import history"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/history")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "history" in data
        assert "total" in data
        
        print(f"Import history: {data['total']} total records")
        if data["history"]:
            print(f"Latest import: {data['history'][0].get('file_name')} at {data['history'][0].get('created_utc')}")
    
    def test_filter_history_by_type(self):
        """Should filter history by ingestion type"""
        response = requests.get(f"{BASE_URL}/api/sales/file-import/history?ingestion_type=sales_order")
        assert response.status_code == 200
        
        data = response.json()
        assert "history" in data
        # All results should be sales_order type
        for item in data["history"]:
            assert item.get("ingestion_type") == "sales_order"


class TestImportInventory:
    """Test POST /api/sales/file-import/import-inventory"""
    
    def test_import_inventory_dry_run(self):
        """Should preview inventory import"""
        files = {
            'file': ('inventory.csv', INVENTORY_CSV_CONTENT, 'text/csv')
        }
        data = {
            'dry_run': 'true',
            'customer_id': 'test_customer',
            'warehouse_id': 'test_warehouse'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/import-inventory", files=files, data=data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["success"] == True
        assert result["dry_run"] == True
        assert result["positions_created"] == 3
        assert "total_on_hand" in result
        
        print(f"Inventory dry run: {result['positions_created']} positions, {result['total_on_hand']} total on hand")


class TestFileFromDisk:
    """Test using the actual test file from /tmp/test_orders.csv"""
    
    def test_parse_actual_test_file(self):
        """Should parse the actual test file provided in /tmp"""
        test_file_path = "/tmp/test_orders.csv"
        
        # Read the actual file
        with open(test_file_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'file': ('test_orders.csv', file_content, 'text/csv')
        }
        data = {
            'ingestion_type': 'sales_order'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/parse", files=files, data=data)
        assert response.status_code == 200
        
        result = response.json()
        assert result["success"] == True
        # The file has 4 data rows as per description
        assert result["rows_parsed"] == 4
        assert result["rows_valid"] == 4
        
        # Verify PO grouping would result in 3 orders
        print(f"Test file parsed: {result['rows_parsed']} rows, {result['rows_valid']} valid")
    
    def test_import_actual_test_file_dry_run(self):
        """Should show correct order grouping for test file"""
        test_file_path = "/tmp/test_orders.csv"
        
        with open(test_file_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'file': ('test_orders.csv', file_content, 'text/csv')
        }
        data = {
            'dry_run': 'true'
        }
        
        response = requests.post(f"{BASE_URL}/api/sales/file-import/import-orders", files=files, data=data)
        assert response.status_code == 200
        
        result = response.json()
        assert result["success"] == True
        # 4 lines grouped into 3 orders (PO-2024-001 has 2 lines)
        assert result["orders_created"] == 3
        assert result["lines_created"] == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
