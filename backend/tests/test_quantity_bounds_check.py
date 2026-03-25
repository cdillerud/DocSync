"""
Test Quantity Bounds Checking Feature

Tests the PO line item quantity bounds checking functionality:
- Normal quantities within ±2σ should pass
- Quantities outside ±2σ should trigger violations
- Violations should block approval and flag document for review
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestQuantityBoundsCheck:
    """Tests for quantity bounds checking on PO line items"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Seed demo data before tests"""
        # Run batch demo to seed data
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        assert response.status_code == 200
        time.sleep(5)  # Wait for batch processing
        
        # Get batch-child documents (status=processed)
        response = requests.get(f"{BASE_URL}/api/documents?status=processed&limit=50")
        assert response.status_code == 200
        data = response.json()
        
        # Find batch-child documents with C-9874-10001833 item
        self.test_doc_id = None
        for doc in data.get('documents', []):
            doc_id = doc.get('id', '')
            if not doc_id.startswith('batch-child-'):
                continue
            
            # Check extracted_fields in the list response
            ef = doc.get('extracted_fields', {})
            items = ef.get('line_items', [])
            
            # If no items in list response, fetch full document
            if not items:
                full_doc_resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
                if full_doc_resp.status_code == 200:
                    full_doc = full_doc_resp.json().get('document', {})
                    ef = full_doc.get('extracted_fields', {})
                    items = ef.get('line_items', [])
            
            for item in items:
                if 'C-9874-10001833' in item.get('item_no', ''):
                    self.test_doc_id = doc_id
                    break
            if self.test_doc_id:
                break
        
        assert self.test_doc_id, "Could not find test document with C-9874-10001833 item"
        yield
    
    def test_normal_quantity_within_bounds(self):
        """Test that normal quantity (62.062 M) is within bounds"""
        # First reset quantity to normal value
        self._update_quantity(62.062)
        
        # Run preflight
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        bounds_check = data.get('bounds_check', {})
        
        # Verify in_bounds is True
        assert bounds_check.get('in_bounds') is True, f"Expected in_bounds=True, got {bounds_check}"
        assert len(bounds_check.get('violations', [])) == 0, "Expected no violations for normal qty"
        
        # Verify ready is True (not blocked)
        assert data.get('ready') is True, "Expected ready=True for normal qty"
        
        # Verify validation checklist shows pass
        checklist = data.get('validation_checklist', [])
        bounds_item = next((c for c in checklist if 'bounds' in c.get('label', '').lower()), None)
        assert bounds_item is not None, "Bounds check item not found in checklist"
        assert bounds_item.get('passed') is True, "Bounds check should pass for normal qty"
    
    def test_out_of_bounds_quantity_triggers_violation(self):
        """Test that 620 (10x normal) triggers bounds violation"""
        # Update quantity to 620 (10x normal, >2σ)
        self._update_quantity(620.0)
        
        # Run preflight
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        bounds_check = data.get('bounds_check', {})
        
        # Verify in_bounds is False
        assert bounds_check.get('in_bounds') is False, f"Expected in_bounds=False for qty=620"
        
        # Verify violations exist
        violations = bounds_check.get('violations', [])
        assert len(violations) > 0, "Expected violations for out-of-bounds qty"
        
        # Verify violation details
        v = violations[0]
        assert v.get('item_no') == 'C-9874-10001833', f"Wrong item_no: {v.get('item_no')}"
        assert v.get('po_quantity') == 620.0, f"Wrong po_quantity: {v.get('po_quantity')}"
        assert 'expected_min' in v, "Missing expected_min"
        assert 'expected_max' in v, "Missing expected_max"
        assert 'mean' in v, "Missing mean"
        assert 'std_dev' in v, "Missing std_dev"
        assert 'deviation_factor' in v, "Missing deviation_factor"
        assert v.get('severity') == 'critical', f"Expected severity=critical, got {v.get('severity')}"
        
        # Verify bounds are approximately correct (mean=60.95, std_dev=2.72)
        assert 55 < v.get('expected_min', 0) < 56, f"expected_min should be ~55.51"
        assert 66 < v.get('expected_max', 0) < 67, f"expected_max should be ~66.39"
    
    def test_violation_blocks_approval(self):
        """Test that bounds violation sets ready=False (blocking approval)"""
        # Update quantity to out-of-bounds value
        self._update_quantity(620.0)
        
        # Run preflight
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify ready is False (blocked)
        assert data.get('ready') is False, "Expected ready=False when bounds violation exists"
        
        # Verify validation checklist shows fail with blocking=True
        checklist = data.get('validation_checklist', [])
        bounds_item = next((c for c in checklist if 'bounds' in c.get('label', '').lower()), None)
        assert bounds_item is not None, "Bounds check item not found in checklist"
        assert bounds_item.get('passed') is False, "Bounds check should fail for out-of-bounds qty"
        assert bounds_item.get('blocking') is True, "Bounds check should be blocking"
    
    def test_violation_flags_document_for_review(self):
        """Test that bounds violation sets bounds_alert=True and workflow_status='bounds_review'"""
        # Update quantity to out-of-bounds value
        self._update_quantity(620.0)
        
        # Run preflight to trigger the flag
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        # Fetch the document to verify flags
        response = requests.get(f"{BASE_URL}/api/documents/{self.test_doc_id}")
        assert response.status_code == 200
        
        doc = response.json().get('document', {})
        
        # Verify bounds_alert is True
        assert doc.get('bounds_alert') is True, "Expected bounds_alert=True"
        
        # Verify workflow_status is 'bounds_review'
        assert doc.get('workflow_status') == 'bounds_review', f"Expected workflow_status='bounds_review', got {doc.get('workflow_status')}"
        
        # Verify bounds_violations are stored
        violations = doc.get('bounds_violations', [])
        assert len(violations) > 0, "Expected bounds_violations to be stored on document"
    
    def test_validation_checklist_includes_bounds_check(self):
        """Test that validation checklist includes 'Quantity bounds check' item"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        checklist = data.get('validation_checklist', [])
        
        # Find bounds check item
        bounds_item = next((c for c in checklist if 'quantity bounds' in c.get('label', '').lower()), None)
        assert bounds_item is not None, "Validation checklist should include 'Quantity bounds check'"
        assert 'passed' in bounds_item, "Bounds check item should have 'passed' field"
        assert 'detail' in bounds_item, "Bounds check item should have 'detail' field"
    
    def test_deviation_factor_calculation(self):
        """Test that deviation_factor is calculated correctly"""
        # Update quantity to 620 (should be ~205σ away from mean of 60.95)
        self._update_quantity(620.0)
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        violations = data.get('bounds_check', {}).get('violations', [])
        assert len(violations) > 0
        
        v = violations[0]
        # deviation_factor = |620 - 60.95| / 2.72 ≈ 205.53
        assert v.get('deviation_factor', 0) > 200, f"Expected deviation_factor > 200, got {v.get('deviation_factor')}"
    
    def test_severity_critical_for_large_deviation(self):
        """Test that severity is 'critical' for >3σ deviation"""
        self._update_quantity(620.0)  # Way more than 3σ
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{self.test_doc_id}")
        assert response.status_code == 200
        
        data = response.json()
        violations = data.get('bounds_check', {}).get('violations', [])
        assert len(violations) > 0
        
        assert violations[0].get('severity') == 'critical', "Expected severity='critical' for >3σ"
    
    def _update_quantity(self, qty: float):
        """Helper to update the test document's line item quantity via MongoDB"""
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def do_update():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            # Reset bounds_alert and workflow_status first
            await db.hub_documents.update_one(
                {'id': self.test_doc_id},
                {'$set': {
                    'extracted_fields.line_items.0.quantity': qty,
                    'bounds_alert': False,
                    'bounds_violations': [],
                    'workflow_status': 'processed'
                }}
            )
            client.close()
        
        asyncio.run(do_update())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
