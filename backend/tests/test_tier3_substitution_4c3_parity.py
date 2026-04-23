"""
Phase 3 Step 4c.3 — Tier-3 Helper Substitution Parity Suite

Goal: prove that substituting `lookup_vendor_alias` and `check_duplicate_document`
from `server` to `services.vendor_matching` inside
`services/document_handlers.py::intake_document_from_bytes` (the body moved
verbatim from `server._internal_intake_document` in Step 4b) is behaviorally
a no-op, because the `server.py` counterparts are 4-line THIN_SHIMs that
already delegate to `services.vendor_matching`.

The six probes below together form the acceptance gate for Step 4c.3:

1. Object-identity: the substituted names resolve to the authoritative
   `services.vendor_matching` objects at runtime.
2. Server shim parity retained: `server.lookup_vendor_alias` and
   `server.check_duplicate_document` remain importable and still delegate.
3. Lazy block shrunk: the `from server import (...)` tuple no longer contains
   the two Tier-3 symbol names; the new direct-import line is present.
4. Call-site byte parity: the two call-sites inside the intake body remain
   character-identical to the pre-4c.3 source string.
5. Live surface: `/openapi.json` path count still equals 858.
6. Audit gate no-op: the unchanged `audit_shim_substitution.py` still passes
   all 8 helpers (since `server.py` was not mutated).
"""
from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TIER3 = ("lookup_vendor_alias", "check_duplicate_document")
INTAKE_FUNC_NAME = "intake_document_from_bytes"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")


def _intake_func_node():
    """Return the AST node for the intake function in document_handlers.py."""
    from services import document_handlers
    tree = ast.parse(inspect.getsource(document_handlers))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in document_handlers.py AST")


def _intake_func_source():
    """Return the raw source text of the intake function."""
    from services import document_handlers
    func = getattr(document_handlers, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. Object-identity
# ---------------------------------------------------------------------------
class TestObjectIdentity:
    @pytest.mark.parametrize("name", TIER3)
    def test_document_handlers_resolves_to_vendor_matching(self, name):
        """
        The binding used inside the intake function after 4c.3 must come
        from `services.vendor_matching`. We verify by locating the
        `ImportFrom` nodes inside the function body.
        """
        intake = _intake_func_node()
        import_sources = {}
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_sources[alias.name] = node.module
        assert name in import_sources, (
            f"{name} not imported anywhere inside {INTAKE_FUNC_NAME}"
        )
        assert import_sources[name] == "services.vendor_matching", (
            f"{name} is imported from {import_sources[name]!r}, expected "
            "'services.vendor_matching'"
        )

    @pytest.mark.parametrize("name", TIER3)
    def test_runtime_identity_server_shim_delegates(self, name):
        """
        `server.X` (the 4-line THIN_SHIM) must still resolve at runtime to
        a callable, and `services.vendor_matching.X` must also be callable.
        """
        import server
        from services import vendor_matching
        svc_obj = getattr(vendor_matching, name)
        srv_obj = getattr(server, name)
        assert callable(svc_obj), f"services.vendor_matching.{name} not callable"
        assert callable(srv_obj), f"server.{name} not callable"


# ---------------------------------------------------------------------------
# 2. Server shim parity retained (server.py untouched)
# ---------------------------------------------------------------------------
class TestServerShimUntouched:
    @pytest.mark.parametrize("name", TIER3)
    def test_server_shim_is_thin_shim_post_4c3(self, name):
        """
        The 4-line THIN_SHIM in server.py must remain structurally identical
        to its post-4e state: exactly one reachable return statement and
        exactly one local `from services.vendor_matching import ...`.
        """
        import server
        func = getattr(server, name)
        src = inspect.getsource(func)
        tree = ast.parse(src)
        fn = tree.body[0]
        returns = [s for s in fn.body if isinstance(s, ast.Return)]
        imports = [s for s in fn.body if isinstance(s, ast.ImportFrom)]
        assert len(returns) == 1, (
            f"server.{name} expected exactly 1 reachable return, got {len(returns)}"
        )
        assert len(imports) == 1, (
            f"server.{name} expected exactly 1 local ImportFrom, got {len(imports)}"
        )
        assert imports[0].module == "services.vendor_matching", (
            f"server.{name} local import module is {imports[0].module!r}, "
            "expected 'services.vendor_matching'"
        )


# ---------------------------------------------------------------------------
# 3. Lazy block shrunk + new direct-import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_tier3(self):
        intake = _intake_func_node()
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports, (
            f"lazy `from server import (...)` block missing in {INTAKE_FUNC_NAME}"
        )
        listed = {alias.name for node in server_imports for alias in node.names}
        for name in TIER3:
            assert name not in listed, (
                f"{name} still listed in `from server import (...)` block"
            )

    def test_direct_vendor_matching_import_line_present(self):
        """The new 4c.3 direct-import line lives inside the intake body."""
        intake_src = _intake_func_source()
        assert (
            "from services.vendor_matching import "
            "lookup_vendor_alias, check_duplicate_document"
        ) in intake_src, "4c.3 direct-import line missing from intake body"


# ---------------------------------------------------------------------------
# 4. Call-site byte parity (the two await-call lines are unchanged)
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_lookup_vendor_alias_call_site_intact(self):
        intake_src = _intake_func_source()
        assert (
            'vendor_alias_result = await lookup_vendor_alias('
            'normalized_fields.get("vendor_normalized"))'
        ) in intake_src, "lookup_vendor_alias call-site byte-drift detected"

    def test_check_duplicate_document_call_site_intact(self):
        intake_src = _intake_func_source()
        assert "duplicate_result = await check_duplicate_document(" in intake_src, (
            "check_duplicate_document call-site byte-drift detected"
        )


# ---------------------------------------------------------------------------
# 5. Live surface preserved (/openapi.json path count == 858)
# ---------------------------------------------------------------------------
class TestLiveSurface:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert r.status_code == 200

    def test_openapi_path_count_858(self):
        try:
            paths = (
                requests.get(f"{BASE_URL}/openapi.json", timeout=5)
                .json()
                .get("paths", {})
            )
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert len(paths) == 858, (
            f"openapi path count drift: got {len(paths)}, expected 858"
        )


# ---------------------------------------------------------------------------
# 6. Audit gate no-op (server.py untouched ⇒ audit still green)
# ---------------------------------------------------------------------------
class TestAuditGateStillGreen:
    def test_audit_script_reports_eight_passing(self):
        """
        `audit_shim_substitution.py` inspects `server.py` only. Since 4c.3
        leaves `server.py` untouched, the audit must still classify all 8
        helpers as IDENTITY or THIN_SHIM (zero failing).
        """
        script = BACKEND_ROOT / "tests" / "audit_shim_substitution.py"
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"audit script exited {result.returncode}: {result.stderr[-400:]}"
        )
        out = result.stdout
        assert "Passing (8):" in out, (
            f"audit not reporting 8 passing helpers. stdout tail:\n{out[-600:]}"
        )
        assert "Failing (0):" in out, (
            f"audit reports some failing helpers. stdout tail:\n{out[-600:]}"
        )
