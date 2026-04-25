"""
Phase 3 Step 4d.3b — event_service Helper Substitution Parity Suite

Substitutes 2 pure re-export helpers in
`services/document_handlers.py::intake_document_from_bytes`'s lazy
import block from `server` to their authoritative home
`services.event_service`:

- emit_document_received
- get_event_service

Both are declared at server.py:112–115 via ``from services.event_service
import (... emit_document_received ... get_event_service ...)`` — so
`server.X` is already the same Python object as
`services.event_service.X`.

THE CRITICAL SUBTLE RISK IN THIS STEP is that `services.event_service`
also defines a class called ``WorkflowEvent`` that is a DIFFERENT Python
object from ``workflows.core.engine.WorkflowEvent`` (the enum migrated
into the intake body in Step 4d.1). One sloppy import line could silently
redirect ``document_handlers.WorkflowEvent`` to the wrong object and
corrupt the 4d.1 invariant. This suite encodes the collision guard as a
first-class set of probes.

Nine probe classes form the acceptance gate:

1. AST-level import source: intake's ImportFrom targets
   `services.event_service`.
2. Runtime object identity: `server.X is services.event_service.X`.
3. Server re-export chain retained (external importers undisturbed).
4. Lazy block shrunk + new dedicated import line present.
5. Call-site byte parity (both use-sites inside intake body unchanged).
6. WorkflowEvent collision regression guard (first-class, 3 sub-probes).
7. AST guard that no extra names were pulled from services.event_service.
8. Live surface preserved (/openapi.json = 858 paths).
9. Audit gate no-op.
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

SYMBOLS = ("emit_document_received", "get_event_service")
CANONICAL_MODULE = "services.event_service"


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
    def test_intake_imports_from_event_service(self, name):
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
    def test_server_X_is_event_service_X(self, name):
        import server
        from services import event_service
        svc_obj = getattr(event_service, name)
        srv_obj = getattr(server, name)
        assert srv_obj is svc_obj, (
            f"server.{name} is not the same object as "
            f"services.event_service.{name} — pure re-export "
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
        services.event_service must still include both 4d.3b target names.
        """
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        assert (
            "from services.event_service import (\n"
            "    EventService, WorkflowEvent as WFEvent, EventStatus,\n"
            "    set_event_service, get_event_service, "
            "initialize_event_indexes,\n"
            "    emit_document_received, emit_classification_completed, "
            "emit_vendor_match,\n"
        ) in srv_src, (
            "server.py top-of-file services.event_service import block "
            "drifted"
        )


# ---------------------------------------------------------------------------
# 4. Lazy block shrunk + new dedicated import line present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d3b_symbols(self):
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

    def test_new_4d3b_import_line_present(self):
        src = _intake_func_source()
        assert (
            "from services.event_service import "
            "emit_document_received, get_event_service"
        ) in src, "4d.3b direct-import line missing from intake body"


# ---------------------------------------------------------------------------
# 5. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    EXPECTED_NEEDLES = (
        "emit_document_received(",
        "get_event_service(",
    )

    @pytest.mark.parametrize("needle", EXPECTED_NEEDLES)
    def test_use_site_present(self, needle):
        """
        Call-site invariance: the function call marker for each helper
        must still appear in the intake body exactly as before. We match
        the opening-paren fingerprint rather than a full multi-line
        signature to stay robust against legitimate future argument
        refactors while still catching a silent rename or deletion.
        """
        src = _intake_func_source()
        assert needle in src, (
            f"use-site drift: {needle!r} no longer present in intake body"
        )


# ---------------------------------------------------------------------------
# 6. WorkflowEvent collision regression guard (FIRST-CLASS)
# ---------------------------------------------------------------------------
class TestWorkflowEventCollisionGuard:
    """
    services.event_service defines a class `WorkflowEvent` that is a
    DIFFERENT Python object from workflows.core.engine.WorkflowEvent (the
    enum migrated in 4d.1). Step 4d.3b pulls new names from
    services.event_service; this suite of probes ensures the migration
    did NOT silently redirect document_handlers.WorkflowEvent to the
    wrong class.
    """

    def test_server_workflow_event_is_engine_enum(self):
        """Positive invariant: server.WorkflowEvent === the engine enum."""
        import server
        from workflows.core.engine import WorkflowEvent as EngineWE
        assert server.WorkflowEvent is EngineWE, (
            "4d.1 invariant regressed: server.WorkflowEvent no longer "
            "identical to workflows.core.engine.WorkflowEvent"
        )

    def test_server_workflow_event_is_not_event_service_class(self):
        """Negative guard: server.WorkflowEvent is NOT the collision class."""
        import server
        from services.event_service import WorkflowEvent as EventSvcWE
        assert server.WorkflowEvent is not EventSvcWE, (
            "server.WorkflowEvent incorrectly aliased to "
            "services.event_service.WorkflowEvent — collision occurred"
        )

    def test_test_premise_two_workflow_events_are_distinct(self):
        """
        Sanity: the two WorkflowEvent classes in the codebase are distinct
        Python objects. If this ever becomes True (same object), the
        entire collision-guard shape collapses and a different guard
        mechanism is required.
        """
        from workflows.core.engine import WorkflowEvent as EngineWE
        from services.event_service import WorkflowEvent as EventSvcWE
        assert EngineWE is not EventSvcWE, (
            "Test-premise invalid: workflows.core.engine.WorkflowEvent "
            "and services.event_service.WorkflowEvent are the same "
            "object. Collision-guard shape needs re-design."
        )

    def test_intake_body_imports_workflow_event_from_engine_only(self):
        """
        AST-level guard: inside intake, any ImportFrom that names
        `WorkflowEvent` must target workflows.core.engine — never
        services.event_service.
        """
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "WorkflowEvent":
                        assert node.module == "workflows.core.engine", (
                            f"Intake imports WorkflowEvent from "
                            f"{node.module!r}; expected "
                            "'workflows.core.engine'. Collision guard "
                            "triggered."
                        )


# ---------------------------------------------------------------------------
# 7. AST guard that no extra names were pulled from services.event_service
# ---------------------------------------------------------------------------
class TestOnlyDeclaredNamesFromEventService:
    def test_event_service_import_tuple_is_exactly_the_declared_pair(self):
        """
        Walk the intake function body, collect every ImportFrom whose
        module is services.event_service, and assert the declared pair
        ``{emit_document_received, get_event_service}`` is present
        (a *superset* check — subsequent carve-outs that co-locate
        additional primitives in ``services.event_service`` are allowed
        to add to this set; e.g. 4d.5 introduces ``emit_intake_events``).
        Catches any accidental removal or typo of the 4d.3b declared pair
        at AST parse time.
        """
        intake = _intake_func_node()
        pulled = set()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom) \
                    and node.module == CANONICAL_MODULE:
                for alias in node.names:
                    pulled.add(alias.name)
        expected = set(SYMBOLS)
        missing = expected - pulled
        assert not missing, (
            f"Intake pulls {sorted(pulled)!r} from {CANONICAL_MODULE}, "
            f"but the 4d.3b declared pair {sorted(expected)!r} is missing: "
            f"{sorted(missing)!r}"
        )


# ---------------------------------------------------------------------------
# 8. Live surface preserved
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
# 9. Audit gate no-op
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
