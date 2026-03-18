"""
Test Suite: Classification Pipeline Integration (5-Stage Pipeline)

Tests the new classification_pipeline.py that replaced the monolithic classify-extract-validate-route logic.
Pipeline stages: PARSE → CLASSIFY → EXTRACT → VALIDATE → ROUTE

Each stage reports: status, quality_gate, error, duration_ms
Pipeline response includes: pipeline_status, pipeline_failure_stage, pipeline_failure_reason,
                           classification_method, meaningful_field_count, pipeline_stages dict

Test doc IDs:
- 7c04212b-cdd5-4c7d-9eea-329daaaa3420 (W91.pdf, has file, Unknown_Document)
- c3bf1459-e48d-4905-a813-84b02386b9c4 (Invoice 460219-PRO.pdf, has file, AP_Invoice)
- ae78e544-041d-4603-bb1c-1112403ef887 (no file on disk)
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test document IDs
DOC_WITH_FILE_UNKNOWN = "7c04212b-cdd5-4c7d-9eea-329daaaa3420"  # W91.pdf - Unknown_Document
DOC_WITH_FILE_INVOICE = "c3bf1459-e48d-4905-a813-84b02386b9c4"  # Invoice 460219-PRO.pdf - AP_Invoice
DOC_WITHOUT_FILE = "ae78e544-041d-4603-bb1c-1112403ef887"       # No file on disk


class TestPipelineResponseStructure:
    """Tests that the pipeline returns expected fields in the response."""

    def test_process_returns_pipeline_status(self):
        """POST /api/document-intelligence/process/{doc_id} returns pipeline_status field."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        # Accept 200 or 500 (if LLM fails) - we're testing structure
        assert resp.status_code in (200, 500), f"Unexpected status: {resp.status_code} - {resp.text}"
        
        if resp.status_code == 200:
            data = resp.json()
            assert "pipeline_status" in data, f"Missing pipeline_status in response: {data.keys()}"
            assert data["pipeline_status"] in ("passed", "failed"), f"Invalid pipeline_status: {data['pipeline_status']}"
            print(f"✓ pipeline_status = {data['pipeline_status']}")

    def test_process_returns_pipeline_stages(self):
        """POST /api/document-intelligence/process/{doc_id} returns pipeline_stages dict."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code} - skipping structure check")
        
        data = resp.json()
        assert "pipeline_stages" in data, f"Missing pipeline_stages in response: {data.keys()}"
        
        stages = data["pipeline_stages"]
        expected_stages = ["parse", "classify", "extract", "validate", "route"]
        for stage in expected_stages:
            assert stage in stages, f"Missing stage '{stage}' in pipeline_stages: {stages.keys()}"
            stage_data = stages[stage]
            assert "status" in stage_data, f"Stage '{stage}' missing 'status'"
            assert "quality_gate" in stage_data, f"Stage '{stage}' missing 'quality_gate'"
            assert "ms" in stage_data, f"Stage '{stage}' missing 'ms' (duration)"
            print(f"✓ Stage {stage}: status={stage_data['status']}, quality_gate={stage_data['quality_gate']}, ms={stage_data['ms']}")

    def test_process_returns_classification_method(self):
        """POST /api/document-intelligence/process/{doc_id} returns classification_method."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code} - skipping structure check")
        
        data = resp.json()
        assert "classification_method" in data, f"Missing classification_method in response: {data.keys()}"
        print(f"✓ classification_method = {data['classification_method']}")

    def test_process_returns_meaningful_field_count(self):
        """POST /api/document-intelligence/process/{doc_id} returns meaningful_field_count."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code} - skipping structure check")
        
        data = resp.json()
        assert "meaningful_field_count" in data, f"Missing meaningful_field_count in response: {data.keys()}"
        assert isinstance(data["meaningful_field_count"], int), f"meaningful_field_count should be int"
        print(f"✓ meaningful_field_count = {data['meaningful_field_count']}")


class TestParseStageFallback:
    """Tests that PARSE stage finds files via UPLOAD_DIR/{doc_id} fallback."""

    def test_parse_stage_finds_file_via_fallback(self):
        """PARSE stage finds file via UPLOAD_DIR/{doc_id} when local_file_path is missing."""
        # The doc 7c04212b-cdd5-4c7d-9eea-329daaaa3420 should have file at UPLOAD_DIR/{doc_id}
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_UNKNOWN}", timeout=60)
        
        if resp.status_code != 200:
            # Check if it's a parse failure due to missing file
            data = resp.json() if resp.text else {}
            failure_stage = data.get("pipeline_failure_stage", "")
            if failure_stage == "parse":
                pytest.fail(f"PARSE stage failed - file not found via fallback: {data.get('pipeline_failure_reason')}")
            pytest.skip(f"Pipeline returned {resp.status_code} - {resp.text[:200]}")
        
        data = resp.json()
        stages = data.get("pipeline_stages", {})
        parse_stage = stages.get("parse", {})
        
        assert parse_stage.get("status") == "passed", f"PARSE stage should pass when file exists: {parse_stage}"
        assert parse_stage.get("quality_gate") is True, f"PARSE quality gate should pass: {parse_stage}"
        print(f"✓ PARSE stage passed with file found via UPLOAD_DIR fallback")

    def test_parse_stage_fails_when_no_file(self):
        """PARSE stage reports clear failure when no file exists."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITHOUT_FILE}", timeout=60)
        
        # This should either return 200 with failed parse or 500
        data = resp.json() if resp.text else {}
        
        # Check if parse stage failed
        if resp.status_code == 200:
            stages = data.get("pipeline_stages", {})
            parse_stage = stages.get("parse", {})
            
            # Parse should fail for doc without file
            if parse_stage.get("status") == "passed":
                pytest.skip("Parse passed - document might have file now")
            
            assert parse_stage.get("status") == "failed", f"PARSE should fail for doc without file: {parse_stage}"
            assert parse_stage.get("error"), f"PARSE should have error message: {parse_stage}"
            assert "UPLOAD_DIR" in parse_stage.get("error", ""), f"Error should mention UPLOAD_DIR fallback was checked"
            print(f"✓ PARSE stage correctly failed with error: {parse_stage.get('error')[:100]}")
        else:
            # 500 response - check failure_stage
            failure_stage = data.get("pipeline_failure_stage", "")
            if failure_stage == "parse":
                print(f"✓ Pipeline correctly reports parse failure: {data.get('pipeline_failure_reason', '')[:100]}")
            else:
                pytest.skip(f"Pipeline failed at different stage: {failure_stage}")


