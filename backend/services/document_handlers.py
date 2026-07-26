"""
GPI Document Hub route-handler compatibility facade.

Every route-facing handler is re-exported directly from its authoritative
service module.
"""

from services.document_reprocess_service import reprocess_document
from services.document_batch_revalidate_service import (
    batch_revalidate_documents,
)
from services.document_preview_service import (
    DryRunPreviewRequest,
    preview_post_to_bc,
)
from services.document_classification_service import classify_document
from services.document_resolution_service import (
    ResolveRequest,
    resolve_and_link_document,
)
from services.document_link_service import link_document
from services.document_resubmit_service import resubmit_document
from services.document_retry_service import retry_document
from services.document_upload_service import upload_document
from services.document_intake_service import intake_document
from services.document_bytes_intake_service import (
    intake_document_from_bytes,
)
