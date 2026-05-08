"""Tests for sharepoint_body_fetcher (offline, deterministic).

No real Graph calls. The fetcher is constructor-injected with a token
provider and an HTTP client factory; tests pass fakes that return
canned bytes / canned status codes / canned exceptions.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from scripts import sharepoint_body_fetcher as sbf


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content


class _FakeClient:
    """Context-manager mock that records calls and returns canned responses."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: List[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, headers=None, follow_redirects=False):
        self.calls.append(url)
        if self.exc is not None:
            raise self.exc
        return self.response


def _client_factory(client: _FakeClient):
    def _f(_timeout: float):
        return client
    return _f


def _row(url: str = "https://example.sharepoint.com/sites/x/Documents/y.pdf"
         ) -> Dict[str, str]:
    return {"square9_web_url": url}


def _make_pdf_with_blank_page() -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_url_to_share_id_uses_graph_base64url_encoding():
    sid = sbf.url_to_share_id("https://example.com/x.pdf")
    assert sid.startswith("u!")
    # No padding, no "/" or "+" left over.
    assert "=" not in sid
    assert "/" not in sid[2:]
    assert "+" not in sid[2:]


def test_cache_key_is_stable_per_url():
    a = sbf.cache_key_for("https://x/y.pdf")
    b = sbf.cache_key_for("https://x/y.pdf")
    c = sbf.cache_key_for("https://x/y2.pdf")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


def test_classify_bytes_image_or_tiff_is_ocr_required():
    text, status = sbf.classify_bytes(
        b"any binary",
        "https://x.sharepoint.com/sites/x/scan.tiff",
    )
    assert (text, status) == ("", sbf.STATUS_OCR)


def test_classify_bytes_image_with_query_string():
    text, status = sbf.classify_bytes(
        b"any binary",
        "https://x.sharepoint.com/sites/x/scan.PNG?web=1",
    )
    assert (text, status) == ("", sbf.STATUS_OCR)


def test_classify_bytes_pdf_with_no_extractable_text_is_ocr_required():
    pdf = _make_pdf_with_blank_page()
    text, status = sbf.classify_bytes(
        pdf, "https://x.sharepoint.com/sites/x/scanned.pdf")
    assert text == ""
    assert status == sbf.STATUS_OCR


def test_classify_bytes_pdf_with_long_text_is_ok(monkeypatch):
    fake_text = "Acme Corp Invoice INV-12345 Total $1,500.00 " * 10
    monkeypatch.setattr(sbf, "_extract_pdf_text", lambda _data: fake_text)
    text, status = sbf.classify_bytes(
        b"%PDF-1.4\nfake", "https://x.sharepoint.com/sites/x/x.pdf")
    assert status == sbf.STATUS_OK
    assert "Invoice" in text


# ---------------------------------------------------------------------------
# Fetcher behavior — happy path
# ---------------------------------------------------------------------------

def test_successful_pdf_text_extraction_returns_ok(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Fake bytes; classify_bytes monkeypatched to bypass pypdf decoding
    # (pure-extractor logic is exercised by classify_bytes tests above).
    fake_bytes = b"%PDF-1.4 fake content"
    fake_text = "Acme Corp Invoice INV-12345 Total $1,500.00 " * 5
    monkeypatch.setattr(sbf, "_extract_pdf_text",
                        lambda _data: fake_text)
    client = _FakeClient(response=_FakeResponse(200, fake_bytes))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert status == sbf.STATUS_OK
    assert "INV-12345" in text
    assert len(client.calls) == 1


def test_empty_text_pdf_returns_ocr_required(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sbf, "_extract_pdf_text", lambda _data: "   \n  ")
    client = _FakeClient(response=_FakeResponse(200, b"%PDF-1.4 fake"))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert (text, status) == ("", sbf.STATUS_OCR)


def test_image_or_tiff_extension_short_circuits_to_ocr(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Even when the Graph fetch succeeds, image/tiff URLs return ocr_required.
    extract_calls = {"n": 0}

    def _spy(_data):
        extract_calls["n"] += 1
        return ""
    monkeypatch.setattr(sbf, "_extract_pdf_text", _spy)
    client = _FakeClient(response=_FakeResponse(200, b"any"))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row(
        "https://x.sharepoint.com/sites/x/Documents/scan.tiff"))
    assert (text, status) == ("", sbf.STATUS_OCR)
    # Image suffix short-circuited; pypdf was never invoked.
    assert extract_calls["n"] == 0


# ---------------------------------------------------------------------------
# Fetcher behavior — error paths
# ---------------------------------------------------------------------------

def test_missing_or_empty_web_url_returns_no_access(tmp_path: Path):
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(_FakeClient()),
        cache_dir=str(tmp_path / "cache"),
    )
    assert fetcher({"square9_web_url": ""}) == ("", sbf.STATUS_NO_ACCESS)
    assert fetcher({}) == ("", sbf.STATUS_NO_ACCESS)


