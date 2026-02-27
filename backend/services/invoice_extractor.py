"""
GPI Document Hub - Invoice Data Extraction Service

This service uses Gemini AI with vision capabilities to extract structured data
from invoice PDFs, including:
- Invoice number
- Invoice date
- Due date
- Vendor name
- PO number
- Line items (description, quantity, unit price, total)
- Total amount
- Tax amount

The extraction is designed to enable auto-population of AP Review forms
and potentially auto-posting to Business Central.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# Confidence thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.90
MEDIUM_CONFIDENCE_THRESHOLD = 0.75


class InvoiceExtractionResult:
    """Result of invoice data extraction."""
    
    def __init__(
        self,
        success: bool = False,
        confidence: float = 0.0,
        invoice_number: str = None,
        invoice_date: str = None,
        due_date: str = None,
        vendor_name: str = None,
        vendor_number: str = None,
        po_number: str = None,
        total_amount: float = None,
        tax_amount: float = None,
        currency: str = "USD",
        line_items: List[Dict] = None,
        raw_response: str = None,
        error: str = None
    ):
        self.success = success
        self.confidence = confidence
        self.invoice_number = invoice_number
        self.invoice_date = invoice_date
        self.due_date = due_date
        self.vendor_name = vendor_name
        self.vendor_number = vendor_number
        self.po_number = po_number
        self.total_amount = total_amount
        self.tax_amount = tax_amount
        self.currency = currency
        self.line_items = line_items or []
        self.raw_response = raw_response
        self.error = error
        self.extracted_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "confidence": self.confidence,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
            "vendor_name": self.vendor_name,
            "vendor_number": self.vendor_number,
            "po_number": self.po_number,
            "total_amount": self.total_amount,
            "tax_amount": self.tax_amount,
            "currency": self.currency,
            "line_items": self.line_items,
            "extracted_at": self.extracted_at,
            "error": self.error
        }
    
    def can_auto_post(self) -> bool:
        """Check if extraction quality is sufficient for auto-posting."""
        return (
            self.success and
            self.confidence >= HIGH_CONFIDENCE_THRESHOLD and
            self.invoice_number and
            self.invoice_date and
            self.vendor_name and
            self.total_amount is not None
        )


EXTRACTION_PROMPT = """You are an expert invoice data extraction system. Analyze this invoice document and extract all relevant data.

IMPORTANT: Return ONLY a valid JSON object with NO additional text, markdown, or explanation.

Extract the following fields from the invoice:

1. **invoice_number**: The vendor's invoice number/reference
2. **invoice_date**: Invoice date in YYYY-MM-DD format
3. **due_date**: Payment due date in YYYY-MM-DD format (if shown)
4. **vendor_name**: The vendor/supplier company name
5. **vendor_number**: The vendor's account number (if shown)
6. **po_number**: Purchase order number reference (if shown)
7. **total_amount**: Total invoice amount as a number (no currency symbol)
8. **tax_amount**: Tax/VAT amount as a number (if shown, otherwise null)
9. **currency**: Currency code (USD, CAD, EUR, etc.) - default to USD if not shown
10. **line_items**: Array of line items, each with:
    - description: Item/service description
    - quantity: Quantity as a number
    - unit_price: Price per unit as a number
    - total: Line total as a number
11. **confidence**: Your confidence in the extraction accuracy (0.0 to 1.0)

For freight/transportation invoices, common line item fields may include:
- Weight, distance, rate, charges
- Fuel surcharges, accessorial charges
- Treat these as line items with appropriate descriptions

JSON Response format:
{
    "invoice_number": "string",
    "invoice_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD or null",
    "vendor_name": "string",
    "vendor_number": "string or null",
    "po_number": "string or null",
    "total_amount": number,
    "tax_amount": number or null,
    "currency": "USD",
    "line_items": [
        {
            "description": "string",
            "quantity": number,
            "unit_price": number,
            "total": number
        }
    ],
    "confidence": number
}

