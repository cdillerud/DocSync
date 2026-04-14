"""
Tests for the Inside Sales Pilot Ingestion feature.

Tests the router endpoints, safety guards, and configuration.
"""
import pytest
import httpx
import os

API_URL = os.environ.get(
    "API_URL",
    (open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0])
    if os.path.exists("/app/frontend/.env") else "http://localhost:8001"
)


@pytest.mark.asyncio
async def test_pilot_status_endpoint():
    """GET /api/inside-sales-pilot/status returns config + summary."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "mailboxes" in data
    assert "mkoch@gamerpackaging.com" in data["mailboxes"]
    assert "nhannover@gamerpackaging.com" in data["mailboxes"]
    assert "interval_minutes" in data
    assert "total_documents" in data
    assert "by_mailbox" in data
    assert "by_doc_type" in data
    assert "extraction_coverage" in data


@pytest.mark.asyncio
async def test_pilot_documents_endpoint():
    """GET /api/inside-sales-pilot/documents returns list (even if empty)."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "documents" in data
    assert isinstance(data["documents"], list)


@pytest.mark.asyncio
async def test_pilot_runs_endpoint():
    """GET /api/inside-sales-pilot/runs returns run history."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_pilot_logs_endpoint():
    """GET /api/inside-sales-pilot/logs returns detailed logs."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "logs" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_pilot_extraction_review_endpoint():
    """GET /api/inside-sales-pilot/extraction-review returns extraction results."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/extraction-review")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "documents" in data


@pytest.mark.asyncio
async def test_poll_now_when_disabled():
    """POST /api/inside-sales-pilot/poll-now should return error when disabled."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(f"{API_URL}/api/inside-sales-pilot/poll-now")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert "disabled" in data["error"].lower() or "INSIDE_SALES_PILOT_ENABLED" in data["error"]


@pytest.mark.asyncio
async def test_status_shows_correct_mailboxes():
    """Status endpoint should always list the 2 pilot mailboxes."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{API_URL}/api/inside-sales-pilot/status")
    data = resp.json()
    mailboxes = data.get("mailboxes", [])
    assert len(mailboxes) == 2
    assert "mkoch@gamerpackaging.com" in mailboxes
    assert "nhannover@gamerpackaging.com" in mailboxes


@pytest.mark.asyncio
async def test_documents_filter_by_mailbox():
    """Documents endpoint supports mailbox filter."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            f"{API_URL}/api/inside-sales-pilot/documents",
            params={"mailbox": "mkoch@gamerpackaging.com"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data


@pytest.mark.asyncio
async def test_logs_filter_by_status():
    """Logs endpoint supports status filter."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            f"{API_URL}/api/inside-sales-pilot/logs",
            params={"status": "ingested"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "logs" in data


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_pilot_status_endpoint())
    asyncio.run(test_pilot_documents_endpoint())
    asyncio.run(test_pilot_runs_endpoint())
    asyncio.run(test_pilot_logs_endpoint())
    asyncio.run(test_pilot_extraction_review_endpoint())
    asyncio.run(test_poll_now_when_disabled())
    asyncio.run(test_status_shows_correct_mailboxes())
    asyncio.run(test_documents_filter_by_mailbox())
    asyncio.run(test_logs_filter_by_status())
    print("All tests passed!")
