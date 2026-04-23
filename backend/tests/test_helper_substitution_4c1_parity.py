"""Phase 3 Step 4c.1 — re-exported helpers substitution parity tests.

Proves that substituting ``compute_ap_normalized_fields`` and
``compute_ap_validation`` in the Step-4b lazy-import block from ``server``
to their authoritative service-module paths is behavior-preserving.

Five classes:

* Class A — Object identity: ``from server import X`` and
  ``from services.<home> import X`` resolve to the SAME function object
  (Python ``is`` check). Strongest possible parity proof.
* Class B — Pure-call parity: both helpers are pure dict→dict functions;
  identical inputs produce identical outputs across both import paths.
* Class C — Source inspection: substitution applied at the correct site;
  ``server.py`` re-exports preserved (not deleted by this step).
* Class D — Moved-body byte-identity held: Step 4b baseline sha256 unchanged.
* Class E — Live surface smoke: OpenAPI unchanged at 858.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import textwrap
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = BACKEND_DIR / "tests" / "fixtures" / "intake_body_move_baseline.json"


# ---------------------------------------------------------------------------
# Class A — Object identity (STRONGEST proof)
# ---------------------------------------------------------------------------
class TestObjectIdentity:
    """from server import X is services.<home>.X — literally the same object."""

    def test_compute_ap_normalized_fields_identity(self):
        from server import compute_ap_normalized_fields as srv_X
        from services.document_intel_helpers import compute_ap_normalized_fields as svc_X
        assert srv_X is svc_X, (
            "compute_ap_normalized_fields drifted between import paths — "
            "server re-export and services.document_intel_helpers resolve "
            "to different objects. Substitution is UNSAFE."
        )

    def test_compute_ap_validation_identity(self):
        from server import compute_ap_validation as srv_X
        from services.ap_computation import compute_ap_validation as svc_X
        assert srv_X is svc_X, (
            "compute_ap_validation drifted between import paths — "
            "server re-export and services.ap_computation resolve to "
            "different objects. Substitution is UNSAFE."
        )


# ---------------------------------------------------------------------------
# Class B — Pure-call parity
# ---------------------------------------------------------------------------
class TestPureCallParity:
    """Both helpers produce identical outputs across both import paths."""

    def test_compute_ap_normalized_fields_call_parity(self):
        from server import compute_ap_normalized_fields as srv_X
        from services.document_intel_helpers import compute_ap_normalized_fields as svc_X

        # Canonical minimal AP-invoice extracted_fields payload.
        extracted = {
            "invoice_number": "INV-2026-00042",
            "invoice_date": "2026-04-15",
            "total_amount": "1,234.56",
            "vendor_name": "ACME Corp",
            "po_number": "PO-998877",
            "currency": "USD",
            "payment_terms": "Net 30",
        }
        srv_out = srv_X(extracted)
        svc_out = svc_X(extracted)
        assert srv_out == svc_out, (
            "compute_ap_normalized_fields produced different output across "
            f"import paths.\n  server: {srv_out}\n  service: {svc_out}"
        )

    def test_compute_ap_validation_call_parity(self):
        from server import compute_ap_validation as srv_X
        from services.ap_computation import compute_ap_validation as svc_X

        # Canonical call args (positional per actual signature).
        canonical_args = (
            "AP_Invoice",        # document_type
            "acme corp",         # vendor_normalized
            "INV-2026-00042",    # invoice_number_clean
            1234.56,             # amount_float
            "PO-998877",         # po_number_clean
            0.92,                # ai_confidence
        )
        srv_out = srv_X(*canonical_args)
        svc_out = svc_X(*canonical_args)
        assert srv_out == svc_out, (
            "compute_ap_validation produced different output across "
            f"import paths.\n  server: {srv_out}\n  service: {svc_out}"
        )

        # Also exercise the possible_duplicate kwarg branch.
        srv_out2 = srv_X(*canonical_args, possible_duplicate=True)
        svc_out2 = svc_X(*canonical_args, possible_duplicate=True)
        assert srv_out2 == svc_out2


# ---------------------------------------------------------------------------
# Class C — Source-inspection guardrail
# ---------------------------------------------------------------------------
class TestSourceInspectionGuardrail:
    """Substitution applied at the correct site; re-exports preserved."""

    @pytest.fixture(scope="class")
    def dh_source(self) -> str:
        return (BACKEND_DIR / "services" / "document_handlers.py").read_text()

    @pytest.fixture(scope="class")
    def server_source(self) -> str:
        return (BACKEND_DIR / "server.py").read_text()

    def _lazy_import_names(self) -> set:
        """Names imported from ``server`` inside intake_document_from_bytes."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                for n in node.body:
                    if isinstance(n, ast.ImportFrom) and n.module == "server":
                        for alias in n.names:
                            names.add(alias.asname or alias.name)
                break
        return names

    def _authoritative_import_names(self) -> dict:
        """Names imported from authoritative service modules inside the function."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        result = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                for n in node.body:
                    if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("services."):
                        for alias in n.names:
                            name = alias.asname or alias.name
                            result[name] = n.module
                break
        return result

    def test_helpers_removed_from_server_import_block(self):
        lazy = self._lazy_import_names()
        assert "compute_ap_normalized_fields" not in lazy, (
            "compute_ap_normalized_fields still imported from server — "
            "Step 4c.1 should have removed it from the lazy-import block."
        )
        assert "compute_ap_validation" not in lazy, (
            "compute_ap_validation still imported from server — "
            "Step 4c.1 should have removed it from the lazy-import block."
        )

    def test_helpers_imported_from_authoritative_homes(self):
        auth = self._authoritative_import_names()
        assert auth.get("compute_ap_normalized_fields") == "services.document_intel_helpers", (
            f"compute_ap_normalized_fields import source: {auth.get('compute_ap_normalized_fields')!r}"
        )
        assert auth.get("compute_ap_validation") == "services.ap_computation", (
            f"compute_ap_validation import source: {auth.get('compute_ap_validation')!r}"
        )

    def test_step_4c1_comment_present(self, dh_source: str):
        assert "Phase 3 Step 4c.1" in dh_source, (
            "Factual Step 4c.1 comment missing — required per signed declaration."
        )

    def test_server_py_reexports_preserved(self, server_source: str):
        """Step 4c.1 must NOT delete the server.py re-exports."""
        assert "from services.document_intel_helpers import compute_ap_normalized_fields" in server_source, (
            "server.py lost its compute_ap_normalized_fields re-export — "
            "Step 4c.1 must preserve it for other callers."
        )
        assert "compute_ap_validation" in server_source, (
            "server.py lost its compute_ap_validation re-export."
        )


# ---------------------------------------------------------------------------
# Class D — Moved-body byte-identity held
# ---------------------------------------------------------------------------
class TestMovedBodyByteIdentityHeld:
    """Step 4b baseline sha256 must still match after Step 4c.1."""

    def _extract_moved_body_source(self) -> str:
        """Return the moved body as dedented source, EXCLUDING the leading
        docstring and EXCLUDING all lazy imports (from server + from services)."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                body = node.body
                # Strip docstring
                if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                    body = body[1:]
                # Strip ALL leading ImportFrom nodes (now includes Step 4c.1 new imports).
                while body and isinstance(body[0], ast.ImportFrom):
                    body = body[1:]
                if not body:
                    return ""
                first, last = body[0], body[-1]
                lines = dh_src.splitlines(keepends=True)
                raw = "".join(lines[first.lineno - 1:last.end_lineno])
                return textwrap.dedent(raw)
        raise LookupError("intake_document_from_bytes not found")

    def test_post_4c1_body_sha256_matches_step_4b_baseline(self):
        baseline = json.loads(BASELINE_PATH.read_text())
        post_body = self._extract_moved_body_source()
        post_sha = hashlib.sha256(post_body.encode("utf-8")).hexdigest()
        assert post_sha == baseline["pre_move_source_sha256"], (
            f"Moved body drifted during Step 4c.1.\n"
            f"  Step 4b baseline sha256: {baseline['pre_move_source_sha256']}\n"
            f"  Post-4c.1 body sha256:   {post_sha}\n"
            "Step 4c.1 must touch only the import block above the body."
        )

    def test_post_4c1_body_line_count_matches_baseline(self):
        baseline = json.loads(BASELINE_PATH.read_text())
        post_body = self._extract_moved_body_source()
        assert len(post_body.splitlines()) == baseline["pre_move_body_line_count"]


# ---------------------------------------------------------------------------
# Class E — Live surface smoke
# ---------------------------------------------------------------------------
class TestLiveSurfaceSmoke:
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
            pytest.skip("No backend reachable")
        import requests
        paths = requests.get(f"{self.BASE_URL}/openapi.json").json().get("paths", {})
        assert len(paths) == 858

    def test_wrapper_still_coroutine_with_signature(self):
        from services.document_handlers import intake_document_from_bytes
        assert inspect.iscoroutinefunction(intake_document_from_bytes)
        sig = inspect.signature(intake_document_from_bytes)
        assert list(sig.parameters.keys()) == [
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        ]
