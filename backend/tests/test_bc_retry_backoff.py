"""
Lane A A2 — BC retry/backoff wrapper.

Contract:
  * 3 attempts max by default.
  * Retriable HTTP statuses: 429, 502, 503, 504.
  * Retriable exceptions: ConnectError, ConnectTimeout, ReadTimeout,
    ReadError, PoolTimeout, WriteTimeout.
  * Non-retriable 4xx passes through immediately — no retry.
  * Sleeps between attempts with exponential base + jitter (±25 %).
  * Successful call attaches ``response.extensions["bc_retry"]`` metadata.
  * Exhausted retries raise ``BCRetriesExhausted`` with last_status,
    last_detail, attempts, retry_reasons.

Tests patch ``httpx.AsyncClient`` so no real BC tenant is contacted.
"""

import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Retry helper — direct unit tests
# ---------------------------------------------------------------------------


def _fake_resp(status_code: int, text: str = "") -> httpx.Response:
    # Create a real httpx.Response so .extensions is a real mapping we can
    # read back (Mocks don't give us that).
    req = httpx.Request("POST", "https://example.invalid/foo")
    return httpx.Response(status_code=status_code, text=text, request=req)


@pytest.mark.asyncio
async def test_retry_returns_immediately_on_2xx():
    from services.business_central_service import bc_http_with_retry

    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        return _fake_resp(201, "")

    # Zero sleep between attempts for speed.
    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        resp = await bc_http_with_retry(send, op="test_op")

    assert call_count == 1, "2xx must return on first attempt"
    assert resp.status_code == 201
    assert resp.extensions["bc_retry"]["attempts"] == 1
    assert resp.extensions["bc_retry"]["retry_reasons"] == []


@pytest.mark.asyncio
async def test_retry_passes_through_4xx_non_429_immediately():
    from services.business_central_service import bc_http_with_retry

    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        return _fake_resp(400, "Bad Request")

    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        resp = await bc_http_with_retry(send, op="test_op")

    assert call_count == 1, "400 must not be retried — data problem, not transient"
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_retry_recovers_after_429_then_200():
    """The canonical A2 test: BC rate-limits us, we back off, we succeed."""
    from services.business_central_service import bc_http_with_retry

    sequence = iter([_fake_resp(429, "slow down"), _fake_resp(201, "")])
    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        return next(sequence)

    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        resp = await bc_http_with_retry(send, op="test_op", max_attempts=3)

    assert call_count == 2
    assert resp.status_code == 201
    meta = resp.extensions["bc_retry"]
    assert meta["attempts"] == 2
    assert meta["retry_reasons"] == ["429"]


@pytest.mark.asyncio
async def test_retry_exhausts_on_three_consecutive_503():
    from services.business_central_service import bc_http_with_retry, BCRetriesExhausted

    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        return _fake_resp(503, "BC is down")

    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        with pytest.raises(BCRetriesExhausted) as excinfo:
            await bc_http_with_retry(send, op="test_op", max_attempts=3)

    assert call_count == 3, "must try exactly max_attempts times"
    assert excinfo.value.attempts == 3
    assert excinfo.value.last_status == 503
    assert excinfo.value.retry_reasons == ["503", "503", "503"]


@pytest.mark.asyncio
async def test_retry_handles_connection_errors_as_retriable():
    from services.business_central_service import bc_http_with_retry

    sequence = iter([
        httpx.ConnectError("boom", request=httpx.Request("POST", "https://x")),
        _fake_resp(201, ""),
    ])
    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        item = next(sequence)
        if isinstance(item, Exception):
            raise item
        return item

    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        resp = await bc_http_with_retry(send, op="test_op")

    assert call_count == 2
    assert resp.status_code == 201
    assert resp.extensions["bc_retry"]["retry_reasons"] == ["ConnectError"]


@pytest.mark.asyncio
async def test_retry_respects_max_attempts_of_1():
    """max_attempts=1 disables retry — used when the caller knows retrying is unsafe."""
    from services.business_central_service import bc_http_with_retry, BCRetriesExhausted

    call_count = 0
    async def send():
        nonlocal call_count
        call_count += 1
        return _fake_resp(503, "")

    with patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        with pytest.raises(BCRetriesExhausted):
            await bc_http_with_retry(send, op="test_op", max_attempts=1)

    assert call_count == 1


# ---------------------------------------------------------------------------
# create_purchase_invoice surfaces retry metadata / exhaustion correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_purchase_invoice_returns_retries_exhausted_on_all_503():
    """End-to-end: when BC is completely down, the service returns a sane
    failure dict with retries_exhausted=True, not an unhandled exception."""
    from services.business_central_service import BusinessCentralService

    svc = BusinessCentralService()
    svc.use_mock = False

    fake_header_resp = _fake_resp(503, "service unavailable")

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return fake_header_resp

    with patch("services.business_central_service.get_bc_token", AsyncMock(return_value="tkn")), \
         patch.object(svc, "_get_company_id", AsyncMock(return_value="co-guid")), \
         patch("services.business_central_service._check_write_protection", lambda *_a, **_k: None), \
         patch("services.business_central_service.httpx.AsyncClient", FakeClient), \
         patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0):
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V-TEST",
            "invoiceNumber": "INV-1",
            "invoiceDate": "2026-04-22",
            "lines": [],
        })

    assert result["success"] is False
    assert result["retries_exhausted"] is True
    assert result["retry_reasons"] == ["503", "503", "503"]


@pytest.mark.asyncio
async def test_create_purchase_invoice_recovers_after_one_429():
    """End-to-end: one 429 → retry succeeds → invoice reports success."""
    from services.business_central_service import BusinessCentralService

    svc = BusinessCentralService()
    svc.use_mock = False

    responses = iter([
        _fake_resp(429, "slow down"),
        httpx.Response(
            status_code=201,
            json={"id": "inv-guid-ok", "number": "PI-TEST-OK"},
            request=httpx.Request("POST", "https://example.invalid/foo"),
        ),
    ])

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): return next(responses)

    with patch("services.business_central_service.get_bc_token", AsyncMock(return_value="tkn")), \
         patch.object(svc, "_get_company_id", AsyncMock(return_value="co-guid")), \
         patch("services.business_central_service._check_write_protection", lambda *_a, **_k: None), \
         patch("services.business_central_service.httpx.AsyncClient", FakeClient), \
         patch("services.business_central_service.BC_RETRY_BASE_SECONDS", 0.0), \
         patch.object(svc, "_add_invoice_lines",
                      AsyncMock(return_value={"added": 0, "total": 0, "errors": []})):
        result = await svc.create_purchase_invoice({
            "vendorNumber": "V-TEST",
            "invoiceNumber": "INV-2",
            "invoiceDate": "2026-04-22",
            "lines": [],
        })

    assert result["success"] is True
    assert result["bcDocumentNumber"] == "PI-TEST-OK"


# ---------------------------------------------------------------------------
# Jitter sanity — the sleep helper never returns negative, stays roughly
# within ±25% of base
# ---------------------------------------------------------------------------


def test_jitter_sleep_within_expected_band():
    from services.business_central_service import _jitter_sleep

    for base in (1.0, 2.0, 4.0):
        for _ in range(200):
            v = _jitter_sleep(base)
            assert v >= 0.0
            assert v <= base * 1.26, f"jitter exceeded +25% band: {v} vs base={base}"
            assert v >= base * 0.74, f"jitter exceeded -25% band: {v} vs base={base}"
