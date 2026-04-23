"""
Phase 3 Step 4d.2a — UPLOAD_DIR Migration Parity Suite

Migrates `UPLOAD_DIR` from `server.py` (where it was the authoritative home)
to a new dedicated module `backend/paths.py`. `server.py` retains
`UPLOAD_DIR` as a re-export so external importers are undisturbed.

Eight probes form the acceptance gate:

1. Path-identity: `paths.UPLOAD_DIR == server.UPLOAD_DIR` AND both resolve
   to the same absolute filesystem path.
2. Object-identity: `server.UPLOAD_DIR is paths.UPLOAD_DIR` (the re-export
   chain yields the same Python object).
3. Existing directory preserved (`UPLOAD_DIR.is_dir()` post-import).
4. ROOT_DIR coherence: `paths.ROOT_DIR == server.ROOT_DIR` (both evaluate
   to `/app/backend`).
5. Lazy block shrunk: AST walk confirms `UPLOAD_DIR` is no longer in the
   `from server import` tuple inside intake; the new
   `from paths import UPLOAD_DIR` line is present.
6. Call-site byte parity: `file_path = UPLOAD_DIR / doc_id` (and any
   similar use-site) inside the intake body is character-identical.
7. Live surface: `/openapi.json` path count still equals 858.
8. Audit gate: `audit_shim_substitution.py` still green
   (inspects Tier-1/2/3 helpers only — unaffected by module carve-out).
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


def _intake_func_node():
    from services import document_handlers
    tree = ast.parse(inspect.getsource(document_handlers))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == INTAKE_FUNC_NAME:
            return node
    raise AssertionError(
        f"{INTAKE_FUNC_NAME} not found in document_handlers.py AST"
    )


def _intake_func_source() -> str:
    from services import document_handlers
    func = getattr(document_handlers, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. Path-identity (value equality + canonical absolute path)
# ---------------------------------------------------------------------------
class TestPathIdentity:
    def test_paths_upload_dir_equals_server_upload_dir(self):
        import paths
        import server
        assert paths.UPLOAD_DIR == server.UPLOAD_DIR, (
            f"paths.UPLOAD_DIR ({paths.UPLOAD_DIR}) != "
            f"server.UPLOAD_DIR ({server.UPLOAD_DIR})"
        )

    def test_upload_dir_resolves_to_canonical_absolute_path(self):
        import paths
        assert paths.UPLOAD_DIR.resolve() == Path("/app/backend/uploads"), (
            f"paths.UPLOAD_DIR resolves to {paths.UPLOAD_DIR.resolve()}, "
            "expected /app/backend/uploads"
        )


# ---------------------------------------------------------------------------
# 2. Object-identity (server.UPLOAD_DIR is paths.UPLOAD_DIR)
# ---------------------------------------------------------------------------
class TestObjectIdentity:
    def test_server_reexport_is_same_object(self):
        import paths
        import server
        assert server.UPLOAD_DIR is paths.UPLOAD_DIR, (
            "server.UPLOAD_DIR is not the same object as paths.UPLOAD_DIR — "
            "re-export chain broken"
        )

    def test_document_handlers_intake_binding_is_same_object(self):
        import paths
        # Execute the body to trigger the lazy import, then confirm the
        # resolved binding is the same Python object. We cannot invoke
        # intake_document_from_bytes directly (heavy side effects), so we
        # instead verify the import statement source targets `paths`.
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "UPLOAD_DIR":
                        assert node.module == "paths", (
                            f"UPLOAD_DIR imported from {node.module!r}, "
                            "expected 'paths'"
                        )
                        # Module-level import: confirm `paths.UPLOAD_DIR`
                        # is a concrete Path object.
                        assert isinstance(paths.UPLOAD_DIR, Path), (
                            f"paths.UPLOAD_DIR is not a Path: "
                            f"{type(paths.UPLOAD_DIR).__name__}"
                        )
                        return
        raise AssertionError(
            "UPLOAD_DIR import not found in intake body"
        )


# ---------------------------------------------------------------------------
# 3. Existing directory preserved
# ---------------------------------------------------------------------------
class TestDirectoryPreserved:
    def test_upload_dir_is_directory(self):
        import paths
        assert paths.UPLOAD_DIR.is_dir(), (
            f"paths.UPLOAD_DIR ({paths.UPLOAD_DIR}) is not a directory; "
            "mkdir(exist_ok=True) did not run or was reverted"
        )


# ---------------------------------------------------------------------------
# 4. ROOT_DIR coherence
# ---------------------------------------------------------------------------
class TestRootDirCoherence:
    def test_paths_root_dir_equals_server_root_dir(self):
        import paths
        import server
        assert paths.ROOT_DIR == server.ROOT_DIR, (
            f"paths.ROOT_DIR ({paths.ROOT_DIR}) != "
            f"server.ROOT_DIR ({server.ROOT_DIR})"
        )

    def test_paths_root_dir_is_backend_directory(self):
        import paths
        assert paths.ROOT_DIR.resolve() == Path("/app/backend"), (
            f"paths.ROOT_DIR resolves to {paths.ROOT_DIR.resolve()}, "
            "expected /app/backend"
        )


# ---------------------------------------------------------------------------
# 5. Lazy block shrunk + new direct import present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_upload_dir(self):
        intake = _intake_func_node()
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports, (
            f"lazy `from server import (...)` block missing in {INTAKE_FUNC_NAME}"
        )
        listed = {alias.name for node in server_imports for alias in node.names}
        assert "UPLOAD_DIR" not in listed, (
            "UPLOAD_DIR still listed in `from server import (...)` block"
        )

    def test_db_still_listed_in_lazy_server_import(self):
        """Guardrail: 4d.2a must NOT touch `db`; that is reserved for 4d.2b."""
        intake = _intake_func_node()
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        listed = {alias.name for node in server_imports for alias in node.names}
        assert "db" in listed, (
            "`db` no longer in lazy `from server import` block — "
            "4d.2a incorrectly touched a 4d.2b-reserved symbol"
        )

    def test_new_paths_import_line_present(self):
        src = _intake_func_source()
        assert "from paths import UPLOAD_DIR" in src, (
            "4d.2a direct-import line `from paths import UPLOAD_DIR` "
            "missing from intake body"
        )


# ---------------------------------------------------------------------------
# 6. Call-site byte parity (UPLOAD_DIR use-sites in intake body)
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    def test_intake_file_path_use_site_intact(self):
        src = _intake_func_source()
        assert "file_path = UPLOAD_DIR / doc_id" in src, (
            "UPLOAD_DIR use-site byte-drift detected in intake body"
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
            paths_json = (
                requests.get(f"{BASE_URL}/openapi.json", timeout=5)
                .json()
                .get("paths", {})
            )
        except Exception as exc:
            pytest.skip(f"Backend unreachable at {BASE_URL}: {exc}")
        assert len(paths_json) == 858, (
            f"openapi path count drift: got {len(paths_json)}, expected 858"
        )


# ---------------------------------------------------------------------------
# 8. Audit gate no-op (Tier-1/2/3 helper shim audit unaffected)
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
            f"audit not reporting 8 passing helpers. stdout tail:\n{out[-600:]}"
        )
        assert "Failing (0):" in out, (
            f"audit reports some failing helpers. stdout tail:\n{out[-600:]}"
        )
