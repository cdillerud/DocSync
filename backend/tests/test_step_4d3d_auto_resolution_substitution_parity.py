"""
Phase 3 Step 4d.3d — auto_resolution_service Helper Substitution Parity Suite

Substitutes 1 pure re-export helper in
`services/document_handlers.py::intake_document_from_bytes`'s lazy
import block from `server` to its authoritative home
`services.auto_resolution_service`:

- get_auto_resolve_service

The helper is declared at server.py:145–147 via
``from services.auto_resolution_service import (AutoResolutionService,
get_auto_resolve_service, set_auto_resolve_service, ...)`` — so
`server.get_auto_resolve_service` is already the same Python object as
`services.auto_resolution_service.get_auto_resolve_service`.

No family-sibling or collision risk in this subgroup. Minimal
object-identity parity shape, seven probe classes:

1. AST-level import source.
2. Runtime object identity.
3. Server re-export chain retained.
4. Lazy block shrunk + new direct-import line present.
5. Call-site byte parity (opening-paren fingerprint).
6. Live surface preserved.
7. Audit gate no-op.
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

SYMBOL = "get_auto_resolve_service"
CANONICAL_MODULE = "services.auto_resolution_service"


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
    def test_intake_imports_from_auto_resolution_service(self):
        intake = _intake_func_node()
        import_sources = {}
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_sources[alias.name] = node.module
        assert SYMBOL in import_sources, (
            f"{SYMBOL} not imported anywhere inside {INTAKE_FUNC_NAME}"
        )
        assert import_sources[SYMBOL] == CANONICAL_MODULE, (
            f"{SYMBOL} imported from {import_sources[SYMBOL]!r}, "
            f"expected {CANONICAL_MODULE!r}"
        )


# ---------------------------------------------------------------------------
# 2. Runtime object identity
# ---------------------------------------------------------------------------
class TestRuntimeObjectIdentity:
    def test_server_symbol_is_auto_resolution_service_symbol(self):
        import server
        from services import auto_resolution_service
        svc_obj = getattr(auto_resolution_service, SYMBOL)
        srv_obj = getattr(server, SYMBOL)
        assert srv_obj is svc_obj, (
            f"server.{SYMBOL} is not the same object as "
            f"services.auto_resolution_service.{SYMBOL} — pure re-export "
            "chain broken"
        )


# ---------------------------------------------------------------------------
# 3. Server re-export chain retained
# ---------------------------------------------------------------------------
class TestServerReExportRetained:
    def test_server_still_exposes_symbol(self):
        """External importers doing `from server import X` still work."""
        import server
        assert hasattr(server, SYMBOL), (
            f"server.{SYMBOL} no longer importable — "
            "re-export chain broken"
        )
        assert callable(getattr(server, SYMBOL)), (
            f"server.{SYMBOL} is no longer callable"
        )

    def test_server_top_of_file_import_block_unchanged(self):
        """server.py's top-of-file services.auto_resolution_service
        import block must still include the 4d.3d target name."""
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        assert (
            "from services.auto_resolution_service import ("
        ) in srv_src, (
            "server.py top-of-file auto_resolution_service import block "
            "missing"
        )
        assert (
            "get_auto_resolve_service"
        ) in srv_src, (
            "server.py top-of-file import block lost "
            "`get_auto_resolve_service`"
        )


# ---------------------------------------------------------------------------
# 4. Lazy block shrunk + new dedicated import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d3d_symbol(self):
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
        assert SYMBOL not in listed, (
            f"{SYMBOL} still listed in `from server import (...)` block"
        )

    def test_new_4d3d_import_line_present(self):
        src = _intake_func_source()
        assert (
            "from services.auto_resolution_service import "
            "get_auto_resolve_service"
        ) in src, "4d.3d direct-import line missing from intake body"


# ---------------------------------------------------------------------------
# 5. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_use_site_present(self):
        """Call-site invariance: the function-call marker
        `get_auto_resolve_service(` must still appear in the intake body."""
        src = _intake_func_source()
        assert "get_auto_resolve_service(" in src, (
            "use-site drift: `get_auto_resolve_service(` no longer "
            "present in intake body"
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
