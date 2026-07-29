# Tests for non-blocking document-learning integration hooks.

from __future__ import annotations

import ast
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.asyncio
async def test_helper_delegates_to_learning_engine(monkeypatch):
    from services import per_document_learning_service
    from services.document_learning_hooks import record_document_learning

    calls = []

    async def fake_learn(db, doc_id, trigger="ingestion"):
        calls.append((db, doc_id, trigger))
        return {"learned": True, "trigger": trigger}

    monkeypatch.setattr(
        per_document_learning_service,
        "learn_from_document",
        fake_learn,
    )

    db = object()
    result = await record_document_learning(
        db,
        "doc-123",
        "classification",
    )

    assert calls == [(db, "doc-123", "classification")]
    assert result == {
        "learned": True,
        "trigger": "classification",
    }


@pytest.mark.asyncio
async def test_helper_does_not_break_primary_workflow(monkeypatch):
    from services import per_document_learning_service
    from services.document_learning_hooks import record_document_learning

    async def failing_learn(db, doc_id, trigger="ingestion"):
        raise RuntimeError("learning failure")

    monkeypatch.setattr(
        per_document_learning_service,
        "learn_from_document",
        failing_learn,
    )

    result = await record_document_learning(
        object(),
        "doc-456",
        "link",
    )

    assert result["learned"] is False
    assert result["trigger"] == "link"
    assert "learning failure" in result["error"]


def _learning_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not (
            isinstance(call.func, ast.Name)
            and call.func.id == "record_document_learning"
        ):
            continue

        trigger = None
        if len(call.args) >= 3 and isinstance(call.args[2], ast.Constant):
            trigger = call.args[2].value
        calls.append(trigger)

    return calls


def test_classification_service_records_learning():
    path = BACKEND_DIR / "services" / "document_classification_service.py"
    assert _learning_calls(path) == ["classification"]


def test_resolution_service_records_learning():
    path = BACKEND_DIR / "services" / "document_resolution_service.py"
    assert _learning_calls(path) == ["link"]


def test_handler_facade_still_exports_live_services():
    from services import document_handlers
    from services import document_classification_service
    from services import document_resolution_service

    assert (
        document_handlers.classify_document
        is document_classification_service.classify_document
    )
    assert (
        document_handlers.ResolveRequest
        is document_resolution_service.ResolveRequest
    )
    assert (
        document_handlers.resolve_and_link_document
        is document_resolution_service.resolve_and_link_document
    )
