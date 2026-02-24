"""
GPI Document Hub - AI Document Classification Service

This module provides AI-assisted document type classification using EMERGENT_LLM_KEY.
It is only invoked when deterministic classification rules cannot determine the doc_type.

Key principles:
1. AI classification is ASSIST ONLY - deterministic rules always win
2. Only called when doc_type would otherwise be "OTHER"
3. Requires confidence >= threshold (default 0.8) to override "OTHER"
4. All AI classifications are audited on the document
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Valid doc_type values the AI can return
VALID_DOC_TYPES = [
    "AP_INVOICE",
    "SALES_INVOICE",
    "PURCHASE_ORDER",
    "SALES_ORDER",
    "SALES_CREDIT_MEMO",
    "PURCHASE_CREDIT_MEMO",
    "STATEMENT",
    "REMINDER",
    "FINANCE_CHARGE_MEMO",
    "QUALITY_DOC",
    "PACKING_SLIP",
    "BILL_OF_LADING",
    "OTHER"
]

# AI Model configuration
AI_MODEL_PROVIDER = "gemini"
AI_MODEL_NAME = "gemini-3-flash-preview"

# Default confidence threshold for accepting AI classification
DEFAULT_CONFIDENCE_THRESHOLD = 0.8


@dataclass
class AIClassificationResult:
    """Result of AI document type classification."""
    proposed_doc_type: str
    confidence: float
    model_name: str
    timestamp: str
    raw_response: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        result = {
            "proposed_doc_type": self.proposed_doc_type,
            "confidence": self.confidence,
            "model_name": self.model_name,
            "timestamp": self.timestamp
        }
        if self.error:
            result["error"] = self.error
        return result
    
    def is_valid(self) -> bool:
        """Check if result is valid (no error, valid doc_type)."""
        return (
            self.error is None and 
            self.proposed_doc_type in VALID_DOC_TYPES
        )
    
    def should_accept(self, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
        """Check if we should accept this classification."""
        return (
            self.is_valid() and 
            self.confidence >= threshold and 
            self.proposed_doc_type != "OTHER"
        )


async def classify_doc_type_with_ai(
    document: Dict[str, Any],
    extracted_text: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> AIClassificationResult:
    """
    Classify document type using AI when deterministic rules return OTHER.
    
    Args:
        document: The document dict with any existing metadata
        extracted_text: OCR or text content from the document
        metadata: Additional metadata (Zetadocs code, Square9 workflow, etc.)
    
    Returns:
        AIClassificationResult with proposed_doc_type and confidence
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    model_name = AI_MODEL_NAME
    
    # Check if EMERGENT_LLM_KEY is configured
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        logger.warning("EMERGENT_LLM_KEY not configured, skipping AI classification")
        return AIClassificationResult(
            proposed_doc_type="OTHER",
            confidence=0.0,
            model_name="none",
            timestamp=timestamp,
            error="EMERGENT_LLM_KEY not configured"
        )
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        # Build context from document metadata
        context_parts = []
        
        # File name and type
        file_name = document.get("file_name", "unknown")
        context_parts.append(f"File name: {file_name}")
        
        # Email metadata
        email_sender = document.get("email_sender")
        email_subject = document.get("email_subject")
        if email_sender:
            context_parts.append(f"Email sender: {email_sender}")
        if email_subject:
            context_parts.append(f"Email subject: {email_subject}")
        
        # Existing metadata that didn't provide a clear classification
        if metadata:
            if metadata.get("zetadocs_set"):
                context_parts.append(f"Zetadocs set code: {metadata['zetadocs_set']}")
            if metadata.get("square9_workflow"):
                context_parts.append(f"Square9 workflow: {metadata['square9_workflow']}")
            if metadata.get("mailbox_category"):
                context_parts.append(f"Mailbox category: {metadata['mailbox_category']}")
        
        # Extracted fields from AI extraction (if available)
        extracted_fields = document.get("extracted_fields", {})
        if extracted_fields:
            if extracted_fields.get("vendor"):
                context_parts.append(f"Vendor: {extracted_fields['vendor']}")
            if extracted_fields.get("invoice_number"):
                context_parts.append(f"Invoice/Document number: {extracted_fields['invoice_number']}")
            if extracted_fields.get("amount"):
                context_parts.append(f"Amount: {extracted_fields['amount']}")
            if extracted_fields.get("po_number"):
                context_parts.append(f"PO Number: {extracted_fields['po_number']}")
        
        # Flat fields from document
        vendor_raw = document.get("vendor_raw")
        invoice_number = document.get("invoice_number_clean") or document.get("invoice_number_raw")
        amount = document.get("amount_float") or document.get("amount_raw")
        
        if vendor_raw:
            context_parts.append(f"Vendor (extracted): {vendor_raw}")
        if invoice_number:
            context_parts.append(f"Invoice number (extracted): {invoice_number}")
        if amount:
            context_parts.append(f"Amount (extracted): {amount}")
        
        # Text content (truncated)
        text_content = extracted_text or document.get("text_content") or ""
        if text_content:
            # Truncate to first 2000 chars for prompt efficiency
            truncated_text = text_content[:2000]
            if len(text_content) > 2000:
                truncated_text += "... [truncated]"
            context_parts.append(f"Document text:\n{truncated_text}")
        
        context_str = "\n".join(context_parts)
        
        # Build the classification prompt
        system_message = """You are a document classification expert for a business document management system.
Your task is to classify business documents into the correct document type.

You MUST respond with ONLY a JSON object in this exact format:
{"doc_type": "TYPE", "confidence": 0.XX}

Where TYPE must be EXACTLY one of these values:
- AP_INVOICE: Vendor invoices/bills we receive and need to pay
- SALES_INVOICE: Invoices we send to our customers
- PURCHASE_ORDER: Purchase orders we send to vendors
- SALES_CREDIT_MEMO: Credit memos/returns we issue to customers
- PURCHASE_CREDIT_MEMO: Credit memos we receive from vendors
- STATEMENT: Account statements from vendors or to customers
- REMINDER: Payment reminders
- FINANCE_CHARGE_MEMO: Finance charge documents
- QUALITY_DOC: Quality assurance documentation
- OTHER: Cannot confidently classify

The confidence should be between 0.0 and 1.0, where:
- 1.0 = absolutely certain
- 0.8+ = confident enough to classify
- 0.5-0.8 = somewhat uncertain
- <0.5 = not confident, should likely be OTHER

Classification guidelines:
- AP_INVOICE: Documents from vendors requesting payment, includes "invoice", "bill", vendor names
- SALES_INVOICE: Documents we send for payment, addressed to customers
- PURCHASE_ORDER: PO documents with line items, sent to vendors
- STATEMENT: Summary of account activity, not a single transaction
- Look at sender/recipient context to distinguish AP vs Sales documents

RESPOND ONLY WITH THE JSON OBJECT, NO OTHER TEXT."""

        user_prompt = f"""Classify this document based on the available information:

{context_str}

Respond with only the JSON object."""

        # Initialize chat and send message
        chat = LlmChat(
            api_key=api_key,
            session_id=f"doc_classify_{document.get('id', 'unknown')}",
            system_message=system_message
        ).with_model(AI_MODEL_PROVIDER, AI_MODEL_NAME)
        
        user_message = UserMessage(text=user_prompt)
        response = await chat.send_message(user_message)
        
        logger.info("AI classification raw response: %s", response)
        
        # Parse the response
        import json
        
        # Try to extract JSON from response
        response_text = str(response).strip()
        
        # Handle cases where response might have extra text
        if response_text.startswith("{"):
            json_str = response_text
        elif "{" in response_text:
            # Extract JSON from response
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            json_str = response_text[start:end]
        else:
            raise ValueError(f"No JSON found in response: {response_text}")
        
        result_data = json.loads(json_str)
        
        proposed_type = result_data.get("doc_type", "OTHER").upper()
        confidence = float(result_data.get("confidence", 0.0))
        
        # Validate doc_type
        if proposed_type not in VALID_DOC_TYPES:
            logger.warning("AI returned invalid doc_type: %s, defaulting to OTHER", proposed_type)
            proposed_type = "OTHER"
            confidence = 0.0
        
        # Clamp confidence to valid range
        confidence = max(0.0, min(1.0, confidence))
        
        return AIClassificationResult(
            proposed_doc_type=proposed_type,
            confidence=confidence,
            model_name=model_name,
            timestamp=timestamp,
            raw_response=response_text
        )
        
    except ImportError as e:
        logger.error("emergentintegrations not installed: %s", str(e))
        return AIClassificationResult(
            proposed_doc_type="OTHER",
            confidence=0.0,
            model_name=model_name,
            timestamp=timestamp,
            error=f"emergentintegrations not available: {str(e)}"
        )
    except Exception as e:
        logger.error("AI classification failed: %s", str(e))
        return AIClassificationResult(
            proposed_doc_type="OTHER",
            confidence=0.0,
            model_name=model_name,
            timestamp=timestamp,
            error=str(e)
        )


def apply_ai_classification(
    document: Dict[str, Any],
    ai_result: AIClassificationResult,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> Dict[str, Any]:
    """
    Apply AI classification result to a document if it meets the threshold.
    
    Args:
        document: The document dict to update
        ai_result: The AI classification result
        threshold: Confidence threshold for accepting classification
    
    Returns:
        Updated document dict
    """
    # Always add the AI classification audit trail
    document["ai_classification"] = ai_result.to_dict()
    
    # Only change doc_type if AI result passes threshold
    if ai_result.should_accept(threshold):
        document["doc_type"] = ai_result.proposed_doc_type
        logger.info(
            "AI classification accepted for doc %s: %s (confidence: %.2f)",
            document.get("id"), ai_result.proposed_doc_type, ai_result.confidence
        )
    else:
        logger.info(
            "AI classification NOT accepted for doc %s: %s (confidence: %.2f, threshold: %.2f)",
            document.get("id"), ai_result.proposed_doc_type, ai_result.confidence, threshold
        )
    
    return document
