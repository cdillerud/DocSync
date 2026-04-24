"""
Phase 3 Step 4d.3c — pilot_config Helper Substitution Parity Suite

Substitutes 2 pure re-export helpers in
`services/document_handlers.py::intake_document_from_bytes`'s lazy
import block from `server` to their authoritative home
`services.pilot_config`:

- get_pilot_capture_channel
- get_pilot_metadata

Both are declared at server.py:95–98 via ``from services.pilot_config
import (... get_pilot_metadata ... get_pilot_capture_channel ...)`` — so
`server.X` is already the same Python object as
`services.pilot_config.X`.

No collision-partner risk exists in this subgroup. The one invariant to
re-verify post-migration is the Class 1 family sibling: PILOT_MODE_ENABLED
(migrated in 4d.1) must still resolve authoritatively through
services.pilot_config.

Eight probe classes form the acceptance gate:

1. AST-level import source.
2. Runtime object identity.
3. Server re-export chain retained.
4. Lazy block shrunk + new direct-import line present.
5. Call-site byte parity (opening-paren fingerprints).
6. Class 1 family-sibling invariant (PILOT_MODE_ENABLED 4d.1 guard).
7. Live surface preserved (/openapi.json = 858 paths).
8. Audit gate no-op.
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

SYMBOLS = ("get_pilot_capture_channel", "get_pilot_metadata")
CANONICAL_MODULE = "services.pilot_config"


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
    def test_intake_imports_from_pilot_config(self, name):
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
    def test_server_X_is_pilot_config_X(self, name):
        import server
        from services import pilot_config
        svc_obj = getattr(pilot_config, name)
        srv_obj = getattr(server, name)
        assert srv_obj is svc_obj, (
            f"server.{name} is not the same object as "
            f"services.pilot_config.{name} — pure re-export "
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
        """server.py's top-of-file services.pilot_config import block
        must still include both 4d.3c target names."""
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        assert (
            "from services.pilot_config import (\n"
            "    PILOT_MODE_ENABLED, CURRENT_PILOT_PHASE,\n"
            "    get_pilot_metadata, is_pilot_document, "
            "get_pilot_capture_channel,\n"
        ) in srv_src, (
            "server.py top-of-file services.pilot_config import block "
            "drifted"
        )


# ---------------------------------------------------------------------------
# 4. Lazy block shrunk + new dedicated import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d3c_symbols(self):
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

    def test_new_4d3c_import_line_present(self):
        src = _intake_func_source()
        assert (
            "from services.pilot_config import "
            "get_pilot_capture_channel, get_pilot_metadata"
        ) in src, "4d.3c direct-import line missing from intake body"


# ---------------------------------------------------------------------------
# 5. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    EXPECTED_NEEDLES = (
        "get_pilot_capture_channel(",
        "get_pilot_metadata(",
    )

    @pytest.mark.parametrize("needle", EXPECTED_NEEDLES)
    def test_use_site_present(self, needle):
        """
        Call-site invariance: the function call marker for each helper
        must still appear in the intake body. Matches opening-paren
        fingerprint for robustness against legitimate future refactors.
        """
        src = _intake_func_source()
        assert needle in src, (
            f"use-site drift: {needle!r} no longer present in intake body"
        )


# ---------------------------------------------------------------------------
# 6. Class 1 family-sibling invariant (PILOT_MODE_ENABLED 4d.1 guard)
# ---------------------------------------------------------------------------
class TestClass1FamilySiblingIntact:
    def test_server_pilot_mode_enabled_is_pilot_config_pilot_mode_enabled(self):
        """
        Runtime invariant: server.PILOT_MODE_ENABLED must remain the
        same Python object as services.pilot_config.PILOT_MODE_ENABLED.
        This is the 4d.1 authoritative-home contract. 4d.3c must not
        regress it.
        """
        import server
        from services import pilot_config
        assert server.PILOT_MODE_ENABLED is pilot_config.PILOT_MODE_ENABLED, (
            "4d.1 invariant regressed: server.PILOT_MODE_ENABLED no longer "
            "identical to services.pilot_config.PILOT_MODE_ENABLED"
        )

    def test_intake_imports_pilot_mode_enabled_from_pilot_config(self):
        """
        The 4d.1 direct-import line for PILOT_MODE_ENABLED must still be
        present in the intake body, unchanged.
        """
        src = _intake_func_source()
        assert (
            "from services.pilot_config import PILOT_MODE_ENABLED"
        ) in src, (
            "4d.1 PILOT_MODE_ENABLED direct-import line drifted or removed"
        )

    def test_pilot_family_coherence_three_way(self):
        """
        After 4d.3c, all 3 migrated pilot_config symbols resolve
        authoritatively through the same module:
        - PILOT_MODE_ENABLED (4d.1)
        - get_pilot_capture_channel (4d.3c)
        - get_pilot_metadata (4d.3c)
        Each server.X must `is` services.pilot_config.X.
        """
        import server
        from services import pilot_config
        family = ("PILOT_MODE_ENABLED",) + SYMBOLS
        for name in family:
            assert getattr(server, name) is getattr(pilot_config, name), (
                f"Family coherence broken: server.{name} is not "
                f"services.pilot_config.{name}"
            )


# ---------------------------------------------------------------------------
# 7. Live surface preserved
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
# 8. Audit gate no-op
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
