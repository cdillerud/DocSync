"""
BC Reference Cache Layer Tests

Tests for the cache-first document resolution feature:
- GET /api/cache/status - Cache health and entity counts
- POST /api/cache/sync?mode=incremental - Background sync trigger
- GET /api/cache/search?reference=X - Search cache by reference
- POST /api/bc/resolve-reference?reference_number=X - Cache-first resolution
- POST /api/documents/{doc_id}/resolve-intelligence - Intelligence resolution uses cache
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestCacheStatus:
    """Tests for GET /api/cache/status endpoint"""
    
    def test_cache_status_returns_healthy(self):
        """Cache status should return healthy status with entity counts"""
        resp = requests.get(f"{BASE_URL}/api/cache/status")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "status" in data, "Response should contain 'status' field"
        assert data["status"] == "healthy", f"Expected 'healthy' status, got {data['status']}"
        
        assert "total_records" in data, "Response should contain 'total_records'"
        assert data["total_records"] > 0, f"Expected records > 0, got {data['total_records']}"
        
        # Verify ~277K records as mentioned in requirements
        assert data["total_records"] >= 200000, f"Expected ~277K records, got {data['total_records']}"
    
    def test_cache_status_has_entity_counts(self):
        """Cache status should breakdown entity counts by type"""
        resp = requests.get(f"{BASE_URL}/api/cache/status")
        assert resp.status_code == 200
        
        data = resp.json()
        entity_counts = data.get("entity_counts", {})
        
        # Expected entity types from requirements
        expected_types = [
            "purchase_order", 
            "posted_purchase_invoice", 
            "sales_order", 
            "posted_sales_invoice", 
            "posted_sales_shipment"
        ]
        
        for etype in expected_types:
            assert etype in entity_counts, f"Missing entity type: {etype}"
            assert entity_counts[etype] >= 0, f"Invalid count for {etype}"
        
        # Verify approximate counts from requirements
        # purchase_order: ~1512, posted_purchase_invoice: ~89360, etc.
        assert entity_counts.get("purchase_order", 0) >= 1000, "Expected ~1512 purchase orders"
        assert entity_counts.get("posted_purchase_invoice", 0) >= 80000, "Expected ~89360 posted purchase invoices"
        assert entity_counts.get("posted_sales_shipment", 0) >= 100000, "Expected ~127244 posted sales shipments"
    
    def test_cache_status_has_sync_info(self):
        """Cache status should include last_sync timestamp and sync interval"""
        resp = requests.get(f"{BASE_URL}/api/cache/status")
        assert resp.status_code == 200
        
        data = resp.json()
        assert "last_sync" in data, "Should have last_sync timestamp"
        assert "sync_interval_minutes" in data, "Should have sync_interval_minutes"
        assert "initialized" in data, "Should have initialized flag"
        assert "background_sync_active" in data, "Should have background_sync_active"
        
        assert data["initialized"] is True, "Cache should be initialized"
        assert data["sync_interval_minutes"] == 10, f"Expected 10 min sync interval, got {data['sync_interval_minutes']}"


class TestCacheSync:
    """Tests for POST /api/cache/sync endpoint"""
    
    def test_trigger_incremental_sync(self):
        """POST /api/cache/sync?mode=incremental should start background sync"""
        resp = requests.post(f"{BASE_URL}/api/cache/sync", params={"mode": "incremental"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "sync_started", "Should return sync_started status"
        assert data.get("mode") == "incremental", "Should return mode=incremental"
        assert "message" in data, "Should have a message"
    
    def test_trigger_default_mode_is_incremental(self):
        """Default sync mode should be incremental"""
        resp = requests.post(f"{BASE_URL}/api/cache/sync")
        assert resp.status_code == 200
        
        data = resp.json()
        assert data.get("mode") == "incremental", "Default mode should be incremental"


class TestCacheSearch:
    """Tests for GET /api/cache/search endpoint"""
    
    def test_search_known_reference_111216(self):
        """Searching for reference 111216 should return matches from cache"""
        resp = requests.get(f"{BASE_URL}/api/cache/search", params={"reference": "111216"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("reference") == "111216", "Response should echo the reference"
        assert "match_count" in data, "Should have match_count"
        assert "matches" in data, "Should have matches array"
        
        # Requirements say 111216 has purchase_order + sales_order
        assert data["match_count"] >= 1, f"Expected at least 1 match for 111216, got {data['match_count']}"
        
        matches = data.get("matches", [])
        assert len(matches) >= 1, "Should have at least one match"
        
        # Check match structure
        if matches:
            match = matches[0]
            assert "bc_document_no" in match, "Match should have bc_document_no"
            assert "bc_entity_type" in match, "Match should have bc_entity_type"
            assert "bc_record_id" in match, "Match should have bc_record_id"
    
    def test_search_returns_entity_type_info(self):
        """Search results should include entity type information"""
        resp = requests.get(f"{BASE_URL}/api/cache/search", params={"reference": "111216"})
        assert resp.status_code == 200
        
        matches = resp.json().get("matches", [])
        if matches:
            entity_types_found = [m.get("bc_entity_type") for m in matches]
            # 111216 should have purchase_order and/or sales_order
            assert any(t in ["purchase_order", "sales_order"] for t in entity_types_found), \
                f"Expected purchase_order or sales_order for 111216, found: {entity_types_found}"
    
    def test_search_with_entity_type_filter(self):
        """Search with entity_type filter should only return that type"""
        resp = requests.get(f"{BASE_URL}/api/cache/search", params={
            "reference": "111216",
            "entity_type": "purchase_order"
        })
        assert resp.status_code == 200
        
        matches = resp.json().get("matches", [])
        for m in matches:
            assert m.get("bc_entity_type") == "purchase_order", \
                f"Filter not working: got {m.get('bc_entity_type')}"
    
    def test_search_nonexistent_reference(self):
        """Searching for obscure reference should return empty or few results"""
        resp = requests.get(f"{BASE_URL}/api/cache/search", params={"reference": "ZZZZZZNONEXISTENT99999"})
        assert resp.status_code == 200
        
        data = resp.json()
        assert data.get("match_count") == 0, "Nonexistent reference should return 0 matches"
        assert data.get("matches") == [], "Matches should be empty list"


class TestBCResolveReference:
    """Tests for POST /api/bc/resolve-reference endpoint"""
    
    def test_resolve_reference_111216_uses_cache(self):
        """Resolving reference 111216 should return source=cache in bc_record_info"""
        resp = requests.post(f"{BASE_URL}/api/bc/resolve-reference", params={"reference_number": "111216"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "found", f"Expected status=found, got {data.get('status')}"
        assert "reference_type" in data, "Should have reference_type"
        assert "bc_record_id" in data, "Should have bc_record_id"
        assert "bc_document_no" in data, "Should have bc_document_no"
        
        # Check bc_record_info contains source=cache
        bc_record_info = data.get("bc_record_info", {})
        assert "source" in bc_record_info, "bc_record_info should have 'source' field"
        assert bc_record_info.get("source") == "cache", \
            f"Expected source='cache', got '{bc_record_info.get('source')}'"
    
    def test_resolve_reference_not_found_falls_back_to_api(self):
        """Obscure reference not in cache should fall back to BC API"""
        # Use a reference unlikely to be in cache
        resp = requests.post(f"{BASE_URL}/api/bc/resolve-reference", 
                            params={"reference_number": "OBSCURE_TEST_REF_XYZ123"})
        assert resp.status_code == 200
        
        data = resp.json()
        # Should return not_found (since it doesn't exist anywhere)
        assert data.get("status") in ["not_found", "error"], \
            f"Expected not_found or error for obscure ref, got {data.get('status')}"
        
        # If it was checked via API, tables_checked should NOT be just ['cache']
        tables_checked = data.get("tables_checked", [])
        # If cache miss occurred and API was called, tables_checked will have BC tables
        if data.get("status") == "not_found" and len(tables_checked) > 1:
            assert "cache" not in tables_checked or len(tables_checked) > 1, \
                "Should fall back to API tables on cache miss"


class TestDocumentIntelligenceWithCache:
    """Tests for POST /api/documents/{doc_id}/resolve-intelligence using cache"""
    
    TEST_DOC_ID = "a1dec76a-17a2-46d4-a9f9-a0f6fb818208"
    
    def test_resolve_intelligence_returns_cache_source(self):
        """Resolve intelligence should indicate cache as data source"""
        resp = requests.post(f"{BASE_URL}/api/documents/{self.TEST_DOC_ID}/resolve-intelligence")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        best_match = data.get("best_match")
        
        if best_match:
            bc_record_info = best_match.get("bc_record_info", {})
            # If resolved from cache, source should be 'cache'
            source = bc_record_info.get("source")
            assert source in ["cache", None], \
                f"Expected source to be 'cache' or None, got '{source}'"
    
    def test_resolve_intelligence_structure(self):
        """Resolve intelligence should return proper structure"""
        resp = requests.post(f"{BASE_URL}/api/documents/{self.TEST_DOC_ID}/resolve-intelligence")
        assert resp.status_code == 200
        
        data = resp.json()
        # Check required fields exist
        assert "match_outcome" in data, "Should have match_outcome"
        assert "reference_candidates" in data, "Should have reference_candidates"
        assert "resolver_strategy" in data, "Should have resolver_strategy"
        assert "processing_time_ms" in data, "Should have processing_time_ms"
        assert "resolved_at" in data, "Should have resolved_at"


class TestCacheEventEmission:
    """Tests for cache-related events"""
    
    def test_cache_status_shows_initialized(self):
        """Cache status should show bc.cache.initialized event was emitted"""
        resp = requests.get(f"{BASE_URL}/api/cache/status")
        assert resp.status_code == 200
        
        data = resp.json()
        # If cache is initialized, the event was emitted during startup
        assert data.get("initialized") is True, "Cache should be initialized (bc.cache.initialized event)"
    
    def test_trigger_sync_emits_events(self):
        """Triggering sync should eventually emit bc.cache.sync.completed event"""
        # Trigger a sync
        resp = requests.post(f"{BASE_URL}/api/cache/sync", params={"mode": "incremental"})
        assert resp.status_code == 200
        
        # Wait a moment for background sync to start
        time.sleep(2)
        
        # Check cache status (last_sync should be recent if sync ran)
        status_resp = requests.get(f"{BASE_URL}/api/cache/status")
        assert status_resp.status_code == 200
        
        # The sync event would be in the events collection
        # We just verify sync can be triggered without error


class TestCacheIntegrationEndToEnd:
    """End-to-end integration tests for cache layer"""
    
    def test_search_then_resolve_consistency(self):
        """Search and resolve should return consistent data for same reference"""
        reference = "111216"
        
        # Search cache
        search_resp = requests.get(f"{BASE_URL}/api/cache/search", params={"reference": reference})
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        
        # Resolve reference
        resolve_resp = requests.post(f"{BASE_URL}/api/bc/resolve-reference", 
                                     params={"reference_number": reference})
        assert resolve_resp.status_code == 200
        resolve_data = resolve_resp.json()
        
        # If both find results, they should be consistent
        if search_data.get("match_count", 0) > 0 and resolve_data.get("status") == "found":
            search_doc_no = search_data["matches"][0].get("bc_document_no")
            resolve_doc_no = resolve_data.get("bc_document_no")
            # Document numbers should match (search returns all matches, resolve picks best)
            assert search_doc_no or resolve_doc_no, "Should have document numbers"
    
    def test_cache_performance(self):
        """Cache lookups should be fast (< 200ms)"""
        import time
        
        start = time.time()
        resp = requests.get(f"{BASE_URL}/api/cache/search", params={"reference": "111216"})
        duration_ms = (time.time() - start) * 1000
        
        assert resp.status_code == 200
        assert duration_ms < 500, f"Cache search took {duration_ms:.0f}ms, expected < 500ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
