"""
Test Vendor Invoice Profile Learning Fix - Iteration 159

Tests the vendor profile learning from BC reference cache when BC API fails:
1. _learn_from_reference_cache returns correct stats for TUMALOC (count, po_rate=0.0, amount_stats)
2. build_vendor_profile returns po_expected=False and amount_stats populated for TUMALOC
3. GET /api/ap-review/vendor-profile/TUMALOC?refresh=true returns po_expected=False, bc_invoice_count=18731
4. check_ap_ready_to_post with po_expected=False profile skips PO check and returns ready=True
5. check_ap_ready_to_post WITHOUT profile still blocks when po_number is set but not found in BC
6. attempt_ap_auto_post loads vendor profile before calling check_ap_ready_to_post
7. bc_validation_service PO candidate filtering excludes BOL numbers and invoice numbers
"""

import pytest
import requests
import os
import sys
import asyncio

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://doc-hub-queue-repair.preview.emergentagent.com').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_returns_200(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health returns 200 with status=healthy")


class TestLearnFromReferenceCache:
    """Test _learn_from_reference_cache function directly"""
    
    def test_learn_from_cache_returns_correct_stats_for_tumaloc(self):
        """_learn_from_reference_cache returns correct stats for TUMALOC vendor"""
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client['gpi_document_hub']
            
            from services.vendor_invoice_profile_service import _learn_from_reference_cache
            
            result = await _learn_from_reference_cache(db, "TUMALOC")
            
            assert result is not None, "Expected result from cache but got None"
            assert result.get("count") >= 18000, f"Expected count >= 18000 but got {result.get('count')}"
            assert result.get("po_rate") == 0.0, f"Expected po_rate=0.0 but got {result.get('po_rate')}"
            assert result.get("has_order_count") == 0, f"Expected has_order_count=0 but got {result.get('has_order_count')}"
            
            amount_stats = result.get("amount_stats", {})
            assert amount_stats.get("avg_amount") > 0, f"Expected avg_amount > 0 but got {amount_stats.get('avg_amount')}"
            assert amount_stats.get("min_amount") >= 0, f"Expected min_amount >= 0 but got {amount_stats.get('min_amount')}"
            assert amount_stats.get("max_amount") > 0, f"Expected max_amount > 0 but got {amount_stats.get('max_amount')}"
            assert amount_stats.get("sample_count") >= 18000, f"Expected sample_count >= 18000 but got {amount_stats.get('sample_count')}"
            
            print(f"PASS: _learn_from_reference_cache returns correct stats for TUMALOC:")
            print(f"  - count: {result.get('count')}")
            print(f"  - po_rate: {result.get('po_rate')}")
            print(f"  - has_order_count: {result.get('has_order_count')}")
            print(f"  - avg_amount: ${amount_stats.get('avg_amount', 0):.2f}")
            print(f"  - min_amount: ${amount_stats.get('min_amount', 0):.2f}")
            print(f"  - max_amount: ${amount_stats.get('max_amount', 0):.2f}")
            
            client.close()
            return result
        
        result = asyncio.get_event_loop().run_until_complete(run_test())
        assert result is not None
    
    def test_learn_from_cache_returns_none_for_unknown_vendor(self):
        """_learn_from_reference_cache returns None for unknown vendor"""
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client['gpi_document_hub']
            
            from services.vendor_invoice_profile_service import _learn_from_reference_cache
            
            result = await _learn_from_reference_cache(db, "NONEXISTENT_VENDOR_XYZ123")
            
            assert result is None, f"Expected None for unknown vendor but got {result}"
            print("PASS: _learn_from_reference_cache returns None for unknown vendor")
            
            client.close()
            return result
        
        asyncio.get_event_loop().run_until_complete(run_test())


