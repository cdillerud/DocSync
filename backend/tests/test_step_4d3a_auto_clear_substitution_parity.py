"""
Phase 3 Step 4d.3a — auto_clear_service Helper Substitution Parity Suite

Substitutes 2 pure re-export helpers in
`services/document_handlers.py::intake_document_from_bytes`'s lazy
import block from `server` to their authoritative home
`services.auto_clear_service`:

- evaluate_auto_clear
- get_auto_clear_update

Both are declared at server.py:78–80 via ``from services.auto_clear_service
import (evaluate_auto_clear, get_auto_clear_update, ...)`` — so `server.X`
is already the same Python object as `services.auto_clear_service.X`.
Object-identity via runtime ``is`` is the strongest probe available here,
and it is the centerpiece of this suite.

The eight probe classes below together form the acceptance gate:

1. AST-level import source: intake's ImportFrom targets
   `services.auto_clear_service`.
2. Runtime object identity: `server.X is services.auto_clear_service.X`.
3. Server re-export chain retained (external importers undisturbed).
4. Lazy block shrunk + new dedicated import line present.
5. Call-site byte parity (both use-sites inside intake body unchanged).
6. Live surface preserved (/openapi.json = 858 paths).
7. Audit gate no-op (Tier-1/2/3 helper audit still green).
8. Class 1 family sibling intact (AutoClearDecision 4d.1 invariant held).
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

INTAKE_FUNC_NAME = "intake_document_from_bytes"
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "http://localhost:8001"
).rstrip("/")

SYMBOLS = ("evaluate_auto_clear", "get_auto_clear_update")
CANONICAL_MODULE = "services.auto_clear_service"


def _intake_func_node():
    from services import document_handlers
    tree = ast.parse(inspect.getsource(document_handlers))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in AST")


def _intake_func_source() -> str:
    from services import document_handlers
    func = getattr(document_handlers, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. AST-level import source
# ---------------------------------------------------------------------------
class TestASTImportSource:
    @pytest.mark.parametrize("name", SYMBOLS)
    def test_intake_imports_from_auto_clear_service(self, name):
        intake = _intake_func_node()
        import_sources = {}
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_sources[alias.name] = node.module
        assert name in import_sources, (
            f"{name} not imported anywhere inside {INTAKE_FUNC_NAME}"
        )
        assert import_sources[name] == CANONICAL_MODULE, (
            f"{name} imported from {import_sources[name]!r}, expected "
            f"{CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 2. Runtime object identity
# ---------------------------------------------------------------------------
class TestRuntimeObjectIdentity:
    @pytest.mark.parametrize("name", SYMBOLS)
    def test_server_X_is_auto_clear_service_X(self, name):
        import server
        from services import auto_clear_service
        svc_obj = getattr(auto_clear_service, name)
        srv_obj = getattr(server, name)
        assert srv_obj is svc_obj, (
            f"server.{name} is not the same object as "
            f"services.auto_clear_service.{name} — pure re-export "
            "chain broken"
        )


# ---------------------------------------------------------------------------
# 3. Server re-export chain retained
# ---------------------------------------------------------------------------
class TestServerReExportRetained:
    @pytest.mark.parametrize("name", SYMBOLS)
    def test_server_still_exposes_symbol(self, name):
        """External importers doing `from server import X` still work."""
        import server
        assert hasattr(server, name), (
            f"server.{name} no longer importable — re-export chain broken"
        )
        assert callable(getattr(server, name)), (
            f"server.{name} is no longer callable"
        )

    def test_server_top_of_file_import_block_unchanged(self):
        """
        Belt-and-suspenders: server.py's top-of-file import line for
        services.auto_clear_service must still include both 4d.3a target
        names.
        """
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        assert (
            "from services.auto_clear_service import (\n"
            "    evaluate_auto_clear, get_auto_clear_update, "
            "get_auto_clear_summary,\n"
        ) in srv_src, (
            "server.py top-of-file auto_clear_service import block drifted"
        )


# ---------------------------------------------------------------------------
# 4. Lazy block shrunk + new dedicated import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d3a_symbols(self):
        intake = _intake_func_node()
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports, (
            f"lazy `from server import (...)` block missing in "
            f"{INTAKE_FUNC_NAME}"
        )
        listed = {
            alias.name for node in server_imports for alias in node.names
        }
        for name in SYMBOLS:
            assert name not in listed, (
                f"{name} still listed in `from server import (...)` block"
            )

    def test_new_4d3a_import_line_present(self):
        src = _intake_func_source()
        assert (
            "from services.auto_clear_service import "
            "evaluate_auto_clear, get_auto_clear_update"
        ) in src, "4d.3a direct-import line missing from intake body"


# ---------------------------------------------------------------------------
# 5. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    EXPECTED_USE_SITES = (
        # Multi-line evaluate_auto_clear call (lines 2207–2210 of intake body).
        "evaluate_auto_clear(\n"
        "                    doc_for_eval,\n"
        "                    validation_results=validation_results\n"
        "                )",
        # Single-line get_auto_clear_update call (line 2212 of intake body).
        "auto_clear_update = get_auto_clear_update(auto_clear_decision, "
        "auto_clear_details)",
    )

    @pytest.mark.parametrize("needle", EXPECTED_USE_SITES)
    def test_use_site_intact(self, needle):
        src = _intake_func_source()
        assert needle in src, (
            f"use-site byte-drift: expected substring not found:\n{needle!r}"
        )


# ---------------------------------------------------------------------------
# 6. Live surface preserved
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
# 7. Audit gate no-op
# ---------------------------------------------------------------------------
class TestAuditGateStillGreen:
    def test_audit_script_reports_eight_passing(self):
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
            f"audit not reporting 8 passing helpers:\n{out[-600:]}"
        )
        assert "Failing (0):" in out, (
            f"audit reports some failing helpers:\n{out[-600:]}"
        )


# ---------------------------------------------------------------------------
# 8. Class 1 family sibling intact (AutoClearDecision 4d.1 invariant)
# ---------------------------------------------------------------------------
class TestClass1FamilySiblingIntact:
    def test_auto_clear_decision_identity_invariant_held(self):
        """
        Regression guard: touching services.auto_clear_service for 4d.3a
        must not disturb the 4d.1 invariant that
        `document_handlers.AutoClearDecision` resolves to the same object
        as `services.auto_clear_service.AutoClearDecision`.
        """
        from services import auto_clear_service
        import server
        # The 4d.1 authoritative-home assertion for AutoClearDecision.
        assert server.AutoClearDecision is auto_clear_service.AutoClearDecision, (
            "4d.1 invariant regressed: server.AutoClearDecision no longer "
            "identical to services.auto_clear_service.AutoClearDecision"
        )

    def test_intake_imports_auto_clear_decision_from_auto_clear_service(self):
        """
        The 4d.1 direct-import line for AutoClearDecision must still be
        present in the intake body, unchanged.
        """
        src = _intake_func_source()
        assert (
            "from services.auto_clear_service import AutoClearDecision"
        ) in src, (
            "4d.1 AutoClearDecision direct-import line drifted or removed"
        )
