"""
Batch PO Split Demo API Tests

Tests the batch PO splitting feature:
- POST /api/sales-dashboard/demo/run-batch - Start batch job (returns immediately with job_id)
- GET /api/sales-dashboard/demo/batch-status/{job_id} - Poll for job progress
- Background processing: started -> ingesting -> detecting -> splitting -> summarizing -> completed
- Child documents with page/type/customer/confidence/assigned_rep/queue data
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBatchPOSplitDemo:
    """Tests for Batch PO Split Demo feature"""

    def test_run_batch_returns_immediately(self):
        """POST /api/sales-dashboard/demo/run-batch returns immediately with job_id"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run-batch")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "job_id" in data, "Response should contain job_id"
        assert "status" in data, "Response should contain status"
        assert data["status"] == "started", f"Expected status 'started', got {data['status']}"
        assert "total_pages" in data, "Response should contain total_pages"
        assert data["total_pages"] == 5, f"Expected 5 pages, got {data['total_pages']}"
        assert "message" in data, "Response should contain message"
        
        # Store job_id for subsequent tests
        TestBatchPOSplitDemo.job_id = data["job_id"]
        print(f"✓ Batch job started with job_id: {data['job_id']}")

    def test_batch_status_endpoint_exists(self):
        """GET /api/sales-dashboard/demo/batch-status/{job_id} returns job progress"""
        job_id = getattr(TestBatchPOSplitDemo, 'job_id', None)
        if not job_id:
            pytest.skip("No job_id from previous test")
        
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "job_id" in data, "Response should contain job_id"
        assert data["job_id"] == job_id, "job_id should match"
        assert "status" in data, "Response should contain status"
        assert "steps" in data, "Response should contain steps array"
        assert "total_pages" in data, "Response should contain total_pages"
        
        print(f"✓ Batch status endpoint working, current status: {data['status']}")

    def test_batch_status_404_for_invalid_job(self):
        """GET /api/sales-dashboard/demo/batch-status/{invalid_id} returns 404"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/invalid-job-id-12345")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid job_id returns 404")

    def test_batch_processing_completes(self):
        """Background processing completes with all steps"""
        job_id = getattr(TestBatchPOSplitDemo, 'job_id', None)
        if not job_id:
            pytest.skip("No job_id from previous test")
        
        # Poll for completion (max 120 seconds)
        max_wait = 120
        poll_interval = 5
        elapsed = 0
        final_data = None
        
        while elapsed < max_wait:
            response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
            assert response.status_code == 200
            
            data = response.json()
            status = data.get("status", "")
            
            print(f"  Polling... status={status}, steps={len(data.get('steps', []))}, elapsed={elapsed}s")
            
            if status == "completed":
                final_data = data
                break
            elif status == "error":
                pytest.fail(f"Batch job failed with error: {data.get('error', 'Unknown')}")
            
            time.sleep(poll_interval)
            elapsed += poll_interval
        
        assert final_data is not None, f"Batch job did not complete within {max_wait}s"
        assert final_data["status"] == "completed", f"Expected 'completed', got {final_data['status']}"
        
        # Verify all 5 steps completed
        steps = final_data.get("steps", [])
        assert len(steps) == 5, f"Expected 5 steps, got {len(steps)}"
        
        step_names = [s["name"] for s in steps]
        expected_steps = [
            "Batch PO Generation",
            "Parent Document Ingestion",
            "Batch PO Detection",
            "Page Splitting & Full Pipeline",
            "Child Documents Summary"
        ]
        for expected in expected_steps:
            assert expected in step_names, f"Missing step: {expected}"
        
        # Store final data for subsequent tests
        TestBatchPOSplitDemo.final_data = final_data
        print(f"✓ Batch processing completed in {final_data.get('total_duration_ms', 0)}ms")

    def test_completed_batch_has_5_children(self):
        """Completed batch job has 5 children entries"""
        final_data = getattr(TestBatchPOSplitDemo, 'final_data', None)
        if not final_data:
            pytest.skip("No final_data from previous test")
        
        children = final_data.get("children", [])
        assert len(children) == 5, f"Expected 5 children, got {len(children)}"
        
        # Verify children_created count
        assert final_data.get("children_created") == 5, "children_created should be 5"
        
        print(f"✓ Batch has 5 children documents")

    def test_children_have_required_fields(self):
        """Each child has page/type/customer/confidence/assigned_rep/queue data"""
        final_data = getattr(TestBatchPOSplitDemo, 'final_data', None)
        if not final_data:
            pytest.skip("No final_data from previous test")
        
        children = final_data.get("children", [])
        required_fields = ["page", "doc_id", "type", "po_number", "confidence", "assigned_rep", "queue"]
        
        for i, child in enumerate(children):
            for field in required_fields:
                assert field in child, f"Child {i+1} missing field: {field}"
            
            # Verify page numbers are 1-5
            assert child["page"] == i + 1, f"Child {i+1} has wrong page number: {child['page']}"
            
            # Verify type is Sales_Order
            assert child["type"] in ["Sales_Order", "SalesOrder", "PurchaseOrder"], f"Unexpected type: {child['type']}"
            
            # Verify confidence is a number between 0 and 1
            assert 0 <= child["confidence"] <= 1, f"Invalid confidence: {child['confidence']}"
            
            # Verify queue is either "My Queue" or "Triage"
            assert child["queue"] in ["My Queue", "Triage"], f"Invalid queue: {child['queue']}"
        
        print("✓ All children have required fields with valid values")

    def test_children_have_po_numbers(self):
        """Children have PO numbers extracted (PO-61312 through PO-61316)"""
        final_data = getattr(TestBatchPOSplitDemo, 'final_data', None)
        if not final_data:
            pytest.skip("No final_data from previous test")
        
        children = final_data.get("children", [])
        expected_pos = ["PO-61312", "PO-61313", "PO-61314", "PO-61315", "PO-61316"]
        
        extracted_pos = [c.get("po_number", "") for c in children]
        
        for expected_po in expected_pos:
            assert expected_po in extracted_pos, f"Missing PO number: {expected_po}"
        
        print(f"✓ All PO numbers extracted: {extracted_pos}")

    def test_step_details_structure(self):
        """Each step has proper details structure"""
        final_data = getattr(TestBatchPOSplitDemo, 'final_data', None)
        if not final_data:
            pytest.skip("No final_data from previous test")
        
        steps = final_data.get("steps", [])
        
        # Step 1: Batch PO Generation
        step1 = next((s for s in steps if s["step"] == 1), None)
        assert step1 is not None, "Step 1 not found"
        assert "details" in step1, "Step 1 missing details"
        assert "filename" in step1["details"], "Step 1 missing filename"
        assert "pages" in step1["details"], "Step 1 missing pages"
        assert step1["details"]["pages"] == 5, "Step 1 should have 5 pages"
        
        # Step 2: Parent Document Ingestion
        step2 = next((s for s in steps if s["step"] == 2), None)
        assert step2 is not None, "Step 2 not found"
        assert "parent_doc_id" in step2["details"], "Step 2 missing parent_doc_id"
        
        # Step 3: Batch PO Detection
        step3 = next((s for s in steps if s["step"] == 3), None)
        assert step3 is not None, "Step 3 not found"
        assert step3["details"].get("batch_detected") == True, "batch_detected should be True"
        
        # Step 4: Page Splitting
        step4 = next((s for s in steps if s["step"] == 4), None)
        assert step4 is not None, "Step 4 not found"
        assert step4["details"].get("pages_split") == 5, "pages_split should be 5"
        assert step4["details"].get("children_created") == 5, "children_created should be 5"
        assert step4["details"].get("errors") == 0, "errors should be 0"
        
        # Step 5: Child Documents Summary
        step5 = next((s for s in steps if s["step"] == 5), None)
        assert step5 is not None, "Step 5 not found"
        assert "children" in step5["details"], "Step 5 missing children"
        
        print("✓ All steps have proper details structure")


class TestSinglePOPipelineDemo:
    """Tests for Single PO Pipeline Demo (Run Pipeline button)"""

    def test_scenarios_endpoint(self):
        """GET /api/sales-dashboard/demo/scenarios returns available scenarios"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/scenarios")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "scenarios" in data, "Response should contain scenarios"
        assert len(data["scenarios"]) >= 4, f"Expected at least 4 scenarios, got {len(data['scenarios'])}"
        
        # Verify scenario structure
        for scenario in data["scenarios"]:
            assert "id" in scenario, "Scenario missing id"
            assert "label" in scenario, "Scenario missing label"
            assert "customer" in scenario, "Scenario missing customer"
            assert "po_number" in scenario, "Scenario missing po_number"
        
        print(f"✓ Scenarios endpoint returns {len(data['scenarios'])} scenarios")

    def test_run_pipeline_demo(self):
        """POST /api/sales-dashboard/demo/run runs single PO pipeline"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run?scenario_id=bragg-rush")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "status" in data, "Response should contain status"
        assert data["status"] == "success", f"Expected 'success', got {data['status']}"
        assert "steps" in data, "Response should contain steps"
        assert "document_id" in data, "Response should contain document_id"
        assert "total_duration_ms" in data, "Response should contain total_duration_ms"
        
        # Verify 7 steps for single PO pipeline
        assert len(data["steps"]) == 7, f"Expected 7 steps, got {len(data['steps'])}"
        
        print(f"✓ Single PO pipeline completed in {data['total_duration_ms']}ms")

    def test_run_pipeline_invalid_scenario(self):
        """POST /api/sales-dashboard/demo/run with invalid scenario returns 404"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/demo/run?scenario_id=invalid-scenario")
        
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid scenario returns 404")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
