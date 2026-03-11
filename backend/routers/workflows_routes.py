"""
GPI Document Hub — Workflows Router (Thin Wrapper)

Extracts all /workflows/* routes from server.py during modular refactor.
Covers legacy workflow CRUD, AP invoice queues/mutations, and generic
workflow queues/mutations.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/workflows", tags=["Workflows"])

# ==================== LEGACY WORKFLOW CRUD ====================

# GET /workflows
router.add_api_route("", server.list_workflows, methods=["GET"])

# GET /workflows/{wf_id}
router.add_api_route("/{wf_id}", server.get_workflow, methods=["GET"])

# POST /workflows/{wf_id}/retry
router.add_api_route("/{wf_id}/retry", server.retry_workflow, methods=["POST"])

# ==================== AP INVOICE QUEUES ====================

# GET /workflows/ap_invoice/status-counts
router.add_api_route("/ap_invoice/status-counts", server.get_ap_workflow_status_counts, methods=["GET"])

# GET /workflows/ap_invoice/vendor-pending
router.add_api_route("/ap_invoice/vendor-pending", server.get_vendor_pending_queue, methods=["GET"])

# GET /workflows/ap_invoice/bc-validation-pending
router.add_api_route("/ap_invoice/bc-validation-pending", server.get_bc_validation_pending_queue, methods=["GET"])

# GET /workflows/ap_invoice/bc-validation-failed
router.add_api_route("/ap_invoice/bc-validation-failed", server.get_bc_validation_failed_queue, methods=["GET"])

# GET /workflows/ap_invoice/data-correction-pending
router.add_api_route("/ap_invoice/data-correction-pending", server.get_data_correction_pending_queue, methods=["GET"])

# GET /workflows/ap_invoice/ready-for-approval
router.add_api_route("/ap_invoice/ready-for-approval", server.get_ready_for_approval_queue, methods=["GET"])

# GET /workflows/ap_invoice/metrics
router.add_api_route("/ap_invoice/metrics", server.get_ap_workflow_metrics, methods=["GET"])

# ==================== AP INVOICE MUTATIONS ====================

# POST /workflows/ap_invoice/{doc_id}/set-vendor
router.add_api_route("/ap_invoice/{doc_id}/set-vendor", server.set_vendor_for_document, methods=["POST"])

# POST /workflows/ap_invoice/{doc_id}/update-fields
router.add_api_route("/ap_invoice/{doc_id}/update-fields", server.update_document_fields, methods=["POST"])

# POST /workflows/ap_invoice/{doc_id}/override-bc-validation
router.add_api_route("/ap_invoice/{doc_id}/override-bc-validation", server.override_bc_validation, methods=["POST"])

# POST /workflows/ap_invoice/{doc_id}/start-approval
router.add_api_route("/ap_invoice/{doc_id}/start-approval", server.start_approval, methods=["POST"])

# POST /workflows/ap_invoice/{doc_id}/approve
router.add_api_route("/ap_invoice/{doc_id}/approve", server.approve_document, methods=["POST"])

# POST /workflows/ap_invoice/{doc_id}/reject
router.add_api_route("/ap_invoice/{doc_id}/reject", server.reject_document, methods=["POST"])

# ==================== GENERIC WORKFLOW QUEUES ====================

# GET /workflows/generic/queue
router.add_api_route("/generic/queue", server.get_workflow_queue, methods=["GET"])

# GET /workflows/generic/status-counts-by-type
router.add_api_route("/generic/status-counts-by-type", server.get_status_counts_by_doc_type, methods=["GET"])

# GET /workflows/generic/metrics-by-type
router.add_api_route("/generic/metrics-by-type", server.get_workflow_metrics_by_doc_type, methods=["GET"])

# ==================== GENERIC WORKFLOW MUTATIONS ====================

# POST /workflows/{doc_id}/mark-ready-for-review
router.add_api_route("/{doc_id}/mark-ready-for-review", server.mark_ready_for_review, methods=["POST"])

# POST /workflows/{doc_id}/mark-reviewed
router.add_api_route("/{doc_id}/mark-reviewed", server.mark_reviewed, methods=["POST"])

# POST /workflows/{doc_id}/start-approval
router.add_api_route("/{doc_id}/start-approval", server.start_approval_generic, methods=["POST"])

# POST /workflows/{doc_id}/approve
router.add_api_route("/{doc_id}/approve", server.approve_generic, methods=["POST"])

# POST /workflows/{doc_id}/reject
router.add_api_route("/{doc_id}/reject", server.reject_generic, methods=["POST"])

# POST /workflows/{doc_id}/complete-triage
router.add_api_route("/{doc_id}/complete-triage", server.complete_triage, methods=["POST"])

# POST /workflows/{doc_id}/link-credit-to-invoice
router.add_api_route("/{doc_id}/link-credit-to-invoice", server.link_credit_to_invoice, methods=["POST"])

# POST /workflows/{doc_id}/tag-quality
router.add_api_route("/{doc_id}/tag-quality", server.tag_quality_doc, methods=["POST"])

# POST /workflows/{doc_id}/export
router.add_api_route("/{doc_id}/export", server.export_document, methods=["POST"])