If you cannot extract a field, set it to null. Always provide a confidence score."""


async def extract_invoice_data(file_path: str) -> InvoiceExtractionResult:
    """
    Extract structured data from an invoice PDF using Gemini AI.
    
    Args:
        file_path: Path to the PDF file on disk
        
    Returns:
        InvoiceExtractionResult with extracted data
    """
    if not EMERGENT_LLM_KEY:
        logger.warning("EMERGENT_LLM_KEY not configured, skipping invoice extraction")
        return InvoiceExtractionResult(
            success=False,
            error="EMERGENT_LLM_KEY not configured"
        )
    
    # Verify file exists
    if not os.path.exists(file_path):
        return InvoiceExtractionResult(
            success=False,
            error=f"File not found: {file_path}"
        )
    
    # Check file extension or detect by magic bytes
    file_ext = Path(file_path).suffix.lower()
    
    # If no extension, detect file type from content
    if not file_ext:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(10)
            # PDF files start with %PDF
            if header.startswith(b'%PDF'):
                file_ext = '.pdf'
            # PNG files start with specific bytes
            elif header[:8] == b'\x89PNG\r\n\x1a\n':
                file_ext = '.png'
            # JPEG files start with FFD8FF
            elif header[:3] == b'\xff\xd8\xff':
                file_ext = '.jpg'
            # TIFF files start with II or MM
            elif header[:2] in (b'II', b'MM'):
                file_ext = '.tiff'
            else:
                return InvoiceExtractionResult(
                    success=False,
                    error=f"Unable to detect file type from content"
                )
        except Exception as e:
            return InvoiceExtractionResult(
                success=False,
                error=f"Error reading file header: {str(e)}"
            )
    
    if file_ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif']:
        return InvoiceExtractionResult(
            success=False,
            error=f"Unsupported file type: {file_ext}. Supported: PDF, PNG, JPG, TIFF"
        )
    
    # Determine MIME type
    mime_types = {
        '.pdf': 'application/pdf',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff'
    }
    mime_type = mime_types.get(file_ext, 'application/pdf')
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
        
        # Create file content object for Gemini
        file_content = FileContentWithMimeType(
            file_path=file_path,
            mime_type=mime_type
        )
        
        # Initialize Gemini chat (must use Gemini for file analysis)
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"invoice_extract_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            system_message="You are an expert invoice data extraction system. Always respond with valid JSON only."
        ).with_model("gemini", "gemini-2.5-flash")
        
        # Send message with file attachment
        user_message = UserMessage(
            text=EXTRACTION_PROMPT,
            file_contents=[file_content]
        )
        
        response = await chat.send_message(user_message)
        logger.info("Invoice extraction raw response: %s", str(response)[:500])
        
        # Parse JSON response
        response_text = str(response).strip()
        
        # Extract JSON from response (handle potential markdown wrapping)
        if response_text.startswith("```"):
            # Remove markdown code blocks
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json") or line.startswith("```"):
                    in_json = not in_json
                    continue
                if in_json or (not line.startswith("```")):
                    json_lines.append(line)
            response_text = "\n".join(json_lines).strip()
        
        # Find JSON object in response
        if response_text.startswith("{"):
            json_str = response_text
        elif "{" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            json_str = response_text[start:end]
        else:
            raise ValueError(f"No JSON found in response: {response_text[:200]}")
        
        data = json.loads(json_str)
        
        # Parse line items
        line_items = []
        for item in data.get("line_items", []):
            line_items.append({
                "description": item.get("description", ""),
                "quantity": float(item.get("quantity", 1)) if item.get("quantity") else 1,
                "unit_price": float(item.get("unit_price", 0)) if item.get("unit_price") else 0,
                "total": float(item.get("total", 0)) if item.get("total") else 0
            })
        
        return InvoiceExtractionResult(
            success=True,
            confidence=float(data.get("confidence", 0.8)),
            invoice_number=data.get("invoice_number"),
            invoice_date=data.get("invoice_date"),
            due_date=data.get("due_date"),
            vendor_name=data.get("vendor_name"),
            vendor_number=data.get("vendor_number"),
            po_number=data.get("po_number"),
            total_amount=float(data.get("total_amount")) if data.get("total_amount") is not None else None,
            tax_amount=float(data.get("tax_amount")) if data.get("tax_amount") is not None else None,
            currency=data.get("currency", "USD"),
            line_items=line_items,
            raw_response=response_text
        )
        
    except ImportError as e:
        logger.error("emergentintegrations not available: %s", str(e))
        return InvoiceExtractionResult(
            success=False,
            error=f"emergentintegrations not available: {str(e)}"
        )
    except json.JSONDecodeError as e:
        logger.error("Failed to parse extraction response as JSON: %s", str(e))
        return InvoiceExtractionResult(
            success=False,
            error=f"Invalid JSON response: {str(e)}",
            raw_response=response_text if 'response_text' in locals() else None
        )
    except Exception as e:
        logger.error("Invoice extraction failed: %s", str(e))
        return InvoiceExtractionResult(
            success=False,
            error=str(e)
        )


async def extract_and_update_document(doc_id: str, file_path: str, db) -> Dict[str, Any]:
    """
    Extract invoice data and update the document in the database.
    
    Args:
        doc_id: Document ID in MongoDB
        file_path: Path to the PDF file
        db: MongoDB database reference
        
    Returns:
        Dict with extraction result and updated fields
    """
    result = await extract_invoice_data(file_path)
    
    if not result.success:
        return {
            "success": False,
            "error": result.error,
            "document_id": doc_id
        }
    
    # Build update fields
    update_fields = {
        "ai_extraction": result.to_dict(),
        "ai_extraction_timestamp": result.extracted_at,
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Update extracted_fields
    extracted_fields = {}
    if result.invoice_number:
        extracted_fields["invoice_number"] = result.invoice_number
        update_fields["invoice_number_clean"] = result.invoice_number
    if result.invoice_date:
        extracted_fields["invoice_date"] = result.invoice_date
        update_fields["invoice_date"] = result.invoice_date
    if result.due_date:
        extracted_fields["due_date"] = result.due_date
        update_fields["due_date_iso"] = result.due_date
    if result.vendor_name:
        extracted_fields["vendor"] = result.vendor_name
        update_fields["vendor_raw"] = result.vendor_name
    if result.po_number:
        extracted_fields["po_number"] = result.po_number
        update_fields["po_number_clean"] = result.po_number
    if result.total_amount is not None:
        extracted_fields["amount"] = str(result.total_amount)
        update_fields["amount_float"] = result.total_amount
    if result.tax_amount is not None:
        update_fields["tax_amount"] = result.tax_amount
    if result.currency:
        update_fields["currency"] = result.currency
    if result.line_items:
        update_fields["line_items"] = result.line_items
    
    update_fields["extracted_fields"] = extracted_fields
    
    # Update document in database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": update_fields}
    )
    
    return {
        "success": True,
        "document_id": doc_id,
        "confidence": result.confidence,
        "can_auto_post": result.can_auto_post(),
        "extracted_fields": extracted_fields,
        "line_items_count": len(result.line_items),
        "line_items": result.line_items
    }