class TestBuildVendorProfile:
    """Test build_vendor_profile function"""
    
    def test_build_profile_returns_po_expected_false_for_tumaloc(self):
        """build_vendor_profile returns po_expected=False for TUMALOC (freight carrier)"""
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client['gpi_document_hub']
            
            from services.vendor_invoice_profile_service import build_vendor_profile
            
            # Force refresh to ensure we get fresh data from cache
            profile = await build_vendor_profile(db, "TUMALOC", force_refresh=True)
            
            assert profile is not None, "Expected profile but got None"
            assert profile.get("vendor_no") == "TUMALOC", f"Expected vendor_no=TUMALOC but got {profile.get('vendor_no')}"
            assert profile.get("po_expected") is False, f"Expected po_expected=False but got {profile.get('po_expected')}"
            assert profile.get("bc_invoice_count") >= 18000, f"Expected bc_invoice_count >= 18000 but got {profile.get('bc_invoice_count')}"
            
            amount_stats = profile.get("amount_stats", {})
            assert amount_stats.get("avg_amount") > 0, f"Expected avg_amount > 0 but got {amount_stats.get('avg_amount')}"
            
            sources = profile.get("sources", {})
            assert sources.get("bc_cache") >= 18000, f"Expected bc_cache >= 18000 but got {sources.get('bc_cache')}"
            
            print(f"PASS: build_vendor_profile returns correct profile for TUMALOC:")
            print(f"  - vendor_no: {profile.get('vendor_no')}")
            print(f"  - po_expected: {profile.get('po_expected')}")
            print(f"  - bc_invoice_count: {profile.get('bc_invoice_count')}")
            print(f"  - avg_amount: ${amount_stats.get('avg_amount', 0):.2f}")
            print(f"  - sources.bc_cache: {sources.get('bc_cache')}")
            
            client.close()
            return profile
        
        result = asyncio.get_event_loop().run_until_complete(run_test())
        assert result is not None
    
    def test_build_profile_caches_result(self):
        """build_vendor_profile caches result in vendor_invoice_profiles collection"""
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client['gpi_document_hub']
            
            from services.vendor_invoice_profile_service import build_vendor_profile
            
            # Build profile (should cache)
            await build_vendor_profile(db, "TUMALOC", force_refresh=True)
            
            # Check cache
            cached = await db.vendor_invoice_profiles.find_one({"vendor_no": "TUMALOC"}, {"_id": 0})
            
            assert cached is not None, "Expected cached profile but got None"
            assert cached.get("po_expected") is False, f"Cached profile should have po_expected=False"
            assert cached.get("last_updated") is not None, "Cached profile should have last_updated"
            
            print(f"PASS: build_vendor_profile caches result in vendor_invoice_profiles collection")
            print(f"  - last_updated: {cached.get('last_updated')}")
            
            client.close()
            return cached
        
        asyncio.get_event_loop().run_until_complete(run_test())


