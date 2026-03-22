"""
LLM Pipeline Fixes Tests - Iteration 140
Tests the feedback loop bug fixes and model upgrade:
1. stage_classify_llm receives doc dict and extracts vendor context
2. build_feedback_context_for_prompt is called with vendor_id parameter
3. build_vendor_hints_prompt_section is called with vendor NAME (not filename)
4. Model upgraded from gemini-3-flash-preview to gemini-3-pro-preview
5. General recent corrections always included in prompt
"""
import pytest
import requests
import os
import re

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestModelUpgrade:
    """Verify all models upgraded to gemini-3-pro-preview"""

    def test_classification_pipeline_uses_pro_model(self):
        """Verify classification_pipeline.py uses gemini-3-pro-preview"""
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Check for gemini-3-pro-preview
        assert 'gemini-3-pro-preview' in content, "classification_pipeline.py should use gemini-3-pro-preview"
        
        # Ensure no gemini-3-flash-preview
        assert 'gemini-3-flash-preview' not in content, "classification_pipeline.py should NOT use gemini-3-flash-preview"
        print("✓ classification_pipeline.py uses gemini-3-pro-preview")

    def test_ai_classifier_uses_pro_model(self):
        """Verify ai_classifier.py uses gemini-3-pro-preview"""
        with open('/app/backend/services/ai_classifier.py', 'r') as f:
            content = f.read()
        
        # Check AI_MODEL_NAME constant
        assert 'AI_MODEL_NAME = "gemini-3-pro-preview"' in content, "ai_classifier.py should have AI_MODEL_NAME = gemini-3-pro-preview"
        assert 'gemini-3-flash-preview' not in content, "ai_classifier.py should NOT use gemini-3-flash-preview"
        print("✓ ai_classifier.py uses gemini-3-pro-preview")

    def test_document_intelligence_service_uses_pro_model(self):
        """Verify document_intelligence_service.py uses gemini-3-pro-preview"""
        with open('/app/backend/services/document_intelligence_service.py', 'r') as f:
            content = f.read()
        
        assert 'MODEL_NAME = "gemini-3-pro-preview"' in content, "document_intelligence_service.py should have MODEL_NAME = gemini-3-pro-preview"
        assert 'gemini-3-flash-preview' not in content, "document_intelligence_service.py should NOT use gemini-3-flash-preview"
        print("✓ document_intelligence_service.py uses gemini-3-pro-preview")

    def test_document_intel_helpers_uses_pro_model(self):
        """Verify document_intel_helpers.py uses gemini-3-pro-preview"""
        with open('/app/backend/services/document_intel_helpers.py', 'r') as f:
            content = f.read()
        
        assert 'gemini-3-pro-preview' in content, "document_intel_helpers.py should use gemini-3-pro-preview"
        assert 'gemini-3-flash-preview' not in content, "document_intel_helpers.py should NOT use gemini-3-flash-preview"
        print("✓ document_intel_helpers.py uses gemini-3-pro-preview")

    def test_no_flash_model_in_backend_services(self):
        """Verify no remaining references to gemini-3-flash-preview in backend services"""
        import subprocess
        result = subprocess.run(
            ['grep', '-rn', 'gemini-3-flash-preview', '/app/backend/services/'],
            capture_output=True, text=True
        )
        # Should return empty (no matches)
        assert result.stdout == '', f"Found gemini-3-flash-preview in backend services: {result.stdout}"
        print("✓ No gemini-3-flash-preview references in backend services")


