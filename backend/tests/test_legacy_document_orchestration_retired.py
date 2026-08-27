import pytest

from services.document_orchestration_service import (
    LegacyDocumentOrchestrationRetired,
    run_upload_and_link_workflow,
)


@pytest.mark.asyncio
async def test_legacy_orchestration_fails_closed_before_delivery():
    with pytest.raises(LegacyDocumentOrchestrationRetired, match="retired for Square9 parity"):
        await run_upload_and_link_workflow(
            doc_id="doc-1",
            file_content=b"pdf",
            file_name="invoice.pdf",
            doc_type="PurchaseInvoice",
            bc_record_id="11111111-1111-1111-1111-111111111111",
            bc_document_no="PI-1001",
        )
