"""Phase 3 Step 4a — intake caller-rewire parity tests.

Proves that the 6 external callers of ``server._internal_intake_document`` have
been switched to the new canonical seam
``services.document_handlers.intake_document_from_bytes`` without changing any
behavior.

Five classes:

* Class A — Wrapper identity: signature and kwarg-forwarding byte-identical
  to ``server._internal_intake_document``.
* Class B — Per-caller source-code verification: each of the 6 caller files
  imports the new seam and no longer imports the old symbol.
* Class C — Per-ingest-mode kwarg preservation: each caller's kwargs arrive
  at the underlying function unchanged.
* Class D — OpenAPI surface unchanged: live-smoke at localhost:8001.
* Class E — Guardrails: ``server.py::_internal_intake_document`` signature
  byte-stable; no new backward import from server to document_handlers.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# The 6 caller files and the expected new-seam usage
# ---------------------------------------------------------------------------
CALLER_FILES = [
    ("routers/sales_pipeline_demo.py", 1),  # file, expected call count
    ("routers/pilot.py", 1),
    ("services/email_polling_service.py", 2),
    ("services/inside_sales_pilot_service.py", 1),
    ("services/batch_po_splitter.py", 1),
]


# ---------------------------------------------------------------------------
# Class A — Wrapper identity
# ---------------------------------------------------------------------------
class TestWrapperIdentity:
    """intake_document_from_bytes forwards byte-identical kwargs."""

    def test_signature_parameter_list_matches(self):
        from server import _internal_intake_document
        from services.document_handlers import intake_document_from_bytes

        src_sig = inspect.signature(_internal_intake_document)
        new_sig = inspect.signature(intake_document_from_bytes)
        assert list(src_sig.parameters.keys()) == list(new_sig.parameters.keys()), (
            "Wrapper parameter list drifted from _internal_intake_document"
        )

    def test_signature_defaults_match(self):
        from server import _internal_intake_document
        from services.document_handlers import intake_document_from_bytes

        src_sig = inspect.signature(_internal_intake_document)
        new_sig = inspect.signature(intake_document_from_bytes)
        for name in src_sig.parameters:
            assert (
                src_sig.parameters[name].default == new_sig.parameters[name].default
            ), f"default drift on param {name!r}"

    def test_wrapper_forwards_kwargs_byte_identical(self, monkeypatch):
        """Patch server._internal_intake_document; call wrapper; assert forwarded."""
        captured: Dict[str, Any] = {}

        async def _stub(**kwargs):
            captured.update(kwargs)
            return {"document_id": "stub-id", "skipped_duplicate": False}

        import server as server_module
        monkeypatch.setattr(server_module, "_internal_intake_document", _stub)

        from services.document_handlers import intake_document_from_bytes

        result = asyncio.run(intake_document_from_bytes(
            file_content=b"abc",
            filename="test.pdf",
            content_type="application/pdf",
            source="demo_pipeline",
            sender="s@example.com",
            subject="hi",
            email_id="msg-1",
            mailbox_category="Sales",
        ))

        assert result == {"document_id": "stub-id", "skipped_duplicate": False}
        assert captured == {
            "file_content": b"abc",
            "filename": "test.pdf",
            "content_type": "application/pdf",
            "source": "demo_pipeline",
            "sender": "s@example.com",
            "subject": "hi",
            "email_id": "msg-1",
            "mailbox_category": "Sales",
        }

    def test_wrapper_uses_source_default_when_omitted(self, monkeypatch):
        captured: Dict[str, Any] = {}

        async def _stub(**kwargs):
            captured.update(kwargs)
            return {}

        import server as server_module
        monkeypatch.setattr(server_module, "_internal_intake_document", _stub)

        from services.document_handlers import intake_document_from_bytes

        asyncio.run(intake_document_from_bytes(
            file_content=b"x", filename="f", content_type="application/pdf",
        ))
        # Default for source must match server._internal_intake_document default.
        assert captured["source"] == "email_poll"
        # Optional kwargs must forward as None.
        assert captured["sender"] is None
        assert captured["subject"] is None
        assert captured["email_id"] is None
        assert captured["mailbox_category"] is None


# ---------------------------------------------------------------------------
# Class B — Per-caller source-code verification
# ---------------------------------------------------------------------------
class TestCallerSourceRewire:
    """Each caller imports the new seam; old import is gone; call count matches."""

    @pytest.mark.parametrize("rel_path,expected_calls", CALLER_FILES)
    def test_caller_uses_new_seam(self, rel_path: str, expected_calls: int):
        src = (BACKEND_DIR / rel_path).read_text()

        # New seam imported
        assert "from services.document_handlers import intake_document_from_bytes" in src, (
            f"{rel_path}: missing new-seam import"
        )

        # Old direct `from server import _internal_intake_document` must be gone.
        assert "from server import _internal_intake_document" not in src, (
            f"{rel_path}: old server-direct import still present"
        )

        # Expected number of actual call sites to the new seam (excludes string
        # literals / comments by looking only at `await ...(` usage).
        call_count = src.count("await intake_document_from_bytes(")
        assert call_count == expected_calls, (
            f"{rel_path}: expected {expected_calls} new-seam call(s), got {call_count}"
        )

        # Ensure no actual executable call to the old symbol remains (the
        # batch_po_splitter header docstring mentions the name in prose —
        # that is OK; a live call would look like ``_internal_intake_document(``).
        exec_call_count = src.count("await _internal_intake_document(")
        assert exec_call_count == 0, (
            f"{rel_path}: still has {exec_call_count} live call(s) to _internal_intake_document"
        )


# ---------------------------------------------------------------------------
# Class C — Per-ingest-mode kwarg preservation
# ---------------------------------------------------------------------------
# Each tuple: (ingest mode name, kwargs the caller originally passed).
PER_CALLER_KWARGS = [
    ("demo_pipeline", {
        "file_content": b"pdf-bytes",
        "filename": "demo.pdf",
        "content_type": "application/pdf",
        "source": "demo_pipeline",
        "sender": "scenario@example.com",
        "subject": "PO 123 from ACME",
        "email_id": "demo-abc12345",
        "mailbox_category": "Sales",
    }),
    ("pilot_email", {
        "file_content": b"pilot-bytes",
        "filename": "att.pdf",
        "content_type": "application/pdf",
        "source": "email",
        "sender": "vendor@example.com",
        "subject": "Invoice",
        "email_id": "internet-msg-1",
        "mailbox_category": None,  # pilot.py does not pass mailbox_category
    }),
    ("ap_email_poll", {
        "file_content": b"ap-bytes",
        "filename": "ap.pdf",
        "content_type": "application/pdf",
        "source": "email_poll",
        "sender": "ap@example.com",
        "subject": "AP invoice",
        "email_id": "msg-ap-1",
        "mailbox_category": "AP",
    }),
    ("sales_email_poll", {
        "file_content": b"sales-bytes",
        "filename": "sales.pdf",
        "content_type": "application/pdf",
        "source": "email",
        "sender": "sales@example.com",
        "subject": "Sales doc",
        "email_id": "msg-sales-1",
        "mailbox_category": "SALES",
    }),
    ("inside_sales_pilot", {
        "file_content": b"isp-bytes",
        "filename": "isp.pdf",
        "content_type": "application/pdf",
        "source": "inside_sales_pilot",
        "sender": "isp@example.com",
        "subject": "Pilot",
        "email_id": "msg-isp-1",
        "mailbox_category": "SALES",
    }),
    ("batch_po_splitter_child", {
        "file_content": b"child-pdf",
        "filename": "child.pdf",
        "content_type": "application/pdf",
        "source": "email_poll",  # propagated from parent
        "sender": "vendor@example.com",
        "subject": "Parent [Pages 1-2/3]",
        "email_id": "batch-abcdef12-child1",
        "mailbox_category": None,
    }),
]


class TestPerIngestModeKwargPreservation:
    """Each ingest-mode kwarg bundle arrives at the underlying function unchanged."""

    @pytest.mark.parametrize("mode,kwargs", PER_CALLER_KWARGS)
    def test_kwargs_arrive_unchanged(self, monkeypatch, mode: str, kwargs: Dict[str, Any]):
        captured: Dict[str, Any] = {}

        async def _stub(**recv):
            captured.update(recv)
            return {"document_id": f"{mode}-doc"}

        import server as server_module
        monkeypatch.setattr(server_module, "_internal_intake_document", _stub)

        from services.document_handlers import intake_document_from_bytes
        result = asyncio.run(intake_document_from_bytes(**kwargs))

        assert result["document_id"] == f"{mode}-doc"
        # All 8 declared params must be present and equal to the input.
        for key in (
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        ):
            assert captured[key] == kwargs.get(key), (
                f"[{mode}] kwarg drift on {key!r}: sent={kwargs.get(key)!r} "
                f"recv={captured.get(key)!r}"
            )


# ---------------------------------------------------------------------------
# Class D — OpenAPI surface unchanged
# ---------------------------------------------------------------------------
class TestLiveOpenApiUnchanged:
    BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

    def _reachable(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.BASE_URL}/openapi.json", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def test_openapi_path_count_858(self):
        if not self._reachable():
            pytest.skip("No live backend reachable")
        import requests
        paths = requests.get(f"{self.BASE_URL}/openapi.json").json().get("paths", {})
        assert len(paths) == 858, (
            f"OpenAPI path count changed: {len(paths)} (expected 858). "
            "Step 4a must not add or remove any HTTP routes."
        )

    def test_intake_route_still_registered(self):
        if not self._reachable():
            pytest.skip("No live backend reachable")
        import requests
        paths = requests.get(f"{self.BASE_URL}/openapi.json").json().get("paths", {})
        assert "/api/documents/intake" in paths


# ---------------------------------------------------------------------------
# Class E — Guardrails
# ---------------------------------------------------------------------------
class TestGuardrails:
    """server.py _internal_intake_document untouched; no backward import."""

    def test_internal_intake_document_signature_unchanged(self):
        from server import _internal_intake_document
        sig = inspect.signature(_internal_intake_document)
        param_names = list(sig.parameters.keys())
        assert param_names == [
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        ]
        # Defaults preserved.
        assert sig.parameters["source"].default == "email_poll"
        for opt in ("sender", "subject", "email_id", "mailbox_category"):
            assert sig.parameters[opt].default is None

    def test_server_py_does_not_import_wrapper(self):
        server_src = (BACKEND_DIR / "server.py").read_text()
        # No new module-scope dependency server.py → document_handlers for this seam.
        assert "from services.document_handlers import intake_document_from_bytes" not in server_src, (
            "Step 4a must not introduce a backward import from server.py to "
            "services.document_handlers — would create circular-import risk "
            "since the wrapper lazy-imports _internal_intake_document from server."
        )

    def test_internal_intake_is_still_called_internally_from_server(self):
        """server.py::intake_document (HTTP route at ~line 3670) still calls
        _internal_intake_document in-file — moving that is Step 4b scope."""
        server_src = (BACKEND_DIR / "server.py").read_text()
        # At least one remaining internal dispatch to _internal_intake_document.
        assert "_internal_intake_document(" in server_src, (
            "server.py lost its internal dispatch to _internal_intake_document "
            "— Step 4a should not touch the function body or internal callers."
        )

    def test_document_handlers_wrapper_is_thin_pass_through(self):
        from services.document_handlers import intake_document_from_bytes
        src = inspect.getsource(intake_document_from_bytes)
        # Must contain exactly the forwarding call.
        assert "from server import _internal_intake_document" in src
        assert "return await _internal_intake_document(" in src
        # Must NOT contain prohibited additions per signed guardrail.
        forbidden = [
            # logging additions
            "logger.info(", "logger.warning(", "logger.error(",
            # DB writes
            "db.hub_documents", "db.workflow_events", "insert_one", "update_one",
            # Metrics / telemetry / branching
            "counter", "metric", "shadow_mode", "if source ==", "if source !=",
        ]
        for needle in forbidden:
            assert needle not in src, (
                f"Wrapper has forbidden content {needle!r} — "
                "Step 4a guardrail: thin seam only."
            )

    def test_wrapper_body_is_small(self):
        """Sanity: wrapper body must be small (<= ~25 lines of actual code)."""
        from services.document_handlers import intake_document_from_bytes
        src = inspect.getsource(intake_document_from_bytes)
        code_lines = [
            ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
            and not ln.strip().startswith('"')
        ]
        assert len(code_lines) <= 25, (
            f"Wrapper grew to {len(code_lines)} code lines — "
            "Step 4a guardrail: thin seam only."
        )