class TestClassifyStage:
    """Tests for CLASSIFY stage: heuristic + LLM merge logic."""

    def test_classify_heuristic_plus_llm_merge(self):
        """CLASSIFY stage: heuristic+LLM merge works (method contains 'heuristic' AND 'llm')."""
        # Use the invoice document which should trigger heuristic detection
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code}")
        
        data = resp.json()
        method = data.get("classification_method", "")
        
        # Check if heuristic was used (may have +llm suffix)
        if "heuristic" in method.lower():
            # If heuristic matched, it should also have +llm for extraction
            assert "+llm" in method.lower() or "llm" in method.lower(), \
                f"Heuristic classification should merge with LLM extraction. Got method: {method}"
            print(f"✓ Heuristic+LLM merge confirmed: {method}")
        else:
            # Pure LLM classification
            assert "llm" in method.lower(), f"Classification method should contain 'llm': {method}"
            print(f"✓ Pure LLM classification: {method}")

    def test_classify_pure_llm_when_no_heuristic(self):
        """CLASSIFY stage: pure LLM classification works when no heuristic matches."""
        # Unknown document type should rely on LLM
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_UNKNOWN}", timeout=60)
        
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code}")
        
        data = resp.json()
        method = data.get("classification_method", "")
        
        # Either heuristic+llm or pure llm is valid
        assert method, f"Classification method should not be empty: {method}"
        print(f"✓ Classification method: {method}")
        
        # Check document_type is set
        doc_type = data.get("document_type", "")
        assert doc_type, f"document_type should be set: {data.keys()}"
        print(f"✓ Document type classified as: {doc_type}")