class TestVendorProfileEndpoint:
    """Test GET /api/ap-review/vendor-profile/{vendor_no} endpoint"""
    
    def test_vendor_profile_endpoint_returns_correct_data_for_tumaloc(self):
        """GET /api/ap-review/vendor-profile/TUMALOC?refresh=true returns correct data"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendor-profile/TUMALOC?refresh=true")
        
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data.get("vendor_no") == "TUMALOC", f"Expected vendor_no=TUMALOC but got {data.get('vendor_no')}"
        assert data.get("po_expected") is False, f"Expected po_expected=False but got {data.get('po_expected')}"
        assert data.get("bc_invoice_count") >= 18000, f"Expected bc_invoice_count >= 18000 but got {data.get('bc_invoice_count')}"
        
        amount_stats = data.get("amount_stats", {})
        assert amount_stats.get("avg_amount") > 0, f"Expected avg_amount > 0 but got {amount_stats.get('avg_amount')}"
        assert amount_stats.get("min_amount") >= 0, f"Expected min_amount >= 0 but got {amount_stats.get('min_amount')}"
        assert amount_stats.get("max_amount") > 0, f"Expected max_amount > 0 but got {amount_stats.get('max_amount')}"
        
        sources = data.get("sources", {})
        assert sources.get("bc_cache") >= 18000, f"Expected sources.bc_cache >= 18000 but got {sources.get('bc_cache')}"
        
        print(f"PASS: GET /api/ap-review/vendor-profile/TUMALOC returns correct data:")
        print(f"  - vendor_no: {data.get('vendor_no')}")
        print(f"  - po_expected: {data.get('po_expected')}")
        print(f"  - bc_invoice_count: {data.get('bc_invoice_count')}")
        print(f"  - avg_amount: ${amount_stats.get('avg_amount', 0):.2f}")
        print(f"  - min_amount: ${amount_stats.get('min_amount', 0):.2f}")
        print(f"  - max_amount: ${amount_stats.get('max_amount', 0):.2f}")
        print(f"  - sources.bc_cache: {sources.get('bc_cache')}")
    
    def test_vendor_profile_endpoint_returns_po_expected_true_for_unknown_vendor(self):
        """GET /api/ap-review/vendor-profile/{unknown} returns po_expected=True (default)"""
        response = requests.get(f"{BASE_URL}/api/ap-review/vendor-profile/UNKNOWN_VENDOR_XYZ?refresh=true")
        
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Unknown vendor should default to po_expected=True
        assert data.get("po_expected") is True, f"Expected po_expected=True for unknown vendor but got {data.get('po_expected')}"
        
        print(f"PASS: GET /api/ap-review/vendor-profile/UNKNOWN returns po_expected=True (default)")


class TestCheckApReadyToPostWithVendorProfile:
    """Test check_ap_ready_to_post with vendor_profile parameter"""
    
    def test_po_check_skipped_when_po_expected_false(self):
        """check_ap_ready_to_post skips PO check when vendor_profile.po_expected=False"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        # Document with PO extracted but not matched (would normally fail)
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Tumalo Creek Freight",
                "po_number": "12345"  # PO extracted
            },
            "bc_vendor_number": "TUMALOC",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}  # PO not matched
                ]
            }
        }
        
        # Vendor profile says PO is NOT expected for this vendor
        vendor_profile = {
            "vendor_no": "TUMALOC",
            "po_expected": False,  # Key: PO not expected
            "bc_invoice_count": 18731
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc, vendor_profile=vendor_profile)
        
        # Should be ready because PO check is skipped
        assert ready is True, f"Expected ready=True (PO check skipped) but got {ready}. Failures: {failures}"
        assert "PO" not in str(failures), f"PO failure should not be in failures: {failures}"
        
        print(f"PASS: check_ap_ready_to_post skips PO check when po_expected=False")
        print(f"  - ready: {ready}")
        print(f"  - reason: {reason}")
    
    def test_po_check_enforced_when_po_expected_true(self):
        """check_ap_ready_to_post enforces PO check when vendor_profile.po_expected=True"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        # Document with PO extracted but not matched
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Some Vendor",
                "po_number": "12345"  # PO extracted
            },
            "bc_vendor_number": "SOMEVEND",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}  # PO not matched
                ]
            }
        }
        
        # Vendor profile says PO IS expected
        vendor_profile = {
            "vendor_no": "SOMEVEND",
            "po_expected": True,  # PO expected
            "bc_invoice_count": 100
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc, vendor_profile=vendor_profile)
        
        # Should NOT be ready because PO check failed
        assert ready is False, f"Expected ready=False (PO check enforced) but got {ready}"
        assert "PO extracted but not found/matched in BC" in failures, f"Expected PO failure in failures: {failures}"
        
        print(f"PASS: check_ap_ready_to_post enforces PO check when po_expected=True")
        print(f"  - ready: {ready}")
        print(f"  - failures: {failures}")
    
    def test_po_check_enforced_when_no_profile_provided(self):
        """check_ap_ready_to_post enforces PO check when no vendor_profile provided (default)"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        # Document with PO extracted but not matched
        doc = {
            "doc_type": "AP_Invoice",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Some Vendor",
                "po_number": "12345"  # PO extracted
            },
            "bc_vendor_number": "SOMEVEND",
            "validation_results": {
                "checks": [
                    {"check_name": "po_validation", "passed": False}  # PO not matched
                ]
            }
        }
        
        # No vendor profile provided
        ready, reason, failures = check_ap_ready_to_post(doc, vendor_profile=None)
        
        # Should NOT be ready because PO check failed (default behavior)
        assert ready is False, f"Expected ready=False (default PO check) but got {ready}"
        assert "PO extracted but not found/matched in BC" in failures, f"Expected PO failure in failures: {failures}"
        
        print(f"PASS: check_ap_ready_to_post enforces PO check when no profile provided")
        print(f"  - ready: {ready}")
        print(f"  - failures: {failures}")


class TestAttemptApAutoPostLoadsProfile:
    """Test that attempt_ap_auto_post loads vendor profile"""
    
    def test_attempt_ap_auto_post_imports_vendor_profile_service(self):
        """Verify attempt_ap_auto_post imports and uses vendor_invoice_profile_service"""
        with open('/app/backend/services/ap_auto_post_service.py', 'r') as f:
            content = f.read()
        
        # Check for import of get_or_build_profile
        assert 'from services.vendor_invoice_profile_service import get_or_build_profile' in content, \
            "ap_auto_post_service should import get_or_build_profile"
        
        # Check that vendor_profile is loaded before check_ap_ready_to_post
        assert 'vendor_profile = await get_or_build_profile(db, vendor_no)' in content, \
            "attempt_ap_auto_post should load vendor profile"
        
        # Check that vendor_profile is passed to check_ap_ready_to_post
        assert 'check_ap_ready_to_post(doc, vendor_profile=vendor_profile)' in content, \
            "attempt_ap_auto_post should pass vendor_profile to check_ap_ready_to_post"
        
        print("PASS: attempt_ap_auto_post loads vendor profile before calling check_ap_ready_to_post")


