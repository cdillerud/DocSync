"""
Tests for services/price_list_index.py: the PDFs in each supplier's pricing folders on OneGamer go to the catalog's
price-list intake once, then only when changed. Pins down: only pricing folders are walked (nested years too), only
PDFs modified since the date, the intake URL comes from the new item requests URL, and the sent-files state keeps a
second run from sending the same file again.
"""
import asyncio
import base64
import json

import httpx
import pytest

from services import price_list_index as pli

TREE = {
    "root": [{"id": "amcor", "name": "Amcor", "folder": {}}, {"id": "berry", "name": "Berry (M&H)", "folder": {}}],
    "amcor": [{"id": "ap", "name": "Pricing", "folder": {}}, {"id": "ad", "name": "Drawings", "folder": {}}],
    "ap": [{"id": "a26", "name": "2026", "folder": {}},
           {"id": "old", "name": "Price Book_2019.PDF", "file": {}, "lastModifiedDateTime": "2019-07-01T00:00:00Z"}],
    "a26": [{"id": "pb", "name": "Price Book_0004378227_Legacy 10-8-26.PDF", "file": {}, "eTag": "e1",
             "lastModifiedDateTime": "2026-10-02T00:00:00Z"},
            {"id": "xl", "name": "notes.xlsx", "file": {}, "lastModifiedDateTime": "2026-10-02T00:00:00Z"}],
    "ad": [{"id": "dwg", "name": "bottle.pdf", "file": {}, "lastModifiedDateTime": "2026-10-02T00:00:00Z"}],
    "berry": [{"id": "bp", "name": "Pricing", "folder": {}}],
    "bp": [{"id": "letter", "name": "2026-11-02 2026-10-27 1548 --- 100 GAMER PACKAGING.PDF", "file": {}, "eTag": "e2",
            "lastModifiedDateTime": "2026-10-27T00:00:00Z"}],
}
SENT = []


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if request.method == "POST":
        body = json.loads(request.content)
        SENT.append(body)
        read = [{"supplier": "X"}] if "Price Book" in body["name"] else []
        return httpx.Response(200, json={"status": "OK", "read": read})
    if url.endswith("/content"):
        return httpx.Response(200, content=b"%PDF-1.4 fake")
    if "/sites/" in url and "/drive?" in url:
        return httpx.Response(200, json={"id": "drive1"})
    if "/sites/" in url:
        return httpx.Response(200, json={"id": "site1"})
    if "root:/" in url:
        return httpx.Response(200, json={"id": "root"})
    item = url.split("/items/")[1].split("/children")[0]
    return httpx.Response(200, json={"value": TREE.get(item, [])})


@pytest.fixture(autouse=True)
def fake_graph(monkeypatch):
    SENT.clear()
    real = httpx.AsyncClient
    monkeypatch.setattr(pli.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(_handler), **kw))

    async def token():
        return "tok"
    import services.catalog_forward as cf
    import services.config_service as cs
    monkeypatch.setattr(cf, "_graph_token", token)
    monkeypatch.setattr(cs, "SHAREPOINT_SITE_HOSTNAME", "example.sharepoint.com", raising=False)
    monkeypatch.setenv("NEW_ITEM_REQUESTS_URL", "https://svc/api/v70/catalog/intake/new-items")
    monkeypatch.setenv("NEW_ITEM_REQUESTS_KEY", "k")


def test_only_recent_pdfs_in_pricing_folders():
    out = asyncio.run(pli.crawl(since="2025-01-01", host="example.sharepoint.com"))
    assert sorted(f["name"] for f in out["files"]) == ["2026-11-02 2026-10-27 1548 --- 100 GAMER PACKAGING.PDF",
                                                       "Price Book_0004378227_Legacy 10-8-26.PDF"]
    assert pli._intake_url() == "https://svc/api/v70/catalog/intake/price-lists"


def test_sends_once_then_only_changes(tmp_path):
    state = str(tmp_path / "sent.json")
    out = asyncio.run(pli.run(send_it=True, since="2025-01-01", state_path=state))
    assert out["status"] == "SENT" and out["files_read"] == 1 and out["not_a_price_list_it_reads"] == 1
    assert len(SENT) == 2 and base64.b64decode(SENT[0]["pdf_b64"]).startswith(b"%PDF")
    again = asyncio.run(pli.run(send_it=True, since="2025-01-01", state_path=state))
    assert again["new_or_changed"] == 0 and len(SENT) == 2
    TREE["a26"][0]["eTag"] = "e1-changed"
    try:
        third = asyncio.run(pli.run(send_it=True, since="2025-01-01", state_path=state))
    finally:
        TREE["a26"][0]["eTag"] = "e1"
    assert third["new_or_changed"] == 1 and len(SENT) == 3


def test_preview_sends_nothing(tmp_path):
    out = asyncio.run(pli.run(send_it=False, since="2025-01-01", state_path=str(tmp_path / "s.json")))
    assert out["status"] == "LISTED" and len(out["would_send"]) == 2 and not SENT
