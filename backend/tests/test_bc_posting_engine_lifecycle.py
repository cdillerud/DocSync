"""
Lane A A4 — Pre-claim workflow_engine.advance_workflow on the Phase 5 endpoint.

Contract:
  * routers/ap_review.py::post_document_to_bc drives the engine through
    ``ON_BC_POSTING_STARTED`` BEFORE acquiring the BC post claim.
  * The claim's atomic $set carries the engine state so both land in one
    Mongo write.
  * On BC success, the engine advances via ``ON_BC_POSTED`` and
    workflow_status becomes ``bc_posted`` (via the claim release's extra_set).
  * On partial post, engine advances via ``ON_BC_PARTIAL_POSTED`` →
    workflow_status=``bc_post_partial``.
  * On hard failure, engine advances via ``ON_BC_POST_FAILED`` →
    workflow_status falls back to ``approved`` (retry-eligible).
  * If the engine refuses the transition, the endpoint returns 409 BEFORE
    calling BC — preventing orphan writes.

These tests exercise the WorkflowEngine transition table directly — the full
end-to-end (HTTP → engine → BC → release_claim) is covered by the existing
AP_Review / partial-post integration tests and by testing_agent_v3_fork.
"""

import pytest


# ---------------------------------------------------------------------------
# Engine transition table — the new BC posting lifecycle states/events
# ---------------------------------------------------------------------------


def test_new_events_exist():
    from workflows.core.engine import WorkflowEvent
    assert WorkflowEvent.ON_BC_POSTING_STARTED.value == "on_bc_posting_started"
    assert WorkflowEvent.ON_BC_POSTED.value == "on_bc_posted"
    assert WorkflowEvent.ON_BC_PARTIAL_POSTED.value == "on_bc_partial_posted"
    assert WorkflowEvent.ON_BC_POST_FAILED.value == "on_bc_post_failed"


def test_new_states_exist():
    from workflows.core.engine import WorkflowStatus
    assert WorkflowStatus.BC_POSTING_IN_PROGRESS.value == "bc_posting_in_progress"
    assert WorkflowStatus.BC_POSTED.value == "bc_posted"
    assert WorkflowStatus.BC_POST_PARTIAL.value == "bc_post_partial"


@pytest.mark.parametrize("start_state", ["approved", "ready_for_approval"])
def test_ap_invoice_on_bc_posting_started_from_valid_states(start_state):
    """APPROVED and READY_FOR_APPROVAL both advance into
    BC_POSTING_IN_PROGRESS on ON_BC_POSTING_STARTED — per the pilot flow
    where reviewers post directly from the review panel."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t1", "doc_type": "AP_INVOICE",
           "workflow_status": start_state}
    result, history, ok = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={"source": "test"}, actor="user:test",
    )
    assert ok is True
    assert result["workflow_status"] == "bc_posting_in_progress"
    assert history.event == "on_bc_posting_started"


def test_ap_invoice_on_bc_posting_started_from_invalid_state_is_rejected():
    """Engine refuses ON_BC_POSTING_STARTED from CAPTURED — that's the
    guarantee the endpoint relies on to 409 before calling BC."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t2", "doc_type": "AP_INVOICE", "workflow_status": "captured"}
    result, history, ok = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:test",
    )
    assert ok is False, "captured → bc_posting_in_progress must be rejected"
    assert result["workflow_status"] == "captured"
    # A rejected transition DOES return a history entry whose reason begins
    # with "Transition blocked:"; it just does not apply to the document.
    assert history is not None
    assert history.reason.startswith("Transition blocked:")


def test_ap_invoice_posting_lifecycle_happy_path():
    """APPROVED → BC_POSTING_IN_PROGRESS → BC_POSTED → ARCHIVED."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t3", "doc_type": "AP_INVOICE", "workflow_status": "approved"}

    doc, _, ok1 = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:test",
    )
    assert ok1 and doc["workflow_status"] == "bc_posting_in_progress"

    doc, _, ok2 = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTED.value,
        context={"bc_record_no": "PI-1"}, actor="user:test",
    )
    assert ok2 and doc["workflow_status"] == "bc_posted"

    doc, _, ok3 = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_ARCHIVED.value,
        context={}, actor="user:test",
    )
    assert ok3 and doc["workflow_status"] == "archived"


def test_ap_invoice_posting_lifecycle_partial_path():
    """IN_PROGRESS + partial → bc_post_partial (exception state, not posted)."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t4", "doc_type": "AP_INVOICE", "workflow_status": "approved"}
    doc, _, _ = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:test",
    )
    doc, _, ok = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_PARTIAL_POSTED.value,
        context={"linesAdded": 0, "linesTotal": 2}, actor="user:test",
    )
    assert ok and doc["workflow_status"] == "bc_post_partial"

    doc, _, ok2 = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_RETRY.value,
        context={}, actor="user:test",
    )
    assert ok2 and doc["workflow_status"] == "approved"


def test_ap_invoice_posting_lifecycle_hard_failure_rolls_back_to_approved():
    """Hard failure from IN_PROGRESS returns the doc to APPROVED — retry-eligible
    without the reviewer having to re-approve."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t5", "doc_type": "AP_INVOICE", "workflow_status": "approved"}
    doc, _, _ = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:test",
    )
    assert doc["workflow_status"] == "bc_posting_in_progress"

    doc, _, ok = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POST_FAILED.value,
        context={"error": "BC 500"}, actor="user:test",
    )
    assert ok and doc["workflow_status"] == "approved"


def test_in_progress_cannot_jump_directly_back_to_ready_for_approval():
    """From IN_PROGRESS, no direct transition back to READY_FOR_APPROVAL exists;
    the only backwards path is via ON_BC_POST_FAILED → APPROVED or
    ON_BC_PARTIAL_POSTED → BC_POST_PARTIAL."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t6", "doc_type": "AP_INVOICE", "workflow_status": "approved"}
    doc, _, _ = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:test",
    )

    doc, _, ok = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={}, actor="user:test",
    )
    assert ok is False, (
        "IN_PROGRESS must not accept ON_APPROVAL_STARTED — that would "
        "abandon an in-flight BC post with no claim release."
    )
    assert doc["workflow_status"] == "bc_posting_in_progress"


def test_workflow_history_records_bc_post_events():
    """Every BC-post transition leaves a history entry with event id + actor."""
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    doc = {"id": "t7", "doc_type": "AP_INVOICE", "workflow_status": "approved"}
    doc, h1, _ = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={}, actor="user:reviewer@gamer",
    )
    doc, h2, _ = WorkflowEngine.advance_workflow(
        doc, event=WorkflowEvent.ON_BC_POSTED.value,
        context={"metadata": {"bc_record_no": "PI-42"}},
        actor="user:reviewer@gamer",
    )
    history = doc.get("workflow_history") or []
    events = [h["event"] for h in history]
    assert "on_bc_posting_started" in events
    assert "on_bc_posted" in events
    assert h2.actor == "user:reviewer@gamer"
    assert h2.metadata.get("bc_record_no") == "PI-42"