class TestFeedbackLoopFixes:
    """Verify feedback loop bug fixes"""

    def test_stage_classify_llm_receives_doc_parameter(self):
        """Verify stage_classify_llm function signature includes doc parameter"""
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Check function signature
        assert 'async def stage_classify_llm(' in content, "stage_classify_llm should be async"
        assert 'doc: Optional[Dict[str, Any]] = None' in content, "stage_classify_llm should have doc parameter"
        print("✓ stage_classify_llm has doc parameter")

    def test_stage_classify_llm_extracts_vendor_context(self):
        """Verify stage_classify_llm extracts vendor_id and vendor_name from doc"""
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Check vendor context extraction
        assert 'vendor_id = doc.get("vendor_no")' in content or 'vendor_id = doc.get("vendor_no") or doc.get("vendor_id")' in content, \
            "Should extract vendor_id from doc"
        assert 'vendor_name = doc.get("vendor_canonical")' in content or 'vendor_name = doc.get("vendor_canonical") or doc.get("vendor_raw")' in content, \
            "Should extract vendor_name from doc"
        print("✓ stage_classify_llm extracts vendor context from doc")

    def test_feedback_context_called_with_vendor_id(self):
        """Verify build_feedback_context_for_prompt is called with vendor_id"""
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Check that feedback context is called with vendor_id
        assert 'build_feedback_context_for_prompt(' in content, "Should call build_feedback_context_for_prompt"
        assert 'vendor_id=vendor_id or vendor_name' in content, "Should pass vendor_id to build_feedback_context_for_prompt"
        print("✓ build_feedback_context_for_prompt called with vendor_id")

    def test_vendor_hints_called_with_vendor_name(self):
        """Verify build_vendor_hints_prompt_section is called with vendor NAME (not filename)"""
        with open('/app/backend/services/classification_pipeline.py', 'r') as f:
            content = f.read()
        
        # Check that vendor hints is called with vendor_name
        assert 'build_vendor_hints_prompt_section(vendor_name)' in content, \
            "Should call build_vendor_hints_prompt_section with vendor_name (not filename)"
        print("✓ build_vendor_hints_prompt_section called with vendor_name")

    def test_general_recent_corrections_always_included(self):
        """Verify general recent corrections section always returns data"""
        with open('/app/backend/services/feedback_loop_service.py', 'r') as f:
            content = f.read()
        
        # Check for the general recent corrections section
        assert 'RECENT SYSTEM-WIDE CORRECTIONS' in content, "Should have general recent corrections section"
        assert 'recent = await db.classification_feedback.find(' in content, "Should query classification_feedback"
        
        # Verify it's not conditional on vendor_id
        # The query should be {} (empty filter) to get all recent corrections
        assert 'recent = await db.classification_feedback.find(\n        {},' in content, \
            "General recent corrections should query all records (empty filter)"
        print("✓ General recent corrections always included in prompt")


class TestSecondaryLLMPath:
    """Verify secondary LLM path in document_intel_helpers.py also has fixes"""

    def test_secondary_path_has_feedback_injection(self):
        """Verify _call_llm_for_extraction has feedback loop injection"""
        with open('/app/backend/services/document_intel_helpers.py', 'r') as f:
            content = f.read()
        
        # Check for feedback loop injection in secondary path
        assert 'build_feedback_context_for_prompt' in content, "Should import build_feedback_context_for_prompt"
        assert 'feedback_context = await build_feedback_context_for_prompt(' in content, \
            "Should call build_feedback_context_for_prompt in _call_llm_for_extraction"
        print("✓ Secondary LLM path has feedback loop injection")

    def test_secondary_path_infers_vendor_for_hint(self):
        """Verify secondary path infers vendor from filename for vendor hint"""
        with open('/app/backend/services/document_intel_helpers.py', 'r') as f:
            content = f.read()
        
        # Check for vendor inference
        assert 'vendor_for_hint' in content, "Should have vendor_for_hint variable"
        assert 'infer_vendor(file_name)' in content, "Should call infer_vendor with file_name"
        print("✓ Secondary LLM path infers vendor for hint")


class TestFeedbackLoopHealthAPI:
    """Verify feedback loop health API returns correct data"""

    def test_health_endpoint_returns_200(self):
        """Test that the feedback-loop health endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Feedback loop health endpoint returns 200")

    def test_health_response_has_correct_totals(self):
        """Test that response contains correct seeded data totals"""
        response = requests.get(f"{BASE_URL}/api/feedback-loop/health")
        data = response.json()
        
        # Verify seeded data counts
        assert data["total_events"] == 51, f"Expected 51 total events, got {data['total_events']}"
        assert data["applied_events"] == 46, f"Expected 46 applied events, got {data['applied_events']}"
        assert data["learning_signals"]["vendor_aliases_learned"] == 3, \
            f"Expected 3 vendor aliases, got {data['learning_signals']['vendor_aliases_learned']}"
        assert data["learning_signals"]["classification_examples"] == 2, \
            f"Expected 2 classification examples, got {data['learning_signals']['classification_examples']}"
        assert data["learning_signals"]["routing_corrections"] == 1, \
            f"Expected 1 routing correction, got {data['learning_signals']['routing_corrections']}"
        print("✓ Feedback loop health returns correct seeded data totals")


class TestBackendHealth:
    """Basic backend health checks"""

    def test_backend_health_returns_200(self):
        """Test that /api/health returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "healthy", f"Expected healthy status, got {data}"
        print("✓ Backend health check passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
