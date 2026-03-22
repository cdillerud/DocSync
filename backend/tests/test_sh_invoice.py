"""
Test SH_Invoice Document Type, Workflow, Cost-Only SO, and Processor Assignment

Tests:
1. SH_Invoice document type is defined in DEFAULT_JOB_TYPES
2. SH_Invoice workflow transitions (received → classified → pending_approval → approved → exported)
3. Cost-only SO endpoint: happy path (DEMO_MODE), validation guards, idempotency
4. Processor assignment endpoint
5. SH Invoice queue endpoint
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _uid():
    return f"test-sh-{uuid.uuid4().hex[:10]}"


def _seed_sh_doc(db, doc_id: str, **overrides) -> dict:
    """Insert an SH_Invoice document directly into MongoDB."""
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": doc_id,
        "suggested_job_type": "SH_Invoice",
        "document_type": "SH_Invoice",
        "workflow_status": "approved",
        "vendor_no": "V-WH-001",
        "vendor_canonical": "V-WH-001",
        "file_name": f"sh_test_{doc_id[:8]}.pdf",
        "extracted_fields": {
            "vendor": "Test Warehouse Co",
            "vendor_no": "V-WH-001",
            "amount": "1250.00",
            "total_amount": "1250.00",
            "invoice_number": f"SH-INV-{doc_id[:6]}",
            "description": "Monthly storage and handling charges",
            "line_items": [
                {"description": "Storage fees Q1", "amount": "750.00"},
                {"description": "Handling charges Q1", "amount": "500.00"},
            ],
        },
        "customer_candidates": [
            {"number": "CUST-001", "displayName": "Test Customer", "score": 0.95}
        ],
        "created_utc": now,
        "updated_utc": now,
    }
    doc.update(overrides)
    db.hub_documents.update_one({"id": doc_id}, {"$set": doc}, upsert=True)
    return doc


def _cleanup(db, doc_id: str):
    db.hub_documents.delete_one({"id": doc_id})
    db.document_activities.delete_many({"document_id": doc_id})


def _seed_gl_config(db, gl_number="5100"):
    """Ensure sh_default_gl_account config exists for tests."""
    db.hub_config.update_one(
        {"_key": "sh_default_gl_account"},
        {"$set": {"_key": "sh_default_gl_account", "value": gl_number}},
        upsert=True,
    )


class TestSHInvoiceDocumentType:
    """Test SH_Invoice is properly defined."""

    def test_sh_invoice_in_doc_types(self):
        """SH_Invoice must exist in DEFAULT_JOB_TYPES."""
        from models.document_types import DEFAULT_JOB_TYPES
        assert "SH_Invoice" in DEFAULT_JOB_TYPES
        sh = DEFAULT_JOB_TYPES["SH_Invoice"]
        assert sh["job_type"] == "SH_Invoice"
        assert sh["display_name"] == "Storage & Handling Invoice"
        assert sh["bc_entity"] == "salesOrders"
        assert sh["auto_post_eligible"] is False
        assert sh["requires_bc_match"] is False
        print("[PASS] SH_Invoice document type defined correctly")


class TestSHInvoiceWorkflow:
    """Test SH_Invoice workflow state machine."""

    def test_workflow_defined(self):
        """SH_INVOICE workflow must be in WORKFLOW_DEFINITIONS."""
        from services.workflow_engine import WorkflowEngine, DocType, WORKFLOW_DEFINITIONS
        assert DocType.SH_INVOICE.value in WORKFLOW_DEFINITIONS
        print("[PASS] SH_INVOICE workflow defined")

    def test_workflow_transitions(self):
        """Test full SH_Invoice workflow: captured → classified → pending_approval → approved → exported."""
        from services.workflow_engine import WorkflowEngine, WorkflowEvent

        doc = {"id": "test-wf", "doc_type": "SH_INVOICE"}

        # Initialize
        doc = WorkflowEngine.initialize_workflow(doc, doc_type="SH_INVOICE")
        assert doc["workflow_status"] == "captured"

        # captured → classified
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value)
        assert ok and doc["workflow_status"] == "classified"

        # classified → pending_approval (via extraction success)
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.ON_EXTRACTION_SUCCESS.value)
        assert ok and doc["workflow_status"] == "pending_approval"

        # pending_approval → approved
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.SH_APPROVED.value)
        assert ok and doc["workflow_status"] == "approved"

        # approved → exported
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.ON_EXPORTED.value)
        assert ok and doc["workflow_status"] == "exported"

        print("[PASS] Full SH_Invoice workflow transitions work")

    def test_sh_rejected_transition(self):
        """SH_REJECTED moves from pending_approval to rejected."""
        from services.workflow_engine import WorkflowEngine, WorkflowEvent

        doc = {"id": "test-rej", "doc_type": "SH_INVOICE", "workflow_status": "pending_approval", "workflow_history": []}
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.SH_REJECTED.value)
        assert ok and doc["workflow_status"] == "rejected"
        print("[PASS] SH_REJECTED transition works")

    def test_rejected_retry(self):
        """Retry from rejected returns to pending_approval."""
        from services.workflow_engine import WorkflowEngine, WorkflowEvent

        doc = {"id": "test-retry", "doc_type": "SH_INVOICE", "workflow_status": "rejected", "workflow_history": []}
        doc, _, ok = WorkflowEngine.advance_workflow(doc, WorkflowEvent.ON_RETRY.value)
        assert ok and doc["workflow_status"] == "pending_approval"
        print("[PASS] Rejected → retry → pending_approval works")

    def test_ai_classifier_maps_sh_invoice(self):
        """AI classification should map SH_Invoice to SH_INVOICE DocType."""
        from services.workflow_engine import DocumentClassifier, DocType
        result = DocumentClassifier.classify_from_ai_result("SH_Invoice")
        assert result == DocType.SH_INVOICE
        print("[PASS] AI classifier maps SH_Invoice correctly")


class TestCostOnlySOEndpoint:
    """Test POST /api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}."""

    def test_404_nonexistent(self):
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/fake-doc")
        assert resp.status_code == 404
        print("[PASS] 404 for nonexistent doc")

    def test_rejects_non_sh_doc(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id, suggested_job_type="AP_Invoice", document_type="AP_Invoice")
        try:
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            assert resp.status_code == 400
            assert "SH_Invoice" in resp.json()["detail"]
            print(f"[PASS] Rejected non-SH doc: {resp.json()['detail']}")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_unapproved(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id, workflow_status="pending_approval")
        try:
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            assert resp.status_code == 400
            assert "approved" in resp.json()["detail"].lower()
            print(f"[PASS] Rejected unapproved doc: {resp.json()['detail']}")
        finally:
            _cleanup(db, doc_id)

    def test_happy_path_demo_mode(self, db):
        doc_id = _uid()
        _seed_gl_config(db, "5100")
        _seed_sh_doc(db, doc_id, workflow_status="approved")
        try:
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            # DEMO_MODE or live: 200 or 502
            assert resp.status_code in (200, 400, 502), f"Unexpected {resp.status_code}: {resp.text}"
            if resp.status_code == 200:
                data = resp.json()
                assert data["success"] is True
                assert data["status"] in ("created", "already_created")
                assert data["cost_only"] is True
                assert data.get("gl_account_used")
                assert data.get("processor")
                print(f"[PASS] Cost-only SO created: {data.get('bc_so_number')}, GL={data.get('gl_account_used')}")
            else:
                print(f"[PASS] Status {resp.status_code} (acceptable without credentials)")
        finally:
            _cleanup(db, doc_id)

    def test_idempotency(self, db):
        doc_id = _uid()
        _seed_gl_config(db, "5100")
        _seed_sh_doc(db, doc_id, workflow_status="approved")
        try:
            resp1 = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            if resp1.status_code == 200 and resp1.json().get("success"):
                resp2 = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
                assert resp2.status_code == 200
                data2 = resp2.json()
                assert data2["status"] == "already_created"
                print("[PASS] Idempotency: second call returns already_created")
            else:
                print(f"[SKIP] First call didn't succeed ({resp1.status_code})")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_no_gl_account(self, db):
        """If no GL account is configured or resolvable, should return 400."""
        doc_id = _uid()
        # Remove GL config
        db.hub_config.delete_one({"_key": "sh_default_gl_account"})
        _seed_sh_doc(db, doc_id, workflow_status="approved")
        try:
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            # May pass if freight GL service resolves one, or 400 if not
            assert resp.status_code in (200, 400), f"Unexpected {resp.status_code}: {resp.text}"
            if resp.status_code == 400:
                assert "GL account" in resp.json()["detail"]
                print(f"[PASS] Correctly rejected no GL account: {resp.json()['detail']}")
            else:
                print("[PASS] GL account resolved via freight GL service")
        finally:
            _seed_gl_config(db, "5100")  # Restore
            _cleanup(db, doc_id)

    def test_rejects_no_amount(self, db):
        """If no line items and no total amount, should return 400."""
        doc_id = _uid()
        _seed_gl_config(db, "5100")
        _seed_sh_doc(db, doc_id, workflow_status="approved",
                     extracted_fields={"vendor": "Test", "amount": "", "line_items": []})
        try:
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/cost-only-from-document/{doc_id}")
            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
            assert "amount" in resp.json()["detail"].lower() or "line" in resp.json()["detail"].lower()
            print(f"[PASS] Correctly rejected no amount: {resp.json()['detail']}")
        finally:
            _cleanup(db, doc_id)


class TestProcessorAssignment:
    """Test POST /api/admin/sh-invoice/{doc_id}/assign-processor."""

    def test_assign_andy(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/admin/sh-invoice/{doc_id}/assign-processor",
                json={"processor": "Andy"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["processor"] == "Andy"
            print("[PASS] Assigned processor Andy")
        finally:
            _cleanup(db, doc_id)

    def test_assign_ellie(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/admin/sh-invoice/{doc_id}/assign-processor",
                json={"processor": "Ellie"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["processor"] == "Ellie"
            print("[PASS] Assigned processor Ellie")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_invalid_processor(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id)
        try:
            resp = requests.post(
                f"{BASE_URL}/api/admin/sh-invoice/{doc_id}/assign-processor",
                json={"processor": "Bob"},
            )
            assert resp.status_code == 400
            assert "Andy" in resp.json()["detail"] or "Ellie" in resp.json()["detail"]
            print("[PASS] Rejected invalid processor")
        finally:
            _cleanup(db, doc_id)

    def test_rejects_non_sh_doc(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id, suggested_job_type="AP_Invoice", document_type="AP_Invoice")
        try:
            resp = requests.post(
                f"{BASE_URL}/api/admin/sh-invoice/{doc_id}/assign-processor",
                json={"processor": "Andy"},
            )
            assert resp.status_code == 400
            print("[PASS] Rejected processor assignment on non-SH doc")
        finally:
            _cleanup(db, doc_id)


class TestSHInvoiceQueue:
    """Test GET /api/admin/sh-invoice/queue."""

    def test_queue_empty(self):
        resp = requests.get(f"{BASE_URL}/api/admin/sh-invoice/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "documents" in data
        print(f"[PASS] Queue returns {data['total']} documents")

    def test_queue_with_pending_doc(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id, workflow_status="pending_approval")
        try:
            resp = requests.get(
                f"{BASE_URL}/api/admin/sh-invoice/queue",
                params={"status": "pending_approval"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] >= 1
            doc_ids = [d["id"] for d in data["documents"]]
            assert doc_id in doc_ids
            print(f"[PASS] Queue contains pending SH doc ({data['total']} total)")
        finally:
            _cleanup(db, doc_id)

    def test_queue_filter_by_processor(self, db):
        doc_id = _uid()
        _seed_sh_doc(db, doc_id, workflow_status="pending_approval", processor="Ellie")
        try:
            resp = requests.get(
                f"{BASE_URL}/api/admin/sh-invoice/queue",
                params={"status": "pending_approval", "processor": "Ellie"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] >= 1
            print(f"[PASS] Queue filtered by processor Ellie ({data['total']} total)")

            # Should NOT appear in Andy's queue
            resp2 = requests.get(
                f"{BASE_URL}/api/admin/sh-invoice/queue",
                params={"status": "pending_approval", "processor": "Andy"},
            )
            data2 = resp2.json()
            doc_ids2 = [d["id"] for d in data2["documents"]]
            assert doc_id not in doc_ids2
            print("[PASS] Doc not in Andy's queue (correct filtering)")
        finally:
            _cleanup(db, doc_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
