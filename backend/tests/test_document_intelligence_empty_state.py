"""Tests for the document_intelligence empty-state behaviour.

Verifies that GET /api/document-intelligence/{doc_id} and
GET /api/document-intelligence/decision/{doc_id} return a 200 empty
envelope when no result/decision exists, instead of a 404 (which
produces browser-console noise on every page load).
"""
from __future__ import annotations

import importlib
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """Build a minimal FastAPI app wrapping the document_intelligence
    router. The router uses module-level `from … import name` for
    its service deps, so individual tests patch the resolved symbols
    on the router module via `unittest.mock.patch.object` rather
    than swapping in fake submodules.
    """
    from routers import document_intelligence as router_mod
    importlib.reload(router_mod)

    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api")
    return TestClient(app), router_mod


def test_get_intelligence_returns_200_empty_state_when_no_result(
        app_client):
    client, router_mod = app_client
    with patch.object(router_mod, "get_intelligence_result",
                      new=AsyncMock(return_value=None)):
        resp = client.get("/api/document-intelligence/missing-doc-id")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "exists": False,
        "result": None,
        "document_id": "missing-doc-id",
    }


def test_get_intelligence_returns_existing_result_unchanged(app_client):
    client, router_mod = app_client
    payload: Dict[str, Any] = {
        "id": "abc",
        "doc_type": "AP_Invoice",
        "extracted_fields": {"vendor": "ACME"},
    }
    with patch.object(router_mod, "get_intelligence_result",
                      new=AsyncMock(return_value=payload)):
        resp = client.get("/api/document-intelligence/abc")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_get_decision_returns_200_empty_state_when_no_decision(app_client):
    client, router_mod = app_client
    with patch.object(router_mod, "get_decision",
                      new=AsyncMock(return_value=None)):
        resp = client.get("/api/document-intelligence/decision/missing")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "exists": False,
        "decision": None,
        "document_id": "missing",
    }


def test_get_decision_returns_existing_decision_unchanged(app_client):
    client, router_mod = app_client
    decision: Dict[str, Any] = {
        "id": "dec-1",
        "document_id": "abc",
        "decision_action": "hold_for_review",
    }
    with patch.object(router_mod, "get_decision",
                      new=AsyncMock(return_value=decision)):
        resp = client.get("/api/document-intelligence/decision/abc")
    assert resp.status_code == 200
    assert resp.json() == decision