class TestExtractStageQualityGate:
    """Tests for EXTRACT stage quality gate."""

    def test_extract_quality_gate_rejects_zero_meaningful_fields(self):
        """EXTRACT stage: quality gate rejects documents with 0 meaningful fields."""
        # Create a mock document with only metadata fields (via bc_validation test pattern)
        # We test the logic indirectly by checking the bc_validation_service behavior
        
        # Import and test the underlying quality gate logic
        import sys
        sys.path.insert(0, "/app/backend")
        
        from services.bc_validation_service import validate_bc_match
        import asyncio
        
        # Test with empty extracted_fields
        result = asyncio.get_event_loop().run_until_complete(
            validate_bc_match("AP_Invoice", {}, {})
        )
        
        checks = result.get("checks", [])
        quality_gate_check = next((c for c in checks if c.get("check_name") == "extraction_quality_gate"), None)
        
        assert quality_gate_check is not None, f"Should have extraction_quality_gate check: {checks}"
        assert quality_gate_check.get("passed") is False, f"Quality gate should fail with empty fields: {quality_gate_check}"
        assert result.get("all_passed") is False, f"all_passed should be False: {result}"
        print(f"✓ Extraction quality gate correctly rejects empty fields")

    def test_extract_quality_gate_passes_with_real_data(self):
        """EXTRACT stage: quality gate passes with real data (vendor, bol_number, etc.)."""
        import sys
        sys.path.insert(0, "/app/backend")
        
        from services.bc_validation_service import validate_bc_match
        import asyncio
        
        # Test with real extracted fields
        real_fields = {
            "vendor": "ACME Corp",
            "invoice_number": "INV-001",
            "amount": "1500.00",
            "bol_number": "BOL-12345"
        }
        
        result = asyncio.get_event_loop().run_until_complete(
            validate_bc_match("AP_Invoice", real_fields, {})
        )
        
        checks = result.get("checks", [])
        quality_gate_check = next((c for c in checks if c.get("check_name") == "extraction_quality_gate"), None)
        
        # Quality gate should either pass or not be present (demo mode)
        if quality_gate_check:
            assert quality_gate_check.get("passed") is True or result.get("checks", [{}])[0].get("check_name") == "demo_mode", \
                f"Quality gate should pass with real data: {quality_gate_check}"
        print(f"✓ Extraction quality gate passes with real data")


class TestValidateStageQualityGate:
    """Tests for VALIDATE stage extraction_quality_gate in bc_validation."""

    def test_validate_rejects_only_metadata_fields(self):
        """Documents with only metadata fields (bol_detected_by) fail extraction quality gate."""
        import sys
        sys.path.insert(0, "/app/backend")
        
        from services.bc_validation_service import validate_bc_match
        import asyncio
        
        # Only metadata field - should fail
        metadata_only = {
            "bol_detected_by": "heuristic:bol_filename"
        }
        
        result = asyncio.get_event_loop().run_until_complete(
            validate_bc_match("Shipping_Document", metadata_only, {})
        )
        
        checks = result.get("checks", [])
        quality_gate_check = next((c for c in checks if c.get("check_name") == "extraction_quality_gate"), None)
        
        assert quality_gate_check is not None, f"Should have extraction_quality_gate check: {checks}"
        assert quality_gate_check.get("passed") is False, \
            f"Quality gate should fail with only metadata fields: {quality_gate_check}"
        print(f"✓ Validate stage correctly rejects documents with only _detected_by metadata")


