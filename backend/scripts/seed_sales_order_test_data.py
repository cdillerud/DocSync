"""Seed deterministic customer sales-order documents for isolated testing."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27028")
DB_NAME = os.environ.get("DB_NAME", "gpi_sales_order_test")


def _line(
    *,
    bc_item_number: str | None = "ITEM-100",
    customer_sku: str = "CUSTOMER-SKU-100",
    quantity: Any = 12,
    uom: str | None = "CASE",
    mapping_status: str = "approved",
    confidence: float = 0.99,
) -> Dict[str, Any]:
    return {
        "bc_item_number": bc_item_number,
        "customer_sku": customer_sku,
        "description": "Seeded packaging item",
        "quantity": quantity,
        "uom": uom,
        "mapping_status": mapping_status,
        "item_match_confidence": confidence,
    }


def _document(
    document_id: str,
    *,
    customer_number: str | None = "C10000",
    customer_name: str = "Seeded Customer",
    customer_po: str | None = None,
    confidence: float = 0.98,
    review_status: str = "needs_review",
    sharepoint_url: str | None = None,
    lines: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    po_number = customer_po or f"PO-{document_id.upper()}"
    return {
        "document_id": document_id,
        "file_name": f"{document_id}.pdf",
        "file_size": 4096,
        "file_hash": f"seed-hash-{document_id}",
        "source": "isolated_test_seed",
        "document_type": "Sales_Order",
        "ai_confidence": confidence,
        "classification_reasoning": "Deterministic isolated test seed",
        "bc_customer_no": customer_number,
        "customer_name_extracted": customer_name,
        "extracted_fields": {
            "customer_name": customer_name,
            "customer_po_no": po_number,
            "order_date": "2026-06-23",
            "requested_delivery_date": "2026-07-15",
            "lines": lines if lines is not None else [_line()],
        },
        "sharepoint_web_url": sharepoint_url
        or f"https://example.sharepoint.com/{document_id}.pdf",
        "email_message_id": f"seed-message-{document_id}",
        "status": "NeedsReview",
        "workflow_state": "Classified",
        "workflow_status": "validated",
        "review_status": review_status,
        "validation_errors": [],
        "validation_warnings": [],
        "created_utc": now,
        "updated_utc": now,
        "correlation_id": f"seed-correlation-{document_id}",
    }


def build_documents() -> List[Dict[str, Any]]:
    return [
        _document(
            "so-approved-001",
            review_status="approved",
            customer_po="PO-READY-001",
        ),
        _document(
            "so-approve-001",
            review_status="needs_review",
            customer_po="PO-APPROVE-001",
        ),
        _document(
            "so-reject-001",
            review_status="needs_review",
            customer_po="PO-REJECT-001",
        ),
        _document(
            "so-unknown-customer",
            customer_number=None,
            customer_po="PO-NO-CUSTOMER",
        ),
        _document(
            "so-unmapped-item",
            customer_po="PO-UNMAPPED-ITEM",
            lines=[
                _line(
                    bc_item_number=None,
                    customer_sku="UNKNOWN-CUSTOMER-SKU",
                    mapping_status="unresolved",
                    confidence=0.20,
                )
            ],
        ),
        _document(
            "so-invalid-quantity-uom",
            customer_po="PO-BAD-QTY-UOM",
            lines=[
                _line(
                    quantity="not-a-number",
                    uom=None,
                )
            ],
        ),
        _document(
            "so-low-confidence",
            customer_po="PO-LOW-CONFIDENCE",
            confidence=0.55,
        ),
        _document(
            "so-missing-sharepoint",
            customer_po="PO-NO-SHAREPOINT",
            sharepoint_url="",
        ),
        _document(
            "so-upstream-error",
            customer_po="PO-UPSTREAM-ERROR",
        ),
    ]


def main() -> None:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[DB_NAME]

    documents = build_documents()
    documents[-1]["validation_errors"] = [
        "Seeded upstream extraction validation failure"
    ]

    ids = [doc["document_id"] for doc in documents]
    db.sales_documents.delete_many({"document_id": {"$in": ids}})
    db.sales_documents.insert_many(documents)

    db.sales_documents.create_index("document_id", unique=True)
    db.sales_documents.create_index("document_type")
    db.sales_documents.create_index("review_status")
    db.sales_documents.create_index("bc_posting_status")
    db.sales_documents.create_index("sales_order_idempotency_key")

    print(f"Seeded {len(documents)} sales-order test documents into {DB_NAME}")
    for document in documents:
        print(f"  {document['document_id']}")


if __name__ == "__main__":
    main()
