"""
Unit tests for AI Document Classification Service

Tests the deterministic-first classification pipeline and AI fallback.
"""
import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

# Import the classifier
import sys
sys.path.insert(0, '/app/backend')
from services.ai_classifier import (
    classify_doc_type_with_ai,
    apply_ai_classification,
    AIClassificationResult,
    VALID_DOC_TYPES,
    DEFAULT_CONFIDENCE_THRESHOLD
)


class TestAIClassificationResult:
    """Tests for AIClassificationResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.95,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        d = result.to_dict()
        assert d["proposed_doc_type"] == "AP_INVOICE"
        assert d["confidence"] == 0.95
        assert d["model_name"] == "gpt-5.2"
        assert d["timestamp"] == "2026-02-22T10:00:00Z"
        assert "error" not in d
    
    def test_to_dict_with_error(self):
        """Test conversion includes error when present."""
        result = AIClassificationResult(
            proposed_doc_type="OTHER",
            confidence=0.0,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z",
            error="API call failed"
        )
        d = result.to_dict()
        assert d["error"] == "API call failed"
    
    def test_is_valid_success(self):
        """Test validity check for good result."""
        result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.95,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        assert result.is_valid() is True
    
    def test_is_valid_with_error(self):
        """Test validity check with error."""
        result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.95,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z",
            error="Something went wrong"
        )
        assert result.is_valid() is False
    
    def test_is_valid_invalid_doc_type(self):
        """Test validity check with invalid doc_type."""
        result = AIClassificationResult(
            proposed_doc_type="INVALID_TYPE",
            confidence=0.95,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        assert result.is_valid() is False
    
    def test_should_accept_above_threshold(self):
        """Test acceptance when confidence above threshold."""
        result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.85,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        assert result.should_accept(threshold=0.8) is True
    
    def test_should_accept_below_threshold(self):
        """Test rejection when confidence below threshold."""
        result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.75,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        assert result.should_accept(threshold=0.8) is False
    
    def test_should_accept_other_type(self):
        """Test rejection when type is OTHER (AI uncertain)."""
        result = AIClassificationResult(
            proposed_doc_type="OTHER",
            confidence=0.95,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        # Even with high confidence, OTHER is not accepted
        assert result.should_accept(threshold=0.8) is False


class TestApplyAIClassification:
    """Tests for apply_ai_classification function."""
    
    def test_apply_accepted_classification(self):
        """Test applying accepted AI classification."""
        document = {
            "id": "doc-123",
            "doc_type": "OTHER"
        }
        ai_result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.92,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        
        updated_doc = apply_ai_classification(document, ai_result, threshold=0.8)
        
        assert updated_doc["doc_type"] == "AP_INVOICE"
        assert "ai_classification" in updated_doc
        assert updated_doc["ai_classification"]["proposed_doc_type"] == "AP_INVOICE"
        assert updated_doc["ai_classification"]["confidence"] == 0.92
    
    def test_apply_rejected_classification(self):
        """Test applying rejected AI classification (below threshold)."""
        document = {
            "id": "doc-123",
            "doc_type": "OTHER"
        }
        ai_result = AIClassificationResult(
            proposed_doc_type="AP_INVOICE",
            confidence=0.65,
            model_name="gpt-5.2",
            timestamp="2026-02-22T10:00:00Z"
        )
        
        updated_doc = apply_ai_classification(document, ai_result, threshold=0.8)
        
        # doc_type should NOT be updated
        assert updated_doc["doc_type"] == "OTHER"
        # But audit trail should still be recorded
        assert "ai_classification" in updated_doc
        assert updated_doc["ai_classification"]["proposed_doc_type"] == "AP_INVOICE"


class TestClassifyDocTypeWithAI:
    """Tests for classify_doc_type_with_ai function."""
    
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        """Test behavior when EMERGENT_LLM_KEY is not set."""
        # Clear the env var
        with patch.dict(os.environ, {"EMERGENT_LLM_KEY": ""}, clear=False):
            os.environ.pop("EMERGENT_LLM_KEY", None)
            
            document = {"id": "doc-123", "file_name": "invoice.pdf"}
            result = await classify_doc_type_with_ai(document)
            
            assert result.proposed_doc_type == "OTHER"
            assert result.confidence == 0.0
            assert result.model_name == "none"
            assert "not configured" in result.error
    
    @pytest.mark.asyncio
    async def test_successful_classification(self):
        """Test successful AI classification call."""
        mock_response = '{"doc_type": "AP_INVOICE", "confidence": 0.91}'
        
        mock_chat = MagicMock()
        mock_chat.with_model.return_value = mock_chat
        mock_chat.send_message = AsyncMock(return_value=mock_response)
        
        with patch.dict(os.environ, {"EMERGENT_LLM_KEY": "test-key"}):
            with patch('services.ai_classifier.LlmChat', return_value=mock_chat):
                document = {
                    "id": "doc-123",
                    "file_name": "invoice.pdf",
                    "email_sender": "vendor@company.com",
                    "email_subject": "Invoice #12345"
                }
                result = await classify_doc_type_with_ai(document)
                
                assert result.proposed_doc_type == "AP_INVOICE"
                assert result.confidence == 0.91
                assert result.error is None
    
    @pytest.mark.asyncio
    async def test_invalid_doc_type_from_ai(self):
        """Test handling of invalid doc_type from AI."""
        mock_response = '{"doc_type": "UNKNOWN_TYPE", "confidence": 0.95}'
        
        mock_chat = MagicMock()
        mock_chat.with_model.return_value = mock_chat
        mock_chat.send_message = AsyncMock(return_value=mock_response)
        
        with patch.dict(os.environ, {"EMERGENT_LLM_KEY": "test-key"}):
            with patch('services.ai_classifier.LlmChat', return_value=mock_chat):
                document = {"id": "doc-123", "file_name": "unknown.pdf"}
                result = await classify_doc_type_with_ai(document)
                
                # Invalid types should default to OTHER
                assert result.proposed_doc_type == "OTHER"
                assert result.confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_api_error(self):
        """Test handling of API errors."""
        mock_chat = MagicMock()
        mock_chat.with_model.return_value = mock_chat
        mock_chat.send_message = AsyncMock(side_effect=Exception("API timeout"))
        
        with patch.dict(os.environ, {"EMERGENT_LLM_KEY": "test-key"}):
            with patch('services.ai_classifier.LlmChat', return_value=mock_chat):
                document = {"id": "doc-123", "file_name": "test.pdf"}
                result = await classify_doc_type_with_ai(document)
                
                assert result.proposed_doc_type == "OTHER"
                assert result.confidence == 0.0
                assert "API timeout" in result.error


class TestValidDocTypes:
    """Tests for valid doc types constant."""
    
    def test_all_expected_types_present(self):
        """Ensure all expected doc types are in VALID_DOC_TYPES."""
        expected = [
            "AP_INVOICE",
            "SALES_INVOICE", 
            "PURCHASE_ORDER",
            "SALES_CREDIT_MEMO",
            "PURCHASE_CREDIT_MEMO",
            "STATEMENT",
            "REMINDER",
            "FINANCE_CHARGE_MEMO",
            "QUALITY_DOC",
            "OTHER"
        ]
        for doc_type in expected:
            assert doc_type in VALID_DOC_TYPES, f"{doc_type} missing from VALID_DOC_TYPES"
    
    def test_default_threshold(self):
        """Test default confidence threshold is 0.8."""
        assert DEFAULT_CONFIDENCE_THRESHOLD == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
