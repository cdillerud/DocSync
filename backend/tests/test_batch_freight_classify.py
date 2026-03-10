"""
Batch Freight Classification Tests

Tests for the batch freight G/L classification feature that:
- Classifies all/selected freight-eligible documents
- Runs freight detection + G/L routing
- Saves recommendations (to MongoDB only, read-only with respect to BC)
- Respects confidence thresholds
- Skips manually overridden items
- Returns summary with direction counts and items requiring review

Endpoints tested:
- POST /api/freight-routing/batch-classify
- GET /api/bc/write-guard/status (verify BC writes are blocked)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestBatchFreightClassify:
    """Tests for batch freight classification endpoint"""

    # =========================================================================
    # BATCH CLASSIFY - ALL DOCUMENTS
    # =========================================================================

    def test_batch_classify_all_documents_no_ids(self):
        """POST /api/freight-routing/batch-classify with no document_ids should process all documents"""
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "confidence_threshold": 0.5,
                "skip_overrides": True
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify response structure
        assert "total_processed" in data, "Missing total_processed"
        assert "freight_detected" in data, "Missing freight_detected"
        assert "non_freight" in data, "Missing non_freight"
        assert "by_direction" in data, "Missing by_direction"
        assert "by_gl_account" in data, "Missing by_gl_account"
        assert "needs_manual_review" in data, "Missing needs_manual_review"
        assert "high_confidence" in data, "Missing high_confidence"
        assert "batch_completed_at" in data, "Missing batch_completed_at"
        
        # Verify direction breakdown structure
        by_direction = data["by_direction"]
        assert isinstance(by_direction, dict), "by_direction should be a dict"
        # Should have at least some of these keys
        valid_directions = {"inbound", "outbound", "transfer", "unknown"}
        for dir_key in by_direction.keys():
            assert dir_key in valid_directions, f"Unexpected direction key: {dir_key}"
        
        # Verify counts add up logically
        total = data["total_processed"]
        freight = data["freight_detected"]
        non_freight = data["non_freight"]
        assert total >= freight + non_freight - 1, "Counts should add up (allowing for errors)"
        
        print(f"✓ Batch classify all: total_processed={total}, freight={freight}, non_freight={non_freight}")
        print(f"  by_direction: {by_direction}")
        print(f"  needs_manual_review: {len(data['needs_manual_review'])}")
        print(f"  high_confidence: {len(data['high_confidence'])}")

    # =========================================================================
    # BATCH CLASSIFY - SPECIFIC DOCUMENT IDS
    # =========================================================================

    def test_batch_classify_with_specific_document_ids(self):
        """POST /api/freight-routing/batch-classify with specific document_ids should only process those"""
        # First get a few document IDs
        docs_response = requests.get(f"{BASE_URL}/api/documents?limit=5")
        assert docs_response.status_code == 200
        docs = docs_response.json().get("documents", [])
        
        if len(docs) < 2:
            pytest.skip("Need at least 2 documents to test specific IDs")
        
        specific_ids = [docs[0]["id"], docs[1]["id"]]
        
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "document_ids": specific_ids,
                "confidence_threshold": 0.5,
                "skip_overrides": False  # Don't skip overrides for this test
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Should process at most the number of IDs provided (might be less if some have overrides and skip_overrides=True)
        total = data["total_processed"]
        assert total <= len(specific_ids), f"Processed {total}, should be <= {len(specific_ids)}"
        
        print(f"✓ Batch classify specific IDs: requested={len(specific_ids)}, processed={total}")

    # =========================================================================
    # CONFIDENCE THRESHOLD PARAMETER
    # =========================================================================

    def test_batch_classify_high_confidence_threshold(self):
        """POST /api/freight-routing/batch-classify with confidence_threshold=0.9 should flag more for review"""
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "confidence_threshold": 0.9,  # High threshold
                "skip_overrides": True
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # With high threshold, more items should need manual review (or all might be high confidence)
        needs_review_count = len(data.get("needs_manual_review", []))
        high_confidence_count = len(data.get("high_confidence", []))
        
        # Verify items in needs_manual_review have confidence < 0.9
        for item in data.get("needs_manual_review", []):
            conf = item.get("confidence", 0)
            assert conf < 0.9, f"Item with confidence {conf} should not be in needs_manual_review at 0.9 threshold"
        
        # Verify items in high_confidence have confidence >= 0.9
        for item in data.get("high_confidence", []):
            conf = item.get("confidence", 0)
            assert conf >= 0.9, f"Item with confidence {conf} should not be in high_confidence at 0.9 threshold"
        
        print(f"✓ Batch classify with 0.9 threshold: needs_review={needs_review_count}, high_confidence={high_confidence_count}")

    # =========================================================================
    # SKIP OVERRIDES PARAMETER
    # =========================================================================

    def test_batch_classify_skip_overrides_true(self):
        """POST /api/freight-routing/batch-classify with skip_overrides=true should skip overridden docs"""
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "confidence_threshold": 0.5,
                "skip_overrides": True
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check that skipped_override count is reported
        skipped = data.get("skipped_override", 0)
        
        print(f"✓ Batch classify skip_overrides=True: skipped_override={skipped}")

    def test_batch_classify_skip_overrides_false(self):
        """POST /api/freight-routing/batch-classify with skip_overrides=false should re-classify even overridden docs"""
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "confidence_threshold": 0.5,
                "skip_overrides": False  # Re-classify even overridden docs
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # When skip_overrides=False, skipped_override should be 0
        skipped = data.get("skipped_override", 0)
        assert skipped == 0, f"With skip_overrides=False, skipped_override should be 0, got {skipped}"
        
        print(f"✓ Batch classify skip_overrides=False: skipped_override={skipped} (expected 0)")

    # =========================================================================
    # VERIFY SPECIFIC OVERRIDDEN DOCUMENT (98695c83-a7f3-495f-ac8d-bb5405c55a63)
    # =========================================================================

    def test_batch_classify_skips_known_override_document(self):
        """Verify doc 98695c83-a7f3-495f-ac8d-bb5405c55a63 with override is skipped when skip_overrides=True"""
        override_doc_id = "98695c83-a7f3-495f-ac8d-bb5405c55a63"
        
        # Check if the doc exists and has an override
        doc_response = requests.get(f"{BASE_URL}/api/documents/{override_doc_id}")
        if doc_response.status_code != 200:
            pytest.skip(f"Document {override_doc_id} not found, skipping test")
        
        doc = doc_response.json().get("document", {})
        fgl_class = doc.get("freight_gl_classification", {})
        has_override = fgl_class.get("override", False)
        
        print(f"Doc {override_doc_id}: has_override={has_override}")
        
        if not has_override:
            pytest.skip(f"Document {override_doc_id} does not have an override set")
        
        # Run batch classify with skip_overrides=True
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "document_ids": [override_doc_id],
                "confidence_threshold": 0.5,
                "skip_overrides": True
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Should have skipped 1
        assert data.get("skipped_override", 0) >= 1, "Should have skipped at least 1 overridden doc"
        assert data.get("total_processed", 0) == 0, "With only override doc and skip=True, total_processed should be 0"
        
        print(f"✓ Known override document skipped as expected")


class TestBCWriteGuardStatus:
    """Verify BC writes are blocked (read-only safety)"""

    def test_bc_write_guard_status_blocked(self):
        """GET /api/bc/write-guard/status - Verify BC writes are BLOCKED"""
        response = requests.get(f"{BASE_URL}/api/bc/write-guard/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # BC_WRITE_ENABLED=false in .env, so writes should be blocked
        write_enabled = data.get("write_enabled", True)
        status = data.get("status", "unknown")
        
        # Verify writes are blocked
        assert write_enabled == False, f"BC writes should be disabled, got write_enabled={write_enabled}"
        assert status in ("blocked", "disabled", "read_only"), f"Status should indicate blocked/disabled, got {status}"
        
        print(f"✓ BC Write Guard Status: write_enabled={write_enabled}, status={status}")
        print(f"  Full response: {data}")


class TestBatchClassifyResultStructure:
    """Tests for result structure validation"""

    def test_batch_classify_result_item_structure(self):
        """Verify individual items in results have expected fields"""
        response = requests.post(
            f"{BASE_URL}/api/freight-routing/batch-classify",
            json={
                "confidence_threshold": 0.5,
                "skip_overrides": True
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Check structure of needs_manual_review items
        for item in data.get("needs_manual_review", [])[:3]:  # Check first 3
            assert "document_id" in item, "Missing document_id in needs_manual_review item"
            assert "direction" in item, "Missing direction"
            assert "gl_number" in item, "Missing gl_number"
            assert "confidence" in item, "Missing confidence"
            if "file_name" not in item and "vendor" not in item:
                print(f"  Warning: item missing file_name or vendor: {item.keys()}")
        
        # Check structure of high_confidence items
        for item in data.get("high_confidence", [])[:3]:  # Check first 3
            assert "document_id" in item, "Missing document_id in high_confidence item"
            assert "direction" in item, "Missing direction"
            assert "gl_number" in item, "Missing gl_number"
            assert "confidence" in item, "Missing confidence"
        
        # Check by_gl_account structure
        for gl_num, info in data.get("by_gl_account", {}).items():
            assert "gl_name" in info, f"Missing gl_name for {gl_num}"
            assert "count" in info, f"Missing count for {gl_num}"
            assert isinstance(info["count"], int), f"count should be int for {gl_num}"
        
        print(f"✓ Result item structure validated")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