class TestBCValidationPOCandidateFiltering:
    """Test bc_validation_service PO candidate filtering"""
    
    def test_po_candidate_filtering_excludes_bol_numbers(self):
        """bc_validation_service filters out BOL numbers from PO candidates"""
        with open('/app/backend/services/bc_validation_service.py', 'r') as f:
            content = f.read()
        
        # Check for BOL exclusion logic
        assert 'bol_number' in content.lower() or 'bol_num' in content.lower(), \
            "bc_validation_service should reference BOL number for filtering"
        
        assert '_exclude_from_po' in content, \
            "bc_validation_service should have _exclude_from_po set for filtering"
        
        # Check that BOL is added to exclusion set
        assert 'bol_num' in content and '_exclude_from_po.add' in content, \
            "bc_validation_service should add BOL number to exclusion set"
        
        print("PASS: bc_validation_service has BOL number exclusion logic")
    
    def test_po_candidate_filtering_excludes_invoice_numbers(self):
        """bc_validation_service filters out invoice numbers from PO candidates"""
        with open('/app/backend/services/bc_validation_service.py', 'r') as f:
            content = f.read()
        
        # Check for invoice number exclusion logic
        assert 'invoice_number' in content.lower() or 'inv_num' in content.lower(), \
            "bc_validation_service should reference invoice number for filtering"
        
        # Check that invoice number is added to exclusion set
        assert 'inv_num' in content and '_exclude_from_po.add' in content, \
            "bc_validation_service should add invoice number to exclusion set"
        
        print("PASS: bc_validation_service has invoice number exclusion logic")
    
    def test_po_candidate_filtering_logs_exclusions(self):
        """bc_validation_service logs when excluding PO candidates"""
        with open('/app/backend/services/bc_validation_service.py', 'r') as f:
            content = f.read()
        
        # Check for logging of exclusions
        assert '[PO-Filter]' in content or 'Excluding' in content, \
            "bc_validation_service should log PO candidate exclusions"
        
        print("PASS: bc_validation_service logs PO candidate exclusions")


class TestVendorProfileServiceCodeStructure:
    """Test vendor_invoice_profile_service code structure"""
    
    def test_learn_from_reference_cache_function_exists(self):
        """_learn_from_reference_cache function exists with correct signature"""
        with open('/app/backend/services/vendor_invoice_profile_service.py', 'r') as f:
            content = f.read()
        
        assert 'async def _learn_from_reference_cache(db, vendor_no: str)' in content, \
            "_learn_from_reference_cache function should exist with correct signature"
        
        # Check it queries bc_reference_cache collection
        assert 'bc_reference_cache' in content, \
            "_learn_from_reference_cache should query bc_reference_cache collection"
        
        # Check it calculates po_rate
        assert 'po_rate' in content, \
            "_learn_from_reference_cache should calculate po_rate"
        
        print("PASS: _learn_from_reference_cache function exists with correct structure")
    
    def test_build_vendor_profile_uses_cache_fallback(self):
        """build_vendor_profile uses cache fallback when BC API returns 0"""
        with open('/app/backend/services/vendor_invoice_profile_service.py', 'r') as f:
            content = f.read()
        
        # Check for cache fallback logic
        assert 'if not bc_invoices:' in content, \
            "build_vendor_profile should check if BC API returned 0 invoices"
        
        assert 'cache_stats = await _learn_from_reference_cache' in content, \
            "build_vendor_profile should call _learn_from_reference_cache as fallback"
        
        # Check for po_expected determination from cache
        assert 'po_expected = False' in content, \
            "build_vendor_profile should set po_expected=False when PO rate is low"
        
        assert 'po_rate < 0.1' in content, \
            "build_vendor_profile should use 10% threshold for po_expected"
        
        print("PASS: build_vendor_profile uses cache fallback when BC API returns 0")
    
    def test_profile_includes_po_expected_field(self):
        """Vendor profile includes po_expected field"""
        with open('/app/backend/services/vendor_invoice_profile_service.py', 'r') as f:
            content = f.read()
        
        # Check profile structure includes po_expected
        assert '"po_expected": po_expected' in content or "'po_expected': po_expected" in content, \
            "Profile should include po_expected field"
        
        print("PASS: Vendor profile includes po_expected field")


class TestApReviewRouterVendorProfileEndpoint:
    """Test ap_review.py vendor-profile endpoint"""
    
    def test_vendor_profile_endpoint_exists(self):
        """GET /api/ap-review/vendor-profile/{vendor_no} endpoint exists"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        assert '@ap_review_router.get("/vendor-profile/{vendor_no}")' in content, \
            "vendor-profile endpoint should exist in ap_review.py"
        
        assert 'async def get_vendor_profile' in content, \
            "get_vendor_profile function should exist"
        
        print("PASS: vendor-profile endpoint exists in ap_review.py")
    
    def test_vendor_profile_endpoint_returns_po_expected(self):
        """vendor-profile endpoint returns po_expected field"""
        with open('/app/backend/routers/ap_review.py', 'r') as f:
            content = f.read()
        
        # Check that endpoint returns po_expected
        assert '"po_expected": profile.get("po_expected"' in content or "'po_expected': profile.get('po_expected'" in content, \
            "vendor-profile endpoint should return po_expected field"
        
        print("PASS: vendor-profile endpoint returns po_expected field")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
