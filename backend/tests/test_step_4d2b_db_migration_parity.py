"""
Phase 3 Step 4d.2b — `db` + `client` Migration Parity Suite

Migrates `db` (the Motor database handle) and `client` (the
AsyncIOMotorClient singleton) from `server.py` to a new dedicated module
`backend/database.py`. `server.py` retains both as re-exports so external
importers and in-module shutdown hooks continue to function.

The nine probe classes below together form the acceptance gate:

1. Object identity for `db` across all consumers.
2. Motor client singleton identity (guards against accidental dual pools).
3. Single connection pool guard + env coherence.
4. Lazy block shrunk; `from server import` tuple contains zero globals.
5. `routers/posting_patterns.py` rewired.
6. `server.py` shutdown hook intact (``client.close()`` resolves to the
   same client object).
7. Live surface preserved (`/openapi.json` = 858 paths).
8. Audit gate no-op (server.py helper shims unchanged).
9. End-to-end ping round-trip works (skipped if MongoDB unreachable).
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
    raise AssertionError(f"{INTAKE_FUNC_NAME} not found in AST")


def _intake_func_source() -> str:
    from services import document_handlers
    func = getattr(document_handlers, INTAKE_FUNC_NAME)
    return inspect.getsource(func)


# ---------------------------------------------------------------------------
# 1. Object identity for `db`
# ---------------------------------------------------------------------------
class TestDbObjectIdentity:
    def test_database_db_is_server_db(self):
        import database
        import server
        assert database.db is server.db, (
            "database.db is not the same object as server.db — "
            "re-export chain broken"
        )

    def test_intake_binding_source_is_database_module(self):
        """AST confirms intake imports db from `database`, not `server`."""
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "db":
                        assert node.module == "database", (
                            f"db imported from {node.module!r}, "
                            "expected 'database'"
                        )
                        return
        raise AssertionError("db import not found in intake body")

    def test_posting_patterns_binding_source_is_database_module(self):
        """routers/posting_patterns.py:get_db imports db from `database`."""
        src = (
            BACKEND_ROOT / "routers" / "posting_patterns.py"
        ).read_text()
        tree = ast.parse(src)
        # Locate the function `get_db` and inspect its body's import.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_db":
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom):
                        for alias in child.names:
                            if alias.name == "db":
                                assert child.module == "database", (
                                    f"posting_patterns.get_db imports db "
                                    f"from {child.module!r}, "
                                    "expected 'database'"
                                )
                                return
        raise AssertionError(
            "get_db function or its db import not found in "
            "routers/posting_patterns.py"
        )


# ---------------------------------------------------------------------------
# 2. Motor client singleton identity
# ---------------------------------------------------------------------------
class TestClientSingletonIdentity:
    def test_database_client_is_server_client(self):
        import database
        import server
        assert database.client is server.client, (
            "database.client is not the same object as server.client — "
            "Motor client re-export chain broken"
        )

    def test_db_client_is_same_as_toplevel_client(self):
        """Motor API: db.client should return the client that owns db."""
        import database
        assert database.db.client is database.client, (
            "database.db.client is not the top-level database.client — "
            "db handle and client are mismatched"
        )

    def test_server_client_close_bound_to_same_object(self):
        """Shutdown hook parity: server.client.close must be callable and the
        client re-export chain must resolve to the exact same Motor client
        object as database.client (verified via `is` comparison, since
        Motor's `.close` bound method's `__self__` is an internal PyMongo
        object, not the AsyncIOMotorClient itself)."""
        import database
        import server
        assert callable(server.client.close), "server.client.close not callable"
        # Top-level Motor client object identity — THE guarantee that matters:
        # when shutdown hook calls `client.close()`, it closes THE SAME client
        # that owns database.db.
        assert server.client is database.client, (
            "server.client and database.client are distinct objects — "
            "shutdown hook would close a different client than db's owner"
        )


# ---------------------------------------------------------------------------
# 3. Single connection pool guard + env coherence
# ---------------------------------------------------------------------------
class TestSingleConnectionPool:
    def test_id_integer_identity(self):
        import database
        import server
        assert id(database.client) == id(server.client), (
            f"Motor client duplicated: id(database.client)="
            f"{id(database.client)}, id(server.client)={id(server.client)}"
        )

    def test_env_populated_at_database_import_time(self):
        """`database.py`'s load_dotenv() ensured MONGO_URL/DB_NAME are set."""
        assert os.environ.get("MONGO_URL"), (
            "MONGO_URL not populated after database module import"
        )
        assert os.environ.get("DB_NAME"), (
            "DB_NAME not populated after database module import"
        )

    def test_db_name_matches_env(self):
        import database
        assert database.db.name == os.environ["DB_NAME"], (
            f"database.db targets DB name {database.db.name!r}, "
            f"env DB_NAME={os.environ['DB_NAME']!r}"
        )


