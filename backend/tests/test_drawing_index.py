"""
Tests for services/drawing_index.py: listing the OneGamer supplier drawing folders and sending them to the
catalog's drawings intake. Pins down: only folders named like drawings/specs under each supplier are walked (nested
too), only drawing file types are listed, the intake URL comes from the new item requests URL, and the listing goes
in batches under one snapshot id.
"""
import asyncio
import json

import httpx
import pytest

from services import drawing_index as di

TREE = {
    "root": [{"id": "anchor", "name": "Anchor Glass", "folder": {}}, {"id": "notes", "name": "readme.txt", "file": {}}],
    "anchor": [{"id": "dw", "name": "Drawings", "folder": {}}, {"id": "qt", "name": "Quotes", "folder": {}}],
    "dw": [{"id": "bev", "name": "Beer-Beverage", "folder": {}},
           {"id": "f1", "name": "B-98499 Lightweight 12oz Ring Neck.pdf", "file": {}, "webUrl": "https://sp/b98499.pdf",
            "lastModifiedDateTime": "2025-08-18T19:31:32Z"}],
    "bev": [{"id": "f2", "name": "854468 12 oz Ring Neck Bottle - 11328A.pdf", "file": {}, "webUrl": "https://sp/854468.pdf"},
            {"id": "f3", "name": "price list.xlsx", "file": {}, "webUrl": "https://sp/x.xlsx"}],
    "qt": [{"id": "f4", "name": "quote 11328A.pdf", "file": {}, "webUrl": "https://sp/q.pdf"}],
}
SENT = []


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if request.method == "POST":
        body = json.loads(request.content)
        SENT.append(body)
        return httpx.Response(200, json={"status": "ACCEPTED", "stored": body["batch"] == body["batches"]})
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
    monkeypatch.setattr(di.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(_handler), **kw))

    async def token():
        return "tok"
    import services.catalog_forward as cf
    monkeypatch.setattr(cf, "_graph_token", token)
    monkeypatch.setenv("NEW_ITEM_REQUESTS_URL", "https://svc/api/v70/catalog/intake/new-items")
    monkeypatch.setenv("NEW_ITEM_REQUESTS_KEY", "k")


def test_lists_only_drawing_folders_and_drawing_files():
    out = asyncio.run(di.crawl(host="example.sharepoint.com"))
    names = sorted(r["name"] for r in out["drawings"])
    assert names == ["854468 12 oz Ring Neck Bottle - 11328A.pdf", "B-98499 Lightweight 12oz Ring Neck.pdf"]
    assert {r["supplier"] for r in out["drawings"]} == {"Anchor Glass"}
    assert out["suppliers"] == 1


def test_sends_in_batches_to_the_drawings_intake(monkeypatch):
    assert di._intake_url() == "https://svc/api/v70/catalog/intake/drawings"
    monkeypatch.setattr(di, "BATCH", 1)
    rows = [{"supplier": "A", "name": f"{i}.pdf", "url": "https://x"} for i in range(3)]
    out = asyncio.run(di.send(rows))
    assert out["status"] == "SENT" and out["batches"] == 3
    assert [b["batch"] for b in SENT] == [1, 2, 3] and len({b["snapshot_id"] for b in SENT}) == 1
