"""Tests for ap_smoke_walk_dom_check storage-state plumbing.

Read-only, fixture-driven. No real Playwright browser is launched; we
test the pure helpers (storage-state validation, context-kwargs
construction, login-wall short-circuit) and the CLI argument
threading via a fake Playwright module.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import ap_smoke_walk_dom_check as dom


# ---------------------------------------------------------------------------
# build_browser_context_kwargs
# ---------------------------------------------------------------------------

def test_build_kwargs_omits_storage_state_when_path_missing():
    assert dom.build_browser_context_kwargs(None) == {}
    assert dom.build_browser_context_kwargs("") == {}


def test_build_kwargs_threads_storage_state_path(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    kwargs = dom.build_browser_context_kwargs(str(state_path))
    assert kwargs == {"storage_state": str(state_path)}


# ---------------------------------------------------------------------------
# validate_storage_state_path
# ---------------------------------------------------------------------------

def test_validate_storage_state_returns_none_when_unset():
    assert dom.validate_storage_state_path(None) is None
    assert dom.validate_storage_state_path("") is None


def test_validate_storage_state_raises_when_missing(tmp_path: Path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError) as excinfo:
        dom.validate_storage_state_path(str(missing))
    assert "missing file" in str(excinfo.value)
    assert "capture_hub_storage_state" in str(excinfo.value)


def test_validate_storage_state_raises_on_bad_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        dom.validate_storage_state_path(str(bad))
    assert "not valid JSON" in str(excinfo.value)


def test_validate_storage_state_accepts_valid_file(tmp_path: Path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"cookies": [], "origins": []}),
                    encoding="utf-8")
    out = dom.validate_storage_state_path(str(good))
    assert out == str(good)


# ---------------------------------------------------------------------------
# Login-wall short-circuit (check_doc) — uses fake page object
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _FakePage:
    """Minimal page double for check_doc; returns a password input."""

    def __init__(self, *, password_count: int) -> None:
        self._password_count = password_count
        self.url = ""

    def goto(self, url: str, wait_until: str = "", timeout: int = 0):
        self.url = url
        return _FakeResponse(200)

    def locator(self, selector: str) -> _FakeLocator:
        if selector == "input[type=password]":
            return _FakeLocator(self._password_count)
        return _FakeLocator(0)

    def inner_text(self, selector: str, timeout: int = 0) -> str:
        return ""

    def screenshot(self, **_: Any) -> None:
        pass


def _row(**overrides: Any) -> Dict[str, str]:
    base = {
        "priority": "P1",
        "test_doc_category": "clean_ap_invoice",
        "hub_doc_id": "doc-1",
        "file_name": "Invoice.pdf",
        "hub_document_url": "/documents/doc-1",
    }
    base.update({k: str(v) for k, v in overrides.items()})
    return base


def test_check_doc_login_wall_explicit_message_mentions_storage_state():
    page = _FakePage(password_count=1)
    out = dom.check_doc(
        page, _row(), "http://hub.example/documents/doc-1",
        timeout_ms=1000, is_ap_invoice=True, screenshot_dir=None,
    )
    assert out["page_loaded"] == "no"
    assert out["overall_pass"] == "no"
    assert "login_redirect_detected" in out["errors"]
    # The new explicit guidance must be present so operators know how
    # to recover. Failing this means the script silently leaves them
    # guessing.
    assert "--storage-state-path" in out["errors"]
    assert "capture_hub_storage_state" in out["errors"]


# ---------------------------------------------------------------------------
# main(): --storage-state-path is threaded into browser.new_context
# ---------------------------------------------------------------------------

class _FakeBrowser:
    def __init__(self, recorder: Dict[str, Any]) -> None:
        self.recorder = recorder

    def new_context(self, **kwargs: Any):
        self.recorder["new_context_kwargs"] = kwargs
        return _FakeContext()

    def close(self) -> None:
        pass


class _FakeContext:
    def new_page(self):
        return _FakePage(password_count=0)

    def close(self) -> None:
        pass


class _FakeChromium:
    def __init__(self, recorder: Dict[str, Any]) -> None:
        self.recorder = recorder

    def launch(self, **kwargs: Any) -> _FakeBrowser:
        self.recorder["launch_kwargs"] = kwargs
        return _FakeBrowser(self.recorder)


class _FakePlaywright:
    def __init__(self, recorder: Dict[str, Any]) -> None:
        self.chromium = _FakeChromium(recorder)


class _FakeSyncPlaywrightCtx:
    def __init__(self, recorder: Dict[str, Any]) -> None:
        self._recorder = recorder

    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright(self._recorder)

    def __exit__(self, *_: Any) -> bool:
        return False


def _install_fake_playwright(monkeypatch, recorder: Dict[str, Any]) -> None:
    """Inject a fake playwright.sync_api so dom.main() runs offline."""
    fake_module = types.ModuleType("playwright")
    fake_sync_api = types.ModuleType("playwright.sync_api")

    def _sync_playwright() -> _FakeSyncPlaywrightCtx:
        return _FakeSyncPlaywrightCtx(recorder)

    fake_sync_api.sync_playwright = _sync_playwright  # type: ignore[attr-defined]
    fake_module.sync_api = fake_sync_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", fake_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    # Bypass the import-or-die guard.
    monkeypatch.setattr(dom, "_import_playwright_or_die", lambda: None)


def _write_minimal_smoke_csv(path: Path) -> None:
    fieldnames = list(_row().keys())
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow(_row())


def test_main_threads_storage_state_path_into_browser_context(
        tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "smoke.csv"
    _write_minimal_smoke_csv(csv_path)

    state_path = tmp_path / "hub_storage_state.json"
    state_path.write_text(
        json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

    out_csv = tmp_path / "results.csv"
    out_md = tmp_path / "summary.md"

    recorder: Dict[str, Any] = {}
    _install_fake_playwright(monkeypatch, recorder)

    rc = dom.main([
        "--hub-origin", "http://hub.example",
        "--input-csv", str(csv_path),
        "--out-csv", str(out_csv),
        "--out-summary-md", str(out_md),
        "--storage-state-path", str(state_path),
    ])
    # 0 (all pass) or 4 (some failed) are both acceptable here — we
    # only care that the kwargs threaded through correctly.
    assert rc in (0, 4)
    assert recorder.get("new_context_kwargs") == {
        "storage_state": str(state_path)}


def test_main_omits_storage_state_when_flag_unset(
        tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "smoke.csv"
    _write_minimal_smoke_csv(csv_path)

    out_csv = tmp_path / "results.csv"
    out_md = tmp_path / "summary.md"

    recorder: Dict[str, Any] = {}
    _install_fake_playwright(monkeypatch, recorder)

    rc = dom.main([
        "--hub-origin", "http://hub.example",
        "--input-csv", str(csv_path),
        "--out-csv", str(out_csv),
        "--out-summary-md", str(out_md),
    ])
    assert rc in (0, 4)
    assert recorder.get("new_context_kwargs") == {}


def test_main_fails_clearly_when_storage_state_missing(
        tmp_path: Path, monkeypatch, capsys):
    csv_path = tmp_path / "smoke.csv"
    _write_minimal_smoke_csv(csv_path)

    recorder: Dict[str, Any] = {}
    _install_fake_playwright(monkeypatch, recorder)

    rc = dom.main([
        "--hub-origin", "http://hub.example",
        "--input-csv", str(csv_path),
        "--out-csv", str(tmp_path / "r.csv"),
        "--out-summary-md", str(tmp_path / "s.md"),
        "--storage-state-path", str(tmp_path / "does_not_exist.json"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "missing file" in err
    assert "capture_hub_storage_state" in err
    # Browser should never have been launched.
    assert "new_context_kwargs" not in recorder
