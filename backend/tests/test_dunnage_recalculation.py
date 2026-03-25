"""
Test Learned Dunnage Patterns - Dynamic Recalculation Feature

Tests the qty_ratio and trigger_item fields returned by preflight endpoint
and verifies the recalculation logic for dunnage quantities.

Features tested:
- Backend: POST /api/gpi-integration/sales-orders/preflight/{doc_id} returns qty_ratio and trigger_item
- Backend: Suggested quantities are correct for different trigger item quantities
- Backend: Comment lines have no qty_ratio (stay at qty 0)
"""

import pytest
import requests
import os
import time
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_batch_child_docs_from_db():
    """Get batch-child document IDs directly from MongoDB"""
    async def _get_docs():
        client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
        db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
        
        docs = await db.hub_documents.find(
            {'id': {'$regex': '^batch-child'}},
            {'_id': 0, 'id': 1, 'extracted_fields.line_items': 1}
        ).limit(20).to_list(20)
        
        result = {'c9874_docs': {}}
        for doc in docs:
            ef = doc.get('extracted_fields', {})
            items = ef.get('line_items', [])
            for item in items:
                item_no = item.get('item_no', '')
                qty = item.get('quantity', 0)
                if item_no.startswith('C-9874'):
                    result['c9874_docs'][doc['id']] = {
                        'item_no': item_no,
                        'qty': qty
                    }
        
        return result
    
    return asyncio.get_event_loop().run_until_complete(_get_docs())


