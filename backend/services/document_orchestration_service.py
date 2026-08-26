"""Retired legacy document upload/link orchestration.

The historical implementation in this module predated the Square9 parity
boundary. It performed a raw SharePoint upload, used Sales Order validation for
Purchase documents, and could default unknown document types to ``salesOrders``.
Those semantics are not safe for AP/Warehouse cutover.

The import symbol is intentionally retained so any stale caller fails loudly and
before a SharePoint or Business Central side effect. New delivery code must use
the authoritative routed SharePoint metadata boundary and the dedicated recovery
services.
"""


class LegacyDocumentOrchestrationRetired(RuntimeError):
    """Raised when stale code attempts to enter the retired delivery bypass."""


async def run_upload_and_link_workflow(
    doc_id: str,
    file_content: bytes,
    file_name: str,
    doc_type: str,
    bc_record_id: str = None,
    bc_document_no: str = None,
):
    """Fail closed before any upload, BC lookup, attachment, or database write."""
    raise LegacyDocumentOrchestrationRetired(
        "run_upload_and_link_workflow is retired for Square9 parity. "
        "Use upload_to_sharepoint_with_routing for initial delivery, "
        "document_retry_service for delivery recovery, or the dedicated AP "
        "posted/draft metadata recovery services for post-success repair."
    )


__all__ = [
    "LegacyDocumentOrchestrationRetired",
    "run_upload_and_link_workflow",
]
