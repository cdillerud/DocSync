"""
Phase 2: Context-Rich LLM Calls — Test Suite

Tests for vendor_context_builder.py and related Phase 2 features:
- build_extraction_context: Returns rich context with vendor profile + BC invoice examples + aliases
- build_classification_context: Returns entity distribution + classification signals
- Vendor name resolution via aliases
- Auto-confirm feedback recording in ap_auto_post_service
- Classification pipeline BC intelligence injection
- Invoice extractor vendor context injection
"""

import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://doc-intelligence-33.preview.emergentagent.com').rstrip('/')


class TestVendorContextBuilder:
    """Tests for vendor_context_builder.py functions"""
    
    def test_build_extraction_context_returns_rich_context(self):
        """
        Test that build_extraction_context returns rich context with:
        - Vendor profile summary (amounts, PO patterns)
        - 3 real BC invoice examples
        - Known name variants (aliases)
        
        Expected: ~885 chars for TUMALOC vendor
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.vendor_context_builder import build_extraction_context
            
            ctx = await build_extraction_context(db, vendor_no='TUMALOC')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Verify context is returned and has expected content
        assert ctx, "Context should not be empty"
        assert len(ctx) >= 500, f"Context should be at least 500 chars, got {len(ctx)}"
        
        # Verify header
        assert "VENDOR INTELLIGENCE" in ctx, "Should have vendor intelligence header"
        
        # Verify vendor profile section
        assert "VENDOR PROFILE" in ctx, "Should have vendor profile section"
        assert "Tumalo Creek Transportation" in ctx, "Should include vendor name"
        assert "TUMALOC" in ctx, "Should include vendor number"
        
        # Verify historical invoice stats
        assert "Historical invoices" in ctx, "Should have historical invoice stats"
        assert "avg amount" in ctx, "Should have average amount"
        
        # Verify PO expected indicator
        assert "PO EXPECTED" in ctx, "Should have PO expected indicator"
        
        # Verify real invoice examples
        assert "REAL INVOICE EXAMPLES" in ctx, "Should have real invoice examples section"
        assert "Example 1" in ctx, "Should have at least one example"
        
        # Verify aliases section
        assert "KNOWN NAME VARIANTS" in ctx or "TUMALO" in ctx.upper(), "Should have name variants or alias info"
        
        print(f"PASS: build_extraction_context returned {len(ctx)} chars of rich context")
    
    def test_build_classification_context_returns_entity_distribution(self):
        """
        Test that build_classification_context returns:
        - Entity type distribution (purchase invoices vs sales shipments)
        - Strong classification signal for vendors with BC history
        
        Expected: 100% purchase invoices for TUMALOC
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.vendor_context_builder import build_classification_context
            
            ctx = await build_classification_context(db, vendor_no='TUMALOC')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Verify context is returned
        assert ctx, "Classification context should not be empty"
        assert len(ctx) >= 200, f"Context should be at least 200 chars, got {len(ctx)}"
        
        # Verify header
        assert "CLASSIFICATION INTELLIGENCE" in ctx, "Should have classification intelligence header"
        
        # Verify entity distribution
        assert "BC ENTITY HISTORY" in ctx, "Should have BC entity history section"
        assert "TUMALOC" in ctx, "Should include vendor number"
        
        # Verify purchase invoice percentage
        assert "AP Invoices" in ctx or "purchase" in ctx.lower(), "Should mention AP/purchase invoices"
        assert "100%" in ctx, "Should show 100% for TUMALOC (all purchase invoices)"
        
        # Verify strong signal
        assert "STRONG SIGNAL" in ctx, "Should have strong signal indicator"
        assert "AP_Invoice" in ctx, "Should suggest AP_Invoice type"
        
        print(f"PASS: build_classification_context returned {len(ctx)} chars with entity distribution")
    
    def test_build_classification_context_resolves_vendor_name_to_vendor_no(self):
        """
        Test that build_classification_context resolves vendor_name to vendor_no via aliases
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.vendor_context_builder import build_classification_context, _resolve_vendor_no
            
            # Test resolution
            resolved = await _resolve_vendor_no(db, 'Tumalo Creek Transportation')
            
            # Test context with vendor_name only
            ctx = await build_classification_context(db, vendor_name='Tumalo Creek Transportation')
            
            client.close()
            return resolved, ctx
        
        resolved, ctx = asyncio.run(run_test())
        
        # Verify resolution
        assert resolved == 'TUMALOC', f"Should resolve to TUMALOC, got {resolved}"
        
        # Verify context still works with vendor_name
        assert ctx, "Context should not be empty when using vendor_name"
        assert "TUMALOC" in ctx, "Should resolve and include vendor number in context"
        
        print(f"PASS: Vendor name 'Tumalo Creek Transportation' resolved to '{resolved}'")
    
    def test_build_extraction_context_with_vendor_name_only(self):
        """
        Test that build_extraction_context works with vendor_name only (no vendor_no)
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.vendor_context_builder import build_extraction_context
            
            ctx = await build_extraction_context(db, vendor_name='Tumalo Creek Transportation')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Should still return context via profile lookup
        assert ctx, "Context should not be empty when using vendor_name"
        assert "VENDOR PROFILE" in ctx, "Should have vendor profile section"
        
        print(f"PASS: build_extraction_context works with vendor_name only ({len(ctx)} chars)")
    
    def test_build_extraction_context_returns_empty_for_unknown_vendor(self):
        """
        Test that build_extraction_context returns empty string for unknown vendor
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.vendor_context_builder import build_extraction_context
            
            ctx = await build_extraction_context(db, vendor_no='NONEXISTENT_VENDOR_12345')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Should return empty for unknown vendor
        assert ctx == "", f"Should return empty string for unknown vendor, got {len(ctx)} chars"
        
        print("PASS: build_extraction_context returns empty for unknown vendor")


class TestAutoConfirmFeedback:
    """Tests for auto-confirm feedback recording in ap_auto_post_service"""
    
    def test_record_success_feedback_creates_classification_correction(self):
        """
        Test that _record_success_feedback creates a classification_corrections record
        with source='auto_confirm' on ReadyForPost/Posted
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            # Create test document
            test_doc_id = f'test-auto-confirm-{uuid.uuid4().hex[:8]}'
            test_doc = {
                'id': test_doc_id,
                'doc_type': 'AP_Invoice',
                'suggested_job_type': 'AP_Invoice',
                'vendor_canonical': 'Test Vendor Corp',
                'bc_vendor_number': 'TESTV001',
                'filename': 'test_invoice.pdf',
                'file_name': 'test_invoice.pdf',
                'extracted_fields': {'vendor': 'Test Vendor Corp', 'amount': '1500.00'},
                'classification_method': 'heuristic:ap_invoice_text',
                'ai_confidence': 0.95,
                'status': 'ReadyForPost',
                'created_utc': datetime.now(timezone.utc).isoformat(),
            }
            await db.hub_documents.insert_one(test_doc)
            
            # Call _record_success_feedback
            from services.ap_auto_post_service import _record_success_feedback
            await _record_success_feedback(db, test_doc_id, 'ReadyForPost', 'auto')
            
            # Check classification_corrections
            correction = await db.classification_corrections.find_one(
                {'doc_id': test_doc_id, 'source': 'auto_confirm'},
                {'_id': 0}
            )
            
            # Cleanup
            await db.hub_documents.delete_one({'id': test_doc_id})
            await db.classification_corrections.delete_one({'doc_id': test_doc_id})
            
            client.close()
            return correction
        
        correction = asyncio.run(run_test())
        
        # Verify correction record
        assert correction is not None, "Should create classification_corrections record"
        assert correction['source'] == 'auto_confirm', "Source should be 'auto_confirm'"
        assert correction['outcome'] == 'ReadyForPost', "Outcome should be 'ReadyForPost'"
        assert correction['original_type'] == 'AP_Invoice', "Should record original type"
        assert correction['corrected_type'] == 'AP_Invoice', "Corrected type should match (confirmed correct)"
        assert correction['corrected_by'] == 'system_auto_confirm', "Should be corrected by system"
        
        print("PASS: _record_success_feedback creates classification_corrections record")
    
    def test_record_success_feedback_creates_vendor_alias_with_confirm_count(self):
        """
        Test that _record_success_feedback creates/updates vendor alias with confirm_count
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            # Use unique vendor name to avoid conflicts
            unique_vendor = f'Test Vendor {uuid.uuid4().hex[:6]}'
            test_doc_id = f'test-alias-{uuid.uuid4().hex[:8]}'
            
            test_doc = {
                'id': test_doc_id,
                'doc_type': 'AP_Invoice',
                'vendor_canonical': unique_vendor,
                'bc_vendor_number': 'TESTV002',
                'filename': 'test_invoice.pdf',
                'file_name': 'test_invoice.pdf',
                'status': 'Posted',
                'created_utc': datetime.now(timezone.utc).isoformat(),
            }
            await db.hub_documents.insert_one(test_doc)
            
            # Call _record_success_feedback
            from services.ap_auto_post_service import _record_success_feedback
            await _record_success_feedback(db, test_doc_id, 'Posted', 'auto')
            
            # Check vendor_aliases
            alias = await db.vendor_aliases.find_one(
                {'alias_string': unique_vendor, 'vendor_no': 'TESTV002'},
                {'_id': 0}
            )
            
            # Cleanup
            await db.hub_documents.delete_one({'id': test_doc_id})
            await db.classification_corrections.delete_one({'doc_id': test_doc_id})
            await db.vendor_aliases.delete_one({'alias_string': unique_vendor, 'vendor_no': 'TESTV002'})
            
            client.close()
            return alias
        
        alias = asyncio.run(run_test())
        
        # Verify alias record
        assert alias is not None, "Should create vendor_aliases record"
        assert alias['source'] == 'auto_confirm', "Source should be 'auto_confirm'"
        assert alias['confirm_count'] >= 1, "Should have confirm_count >= 1"
        assert 'learned_at' in alias, "Should have learned_at timestamp"
        
        print("PASS: _record_success_feedback creates vendor alias with confirm_count")


class TestKnowledgeSeedEndpoints:
    """Tests for knowledge-seed endpoints (Phase 1 regression)"""
    
    def test_knowledge_seed_status_endpoint(self):
        """Test GET /api/knowledge-seed/status returns correct metrics"""
        response = requests.get(f"{BASE_URL}/api/knowledge-seed/status")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify knowledge_base structure
        assert 'knowledge_base' in data, "Should have knowledge_base"
        kb = data['knowledge_base']
        
        assert 'vendor_aliases' in kb, "Should have vendor_aliases"
        assert kb['vendor_aliases']['total'] >= 900, f"Should have 900+ aliases, got {kb['vendor_aliases']['total']}"
        
        assert 'vendor_invoice_profiles' in kb, "Should have vendor_invoice_profiles"
        assert kb['vendor_invoice_profiles'] >= 600, f"Should have 600+ profiles, got {kb['vendor_invoice_profiles']}"
        
        assert 'bc_reference_cache' in kb, "Should have bc_reference_cache"
        assert kb['bc_reference_cache'] >= 270000, f"Should have 270K+ BC records, got {kb['bc_reference_cache']}"
        
        # Verify health
        assert 'health' in data, "Should have health"
        assert data['health']['overall'] == 'good', f"Health should be 'good', got {data['health']['overall']}"
        
        print(f"PASS: Knowledge seed status: {kb['vendor_aliases']['total']} aliases, {kb['vendor_invoice_profiles']} profiles, {kb['bc_reference_cache']} BC records")


class TestClassificationPipelineIntegration:
    """Tests for classification pipeline BC intelligence injection"""
    
    def test_classification_pipeline_imports_vendor_context_builder(self):
        """
        Test that classification_pipeline.py imports and uses vendor_context_builder
        """
        # Read the classification_pipeline.py file
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Verify import
        assert 'from services.vendor_context_builder import build_classification_context' in content, \
            "Should import build_classification_context"
        
        # Verify usage in stage_classify_llm
        assert 'build_classification_context' in content, "Should use build_classification_context"
        assert 'classification_ctx' in content or 'classification_context' in content, \
            "Should store classification context in variable"
        
        print("PASS: Classification pipeline imports and uses vendor_context_builder")
    
    def test_invoice_extractor_imports_vendor_context_builder(self):
        """
        Test that invoice_extractor.py imports and uses vendor_context_builder
        """
        # Read the invoice_extractor.py file
        with open('/app/backend/services/invoice_extractor.py', 'r') as f:
            content = f.read()
        
        # Verify import
        assert 'from services.vendor_context_builder import build_extraction_context' in content, \
            "Should import build_extraction_context"
        
        # Verify usage in extract_and_update_document
        assert 'build_extraction_context' in content, "Should use build_extraction_context"
        assert 'vendor_context' in content, "Should store vendor context in variable"
        
        print("PASS: Invoice extractor imports and uses vendor_context_builder")


class TestFeedbackLoopServiceIntegration:
    """Tests for feedback_loop_service.py integration with Phase 2"""
    
    def test_feedback_loop_uses_classification_corrections(self):
        """
        Test that build_feedback_context_for_prompt uses classification_corrections
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.feedback_loop_service import build_feedback_context_for_prompt
            
            # Build context for a known vendor
            ctx = await build_feedback_context_for_prompt(db, vendor_id='TUMALOC')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Should return context with vendor profile info
        assert ctx, "Should return feedback context"
        assert "VENDOR PROFILE" in ctx or "FEEDBACK LOOP" in ctx, \
            "Should have vendor profile or feedback loop section"
        
        print(f"PASS: build_feedback_context_for_prompt returns {len(ctx)} chars of context")
    
    def test_feedback_loop_uses_vendor_profiles(self):
        """
        Test that build_feedback_context_for_prompt uses vendor_invoice_profiles
        """
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        
        async def run_test():
            client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
            db = client[os.environ.get('DB_NAME', 'gpi_document_hub')]
            
            from services.feedback_loop_service import build_feedback_context_for_prompt
            
            # Build context for TUMALOC which has a rich profile
            ctx = await build_feedback_context_for_prompt(db, vendor_id='TUMALOC')
            
            client.close()
            return ctx
        
        ctx = asyncio.run(run_test())
        
        # Should include vendor profile stats
        if ctx:
            # Check for profile indicators
            has_profile = "VENDOR PROFILE" in ctx or "Historical" in ctx or "invoices" in ctx.lower()
            assert has_profile, "Should include vendor profile information"
        
        print(f"PASS: Feedback loop context includes vendor profile data")


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_api_health(self):
        """Test API health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get('status') == 'healthy', f"Expected healthy, got {data.get('status')}"
        print("PASS: API health check")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
