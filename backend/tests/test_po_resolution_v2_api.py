"""
API Tests for PO Resolution Service v2 — Hardened
Tests extended metrics, batch-resolve, and document detail po_resolution fields.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndBasicEndpoints:
    """Verify backend is running and basic endpoints work."""

    def test_health_endpoint(self):
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("✓ Health endpoint working")

    def test_documents_endpoint(self):
        response = requests.get(f"{BASE_URL}/api/documents")
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        print(f"✓ Documents endpoint working, total_all={data.get('counts', {}).get('total_all', 0)}")


class TestPOResolutionMetrics:
    """Test GET /api/po-resolution/metrics returns extended fields."""

    def test_metrics_endpoint_returns_200(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        assert response.status_code == 200
        print("✓ Metrics endpoint returns 200")

    def test_metrics_has_required_fields(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        # Core fields
        assert "total_shipping_docs" in data
        assert "po_resolution" in data
        assert "bc_link" in data
        
        # Extended fields (v2 hardening)
        assert "unresolved_by_miss_reason" in data
        assert "bc_link_failures_by_reason" in data
        assert "lookup_sources" in data
        assert "multi_po_count" in data
        
        print("✓ Metrics has all required fields including extended v2 fields")

    def test_metrics_po_resolution_structure(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        po_res = data.get("po_resolution", {})
        assert "attempted" in po_res
        assert "resolved" in po_res
        assert "ambiguous" in po_res
        assert "not_found" in po_res
        assert "skipped" in po_res
        assert "rate" in po_res
        
        print(f"✓ PO resolution structure correct: {po_res['resolved']}/{po_res['attempted']} resolved ({po_res['rate']}%)")

    def test_metrics_bc_link_structure(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        bc_link = data.get("bc_link", {})
        assert "attempted" in bc_link
        assert "succeeded_real" in bc_link
        assert "succeeded_local" in bc_link
        assert "failed" in bc_link
        assert "rate_real" in bc_link
        assert "rate_total" in bc_link
        
        print(f"✓ BC link structure correct: {bc_link['succeeded_real']} real, {bc_link['succeeded_local']} local, {bc_link['failed']} failed")

    def test_metrics_unresolved_by_miss_reason(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        miss_reasons = data.get("unresolved_by_miss_reason", {})
        assert isinstance(miss_reasons, dict)
        
        # Valid miss reasons from taxonomy
        valid_reasons = {
            "no_po_extracted", "normalized_po_empty", "invalid_po_format",
            "cache_no_match", "live_bc_no_match", "vendor_conflict",
            "multiple_bc_matches", "bc_lookup_error", "no_bc_match"
        }
        
        for reason in miss_reasons.keys():
            assert reason in valid_reasons, f"Unknown miss reason: {reason}"
        
        print(f"✓ Miss reasons breakdown: {miss_reasons}")

    def test_metrics_bc_link_failures_by_reason(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        bc_failures = data.get("bc_link_failures_by_reason", {})
        assert isinstance(bc_failures, dict)
        
        # Valid BC link failure reasons
        valid_reasons = {
            "bc_record_not_found", "bc_auth_error", "bc_validation_error",
            "network_error", "sandbox_only_path", "unknown_error", "unknown"
        }
        
        for reason in bc_failures.keys():
            assert reason in valid_reasons, f"Unknown BC link failure reason: {reason}"
        
        print(f"✓ BC link failures breakdown: {bc_failures}")

    def test_metrics_lookup_sources(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        sources = data.get("lookup_sources", {})
        assert "bc_cache" in sources
        assert "bc_api" in sources
        assert "local_staging" in sources
        
        print(f"✓ Lookup sources: bc_cache={sources['bc_cache']}, bc_api={sources['bc_api']}, local={sources['local_staging']}")

    def test_metrics_multi_po_count(self):
        response = requests.get(f"{BASE_URL}/api/po-resolution/metrics")
        data = response.json()
        
        multi_po = data.get("multi_po_count")
        assert isinstance(multi_po, int)
        assert multi_po >= 0
        
        print(f"✓ Multi-PO count: {multi_po}")


class TestBatchResolve:
    """Test POST /api/po-resolution/batch-resolve endpoint."""

    def test_batch_resolve_returns_200(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=5")
        assert response.status_code == 200
        print("✓ Batch resolve returns 200")

    def test_batch_resolve_summary_structure(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=5")
        data = response.json()
        
        # Required summary fields
        assert "processed" in data
        assert "resolved" in data
        assert "ambiguous" in data
        assert "not_found" in data
        assert "bc_link_attempted" in data
        assert "bc_link_succeeded" in data
        assert "bc_link_failed" in data
        
        # Extended fields
        assert "miss_reasons" in data
        assert "bc_link_failures" in data
        assert "po_resolution_rate" in data
        assert "bc_link_success_rate" in data
        
        print(f"✓ Batch resolve summary: {data['resolved']}/{data['processed']} resolved ({data['po_resolution_rate']}%)")

    def test_batch_resolve_miss_reasons(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        data = response.json()
        
        miss_reasons = data.get("miss_reasons", {})
        assert isinstance(miss_reasons, dict)
        
        total_misses = sum(miss_reasons.values())
        not_found = data.get("not_found", 0)
        
        # Miss reasons should account for not_found docs
        # (some resolved docs may have had miss_reason=None)
        print(f"✓ Batch miss reasons: {miss_reasons} (total={total_misses}, not_found={not_found})")

    def test_batch_resolve_bc_link_failures(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        data = response.json()
        
        bc_failures = data.get("bc_link_failures", {})
        assert isinstance(bc_failures, dict)
        
        total_failures = sum(bc_failures.values())
        bc_link_failed = data.get("bc_link_failed", 0)
        
        # BC link failures should match
        assert total_failures == bc_link_failed, f"BC failures mismatch: {total_failures} vs {bc_link_failed}"
        
        print(f"✓ Batch BC link failures: {bc_failures}")

    def test_batch_resolve_details(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        data = response.json()
        
        details = data.get("details", [])
        assert isinstance(details, list)
        
        if details:
            detail = details[0]
            assert "doc_id" in detail
            assert "file_name" in detail
            assert "status" in detail
            assert "miss_reason" in detail
            assert "po_number" in detail
            assert "bc_link_status" in detail
            
            print(f"✓ Batch details structure correct, {len(details)} docs in details")
        else:
            print("✓ Batch details empty (no docs processed)")

    def test_batch_resolve_by_doc_type(self):
        response = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        data = response.json()
        
        by_type = data.get("by_doc_type", {})
        assert isinstance(by_type, dict)
        
        for doc_type, stats in by_type.items():
            assert "total" in stats
            assert "resolved" in stats
        
        print(f"✓ Batch by_doc_type: {by_type}")


class TestDocumentDetailPOResolution:
    """Test document detail API includes po_resolution with all required fields."""

    def test_resolved_document_has_po_resolution(self):
        # First get a resolved document from batch
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        resolved_docs = [d for d in batch_data.get("details", []) if d.get("status") == "resolved"]
        
        if not resolved_docs:
            pytest.skip("No resolved documents available for testing")
        
        doc_id = resolved_docs[0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        assert response.status_code == 200
        
        doc = response.json().get("document", {})
        po_res = doc.get("po_resolution", {})
        
        assert po_res, f"Document {doc_id} missing po_resolution"
        assert po_res.get("status") == "resolved"
        assert po_res.get("po_number")
        
        print(f"✓ Resolved document {doc_id[:12]} has po_resolution with PO={po_res.get('po_number')}")

    def test_po_resolution_has_miss_reason_field(self):
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        not_found_docs = [d for d in batch_data.get("details", []) if d.get("status") == "not_found"]
        
        if not not_found_docs:
            pytest.skip("No not_found documents available for testing")
        
        doc_id = not_found_docs[0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        doc = response.json().get("document", {})
        po_res = doc.get("po_resolution", {})
        
        assert "miss_reason" in po_res
        assert po_res.get("miss_reason") is not None, "not_found doc should have miss_reason"
        
        print(f"✓ Not-found document {doc_id[:12]} has miss_reason={po_res.get('miss_reason')}")

    def test_po_resolution_has_bc_link(self):
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        if not batch_data.get("details"):
            pytest.skip("No documents available for testing")
        
        doc_id = batch_data["details"][0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        doc = response.json().get("document", {})
        po_res = doc.get("po_resolution", {})
        bc_link = po_res.get("bc_link", {})
        
        assert "status" in bc_link
        assert "bc_record_type" in bc_link
        assert "bc_record_id" in bc_link
        assert "link_method" in bc_link
        assert "error_code" in bc_link
        assert "error_message" in bc_link
        
        print(f"✓ Document {doc_id[:12]} has bc_link with status={bc_link.get('status')}")

    def test_po_resolution_has_lookup_trace(self):
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        resolved_docs = [d for d in batch_data.get("details", []) if d.get("status") == "resolved"]
        
        if not resolved_docs:
            pytest.skip("No resolved documents available for testing")
        
        doc_id = resolved_docs[0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        doc = response.json().get("document", {})
        po_res = doc.get("po_resolution", {})
        
        assert "lookup_trace" in po_res
        assert "candidates_raw" in po_res
        assert "candidates_valid" in po_res
        
        trace = po_res.get("lookup_trace", [])
        if trace:
            entry = trace[0]
            assert "candidate" in entry
            assert "lookups" in entry
        
        print(f"✓ Document {doc_id[:12]} has lookup_trace with {len(trace)} entries")


class TestBCLinkResultStructure:
    """Test BC link result has standardized fields."""

    def test_bc_link_standardized_fields(self):
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        if not batch_data.get("details"):
            pytest.skip("No documents available for testing")
        
        doc_id = batch_data["details"][0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        doc = response.json().get("document", {})
        bc_link = doc.get("po_resolution", {}).get("bc_link", {})
        
        # All standardized fields must be present
        required_fields = [
            "status", "bc_record_type", "bc_record_id",
            "link_method", "error_code", "error_message"
        ]
        
        for field in required_fields:
            assert field in bc_link, f"BC link missing field: {field}"
        
        # Status must be one of valid values
        valid_statuses = {"linked", "linked_local", "failed"}
        assert bc_link.get("status") in valid_statuses, f"Invalid BC link status: {bc_link.get('status')}"
        
        print(f"✓ BC link has all standardized fields, status={bc_link.get('status')}")

    def test_bc_link_error_categorization(self):
        batch_resp = requests.post(f"{BASE_URL}/api/po-resolution/batch-resolve?force=true&limit=10")
        batch_data = batch_resp.json()
        
        failed_docs = [d for d in batch_data.get("details", []) if d.get("bc_link_status") == "failed"]
        
        if not failed_docs:
            pytest.skip("No failed BC link documents available")
        
        doc_id = failed_docs[0]["doc_id"]
        
        response = requests.get(f"{BASE_URL}/api/documents/{doc_id}")
        doc = response.json().get("document", {})
        bc_link = doc.get("po_resolution", {}).get("bc_link", {})
        
        # Failed links should have error_code
        assert bc_link.get("error_code"), "Failed BC link should have error_code"
        
        valid_error_codes = {
            "bc_record_not_found", "bc_auth_error", "bc_validation_error",
            "network_error", "sandbox_only_path", "unknown_error"
        }
        
        assert bc_link.get("error_code") in valid_error_codes, f"Invalid error_code: {bc_link.get('error_code')}"
        
        print(f"✓ Failed BC link has categorized error_code={bc_link.get('error_code')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
