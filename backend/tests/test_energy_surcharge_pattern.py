"""
Test Energy Surcharge Customer-Level Pattern Feature
Tests the BC historical order learning feature that auto-suggests ENERGY surcharge
for customers where it appears in ≥75% of last 10 orders.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_batch_child_doc_id():
    """Run batch demo and get a batch-child document ID with C-9874 items"""
    # Run batch demo to seed patterns
    response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
    assert response.status_code == 200
    data = response.json()
    job_id = data.get("job_id")
    
    # Wait for batch to complete
    time.sleep(5)
    
    # Get batch status to find parent doc ID
    status_response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data.get("status") == "completed"
    
    parent_doc_id = status_data.get("parent_doc_id")
    
    # Get parent document to find child IDs
    parent_response = requests.get(f"{BASE_URL}/api/documents/{parent_doc_id}")
    if parent_response.status_code == 200:
        parent_doc = parent_response.json().get("document", {})
        children_ids = parent_doc.get("batch_children_ids", [])
        if children_ids:
            return children_ids[0]
    
    # Fallback: search for batch-child documents
    docs_response = requests.get(f"{BASE_URL}/api/documents?document_type=PurchaseOrder&limit=50")
    assert docs_response.status_code == 200
    docs_data = docs_response.json()
    
    for doc in docs_data.get("documents", []):
        doc_id = doc.get("id", "")
        if doc_id.startswith("batch-child"):
            return doc_id
    
    raise Exception("No batch-child document found")


@pytest.fixture(scope="module")
def child_doc_id():
    """Get a batch-child document ID for testing"""
    return get_batch_child_doc_id()


class TestEnergySurchargePattern:
    """Tests for customer-level ENERGY surcharge pattern feature"""
    
    def test_preflight_returns_energy_surcharge(self, child_doc_id):
        """Test that preflight returns ENERGY surcharge as suggested line"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200, f"Preflight failed: {response.text}"
        data = response.json()
        
        # Find ENERGY line in resolved_lines
        resolved_lines = data.get("resolved_lines", [])
        energy_lines = [ln for ln in resolved_lines if ln.get("lineObjectNumber") == "ENERGY"]
        
        assert len(energy_lines) == 1, f"Expected 1 ENERGY line, got {len(energy_lines)}"
        energy_line = energy_lines[0]
        
        # Verify ENERGY line properties
        assert energy_line.get("lineType") == "Item"
        assert energy_line.get("description") == "Energy Surcharge"
        assert energy_line.get("suggested") == True
        assert energy_line.get("source") == "learned_pattern"
        print(f"PASS: ENERGY surcharge found with lineType=Item, description='Energy Surcharge'")
    
    def test_energy_has_customer_level_trigger(self, child_doc_id):
        """Test that ENERGY line has trigger_item='*' (customer-level pattern)"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        energy_line = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "ENERGY"), None)
        
        assert energy_line is not None
        assert energy_line.get("trigger_item") == "*", f"Expected trigger_item='*', got '{energy_line.get('trigger_item')}'"
        print(f"PASS: ENERGY has trigger_item='*' (customer-level pattern)")
    
    def test_energy_has_fixed_qty_and_price(self, child_doc_id):
        """Test that ENERGY line has fixed_qty=1 and unit_price=497.36"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        energy_line = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "ENERGY"), None)
        
        assert energy_line is not None
        assert energy_line.get("fixed_qty") == 1, f"Expected fixed_qty=1, got {energy_line.get('fixed_qty')}"
        assert energy_line.get("quantity") == 1, f"Expected quantity=1, got {energy_line.get('quantity')}"
        assert energy_line.get("unitPrice") == 497.36, f"Expected unitPrice=497.36, got {energy_line.get('unitPrice')}"
        print(f"PASS: ENERGY has fixed_qty=1, quantity=1, unitPrice=497.36")
    
    def test_energy_has_80_percent_frequency(self, child_doc_id):
        """Test that ENERGY line shows 80% frequency (seen in 8 of 10 orders)"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        energy_line = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "ENERGY"), None)
        
        assert energy_line is not None
        assert energy_line.get("pattern_frequency") == 0.8, f"Expected pattern_frequency=0.8, got {energy_line.get('pattern_frequency')}"
        assert energy_line.get("pattern_occurrences") == 8, f"Expected pattern_occurrences=8, got {energy_line.get('pattern_occurrences')}"
        print(f"PASS: ENERGY has pattern_frequency=0.8 (80%), pattern_occurrences=8")
    
    def test_total_suggested_lines_count(self, child_doc_id):
        """Test that total suggested lines = 6 (5 dunnage + 1 energy) for C-9874 items"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Should have 6 suggested lines: 2 comments + 3 dunnage items + 1 ENERGY
        assert len(suggested_lines) == 6, f"Expected 6 suggested lines, got {len(suggested_lines)}"
        
        # Verify breakdown
        dunnage_items = [ln for ln in suggested_lines if ln.get("trigger_item") != "*"]
        customer_items = [ln for ln in suggested_lines if ln.get("trigger_item") == "*"]
        
        assert len(dunnage_items) == 5, f"Expected 5 dunnage lines, got {len(dunnage_items)}"
        assert len(customer_items) == 1, f"Expected 1 customer-level line (ENERGY), got {len(customer_items)}"
        print(f"PASS: Total 6 suggested lines (5 dunnage + 1 ENERGY)")
    
    def test_dunnage_patterns_still_work(self, child_doc_id):
        """Test that product-level dunnage patterns still work alongside customer-level patterns"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{child_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        
        # Check for dunnage items
        oipallet = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "OIPALLET"), None)
        oitiersheet = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "OITIERSHEET"), None)
        oitopframe = next((ln for ln in resolved_lines if ln.get("lineObjectNumber") == "OITOPFRAME"), None)
        
        assert oipallet is not None, "OIPALLET dunnage line not found"
        assert oitiersheet is not None, "OITIERSHEET dunnage line not found"
        assert oitopframe is not None, "OITOPFRAME dunnage line not found"
        
        # Verify they have qty_ratio (product-level pattern)
        assert oipallet.get("qty_ratio") == 0.3546
        assert oitiersheet.get("qty_ratio") == 4.963
        assert oitopframe.get("qty_ratio") == 0.3546
        
        # Verify quantities are calculated correctly for 62.062M qty
        assert oipallet.get("quantity") == 22, f"Expected OIPALLET qty=22, got {oipallet.get('quantity')}"
        assert oitiersheet.get("quantity") == 308, f"Expected OITIERSHEET qty=308, got {oitiersheet.get('quantity')}"
        assert oitopframe.get("quantity") == 22, f"Expected OITOPFRAME qty=22, got {oitopframe.get('quantity')}"
        
        print(f"PASS: Dunnage patterns work correctly (OIPALLET=22, OITIERSHEET=308, OITOPFRAME=22)")


class TestCustomerLevelPatternStorage:
    """Tests for customer-level pattern storage in order_line_patterns collection"""
    
    def test_customer_pattern_stored_in_db(self, child_doc_id):
        """Test that customer-level pattern (trigger_item='*') is stored in order_line_patterns"""
        # This test uses a Python script to check MongoDB directly
        import subprocess
        result = subprocess.run([
            "python3", "-c", """
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
import json

