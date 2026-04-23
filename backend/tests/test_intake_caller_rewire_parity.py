"""Phase 3 Step 4a — intake caller-rewire parity tests.

ORIGINAL PURPOSE (2026-04-23, Step 4a): proved the 6 external callers were
switched to a thin ``intake_document_from_bytes`` seam that lazy-imported
``server._internal_intake_document``.

POST-STEP-4b UPDATE (2026-04-23): Step 4b moved the full function body into
``intake_document_from_bytes`` (replacing the thin seam). The "thin wrapper"
assertions in this file are now architecturally stale. The assertions that
remain valid — all 6 callers use the seam, no production code still imports
``server._internal_intake_document``, OpenAPI surface unchanged — are kept.
Per-ingest-mode kwarg preservation is now covered end-to-end by the moved
body itself (there's nothing for the wrapper to forward because it IS the
implementation), so those parametrized tests are consolidated into a single
import-and-signature check.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent

CALLER_FILES = [
    ("routers/sales_pipeline_demo.py", 1),
    ("routers/pilot.py", 1),
    ("services/email_polling_service.py", 2),
    ("services/inside_sales_pilot_service.py", 1),
    ("services/batch_po_splitter.py", 1),
]


# ---------------------------------------------------------------------------
# Class A — Seam signature stability (post-Step-4b: the seam IS the body)
# ---------------------------------------------------------------------------
class TestSeamSignatureStability:
    """intake_document_from_bytes keeps the Step-4a signature contract."""

    def test_signature_parameter_list(self):
        from services.document_handlers import intake_document_from_bytes
        sig = inspect.signature(intake_document_from_bytes)
        assert list(sig.parameters.keys()) == [
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        ]

    def test_signature_defaults(self):
        from services.document_handlers import intake_document_from_bytes
        sig = inspect.signature(intake_document_from_bytes)
        assert sig.parameters["source"].default == "email_poll"
        for opt in ("sender", "subject", "email_id", "mailbox_category"):
            assert sig.parameters[opt].default is None

    def test_is_coroutine_function(self):
        from services.document_handlers import intake_document_from_bytes
        assert inspect.iscoroutinefunction(intake_document_from_bytes)


# ---------------------------------------------------------------------------
# Class B — Per-caller source-code verification (unchanged validity post-4b)
# ---------------------------------------------------------------------------
class TestCallerSourceRewire:
    """Each caller imports the new seam; old import is gone; call count matches."""

    @pytest.mark.parametrize("rel_path,expected_calls", CALLER_FILES)
    def test_caller_uses_new_seam(self, rel_path: str, expected_calls: int):
        src = (BACKEND_DIR / rel_path).read_text()

        assert "from services.document_handlers import intake_document_from_bytes" in src, (
            f"{rel_path}: missing new-seam import"
        )

        assert "from server import _internal_intake_document" not in src, (
            f"{rel_path}: old server-direct import still present"
        )

        call_count = src.count("await intake_document_from_bytes(")
        assert call_count == expected_calls, (
            f"{rel_path}: expected {expected_calls} new-seam call(s), got {call_count}"
        )

        exec_call_count = src.count("await _internal_intake_document(")
        assert exec_call_count == 0, (
            f"{rel_path}: still has {exec_call_count} live call(s) to _internal_intake_document"
        )


# ---------------------------------------------------------------------------
# Class C — Live surface unchanged
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
        assert len(paths) == 858

    def test_intake_route_still_registered(self):
        if not self._reachable():
            pytest.skip("No live backend reachable")
        import requests
        paths = requests.get(f"{self.BASE_URL}/openapi.json").json().get("paths", {})
        assert "/api/documents/intake" in paths


# ---------------------------------------------------------------------------
# Class D — Guardrails (updated for post-Step-4b reality)
# ---------------------------------------------------------------------------
class TestGuardrails:
    """server.py no longer owns _internal_intake_document; no circular import."""

    def test_internal_intake_document_removed_from_server(self):
        """Step 4b deleted the function from server.py."""
        server_src = (BACKEND_DIR / "server.py").read_text()
        assert "async def _internal_intake_document(" not in server_src, (
            "Step 4b should have deleted _internal_intake_document from server.py"
        )

    def test_no_module_top_backward_import(self):
        """document_handlers.py must not module-top-import _internal_intake_document."""
        import ast
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "server":
                names = [a.name for a in node.names]
                assert "_internal_intake_document" not in names, (
                    "module-top import from server of _internal_intake_document — "
                    "Step 4b should have removed this"
                )

    def test_server_references_only_via_lazy_imports(self):
        """server.py has no remaining live call to _internal_intake_document."""
        server_src = (BACKEND_DIR / "server.py").read_text()
        assert "_internal_intake_document(" not in server_src, (
            "server.py contains a live call to _internal_intake_document — "
            "function is gone, callers must use intake_document_from_bytes"
        )

    def test_move_marker_comment_present(self):
        """server.py has the factual move marker for future readers."""
        server_src = (BACKEND_DIR / "server.py").read_text()
        assert (
            "_internal_intake_document moved to "
            "services/document_handlers.py::intake_document_from_bytes"
        ) in server_src
