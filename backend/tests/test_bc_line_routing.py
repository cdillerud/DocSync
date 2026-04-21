"""
Tests for the BC line-type routing fix + partial-post detection.

Targets two related defects called out in the engineering review:

  * "Posts to BC using a single FREIGHT item code for every line" —
    previously ``_add_invoice_lines`` hardcoded ``lineType=Item`` with a
    single env-default item GUID for every line, ignoring the per-line
    ``lineType`` / ``lineObjectNumber`` produced by the vendor-profile PI
    builder.
  * Partial-post silent success — header-created + lines-rejected used
    to return ``success=True`` with ``linesAdded=0``, causing downstream
    code to mark the document "posted" while BC held an orphan draft.

These tests exercise the rewritten ``_add_invoice_lines`` and
``create_purchase_invoice`` logic with httpx stubbed by ``respx``-like
function mocks — no live BC API needed.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.business_central_service import BusinessCentralService


# ---------------------------------------------------------------------------
# Minimal httpx AsyncClient stand-in that routes requests through a handler.
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, body: Any = None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body

    @property
    def text(self):
        return json.dumps(self._body)


class _FakeClient:
    """Records calls and delegates to a user-supplied handler."""

    def __init__(self, handler: Callable[[str, str, Dict], _FakeResponse]):
        self._handler = handler
        self.calls: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self._handler("GET", url, {"params": params})

    async def post(self, url, headers=None, json=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        return self._handler("POST", url, {"json": json})

    async def delete(self, url, headers=None):
        self.calls.append({"method": "DELETE", "url": url})
        return self._handler("DELETE", url, {})


def _install_fake_client(handler, monkeypatch):
    """Patch httpx.AsyncClient to return our fake. Returns the shared call log."""
    fake = _FakeClient(handler)

    def factory(*a, **kw):
        return fake

    monkeypatch.setattr(
        "services.business_central_service.httpx.AsyncClient", factory
    )
    return fake


# ---------------------------------------------------------------------------
# Per-line type routing — Account vs. Item vs. unresolved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAddInvoiceLinesPerTypeRouting:

    def _handler_factory(self, *, gl_map=None, item_map=None, line_post_status=201):
        """Produce an httpx handler that:
          - resolves GL numbers via `gl_map` and Item codes via `item_map`
          - accepts POSTs to /purchaseInvoiceLines with `line_post_status`
        """
        gl_map = gl_map or {}
        item_map = item_map or {}
        line_posts: List[Dict] = []

        def handler(method, url, kwargs):
            if method == "GET" and "/accounts" in url:
                number = kwargs["params"]["$filter"].split("'")[1]
                if number in gl_map:
                    return _FakeResponse(
                        200,
                        {"value": [{
                            "id": gl_map[number],
                            "number": number,
                            "displayName": f"GL {number}",
                        }]},
                    )
                return _FakeResponse(200, {"value": []})

            if method == "GET" and "/items" in url:
                number = kwargs["params"]["$filter"].split("'")[1]
                if number in item_map:
                    return _FakeResponse(
                        200,
                        {"value": [{
                            "id": item_map[number],
                            "number": number,
                            "displayName": f"Item {number}",
                        }]},
                    )
                return _FakeResponse(200, {"value": []})

            if method == "POST" and "/purchaseInvoiceLines" in url:
                line_posts.append(kwargs["json"])
                return _FakeResponse(
                    line_post_status,
                    {"id": str(uuid.uuid4()), **kwargs["json"]},
                )

            return _FakeResponse(500, {"error": f"unhandled {method} {url}"})

        return handler, line_posts

    async def test_account_line_posts_with_accountId(self, monkeypatch):
        """A preflight-produced Account line must be routed to BC with
        lineType=Account + accountId (the resolved GUID), NOT downgraded
        to a hardcoded FREIGHT Item."""
        handler, posts = self._handler_factory(
            gl_map={"60500": "gl-guid-60500"}
        )
        _install_fake_client(handler, monkeypatch)

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            invoice_id="inv-1",
            lines=[
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "Freight", "quantity": 1, "unitCost": 100.0},
            ],
            token="tok", company_id="co",
        )
        assert result["added"] == 1
        assert result["errors"] == []
        assert len(posts) == 1
        assert posts[0]["lineType"] == "Account"
        assert posts[0]["accountId"] == "gl-guid-60500"
        assert "itemId" not in posts[0]

    async def test_item_line_posts_with_itemId(self, monkeypatch):
        handler, posts = self._handler_factory(
            item_map={"WIDGET": "item-guid-widget"}
        )
        _install_fake_client(handler, monkeypatch)

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            invoice_id="inv-1",
            lines=[
                {"lineType": "Item", "lineObjectNumber": "WIDGET",
                 "description": "Widget", "quantity": 5, "unitCost": 20.0},
            ],
            token="tok", company_id="co",
        )
        assert result["added"] == 1
        assert posts[0]["lineType"] == "Item"
        assert posts[0]["itemId"] == "item-guid-widget"
        assert "accountId" not in posts[0]

    async def test_mixed_lines_each_routed_correctly(self, monkeypatch):
        """XPOLOGI-style mixed payload: 4 Account lines all 60500 plus a
        one-off Item line. Every line must reach BC with its correct
        classification — no FREIGHT collapse."""
        handler, posts = self._handler_factory(
            gl_map={"60500": "gl-guid-60500"},
            item_map={"WIDGET": "item-guid-widget"},
        )
        client = _install_fake_client(handler, monkeypatch)

        svc = BusinessCentralService()
        svc.use_mock = False
        lines = [
            {"lineType": "Account", "lineObjectNumber": "60500",
             "description": "PLT", "quantity": 2600, "unitCost": 2.7768},
            {"lineType": "Account", "lineObjectNumber": "60500",
             "description": "DISC", "quantity": 1, "unitCost": -6750.40},
            {"lineType": "Account", "lineObjectNumber": "60500",
             "description": "FSC", "quantity": 1, "unitCost": 153.69},
            {"lineType": "Account", "lineObjectNumber": "60500",
             "description": "CCS", "quantity": 1, "unitCost": 27.00},
            {"lineType": "Item", "lineObjectNumber": "WIDGET",
             "description": "Widget", "quantity": 1, "unitCost": 10.0},
        ]
        result = await svc._add_invoice_lines("inv-x", lines, "tok", "co")

        assert result["added"] == 5
        assert all(p["lineType"] == "Account" for p in posts[:4])
        assert all(p["accountId"] == "gl-guid-60500" for p in posts[:4])
        assert posts[4]["lineType"] == "Item"
        assert posts[4]["itemId"] == "item-guid-widget"

        # GL 60500 resolved ONCE despite being used on 4 lines (cache).
        gl_lookups = [
            c for c in client.calls
            if c["method"] == "GET" and "/accounts" in c["url"]
        ]
        assert len(gl_lookups) == 1

    async def test_unresolved_account_becomes_error_not_freight(self, monkeypatch):
        """If a GL account number can't be resolved, the line must be
        reported as a failure — NEVER silently substituted with the
        legacy FREIGHT item. This is the whole point of the fix."""
        handler, posts = self._handler_factory(
            gl_map={},  # 99999 not mapped
            item_map={"FREIGHT": "item-freight-guid"},  # available but unused
        )
        _install_fake_client(handler, monkeypatch)
        # Ensure legacy env is set — this line must STILL fail rather
        # than silently fall back to FREIGHT.
        monkeypatch.setenv("BC_DEFAULT_ITEM_CODE", "FREIGHT")

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            invoice_id="inv-1",
            lines=[{
                "lineType": "Account", "lineObjectNumber": "99999",
                "description": "Unknown GL", "quantity": 1, "unitCost": 50.0,
            }],
            token="tok", company_id="co",
        )
        assert result["added"] == 0
        assert len(result["errors"]) == 1
        err = result["errors"][0]
        assert "99999" in err["error"]
        assert "not found" in err["error"].lower()
        assert posts == []   # nothing was sent to BC

    async def test_unclassified_line_falls_back_to_legacy_default(self, monkeypatch):
        """Compatibility bridge: if a line arrives with no lineType AND
        no lineObjectNumber, the legacy BC_DEFAULT_ITEM_CODE fallback is
        still allowed — but it's warning-logged so the gap is visible."""
        handler, posts = self._handler_factory(
            item_map={"FREIGHT": "item-freight-guid"},
        )
        _install_fake_client(handler, monkeypatch)
        monkeypatch.setenv("BC_DEFAULT_ITEM_CODE", "FREIGHT")

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            "inv-1",
            [{"description": "Unclassified", "quantity": 1, "unitCost": 1.0}],
            "tok", "co",
        )
        assert result["added"] == 1
        assert posts[0]["lineType"] == "Item"
        assert posts[0]["itemId"] == "item-freight-guid"

    async def test_unclassified_line_no_legacy_env_errors_cleanly(self, monkeypatch):
        """With the legacy env unset, an unclassified line is an error —
        not a silent success."""
        handler, posts = self._handler_factory()
        _install_fake_client(handler, monkeypatch)
        monkeypatch.delenv("BC_DEFAULT_ITEM_CODE", raising=False)
        monkeypatch.delenv("BC_PI_FREIGHT_ITEM", raising=False)

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            "inv-1",
            [{"description": "Orphan", "quantity": 1, "unitCost": 1.0}],
            "tok", "co",
        )
        assert result["added"] == 0
        assert len(result["errors"]) == 1
        assert "Unsupported" in result["errors"][0]["error"]

    async def test_line_post_failure_is_recorded_per_line(self, monkeypatch):
        """A line that BC rejects (400) is captured in errors; successful
        lines on the same invoice still report added correctly."""
        gl_map = {"60500": "gl-guid-60500"}
        state = {"post_count": 0}

        def handler(method, url, kwargs):
            if method == "GET" and "/accounts" in url:
                number = kwargs["params"]["$filter"].split("'")[1]
                if number in gl_map:
                    return _FakeResponse(
                        200,
                        {"value": [{"id": gl_map[number], "number": number,
                                    "displayName": f"GL {number}"}]},
                    )
                return _FakeResponse(200, {"value": []})
            if method == "POST" and "/purchaseInvoiceLines" in url:
                state["post_count"] += 1
                if state["post_count"] == 2:
                    return _FakeResponse(400, {"error": "line validation failed"})
                return _FakeResponse(201, {"id": str(uuid.uuid4())})
            return _FakeResponse(500, {})

        _install_fake_client(handler, monkeypatch)

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc._add_invoice_lines(
            "inv-1",
            [
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "A", "quantity": 1, "unitCost": 10.0},
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "B", "quantity": 1, "unitCost": 20.0},
            ],
            "tok", "co",
        )
        assert result["added"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["line"] == 2
        assert result["errors"][0]["http_status"] == 400


# ---------------------------------------------------------------------------
# Partial-post detection in create_purchase_invoice
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPartialPostDetection:

    async def test_success_only_when_all_lines_added(self, monkeypatch):
        """Happy path: header OK, all lines OK -> success=True."""
        invoice_guid = str(uuid.uuid4())

        def handler(method, url, kwargs):
            if method == "POST" and url.endswith("/purchaseInvoices"):
                return _FakeResponse(
                    201, {"id": invoice_guid, "number": "PI-OK", "status": "Draft"}
                )
            if method == "GET" and "/accounts" in url:
                return _FakeResponse(
                    200, {"value": [{"id": "gl-guid", "number": "60500"}]}
                )
            if method == "POST" and "/purchaseInvoiceLines" in url:
                return _FakeResponse(201, {"id": str(uuid.uuid4())})
            return _FakeResponse(500, {})

        _install_fake_client(handler, monkeypatch)
        monkeypatch.setattr(
            "services.business_central_service.get_bc_token",
            AsyncMock(return_value="tok"),
        )
        monkeypatch.setattr(
            "services.business_central_service.BusinessCentralService._get_company_id",
            AsyncMock(return_value="co"),
        )
        monkeypatch.setattr(
            "services.business_central_service._check_write_protection",
            lambda *a, **k: None,
        )
        monkeypatch.setenv("BC_WRITE_ENVIRONMENT", "Sandbox")

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V1", "invoiceNumber": "INV-1",
            "invoiceDate": "2026-04-20",
            "lines": [
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "A", "quantity": 1, "unitCost": 50.0},
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "B", "quantity": 1, "unitCost": 50.0},
            ],
        })
        assert result["success"] is True
        assert result["linesAdded"] == 2
        assert result["linesTotal"] == 2

    async def test_header_ok_all_lines_fail_reports_partial_post(self, monkeypatch):
        """THE regression test: previously this returned success=True with
        linesAdded=0. Must now return success=False with error='partial_post'."""
        invoice_guid = str(uuid.uuid4())
        deletion_attempts: List[str] = []

        def handler(method, url, kwargs):
            if method == "POST" and url.endswith("/purchaseInvoices"):
                return _FakeResponse(
                    201, {"id": invoice_guid, "number": "PI-ORPHAN"}
                )
            if method == "GET" and "/accounts" in url:
                # GL not found — every line will fail to resolve.
                return _FakeResponse(200, {"value": []})
            if method == "DELETE" and invoice_guid in url:
                deletion_attempts.append(url)
                return _FakeResponse(204)
            return _FakeResponse(500, {})

        _install_fake_client(handler, monkeypatch)
        monkeypatch.setattr(
            "services.business_central_service.get_bc_token",
            AsyncMock(return_value="tok"),
        )
        monkeypatch.setattr(
            "services.business_central_service.BusinessCentralService._get_company_id",
            AsyncMock(return_value="co"),
        )
        monkeypatch.setattr(
            "services.business_central_service._check_write_protection",
            lambda *a, **k: None,
        )

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V1", "invoiceNumber": "INV-1",
            "invoiceDate": "2026-04-20",
            "lines": [
                {"lineType": "Account", "lineObjectNumber": "99999",
                 "description": "Bad GL", "quantity": 1, "unitCost": 50.0},
            ],
        })
        assert result["success"] is False
        assert result["error"] == "partial_post"
        assert result["linesAdded"] == 0
        assert result["linesTotal"] == 1
        assert result["bcDocumentId"] == invoice_guid
        assert result["orphan_header_deletion"] == "deleted"
        assert len(deletion_attempts) == 1

    async def test_some_lines_fail_still_partial_post(self, monkeypatch):
        """Header + 1/2 lines OK, 1 line rejected -> partial_post."""
        invoice_guid = str(uuid.uuid4())
        state = {"line_posts": 0}

        def handler(method, url, kwargs):
            if method == "POST" and url.endswith("/purchaseInvoices"):
                return _FakeResponse(
                    201, {"id": invoice_guid, "number": "PI-P"}
                )
            if method == "GET" and "/accounts" in url:
                return _FakeResponse(
                    200, {"value": [{"id": "gl-guid", "number": "60500"}]}
                )
            if method == "POST" and "/purchaseInvoiceLines" in url:
                state["line_posts"] += 1
                if state["line_posts"] == 2:
                    return _FakeResponse(400, {"error": "BC rejected line 2"})
                return _FakeResponse(201, {"id": str(uuid.uuid4())})
            if method == "DELETE":
                return _FakeResponse(204)
            return _FakeResponse(500, {})

        _install_fake_client(handler, monkeypatch)
        monkeypatch.setattr(
            "services.business_central_service.get_bc_token",
            AsyncMock(return_value="tok"),
        )
        monkeypatch.setattr(
            "services.business_central_service.BusinessCentralService._get_company_id",
            AsyncMock(return_value="co"),
        )
        monkeypatch.setattr(
            "services.business_central_service._check_write_protection",
            lambda *a, **k: None,
        )

        svc = BusinessCentralService()
        svc.use_mock = False
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V1", "invoiceNumber": "INV-1",
            "invoiceDate": "2026-04-20",
            "lines": [
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "A", "quantity": 1, "unitCost": 50.0},
                {"lineType": "Account", "lineObjectNumber": "60500",
                 "description": "B", "quantity": 1, "unitCost": 50.0},
            ],
        })
        assert result["success"] is False
        assert result["error"] == "partial_post"
        assert result["linesAdded"] == 1
        assert result["linesTotal"] == 2
