"""
Partial-post handling: both BC post entry points must refuse to mark a
document 'posted' when BC accepts the invoice header but rejects any
line.

Entry points under test:
  1. Manual post: services/business_central_service.create_purchase_invoice
     (called from routers/ap_review.py::post_document_to_bc)
  2. Auto-post:   routers/gpi_integration.create_purchase_invoice_from_document
     (called from services/ap_auto_post_service.attempt_ap_auto_post)

Both must return success=False with error="partial_post" and emit a
best-effort orphan-header delete, per AP_PATH_CONSOLIDATION Work Item B
(2026-04-22).

These tests mock BC HTTP responses so they never touch a real tenant.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# Entry point 1: services/business_central_service.create_purchase_invoice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bc_service_header_accepted_lines_rejected_returns_partial_post():
    """Header POST 201 but line POST 400 must flip success=False."""
    from services.business_central_service import BusinessCentralService

    svc = BusinessCentralService()
    svc.use_mock = False

    # Stub the header + orphan-delete HTTP plumbing so we only exercise the
    # partial-post logic itself.
    fake_header_resp = MagicMock(status_code=201)
    fake_header_resp.json.return_value = {"id": "inv-guid-123", "number": "PI-TEST-001"}
    fake_delete_resp = MagicMock(status_code=204, text="")

    async def _post(url, headers=None, json=None):
        return fake_header_resp

    async def _delete(url, headers=None):
        return fake_delete_resp

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        post = staticmethod(_post)
        delete = staticmethod(_delete)

    with patch("services.business_central_service.get_bc_token", AsyncMock(return_value="tkn")), \
         patch.object(svc, "_get_company_id", AsyncMock(return_value="co-guid")), \
         patch("services.business_central_service._check_write_protection", lambda *_a, **_k: None), \
         patch("services.business_central_service.httpx.AsyncClient", FakeClient), \
         patch.object(svc, "_add_invoice_lines",
                      AsyncMock(return_value={
                          "added": 0, "total": 2,
                          "errors": [{"line": 1, "status": 400, "error": "Item not found"}]
                      })):
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V-TEST",
            "invoiceNumber": "INV-1",
            "invoiceDate": "2026-04-22",
            "lines": [{"itemCode": "X", "quantity": 1}, {"itemCode": "Y", "quantity": 1}],
        })

    assert result["success"] is False, (
        f"Header-accepted + lines-rejected must NOT report success, got {result}"
    )
    assert result["error"] == "partial_post"
    assert result["linesAdded"] == 0
    assert result["linesTotal"] == 2
    assert result["bcDocumentId"] == "inv-guid-123"
    assert result["orphan_header_deletion"] in ("deleted", "failed")


@pytest.mark.asyncio
async def test_bc_service_all_lines_accepted_returns_success():
    """Guardrail: when all lines land, success MUST stay True."""
    from services.business_central_service import BusinessCentralService

    svc = BusinessCentralService()
    svc.use_mock = False

    fake_header_resp = MagicMock(status_code=201)
    fake_header_resp.json.return_value = {"id": "inv-guid-ok", "number": "PI-OK-001"}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return fake_header_resp

    with patch("services.business_central_service.get_bc_token", AsyncMock(return_value="tkn")), \
         patch.object(svc, "_get_company_id", AsyncMock(return_value="co-guid")), \
         patch("services.business_central_service._check_write_protection", lambda *_a, **_k: None), \
         patch("services.business_central_service.httpx.AsyncClient", FakeClient), \
         patch.object(svc, "_add_invoice_lines",
                      AsyncMock(return_value={"added": 2, "total": 2, "errors": []})):
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V-TEST",
            "invoiceNumber": "INV-2",
            "invoiceDate": "2026-04-22",
            "lines": [{"itemCode": "X", "quantity": 1}, {"itemCode": "Y", "quantity": 1}],
        })

    assert result["success"] is True, (
        f"All-lines-accepted must report success, got {result}"
    )
    assert result["linesAdded"] == 2
    assert result["linesTotal"] == 2


# ---------------------------------------------------------------------------
# Entry point 2: auto-post path
# routers/gpi_integration.create_purchase_invoice_from_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_post_path_detects_partial_post_and_flips_success_false():
    """The auto-post path must mirror the bc_service partial-post contract.

    Before this fix, add_purchase_invoice_lines' failure was stored in
    bc_purchase_invoice.lines_added/lines_total but the overall result's
    `success` stayed True (header succeeded), and attempt_ap_auto_post
    then marked the document 'posted' — a silent financial-integrity leak.

    This test mocks the header create + line add to simulate partial
    failure and asserts the final result carries success=False with
    error='partial_post', so ap_auto_post_service can no longer mark the
    document posted.
    """
    import os
    # Ensure we pass the HAS_CREDENTIALS gate at import time.
    os.environ.setdefault("BC_TENANT_ID", "tenant-test")
    os.environ.setdefault("BC_CLIENT_ID", "client-test")
    os.environ.setdefault("BC_CLIENT_SECRET", "secret-test")

    from routers import gpi_integration

    fake_db = MagicMock()
    fake_db.hub_documents.find_one = AsyncMock(return_value={
        "id": "doc-pp-1",
        "document_type": "AP_Invoice",
        "extracted_fields": {"invoice_number": "INV-PP-1", "invoice_date": "2026-04-22"},
        "normalized_fields": {},
    })
    fake_db.hub_documents.update_one = AsyncMock()

    with patch.object(gpi_integration, "HAS_CREDENTIALS", True), \
         patch.object(gpi_integration, "get_db", return_value=fake_db), \
         patch.object(gpi_integration, "_resolve_vendor_no",
                      AsyncMock(return_value={"vendor_no": "V-PP", "vendor_name": "Vendor PP"})), \
         patch.object(gpi_integration, "create_purchase_invoice",
                      AsyncMock(return_value={
                          "success": True,
                          "bc_record_no": "PI-PP-001",
                          "bc_system_id": "pi-guid-pp",
                          "status": "Draft",
                      })), \
         patch.object(gpi_integration, "_build_pi_lines_with_mapping",
                      AsyncMock(return_value=[
                          {"lineType": "Item", "lineObjectNumber": "X",
                           "description": "x", "quantity": 1, "unitCost": 10},
                          {"lineType": "Item", "lineObjectNumber": "Y",
                           "description": "y", "quantity": 1, "unitCost": 20},
                      ])), \
         patch.object(gpi_integration, "add_purchase_invoice_lines",
                      AsyncMock(return_value={
                          "added": 0, "total": 2,
                          "errors": [{"line": 1, "status": 400, "error": "Item X not found"}],
                      })), \
         patch("services.business_central_service.get_bc_service") as _mock_bc_service, \
         patch("services.business_central_service.get_bc_token", AsyncMock(return_value="tkn")), \
         patch.object(gpi_integration, "create_gpi_document_link",
                      AsyncMock(return_value={"success": True})):
        mock_svc = MagicMock()
        mock_svc._get_company_id = AsyncMock(return_value="co-guid")
        mock_svc._try_delete_draft_invoice = AsyncMock(return_value="deleted")
        _mock_bc_service.return_value = mock_svc

        response = await gpi_integration.create_purchase_invoice_from_document(
            doc_id="doc-pp-1",
        )

    # Financial-integrity assertion: the auto-post path MUST now report failure.
    assert response["success"] is False, (
        f"Auto-post path must flip success=False on partial post, got {response}"
    )

    # Hub doc write-back must record the partial-post truth.
    update_call = fake_db.hub_documents.update_one.call_args_list[-1]
    bc_pi = update_call.kwargs.get("filter") if False else update_call[0][1]["$set"]["bc_purchase_invoice"]
    assert bc_pi["success"] is False
    assert bc_pi["lines_added"] == 0
    assert bc_pi["lines_total"] == 2
    assert bc_pi["error_message"].startswith("partial_post:")


@pytest.mark.asyncio
async def test_ap_auto_post_service_does_not_mark_posted_on_partial_post():
    """True end-to-end: attempt_ap_auto_post sees the flipped success=False
    and MUST NOT write bc_posting_status='posted' or workflow_status='posted'.

    This is the full financial-integrity loop: we mock the underlying BC
    partial post, call the top-level auto-post orchestrator, and assert
    the hub document ends up marked as failed / pending_retry — never as
    posted. Without Work Item B's fix, the document would have been
    written with bc_posting_status='posted' and a BC record number that
    no longer exists in BC (the orphan draft).
    """
    from services import ap_auto_post_service

    # ── Fake doc + DB ────────────────────────────────────────────────────
    doc_before = {
        "id": "doc-e2e-pp",
        "document_type": "AP_Invoice",
        "status": "ReadyForPost",
        "review_status": "ready_for_post",
        "workflow_status": "ready_for_approval",
        "bc_vendor_number": "V-PP",
        "vendor_canonical": "V-PP",
        "invoice_number_clean": "INV-PP-E2E",
        "amount_float": 100.0,
        "extracted_fields": {
            "invoice_number": "INV-PP-E2E",
            "amount": "100.00",
            "invoice_date": "2026-04-22",
        },
        "normalized_fields": {},
    }
    # State captured after each update_one call so we can assert final state.
    update_history: list = []

    async def _update_one(flt, update):
        update_history.append(update)
        return MagicMock(modified_count=1)

    fake_db = MagicMock()
    fake_db.hub_documents.find_one = AsyncMock(return_value=doc_before)
    fake_db.hub_documents.update_one = AsyncMock(side_effect=_update_one)
    # Anything else the service might poke — make a benign async mock.
    fake_db.hub_documents.find_one_and_update = AsyncMock(return_value=doc_before)
    fake_db.events.insert_one = AsyncMock()
    fake_db.automation_decisions.insert_one = AsyncMock()

    # The partial-post result the upstream `create_purchase_invoice_from_document`
    # now produces after Work Item B. This is the stable contract downstream
    # code is expected to honor.
    partial_post_result = {
        "success": False,
        "error": "partial_post",
        "error_message": "partial_post: BC header created (...) but 0/2 lines accepted.",
        "partial_post": True,
        "bc_record_no": "PI-PP-E2E",
        "bc_system_id": "pi-guid-pp-e2e",
        "status": "Draft",
        "orphan_header_deletion": "deleted",
        "linesAdded": 0,
        "linesTotal": 2,
    }

    with patch.object(ap_auto_post_service, "create_purchase_invoice_from_document",
                      AsyncMock(return_value=partial_post_result), create=True), \
         patch("routers.gpi_integration.create_purchase_invoice_from_document",
               AsyncMock(return_value=partial_post_result)), \
         patch.object(ap_auto_post_service, "_write_event", AsyncMock()), \
         patch.object(ap_auto_post_service, "_record_success_feedback", AsyncMock()), \
         patch.object(ap_auto_post_service, "_check_bc_write_enabled",
                      return_value=(True, None), create=True):

        # Find the real auto-post entry point signature; call it on the fake
        # doc + DB. The function accepts (doc_id, db, source) per existing
        # callsites in routers/ap_review.py.
        result = await ap_auto_post_service.attempt_ap_auto_post(
            "doc-e2e-pp", fake_db, source="test_partial_post_e2e",
        )

    # Collect every field ever written to the doc by the auto-post path.
    writes: dict = {}
    for upd in update_history:
        for k, v in (upd.get("$set") or {}).items():
            writes[k] = v

    # ── Financial-integrity assertions ───────────────────────────────────
    # The document must NEVER be marked as posted.
    assert writes.get("bc_posting_status") != "posted", (
        f"Partial-post result must NOT flip bc_posting_status=posted; "
        f"final writes were: {writes}"
    )
    assert writes.get("workflow_status") != "posted", (
        f"Partial-post result must NOT flip workflow_status=posted; "
        f"final writes were: {writes}"
    )
    assert writes.get("status") != "Posted", (
        f"Partial-post result must NOT flip status=Posted; "
        f"final writes were: {writes}"
    )
    # The auto-post orchestrator must surface the failure to its caller.
    assert result.get("posted") is not True, (
        f"attempt_ap_auto_post must NOT return posted=True on partial post, "
        f"got {result}"
    )