async def check():
    client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
    db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
    pattern = await db.order_line_patterns.find_one({'customer_no': 'C-10250', 'trigger_item_no': '*'})
    if pattern:
        pattern.pop('_id', None)
        print(json.dumps(pattern))
    else:
        print('null')

asyncio.run(check())
"""
        ], capture_output=True, text=True, cwd="/app")
        
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        
        import json
        pattern = json.loads(result.stdout.strip())
        
        assert pattern is not None, "Customer-level pattern not found in database"
        assert pattern.get("trigger_item_no") == "*"
        assert pattern.get("customer_no") == "C-10250"
        assert pattern.get("trigger_item_pattern") == "*"
        
        # Check associated_lines contains ENERGY
        associated_lines = pattern.get("associated_lines", [])
        energy_line = next((ln for ln in associated_lines if ln.get("item_no") == "ENERGY"), None)
        
        assert energy_line is not None, "ENERGY not found in associated_lines"
        assert energy_line.get("line_type") == "Item"
        assert energy_line.get("description") == "Energy Surcharge"
        assert energy_line.get("fixed_qty") == 1
        assert energy_line.get("unit_price") == 497.36
        assert energy_line.get("frequency") == 0.8
        assert energy_line.get("occurrences") == 8
        
        print(f"PASS: Customer-level pattern stored correctly in order_line_patterns collection")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
