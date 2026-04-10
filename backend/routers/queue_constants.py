"""
Shared filter constants for inbox/queue operations.
Single source of truth — imported by documents.py, dashboard.py, readiness.py.
"""

TERMINAL_STATUSES = [
    "Completed", "Posted", "Archived", "completed", "posted", "archived",
    "FileMissing", "batch_parent", "Validated", "validated", "ValidationPassed",
    "ReadyForPost", "ready_for_post", "AutoFiled", "auto_filed", "LinkedToBC",
    "Exception", "exception",
]

DONE_WORKFLOW_STATUSES = [
    "completed", "validation_passed", "processed", "ready_for_approval",
    "exported", "file_missing", "exception_review", "po_pending",
]

AP_TYPES = [
    "AP_INVOICE", "AP_Invoice", "AP Invoice",
    "FREIGHT_INVOICE", "Freight Invoice",
    "CREDIT_MEMO", "Credit Memo",
]

SALES_TYPES = [
    "SALES_ORDER", "Sales Order",
    "PURCHASE_ORDER", "Purchase Order",
    "SHIPPING", "Shipping", "BOL",
]


def build_inbox_filter(*, include_cleared=False):
    """Build the canonical inbox filter matching the documents endpoint (queue_view=true)."""
    conditions = [
        {"is_duplicate": {"$ne": True}},
        {"status": {"$nin": TERMINAL_STATUSES}},
        {"$or": [
            {"workflow_status": {"$nin": DONE_WORKFLOW_STATUSES}},
            {"workflow_status": {"$exists": False}},
        ]},
    ]
    if not include_cleared:
        conditions.append(
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]}
        )
    return {"$and": conditions}
