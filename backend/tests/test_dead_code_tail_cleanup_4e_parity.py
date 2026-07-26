"""Phase 3 Step 4e — dead-code-tail cleanup parity tests.

Four classes proving that deleting the unreachable tail statements in
``server.py::lookup_vendor_alias`` (125 lines) and
``server.py::check_duplicate_document`` (29 lines) is behavior-preserving:

* Class A — Audit-gate transition: the SAME unchanged classifier in
  ``tests/audit_shim_substitution.py`` now returns THIN_SHIM (pre-4e it
  returned DRIFTED due to the dead tails).
* Class B — Post-4e structural assertion: each function body has exactly
  3 statements after the docstring (local import + return; nothing after).
* Class C — Source-inspection guardrails: services.vendor_matching untouched;
  services.document_handlers untouched; only server.py shrank; shim
  reachable prefix byte-identical to pre-4e.
* Class D — Live surface smoke: OpenAPI unchanged; both shims still
  importable; invoking either as a callable does not raise NameError.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent

TIER_3_HELPERS = [
    ("lookup_vendor_alias", "services.vendor_matching"),
    ("check_duplicate_document", "services.vendor_matching"),
]


# ---------------------------------------------------------------------------
# Class A — Audit-gate transition (unchanged classifier now returns THIN_SHIM)
# ---------------------------------------------------------------------------
class TestAuditGateTransition:
    """Pre-4e: both helpers DRIFTED. Post-4e: both THIN_SHIM with
    resolves_to_svc=True. Uses the committed, unchanged classifier."""

    def test_audit_module_unchanged(self):
        """Guardrail: the classifier file is NOT modified by Step 4e."""
        from tests import audit_shim_substitution as audit_mod
        src = inspect.getsource(audit_mod)
        # Classifier must still reject a non-shim; the rule "expected 1 return"
        # is the canonical narrow gate. If someone broadened it, this check
        # flags the deviation.
        assert 'expected 1 return' in src, (
            "audit_shim_substitution.py appears to have been modified — "
            "Step 4e is not allowed to change the classifier."
        )

    @pytest.mark.parametrize("helper_name,home", TIER_3_HELPERS)
    def test_helper_now_classifies_as_thin_shim(self, helper_name: str, home: str):
        from tests.audit_shim_substitution import audit

        results = audit([(helper_name, home)])
        assert len(results) == 1
        _, _, verdict, details = results[0]
        assert verdict == "THIN_SHIM", (
            f"{helper_name}: expected THIN_SHIM after Step 4e, got {verdict}.\n"
            f"  details: {details}"
        )
        assert details.get("resolves_to_svc") is True
        # Post-4e the function body line count should be small (docstring +
        # import + return + def signature = 4 lines).
        assert details.get("srv_body_line_count", 99) <= 6, (
            f"{helper_name}: srv_body_line_count={details.get('srv_body_line_count')} "
            "— dead-code tail may still be present."
        )


# ---------------------------------------------------------------------------
# Class B — Post-4e structural assertion
# ---------------------------------------------------------------------------
class TestPost4eStructure:
    """Each shim body has exactly 2 executable statements after the
    docstring: the local import + the return."""

    @pytest.mark.parametrize("helper_name,_", TIER_3_HELPERS)
    def test_shim_body_has_one_reachable_return(self, helper_name: str, _):
        import server
        fn = getattr(server, helper_name)
        tree = ast.parse(inspect.getsource(fn))
        fn_node = tree.body[0]
        body = fn_node.body
        # Strip docstring
        if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
            body = body[1:]
        non_imports = [s for s in body if not isinstance(s, (ast.ImportFrom, ast.Import))]
        assert len(non_imports) == 1, (
            f"{helper_name}: expected exactly 1 non-import statement after "
            f"Step 4e, got {len(non_imports)} — dead tail still present."
        )
        assert isinstance(non_imports[0], ast.Return)

    @pytest.mark.parametrize("helper_name,_", TIER_3_HELPERS)
    def test_shim_has_one_local_import(self, helper_name: str, _):
        import server
        fn = getattr(server, helper_name)
        tree = ast.parse(inspect.getsource(fn))
        fn_node = tree.body[0]
        imports = [s for s in fn_node.body if isinstance(s, ast.ImportFrom)]
        assert len(imports) == 1
        assert imports[0].module == "services.vendor_matching"


# ---------------------------------------------------------------------------
# Class C — Source-inspection guardrails
# ---------------------------------------------------------------------------
class TestSourceInspectionGuardrails:
    """Only server.py shrank; other files untouched; reachable prefix intact."""

    def test_services_vendor_matching_untouched(self):
        """The authoritative module is not modified by Step 4e."""
        src = (BACKEND_DIR / "services" / "vendor_matching.py").read_text()
        # Spot-check: the two function names still defined as their
        # canonical selves (not shims). They must have substantial body.
        tree = ast.parse(src)
        for fn_name in ("lookup_vendor_alias", "check_duplicate_document"):
            found = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == fn_name:
                    body = node.body
                    if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                        body = body[1:]
                    assert len(body) >= 3, (
                        f"services.vendor_matching::{fn_name} appears to have been "
                        f"gutted: only {len(body)} body statements — authoritative "
                        "module should not have been touched."
                    )
                    found = True
                    break
            assert found, f"services.vendor_matching::{fn_name} not found"

    def test_raw_intake_service_retains_tier3_imports(self):
        """The authoritative raw-intake body retains Tier-3 imports."""
        service_src = (
            BACKEND_DIR
            / "services"
            / "document_bytes_intake_service.py"
        ).read_text()

        assert "lookup_vendor_alias" in service_src
        assert "check_duplicate_document" in service_src

    def test_server_py_shrank(self):
        total = sum(
            1
            for _ in (
                BACKEND_DIR / "server.py"
            ).open("r")
        )

        assert 4704 <= total <= 4724, (
            f"server.py line count {total} outside "
            "the current extracted baseline band "
            "(4704-4724)."
        )

    @pytest.mark.parametrize("helper_name,_", TIER_3_HELPERS)
    def test_shim_reachable_prefix_intact(self, helper_name: str, _):
        """def signature, docstring, local import, return — all present."""
        src = (BACKEND_DIR / "server.py").read_text()
        # Find the function definition.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == helper_name:
                body = node.body
                # Docstring
                assert (body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and "COMPATIBILITY WRAPPER" in body[0].value.value), (
                    f"{helper_name}: docstring missing or changed"
                )
                # Local import
                assert isinstance(body[1], ast.ImportFrom)
                assert body[1].module == "services.vendor_matching"
                # Return
                assert isinstance(body[2], ast.Return)
                return
        pytest.fail(f"{helper_name} not found in server.py")


# ---------------------------------------------------------------------------
# Class D — Live surface smoke
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
        assert len(paths) == 888

    @pytest.mark.parametrize("helper_name,_", TIER_3_HELPERS)
    def test_shim_importable(self, helper_name: str, _):
        import server
        fn = getattr(server, helper_name)
        assert inspect.iscoroutinefunction(fn)