def test_404_returns_no_access_and_does_not_raise(tmp_path: Path):
    client = _FakeClient(response=_FakeResponse(404, b""))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert (text, status) == ("", sbf.STATUS_NO_ACCESS)


def test_403_returns_no_access_and_does_not_raise(tmp_path: Path):
    client = _FakeClient(response=_FakeResponse(403, b""))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert (text, status) == ("", sbf.STATUS_NO_ACCESS)


def test_timeout_returns_no_access_and_does_not_raise(tmp_path: Path):
    class _FakeTimeout(Exception):
        pass
    client = _FakeClient(exc=_FakeTimeout("timed out"))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert (text, status) == ("", sbf.STATUS_NO_ACCESS)


def test_token_acquisition_failure_returns_no_access(tmp_path: Path):
    def _bad_token():
        raise RuntimeError("creds missing")
    fetcher = sbf.GraphBodyFetcher(
        token_provider=_bad_token,
        http_client_factory=_client_factory(_FakeClient()),
        cache_dir=str(tmp_path / "cache"),
    )
    text, status = fetcher(_row())
    assert (text, status) == ("", sbf.STATUS_NO_ACCESS)


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

def test_cache_reuses_bytes_on_second_call_and_does_not_refetch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_text = "Invoice INV-1 Total $9.99 " * 5
    monkeypatch.setattr(sbf, "_extract_pdf_text", lambda _d: fake_text)
    client = _FakeClient(response=_FakeResponse(200, b"%PDF cached"))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
    )
    row = _row()
    fetcher(row)
    fetcher(row)
    # Network only invoked once.
    assert len(client.calls) == 1
    # Cache file exists.
    cache_path = os.path.join(
        str(tmp_path / "cache"),
        sbf.cache_key_for(row["square9_web_url"]) + ".bin")
    assert os.path.exists(cache_path)


def test_no_cache_flag_forces_refetch_each_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sbf, "_extract_pdf_text",
                        lambda _d: "Invoice INV-1 " * 10)
    client = _FakeClient(response=_FakeResponse(200, b"%PDF"))
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(tmp_path / "cache"),
        no_cache=True,
    )
    row = _row()
    fetcher(row)
    fetcher(row)
    fetcher(row)
    assert len(client.calls) == 3


def test_cache_write_failure_does_not_crash(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sbf, "_extract_pdf_text",
                        lambda _d: "Invoice " * 50)
    client = _FakeClient(response=_FakeResponse(200, b"%PDF"))

    # Point cache at a path that cannot be created (an existing file).
    bad_dir = tmp_path / "not_a_dir"
    bad_dir.write_text("hello")  # exists as a file, not a dir
    fetcher = sbf.GraphBodyFetcher(
        token_provider=lambda: "TKN",
        http_client_factory=_client_factory(client),
        cache_dir=str(bad_dir),
    )
    text, status = fetcher(_row())
    # Cache failure is swallowed; the fetch result is still ok.
    assert status == sbf.STATUS_OK