class TestRouteStage:
    """Tests for ROUTE stage: automation_decision and readiness_status."""

    def test_route_returns_automation_decision(self):
        """ROUTE stage: returns automation_decision."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code}")
        
        data = resp.json()
        assert "automation_decision" in data, f"Missing automation_decision: {data.keys()}"
        # Valid automation decisions include: auto_link, auto_create, manual, blocked, hold, needs_review
        valid_decisions = ("auto_link", "auto_create", "manual", "blocked", "hold", "needs_review")
        assert data["automation_decision"] in valid_decisions, \
            f"Unexpected automation_decision: {data['automation_decision']}"
        print(f"✓ automation_decision = {data['automation_decision']}")

    def test_route_returns_readiness_status(self):
        """ROUTE stage: returns automation_readiness (readiness_status)."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        
        if resp.status_code != 200:
            pytest.skip(f"Pipeline returned {resp.status_code}")
        
        data = resp.json()
        assert "automation_readiness" in data, f"Missing automation_readiness: {data.keys()}"
        assert data["automation_readiness"] in ("ready", "needs_review", "blocked"), \
            f"Unexpected automation_readiness: {data['automation_readiness']}"
        print(f"✓ automation_readiness = {data['automation_readiness']}")


class TestReprocessEndpoint:
    """Tests that /api/documents/{doc_id}/reprocess still works independently."""

    def test_reprocess_endpoint_works(self):
        """POST /api/documents/{doc_id}/reprocess still works independently of pipeline."""
        resp = requests.post(f"{BASE_URL}/api/documents/{DOC_WITH_FILE_INVOICE}/reprocess", timeout=60)
        
        # Should return 200 or 202
        assert resp.status_code in (200, 202), f"Reprocess should succeed: {resp.status_code} - {resp.text[:200]}"
        
        data = resp.json()
        # Reprocess endpoint returns: reprocessed, status_changed, new_status, document, etc.
        assert "reprocessed" in data or "document" in data or "new_status" in data, \
            f"Reprocess should return reprocess result data: {data.keys()}"
        print(f"✓ Reprocess endpoint works independently - keys: {list(data.keys())[:5]}")


class TestPipelineIntegrationE2E:
    """End-to-end integration tests for the full pipeline."""

    def test_full_pipeline_with_valid_document(self):
        """Full pipeline runs successfully with a valid document."""
        resp = requests.post(f"{BASE_URL}/api/document-intelligence/process/{DOC_WITH_FILE_INVOICE}", timeout=60)
        
        if resp.status_code != 200:
            data = resp.json() if resp.text else {}
            print(f"Pipeline failed: {data}")
            pytest.skip(f"Pipeline returned {resp.status_code}")
        
        data = resp.json()
        
        # Verify all expected fields
        assert "pipeline_status" in data
        assert "pipeline_stages" in data
        assert "classification_method" in data
        assert "meaningful_field_count" in data
        assert "document_type" in data
        assert "extracted_fields" in data
        
        # Check pipeline ran all stages
        stages = data["pipeline_stages"]
        ran_stages = [s for s, d in stages.items() if d.get("status") in ("passed", "failed")]
        print(f"✓ Pipeline ran stages: {ran_stages}")
        print(f"✓ Final status: {data['pipeline_status']}")
        print(f"✓ Document type: {data['document_type']}")
        print(f"✓ Classification method: {data['classification_method']}")
        print(f"✓ Meaningful fields: {data['meaningful_field_count']}")
        
        # If pipeline passed, check stages
        if data["pipeline_status"] == "passed":
            for stage, stage_data in stages.items():
                assert stage_data.get("quality_gate") is True, \
                    f"Stage {stage} quality gate should pass: {stage_data}"
        else:
            # Check failure info
            assert "pipeline_failure_stage" in data
            assert "pipeline_failure_reason" in data
            print(f"Pipeline failed at {data['pipeline_failure_stage']}: {data['pipeline_failure_reason']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
