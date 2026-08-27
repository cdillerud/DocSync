import pytest

from services import gpi_integration_service as gpi


@pytest.mark.asyncio
async def test_create_gpi_document_link_rejects_blank_system_id_before_network():
    with pytest.raises(ValueError, match="BC SystemId is required"):
        await gpi.create_gpi_document_link(
            bc_system_id="",
            bc_document_no="PO100",
            document_type="Purchase_Order",
            sharepoint_url="https://contoso.sharepoint.com/doc.pdf",
        )
