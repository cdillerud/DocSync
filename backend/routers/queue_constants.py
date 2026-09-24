"""
Shared filter constants for inbox/queue operations.
Single source of truth — imported by documents.py, dashboard.py, readiness.py.
"""

# 2026-09-24: audited against what the backend actually sets and what these
# values mean to a human. Four real problems were found and fixed here:
#   1. "ReadyForPost"/"ready_for_post" is NOT done - it means "still needs to
#      be posted to Business Central" (see ap_auto_post_service.py), and is
#      also reused for a BC post that FAILED and is silently waiting for
#      background retry. Treating it as terminal hid both the genuinely
#      waiting documents and the silently-failing ones from the queue
#      entirely. (The real per-document failure signal is now surfaced via
#      derived_state - see documents.py/derived_state_service.py - rather
#      than by guessing from the raw status string.)
#   2. "Exception" means a document was flagged and needs review - the
#      opposite of done. It was being hidden identically to "Completed".
#   3. "AutoFiled"/"auto_filed" as STATUS STRING values (as opposed to the
#      separate `auto_filed` BOOLEAN field, which is real) are never
#      actually set anywhere in the codebase - dead vocabulary, removed.
#   4. "po_pending" in DONE_WORKFLOW_STATUSES literally means "still
#      pending" - it was being classified as done. Removed.
TERMINAL_STATUSES = [
    "Completed", "Posted", "Archived", "completed", "posted", "archived",
    "FileMissing", "batch_parent", "Validated", "validated", "ValidationPassed",
    "LinkedToBC",
]

DONE_WORKFLOW_STATUSES = [
    "completed", "validation_passed", "processed", "ready_for_approval",
    "exported", "file_missing", "exception_review",
]

# A document with an active, unresolved failure must never be treated as
# terminal/done regardless of what its raw status string says - this is the
# structural fix for the "status=ReadyForPost secretly means BC posting
# failed" and "status=Completed secretly means SharePoint filing failed"
# confusion. Mirrors the fields checked by
# derived_state_service.DerivedStateService._apply_silent_failure_overrides.
def has_unresolved_failure(doc: dict) -> bool:
    bc_posting_status = (doc.get("bc_posting_status") or "").lower()
    if bc_posting_status in ("failed", "pending_retry"):
        return True
    if doc.get("auto_file_failed") and not doc.get("auto_filed"):
        return True
    return False

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
    not_terminal_or_failing = {"$or": [
        {"status": {"$nin": TERMINAL_STATUSES}},
        {"bc_posting_status": {"$in": ["failed", "pending_retry"]}},
        {"$and": [{"auto_file_failed": True}, {"auto_filed": {"$ne": True}}]},
    ]}
    not_done_wf_or_failing = {"$or": [
        {"workflow_status": {"$nin": DONE_WORKFLOW_STATUSES}},
        {"workflow_status": {"$exists": False}},
        {"bc_posting_status": {"$in": ["failed", "pending_retry"]}},
        {"$and": [{"auto_file_failed": True}, {"auto_filed": {"$ne": True}}]},
    ]}
    conditions = [
        {"is_duplicate": {"$ne": True}},
        not_terminal_or_failing,
        not_done_wf_or_failing,
    ]
    if not include_cleared:
        # See documents.py's inline copy of this same carve-out for why.
        conditions.append(
            {"$or": [
                {"auto_cleared": {"$ne": True}},
                {"auto_cleared": {"$exists": False}},
                {"bc_posting_status": {"$in": ["failed", "pending_retry"]}},
                {"$and": [{"auto_file_failed": True}, {"auto_filed": {"$ne": True}}]},
            ]}
        )
    return {"$and": conditions}