# ---------------------------------------------------------------------------
# 4. Lazy block shrunk — zero globals remain
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_db_not_in_server_import_tuple(self):
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        assert "db" not in listed, (
            "`db` still listed in `from server import (...)` block"
        )

    def test_new_database_import_line_present(self):
        src = _intake_func_source()
        assert "from database import db" in src, (
            "4d.2b direct-import line `from database import db` missing "
            "from intake body"
        )

    def test_server_import_tuple_has_no_globals(self):
        """
        Structural milestone: after 4d.2b, the `from server import (...)`
        tuple should contain only helpers (underscore or public function
        names), no module-level globals. We assert by negative list: none
        of the historically-migrated globals should appear.
        """
        intake = _intake_func_node()
        listed = {
            alias.name
            for node in ast.walk(intake)
            if isinstance(node, ast.ImportFrom) and node.module == "server"
            for alias in node.names
        }
        historically_migrated_globals = {
            "AutoClearDecision", "CaptureChannel", "DEFAULT_JOB_TYPES",
            "DocType", "PILOT_MODE_ENABLED", "SourceSystem",
            "WorkflowEvent", "WorkflowStatus", "UPLOAD_DIR", "db",
        }
        leaked = listed & historically_migrated_globals
        assert not leaked, (
            f"Globals {leaked} re-appeared in `from server import` tuple — "
            "migration invariant violated"
        )


# ---------------------------------------------------------------------------
# 5. routers/posting_patterns.py rewired
# ---------------------------------------------------------------------------
class TestPostingPatternsRewire:
    def test_no_from_server_import_db_remains(self):
        src = (
            BACKEND_ROOT / "routers" / "posting_patterns.py"
        ).read_text()
        assert "from server import db" not in src, (
            "`from server import db` still present in posting_patterns.py"
        )

    def test_from_database_import_db_present(self):
        src = (
            BACKEND_ROOT / "routers" / "posting_patterns.py"
        ).read_text()
        assert "from database import db" in src, (
            "`from database import db` missing from posting_patterns.py"
        )

    def test_get_db_returns_same_object(self):
        import database
        from routers.posting_patterns import get_db
        assert get_db() is database.db, (
            "routers.posting_patterns.get_db() returned a different object "
            "than database.db"
        )


# ---------------------------------------------------------------------------
# 6. server.py shutdown hooks intact
# ---------------------------------------------------------------------------
class TestShutdownHooksIntact:
    def test_server_py_still_calls_client_close_twice(self):
        import re
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        # Match only executable `client.close()` calls: lines beginning with
        # whitespace followed by the call. Excludes occurrences inside
        # comments or docstrings (which may reference the symbol in prose).
        executable_calls = re.findall(
            r'^\s+client\.close\(\)\s*$', srv_src, re.MULTILINE
        )
        assert len(executable_calls) == 2, (
            f"server.py has {len(executable_calls)} executable "
            "`client.close()` calls, expected 2 (shutdown hook parity broken)"
        )

    def test_server_client_close_callable(self):
        import server
        assert callable(server.client.close), (
            "server.client.close no longer callable — shutdown hook broken"
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


# ---------------------------------------------------------------------------
# 9. End-to-end ping round-trip
# ---------------------------------------------------------------------------
class TestEndToEndDbPing:
    @pytest.mark.asyncio
    async def test_db_ping_succeeds(self):
        import database
        try:
            result = await database.db.command("ping")
        except Exception as exc:
            pytest.skip(f"MongoDB unreachable in sandbox: {exc}")
        assert result.get("ok") == 1.0, (
            f"MongoDB ping returned {result!r}, expected ok=1.0"
        )