class TestDunnageRecalculation:
    """Tests for the dynamic dunnage recalculation feature"""
    
    @pytest.fixture(scope="class")
    def batch_job_id(self):
        """Run batch demo to seed pattern data"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        assert response.status_code == 200, f"Batch demo failed: {response.text}"
        data = response.json()
        assert data.get("status") == "started"
        job_id = data.get("job_id")
        
        # Wait for completion (max 90 seconds)
        for _ in range(30):
            time.sleep(3)
            status_resp = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
            if status_resp.status_code == 200:
                status_data = status_resp.json()
                if status_data.get("status") == "completed":
                    return job_id
        
        pytest.fail("Batch demo did not complete in time")
    
    def test_preflight_returns_qty_ratio_and_trigger_item(self, batch_job_id):
        """Test that preflight returns qty_ratio and trigger_item fields on suggested lines"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found")
        
        doc_id = list(c9874_docs.keys())[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        assert len(suggested_lines) >= 3, f"Expected at least 3 suggested lines, got {len(suggested_lines)}"
        
        # Check that Item-type suggested lines have qty_ratio and trigger_item
        item_suggestions = [ln for ln in suggested_lines if ln.get("lineType") == "Item"]
        for line in item_suggestions:
            assert "qty_ratio" in line, f"Missing qty_ratio in line: {line.get('lineObjectNumber')}"
            assert "trigger_item" in line, f"Missing trigger_item in line: {line.get('lineObjectNumber')}"
            assert line.get("trigger_item") is not None, f"trigger_item is None for {line.get('lineObjectNumber')}"
    
    def test_suggested_quantities_correct_for_62M_qty(self, batch_job_id):
        """Test that suggested quantities are correct for C-9874-10001833 (qty 62.062M)"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        # Find doc with C-9874-10001833 (qty 62.062)
        found_doc_id = None
        for doc_id, info in c9874_docs.items():
            if info['item_no'] == 'C-9874-10001833' and abs(info['qty'] - 62.062) < 0.1:
                found_doc_id = doc_id
                break
        
        if not found_doc_id:
            pytest.skip("No batch-child document with C-9874-10001833 (qty 62.062) found")
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        
        # Expected quantities for qty 62.062:
        # OIPALLET: 62.062 * 0.3546 = 22.01 → 22
        # OITIERSHEET: 62.062 * 4.963 = 308.01 → 308
        # OITOPFRAME: 62.062 * 0.3546 = 22.01 → 22
        expected = {
            "OIPALLET": 22,
            "OITIERSHEET": 308,
            "OITOPFRAME": 22,
        }
        
        for line in resolved_lines:
            item_no = line.get("lineObjectNumber", "")
            if item_no in expected:
                actual_qty = line.get("quantity", 0)
                expected_qty = expected[item_no]
                assert actual_qty == expected_qty, f"{item_no}: expected qty {expected_qty}, got {actual_qty}"
    
    def test_suggested_quantities_correct_for_43M_qty(self, batch_job_id):
        """Test that suggested quantities are correct for C-9874-10001290 (qty 43.2M)"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        # Find doc with C-9874-10001290 (qty 43.2)
        found_doc_id = None
        for doc_id, info in c9874_docs.items():
            if info['item_no'] == 'C-9874-10001290' and abs(info['qty'] - 43.2) < 0.1:
                found_doc_id = doc_id
                break
        
        if not found_doc_id:
            pytest.skip("No batch-child document with C-9874-10001290 (qty 43.2) found")
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        
        # Expected quantities for qty 43.2:
        # OIPALLET: 43.2 * 0.3546 = 15.32 → 15
        # OITIERSHEET: 43.2 * 4.963 = 214.40 → 214
        # OITOPFRAME: 43.2 * 0.3546 = 15.32 → 15
        expected = {
            "OIPALLET": 15,
            "OITIERSHEET": 214,
            "OITOPFRAME": 15,
        }
        
        for line in resolved_lines:
            item_no = line.get("lineObjectNumber", "")
            if item_no in expected:
                actual_qty = line.get("quantity", 0)
                expected_qty = expected[item_no]
                assert actual_qty == expected_qty, f"{item_no}: expected qty {expected_qty}, got {actual_qty}"
    
    def test_comment_lines_have_no_qty_ratio(self, batch_job_id):
        """Test that Comment lines have no qty_ratio and stay at qty 0"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found")
        
        doc_id = list(c9874_docs.keys())[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Find Comment-type suggested lines
        comment_suggestions = [ln for ln in suggested_lines if ln.get("lineType") == "Comment" or not ln.get("lineObjectNumber")]
        
        for line in comment_suggestions:
            qty_ratio = line.get("qty_ratio")
            qty = line.get("quantity", 0)
            
            # Comment lines should have qty_ratio=None and qty=0
            assert qty_ratio is None, f"Comment line should have qty_ratio=None, got {qty_ratio}"
            assert qty == 0, f"Comment line should have qty=0, got {qty}"
    
    def test_recalculation_formula_accuracy(self, batch_job_id):
        """Test that qty_ratio * trigger_qty = suggested_qty (rounded)"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found")
        
        doc_id = list(c9874_docs.keys())[0]
        doc_info = c9874_docs[doc_id]
        trigger_qty = doc_info['qty']
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Verify recalculation formula for Item-type suggestions
        item_suggestions = [ln for ln in suggested_lines if ln.get("lineType") == "Item" and ln.get("qty_ratio")]
        
        for line in item_suggestions:
            qty_ratio = line.get("qty_ratio")
            actual_qty = line.get("quantity", 0)
            expected_qty = round(trigger_qty * qty_ratio)
            
            assert actual_qty == expected_qty, (
                f"{line.get('lineObjectNumber')}: "
                f"expected {trigger_qty} * {qty_ratio} = {expected_qty}, got {actual_qty}"
            )


class TestPreflightQtyRatioFields:
    """Tests for qty_ratio and trigger_item field presence"""
    
    def test_preflight_returns_fixed_qty_for_fixed_quantity_items(self):
        """Test that fixed_qty is returned for items with fixed quantities"""
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', {})
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found")
        
        doc_id = list(c9874_docs.keys())[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Check that suggested lines have either qty_ratio or fixed_qty (or neither for comments)
        for line in suggested_lines:
            has_qty_ratio = line.get("qty_ratio") is not None
            has_fixed_qty = line.get("fixed_qty") is not None
            is_comment = line.get("lineType") == "Comment" or not line.get("lineObjectNumber")
            
            if not is_comment:
                # Item-type suggestions should have qty_ratio or fixed_qty
                assert has_qty_ratio or has_fixed_qty, (
                    f"Item suggestion {line.get('lineObjectNumber')} should have qty_ratio or fixed_qty"
                )
