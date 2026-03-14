"""
CSV Import Endpoint Tests
Tests POST /api/inventory-ledger/import for inventory balance import from CSV

Features tested:
- Opening balance import with valid CSV
- Manual adjustment import
- Duplicate file import protection (409)
- Invalid import_mode validation (422)
- Missing required columns validation (item, qty)
- Zero qty rejection
- Invalid/non-numeric qty rejection
- Duplicate opening_balance per item/warehouse/ownership rejection
- Empty file validation
- Nonexistent customer returns 404
- Imported rows appear in balances
- Imported rows appear in movement history with source_type=spreadsheet_import
- Optional columns (warehouse, ownership_type, uom, reference, notes, item_description) work
"""

import pytest
import requests
import os
import io
import uuid
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test customer ID (Hormel Foods)
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


def generate_unique_item():
    """Generate unique item name to avoid conflicts with existing data"""
    return f"TEST-IMPORT-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    return session


class TestCSVImportOpeningBalance:
    """Tests for opening_balance import mode"""

    def test_successful_opening_balance_import(self, api_client):
        """Test successful import of 3 rows with opening_balance mode"""
        item1 = generate_unique_item()
        item2 = generate_unique_item()
        item3 = generate_unique_item()
        
        csv_content = f"""item,qty,warehouse,ownership_type,uom,reference,notes,item_description
{item1},100,MAIN,customer_owned,cases,REF-001,Test import,Test Item A
{item2},250,MAIN,customer_owned,units,REF-002,Another import,Test Item B
{item3},50,WH-2,gamer_reserved,pallets,REF-003,Third row,Test Item C"""
        
        files = {'file': ('test_import.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        result = response.json()
        
        assert result['success'] == True
        assert result['rows_processed'] == 3
        assert result['rows_imported'] == 3
        assert result['rows_failed'] == 0
        assert result['errors'] == []
        assert 'import_batch_id' in result
        assert result['import_batch_id'].startswith('CSV-')
        
        # Verify items appear in balances
        balance_resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert balance_resp.status_code == 200
        balances = balance_resp.json()['balances']
        
        item_names = [b['item'] for b in balances]
        assert item1 in item_names, f"Item {item1} not found in balances"
        assert item2 in item_names, f"Item {item2} not found in balances"
        assert item3 in item_names, f"Item {item3} not found in balances"
        
        # Verify correct qty
        for b in balances:
            if b['item'] == item1:
                assert b['on_hand'] == 100
                assert b['warehouse'] == 'MAIN'
            elif b['item'] == item2:
                assert b['on_hand'] == 250
            elif b['item'] == item3:
                assert b['on_hand'] == 50
                assert b['warehouse'] == 'WH-2'
                assert b['ownership_type'] == 'gamer_reserved'

    def test_imported_rows_appear_in_movement_history(self, api_client):
        """Test that imported rows appear with source_type=spreadsheet_import"""
        item = generate_unique_item()
        csv_content = f"item,qty\n{item},75"
        
        files = {'file': ('history_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        assert response.status_code == 200
        assert response.json()['rows_imported'] == 1
        
        # Check movement history
        history_resp = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={'customer_id': HORMEL_CUSTOMER_ID, 'item': item, 'limit': 10}
        )
        assert history_resp.status_code == 200
        movements = history_resp.json()['movements']
        
        assert len(movements) >= 1
        mov = movements[0]
        assert mov['item'] == item
        assert mov['source_type'] == 'spreadsheet_import'
        assert mov['movement_type'] == 'opening_balance'
        assert mov['reference_type'] == 'csv_import'
        assert mov['quantity_delta'] == 75


class TestCSVImportManualAdjustment:
    """Tests for manual_adjustment import mode"""

    def test_successful_manual_adjustment_import(self, api_client):
        """Test successful import with manual_adjustment mode"""
        item = generate_unique_item()
        csv_content = f"item,qty\n{item},-25"  # Negative adjustment
        
        files = {'file': ('adjust_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'manual_adjustment'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200
        result = response.json()
        assert result['success'] == True
        assert result['rows_imported'] == 1
        
        # Verify in history
        history_resp = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={'customer_id': HORMEL_CUSTOMER_ID, 'item': item, 'limit': 5}
        )
        assert history_resp.status_code == 200
        movements = history_resp.json()['movements']
        assert len(movements) >= 1
        assert movements[0]['movement_type'] == 'manual_adjustment'
        assert movements[0]['source_type'] == 'spreadsheet_import'
        assert movements[0]['quantity_delta'] == -25


class TestCSVImportDuplicateProtection:
    """Tests for duplicate file import protection"""

    def test_duplicate_file_import_returns_409(self, api_client):
        """Test that reimporting the same file returns 409"""
        item = generate_unique_item()
        csv_content = f"item,qty\n{item},100"
        
        # First import
        files1 = {'file': ('dup_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files1, data=data)
        assert response1.status_code == 200
        
        # Second import of same file
        files2 = {'file': ('dup_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        response2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files2, data=data)
        
        assert response2.status_code == 409, f"Expected 409, got {response2.status_code}"
        assert 'Duplicate import' in response2.json().get('detail', '')

    def test_same_content_different_mode_is_different_import(self, api_client):
        """Test that same file with different mode is allowed (different hash)"""
        item = generate_unique_item()
        csv_content = f"item,qty\n{item},50"
        
        # Import with opening_balance
        files1 = {'file': ('mode_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data1 = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        response1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files1, data=data1)
        assert response1.status_code == 200
        
        # Import same content but with manual_adjustment (different hash due to mode)
        files2 = {'file': ('mode_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data2 = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'manual_adjustment'}
        response2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files2, data=data2)
        assert response2.status_code == 200  # Should succeed since hash includes mode


class TestCSVImportValidation:
    """Tests for validation errors"""

    def test_invalid_import_mode_returns_422(self, api_client):
        """Test that invalid import_mode returns 422"""
        csv_content = "item,qty\nTEST-ITEM,100"
        files = {'file': ('invalid_mode.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'invalid_mode'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 422
        detail = response.json().get('detail', '')
        assert 'invalid' in detail.lower() or 'import_mode' in detail.lower()

    def test_missing_item_column_returns_422(self, api_client):
        """Test that CSV without 'item' column returns 422"""
        csv_content = "qty,warehouse\n100,MAIN"  # No 'item' column
        files = {'file': ('no_item.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 422
        assert 'item' in response.json().get('detail', '').lower()

    def test_missing_qty_column_returns_422(self, api_client):
        """Test that CSV without 'qty' column returns 422"""
        csv_content = "item,warehouse\nTEST-ITEM,MAIN"  # No 'qty' column
        files = {'file': ('no_qty.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 422
        assert 'qty' in response.json().get('detail', '').lower()

    def test_empty_file_returns_422(self, api_client):
        """Test that empty file returns 422"""
        files = {'file': ('empty.csv', io.BytesIO(b''), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 422
        assert 'empty' in response.json().get('detail', '').lower()

    def test_nonexistent_customer_returns_404(self, api_client):
        """Test that nonexistent customer_id returns 404"""
        csv_content = "item,qty\nTEST-ITEM,100"
        files = {'file': ('fake_customer.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': 'non-existent-customer-id', 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 404
        assert 'customer' in response.json().get('detail', '').lower() or 'not found' in response.json().get('detail', '').lower()


class TestCSVImportRowErrors:
    """Tests for row-level validation errors"""

    def test_zero_qty_row_rejected_in_results(self, api_client):
        """Test that rows with zero qty are rejected"""
        item1 = generate_unique_item()
        item2 = generate_unique_item()
        csv_content = f"""item,qty
{item1},100
{item2},0"""  # Second row has zero qty
        
        files = {'file': ('zero_qty.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200
        result = response.json()
        assert result['rows_processed'] == 2
        assert result['rows_imported'] == 1
        assert result['rows_failed'] == 1
        assert len(result['errors']) == 1
        assert 'zero' in result['errors'][0]['error'].lower()

    def test_invalid_nonnumeric_qty_rejected(self, api_client):
        """Test that non-numeric qty values are rejected"""
        item = generate_unique_item()
        csv_content = f"""item,qty
{item},abc"""  # Non-numeric qty
        
        files = {'file': ('bad_qty.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200
        result = response.json()
        assert result['rows_failed'] == 1
        assert result['rows_imported'] == 0
        assert 'invalid' in result['errors'][0]['error'].lower() or 'qty' in result['errors'][0]['error'].lower()

    def test_duplicate_opening_balance_per_item_warehouse_ownership_rejected(self, api_client):
        """Test that duplicate opening_balance for same item/warehouse/ownership is rejected"""
        item = generate_unique_item()
        
        # First import - should succeed
        csv1 = f"item,qty,warehouse,ownership_type\n{item},100,MAIN,customer_owned"
        files1 = {'file': ('first.csv', io.BytesIO(csv1.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files1, data=data)
        assert response1.status_code == 200
        assert response1.json()['rows_imported'] == 1
        
        # Second import with DIFFERENT file content but SAME item/warehouse/ownership
        csv2 = f"item,qty,warehouse,ownership_type\n{item},200,MAIN,customer_owned"  # Different qty
        files2 = {'file': ('second.csv', io.BytesIO(csv2.encode('utf-8')), 'text/csv')}
        
        response2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files2, data=data)
        
        assert response2.status_code == 200
        result = response2.json()
        assert result['rows_imported'] == 0
        assert result['rows_failed'] == 1
        assert 'opening balance already exists' in result['errors'][0]['error'].lower()


class TestCSVImportOptionalColumns:
    """Tests for optional columns"""

    def test_optional_columns_work(self, api_client):
        """Test that all optional columns are properly handled"""
        item = generate_unique_item()
        csv_content = f"""item,qty,warehouse,ownership_type,uom,reference,notes,item_description
{item},75,WH-OPTIONAL,gamer_reserved,boxes,OPT-REF-123,Optional test notes,Optional Test Description"""
        
        files = {'file': ('optional.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200
        assert response.json()['rows_imported'] == 1
        
        # Verify in balances
        balance_resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        balances = balance_resp.json()['balances']
        
        item_balance = next((b for b in balances if b['item'] == item), None)
        assert item_balance is not None
        assert item_balance['warehouse'] == 'WH-OPTIONAL'
        assert item_balance['ownership_type'] == 'gamer_reserved'
        assert item_balance['unit_of_measure'] == 'boxes'
        
        # Verify in history for notes and reference
        history_resp = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={'customer_id': HORMEL_CUSTOMER_ID, 'item': item}
        )
        movements = history_resp.json()['movements']
        assert len(movements) >= 1
        mov = movements[0]
        assert 'Optional test notes' in mov.get('notes', '')

    def test_unit_of_measure_alias_uom_works(self, api_client):
        """Test that 'uom' column works as alias for unit_of_measure"""
        item = generate_unique_item()
        csv_content = f"item,qty,uom\n{item},30,gallons"
        
        files = {'file': ('uom_alias.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        
        assert response.status_code == 200
        assert response.json()['rows_imported'] == 1
        
        # Verify UOM
        balance_resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        item_balance = next((b for b in balance_resp.json()['balances'] if b['item'] == item), None)
        assert item_balance is not None
        assert item_balance['unit_of_measure'] == 'gallons'


class TestCSVImportDashboardIntegration:
    """Tests for imported rows reflected in dashboard-summary"""

    def test_imported_rows_reflected_in_dashboard_summary(self, api_client):
        """Test that imported rows appear in dashboard-summary totals"""
        item = generate_unique_item()
        
        # Get initial dashboard summary
        summary_before = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        ).json()
        initial_total_on_hand = summary_before.get('total_on_hand', 0)
        
        # Import new item
        csv_content = f"item,qty\n{item},500"
        files = {'file': ('dash_test.csv', io.BytesIO(csv_content.encode('utf-8')), 'text/csv')}
        data = {'customer_id': HORMEL_CUSTOMER_ID, 'import_mode': 'opening_balance'}
        
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/import", files=files, data=data)
        assert response.status_code == 200
        assert response.json()['rows_imported'] == 1
        
        # Check dashboard summary updated
        summary_after = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        ).json()
        
        # Total on_hand should have increased by 500
        assert summary_after['total_on_hand'] >= initial_total_on_hand + 500


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""

    def test_dashboard_summary_still_works(self, api_client):
        """Regression: Dashboard summary endpoint still works"""
        response = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/dashboard-summary",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'total_items' in data
        assert 'items_ok' in data
        assert 'items_low' in data
        assert 'items_short' in data

    def test_balances_endpoint_still_works(self, api_client):
        """Regression: Balances endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert response.status_code == 200
        assert 'balances' in response.json()

    def test_movements_endpoint_still_works(self, api_client):
        """Regression: Movements endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/movements")
        assert response.status_code == 200
        assert 'movements' in response.json()

    def test_reorder_endpoint_still_works(self, api_client):
        """Regression: Reorder recommendations endpoint still works"""
        response = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        assert 'recommendations' in response.json()

    def test_item_settings_endpoint_still_works(self, api_client):
        """Regression: Item settings endpoint still works"""
        response = api_client.get(
            f"{BASE_URL}/api/inventory-items/settings",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        assert 'settings' in response.json()

    def test_csv_export_still_works(self, api_client):
        """Regression: CSV export endpoint still works"""
        response = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/export",
            params={'customer_id': HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        assert 'text/csv' in response.headers.get('content-type', '')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
