"""
GPI Document Hub — Documents Router (Thin Wrapper)

Extracts all /documents/* routes from server.py during modular refactor.
Covers CRUD, metadata, processing, and BC reference resolution routes
that live under the /documents path prefix.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/documents", tags=["Documents"])

# ==================== CRUD & METADATA ====================

# POST /documents/upload
router.add_api_route("/upload", server.upload_document, methods=["POST"])

# GET /documents
router.add_api_route("", server.list_documents, methods=["GET"])

# GET /documents/{doc_id}
router.add_api_route("/{doc_id}", server.get_document, methods=["GET"])

# GET /documents/{doc_id}/events
router.add_api_route("/{doc_id}/events", server.get_document_events, methods=["GET"])

# GET /documents/{doc_id}/timeline
router.add_api_route("/{doc_id}/timeline", server.get_document_timeline, methods=["GET"])

# GET /documents/{doc_id}/derived-state
router.add_api_route("/{doc_id}/derived-state", server.get_document_derived_state, methods=["GET"])

# POST /documents/{doc_id}/refresh-state
router.add_api_route("/{doc_id}/refresh-state", server.refresh_document_state, methods=["POST"])

# GET /documents/{doc_id}/matching-debug
router.add_api_route("/{doc_id}/matching-debug", server.get_matching_debug, methods=["GET"])

# POST /documents/{doc_id}/matching-debug/rerun
router.add_api_route("/{doc_id}/matching-debug/rerun", server.rerun_matching_with_diagnostics, methods=["POST"])

# PUT /documents/{doc_id}
router.add_api_route("/{doc_id}", server.update_document, methods=["PUT"])

# DELETE /documents/{doc_id}
router.add_api_route("/{doc_id}", server.delete_document, methods=["DELETE"])

# GET /documents/{doc_id}/file
router.add_api_route("/{doc_id}/file", server.get_document_file, methods=["GET"])

# GET /documents/{doc_id}/square9-status
router.add_api_route("/{doc_id}/square9-status", server.get_square9_status, methods=["GET"])

# POST /documents/{doc_id}/retry
router.add_api_route("/{doc_id}/retry", server.retry_document, methods=["POST"])

# POST /documents/{doc_id}/reset-retries
router.add_api_route("/{doc_id}/reset-retries", server.reset_document_retries, methods=["POST"])

# POST /documents/{doc_id}/resubmit
router.add_api_route("/{doc_id}/resubmit", server.resubmit_document, methods=["POST"])

# POST /documents/{doc_id}/link
router.add_api_route("/{doc_id}/link", server.link_document, methods=["POST"])

# ==================== BC REFERENCE RESOLUTION ====================

# POST /documents/{doc_id}/resolve-reference
router.add_api_route("/{doc_id}/resolve-reference", server.resolve_document_reference, methods=["POST"])

# POST /documents/{doc_id}/resolve-intelligence
router.add_api_route("/{doc_id}/resolve-intelligence", server.resolve_document_intelligence, methods=["POST"])

# GET /documents/{doc_id}/reference-intelligence
router.add_api_route("/{doc_id}/reference-intelligence", server.get_document_reference_intelligence, methods=["GET"])

# POST /documents/{doc_id}/auto-resolve
router.add_api_route("/{doc_id}/auto-resolve", server.trigger_auto_resolve, methods=["POST"])

# ==================== DOCUMENT PROCESSING ====================

# POST /documents/intake
router.add_api_route("/intake", server.intake_document, methods=["POST"])

# POST /documents/{doc_id}/classify
router.add_api_route("/{doc_id}/classify", server.classify_document, methods=["POST"])

# POST /documents/{doc_id}/resolve
router.add_api_route("/{doc_id}/resolve", server.resolve_and_link_document, methods=["POST"])

# POST /documents/{doc_id}/reprocess
router.add_api_route("/{doc_id}/reprocess", server.reprocess_document, methods=["POST"])

# POST /documents/batch-revalidate
router.add_api_route("/batch-revalidate", server.batch_revalidate_documents, methods=["POST"])

# POST /documents/{doc_id}/preview-post
router.add_api_route("/{doc_id}/preview-post", server.preview_post_to_bc, methods=["POST"])
