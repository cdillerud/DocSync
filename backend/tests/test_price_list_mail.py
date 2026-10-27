"""services/price_list_mail.py: PDFs from the supplier-facing mailbox go to the price-lists intake once each."""
import asyncio
import json

import httpx
import pytest

from services import price_list_mail as plm

POSTED = []


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if request.method == "POST":
        POSTED.append(json.loads(request.content)["name"])
        name = POSTED[-1]
        return httpx.Response(200, json={"status": "ACCEPTED", "read": [{"supplier": "Berry"}] if "Berry" in name else []})
    if url.endswith("/attachments?%24select=id%2Cname%2CcontentType%2Csize") or "/attachments?$select" in url:
        return httpx.Response(200, json={"value": [
            {"id": "a1", "name": "Berry 2026-04-13.PDF", "contentType": "application/pdf", "size": 1000},
            {"id": "a2", "name": "PO 4411.pdf", "contentType": "application/pdf", "size": 1000},
            {"id": "a3", "name": "logo.png", "contentType": "image/png", "size": 10},
            {"id": "a4", "name": "fwd.msg", "@odata.type": "#microsoft.graph.itemAttachment", "size": 10}]})
    if "/attachments/" in url:
        return httpx.Response(200, json={"contentBytes": "JVBERi0xLjQK"})
    if "/messages" in url:
        return httpx.Response(200, json={"value": [{"id": "m1", "receivedDateTime": "2026-10-27T10:00:00Z"}]})
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    POSTED.clear()
    real = httpx.AsyncClient
    monkeypatch.setattr(plm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(_handler), **kw))

    async def token():
        return "tok"
    import services.config_service as cs
    monkeypatch.setattr(cs, "get_email_token", token)
    monkeypatch.setenv("NEW_ITEM_REQUESTS_URL", "https://svc/api/v70/catalog/intake/new-items")
    monkeypatch.setenv("NEW_ITEM_REQUESTS_KEY", "k")


def test_pdfs_go_once_and_counts_only(tmp_path):
    state = str(tmp_path / "seen.json")
    out = asyncio.run(plm.run(days=2, state_path=state))
    assert out["status"] == "OK" and out["pdfs"] == 2 and out["sent"] == 2
    assert out["price_lists_kept"] == 1 and out["not_price_lists"] == 1 and POSTED == ["Berry 2026-04-13.PDF", "PO 4411.pdf"]
    again = asyncio.run(plm.run(days=2, state_path=state))
    assert again["sent"] == 0 and again["already_sent"] == 2
    assert plm._settings()["url"] == "https://svc/api/v70/catalog/intake/price-lists"
