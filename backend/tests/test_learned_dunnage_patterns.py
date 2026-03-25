"""
Test Learned Dunnage Patterns Feature

Tests the pattern learning and suggestion system that auto-suggests
dunnage lines (pallets, tier sheets, top frames) based on historical orders.

Features tested:
- POST /api/gpi-integration/sales-orders/preflight/{doc_id} returns pattern_suggestions
- Suggested lines have correct quantities for C-9874 items
- Pattern suggestions are separated from regular lines with suggested=True
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
        
        result = {'c9874_docs': [], 'non_c9874_docs': []}
        for doc in docs:
            ef = doc.get('extracted_fields', {})
            items = ef.get('line_items', [])
            has_c9874 = any(item.get('item_no', '').startswith('C-9874') for item in items)
            if has_c9874:
                result['c9874_docs'].append(doc['id'])
            else:
                result['non_c9874_docs'].append(doc['id'])
        
        return result
    
    return asyncio.get_event_loop().run_until_complete(_get_docs())

class TestLearnedDunnagePatterns:
    """Tests for the Learned Dunnage Patterns feature"""
    
    @pytest.fixture(scope="class")
    def batch_job_id(self):
        """Run batch demo to seed pattern data and get batch-child doc IDs"""
        # Run batch demo
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
    
    def test_batch_demo_seeds_pattern_data(self, batch_job_id):
        """Verify batch demo completed and seeded pattern data"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{batch_job_id}")
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("status") == "completed"
        assert data.get("children_created") == 5
        assert data.get("total_pages") == 5
        
        # Verify steps completed
        steps = data.get("steps", [])
        assert len(steps) >= 5
        for step in steps:
            assert step.get("status") == "completed", f"Step {step.get('name')} not completed"
    
    def test_preflight_returns_pattern_suggestions_for_c9874_item(self, batch_job_id):
        """Test that preflight returns pattern suggestions for C-9874 items"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', [])
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found in database")
        
        found_c9874_doc = c9874_docs[0]
        
        # Now test the preflight response
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_c9874_doc}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify basic preflight response
        assert data.get("ready") == True
        assert data.get("mapped_values", {}).get("customer_no") == "C-10250"
        
        # Verify pattern suggestions are present
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        assert len(suggested_lines) >= 3, f"Expected at least 3 suggested lines, got {len(suggested_lines)}"
        
        # Verify suggested lines have correct source
        for line in suggested_lines:
            assert line.get("source") == "learned_pattern"
            assert line.get("pattern_confidence") is not None
    
    def test_preflight_suggested_lines_have_correct_quantities(self, batch_job_id):
        """Test that suggested dunnage lines have correct quantities"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', [])
        
        # Find doc with C-9874-10001833 (qty 62.062)
        found_doc_id = None
        for doc_id in c9874_docs:
            preflight_resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
            if preflight_resp.status_code == 200:
                pf_data = preflight_resp.json()
                for line in pf_data.get("resolved_lines", []):
                    if line.get("lineObjectNumber") == "C-9874-10001833":
                        found_doc_id = doc_id
                        break
            if found_doc_id:
                break
        
        if not found_doc_id:
            pytest.skip("No batch-child document with C-9874-10001833 found")
        
        # Get preflight data
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        
        # Find the dunnage items and verify quantities
        # Based on qty_ratio values in sales_pipeline_demo.py:
        # OIPALLET: qty_ratio=0.3546, qty=62.062*0.3546=22
        # OITIERSHEET: qty_ratio=4.963, qty=62.062*4.963=308
        # OITOPFRAME: qty_ratio=0.3546, qty=62.062*0.3546=22
        
        expected_quantities = {
            "OIPALLET": 22,
            "OITIERSHEET": 308,
            "OITOPFRAME": 22,
        }
        
        for line in resolved_lines:
            item_no = line.get("lineObjectNumber", "")
            if item_no in expected_quantities:
                expected_qty = expected_quantities[item_no]
                actual_qty = line.get("quantity", 0)
                assert actual_qty == expected_qty, f"{item_no}: expected qty {expected_qty}, got {actual_qty}"
    
    def test_preflight_separates_suggested_from_regular_lines(self, batch_job_id):
        """Test that suggested lines are marked separately from regular lines"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        c9874_docs = batch_docs.get('c9874_docs', [])
        
        if not c9874_docs:
            pytest.skip("No batch-child document with C-9874 item found")
        
        found_doc_id = c9874_docs[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        
        # Separate regular and suggested lines
        regular_lines = [ln for ln in resolved_lines if not ln.get("suggested")]
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Verify we have both types
        assert len(regular_lines) >= 1, "Expected at least 1 regular line"
        assert len(suggested_lines) >= 3, "Expected at least 3 suggested lines"
        
        # Verify regular lines don't have suggested flag
        for line in regular_lines:
            assert line.get("suggested") is None or line.get("suggested") == False
            assert line.get("source") != "learned_pattern"
        
        # Verify suggested lines have correct attributes
        for line in suggested_lines:
            assert line.get("suggested") == True
            assert line.get("source") == "learned_pattern"
            assert line.get("pattern_confidence") is not None
    
    def test_preflight_no_suggestions_for_non_c9874_items(self, batch_job_id):
        """Test that non-C-9874 items don't get dunnage suggestions"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        non_c9874_docs = batch_docs.get('non_c9874_docs', [])
        
        if not non_c9874_docs:
            pytest.skip("No batch-child document without C-9874 item found")
        
        found_doc_id = non_c9874_docs[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        resolved_lines = data.get("resolved_lines", [])
        suggested_lines = [ln for ln in resolved_lines if ln.get("suggested") == True]
        
        # Should have no or minimal suggestions for non-C-9874 items
        # (The pattern is only seeded for C-9874 items)
        dunnage_suggestions = [ln for ln in suggested_lines if ln.get("lineObjectNumber") in ["OIPALLET", "OITIERSHEET", "OITOPFRAME"]]
        assert len(dunnage_suggestions) == 0, f"Expected no dunnage suggestions for non-C-9874 items, got {len(dunnage_suggestions)}"
    
    def test_preflight_customer_c10250_giovanni(self, batch_job_id):
        """Test that preflight correctly identifies Giovanni customer C-10250"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        all_docs = batch_docs.get('c9874_docs', []) + batch_docs.get('non_c9874_docs', [])
        
        if not all_docs:
            pytest.skip("No batch-child document found")
        
        found_doc_id = all_docs[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        mapped_values = data.get("mapped_values", {})
        assert mapped_values.get("customer_no") == "C-10250"
        assert "Giovanni" in mapped_values.get("customer_name", "")


class TestPreflightEndpointBasics:
    """Basic tests for the preflight endpoint"""
    
    def test_preflight_returns_404_for_nonexistent_doc(self):
        """Test that preflight returns 404 for non-existent document"""
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/nonexistent-doc-id")
        assert response.status_code == 404
    
    def test_preflight_returns_ready_status(self):
        """Test that preflight returns ready status for valid documents"""
        # Get batch-child docs from database
        batch_docs = get_batch_child_docs_from_db()
        all_docs = batch_docs.get('c9874_docs', []) + batch_docs.get('non_c9874_docs', [])
        
        if not all_docs:
            # Run batch demo first
            batch_resp = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
            assert batch_resp.status_code == 200
            job_id = batch_resp.json().get("job_id")
            
            # Wait for completion
            for _ in range(30):
                time.sleep(3)
                status_resp = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
                if status_resp.status_code == 200 and status_resp.json().get("status") == "completed":
                    break
            
            # Try again
            batch_docs = get_batch_child_docs_from_db()
            all_docs = batch_docs.get('c9874_docs', []) + batch_docs.get('non_c9874_docs', [])
        
        if not all_docs:
            pytest.skip("No batch-child document found")
        
        found_doc_id = all_docs[0]
        
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{found_doc_id}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "ready" in data
        assert "eligible" in data
        assert "resolved_lines" in data
        assert "mapped_values" in data
        assert "validation_checklist" in data
