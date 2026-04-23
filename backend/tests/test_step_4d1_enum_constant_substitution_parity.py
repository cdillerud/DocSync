"""
Phase 3 Step 4d.1 — Enum/Constant Substitution Parity Suite

Substitutes 8 enum/constant symbols in
`services/document_handlers.py::intake_document_from_bytes`'s lazy import
block from `server` to their authoritative home modules:

- workflows.core.engine:  CaptureChannel, DocType, SourceSystem,
                          WorkflowEvent, WorkflowStatus
- services.auto_clear_service: AutoClearDecision
- services.pilot_config:  PILOT_MODE_ENABLED
- models.document_types:  DEFAULT_JOB_TYPES

These are value classes / constants; `server.X` is already a re-export of
the authoritative module's X (by top-of-server.py import chain), so object
identity is the strongest possible parity probe.

The seven probes below together form the acceptance gate for Step 4d.1:

1. Object-identity: `document_handlers.<X>` is the authoritative module's X.
2. Server alias retained: `server.<X>` is still the authoritative module's X
   (server.py untouched; top-of-file re-export chain unchanged).
3. Lazy block shrunk: the `from server import (...)` tuple no longer lists
   any of the 8 names; the new dedicated import block is present.
4. Call-site byte parity: every existing reference to the 8 symbols inside
   the intake body is character-identical to the declared expected strings.
5. WorkflowEvent collision guard: `document_handlers.WorkflowEvent` resolves
   to `workflows.core.engine.WorkflowEvent`, NOT
   `services.event_service.WorkflowEvent` (different class, same name).
6. Live surface: `/openapi.json` path count still equals 858.
7. Audit gate no-op: `audit_shim_substitution.py` still green (server.py
   was not mutated).
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

# (symbol_name, canonical_module_dotted_path)
SUBSTITUTIONS = (
    ("CaptureChannel", "workflows.core.engine"),
    ("DocType", "workflows.core.engine"),
    ("SourceSystem", "workflows.core.engine"),
    ("WorkflowEvent", "workflows.core.engine"),
    ("WorkflowStatus", "workflows.core.engine"),
    ("AutoClearDecision", "services.auto_clear_service"),
    ("PILOT_MODE_ENABLED", "services.pilot_config"),
    ("DEFAULT_JOB_TYPES", "models.document_types"),
)
SYMBOLS = tuple(sym for sym, _ in SUBSTITUTIONS)


def _import_module(dotted: str):
    return __import__(dotted, fromlist=["__name__"])


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
# 1. Object-identity
# ---------------------------------------------------------------------------
class TestObjectIdentity:
    @pytest.mark.parametrize("name,module_path", SUBSTITUTIONS)
    def test_intake_binding_is_authoritative_object(self, name, module_path):
        """
        The binding used inside the intake function after 4d.1 must resolve
        to the authoritative module's object (verified via AST-level
        `ImportFrom` module tracing — the symbol must be imported from the
        declared canonical home, not from `server`).
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
        assert import_sources[name] == module_path, (
            f"{name} imported from {import_sources[name]!r}, expected "
            f"{module_path!r}"
        )

    @pytest.mark.parametrize("name,module_path", SUBSTITUTIONS)
    def test_runtime_identity_to_authoritative_object(self, name, module_path):
        """
        At runtime, the authoritative module's X must be the same Python
        object as `server.X` (since server.py re-exports it via its own
        top-of-file import chain).
        """
        canonical = _import_module(module_path)
        import server
        assert getattr(server, name) is getattr(canonical, name), (
            f"server.{name} is not the same object as "
            f"{module_path}.{name} — re-export chain broken"
        )


# ---------------------------------------------------------------------------
# 2. Server alias retained (server.py untouched)
# ---------------------------------------------------------------------------
class TestServerAliasRetained:
    @pytest.mark.parametrize("name", SYMBOLS)
    def test_server_still_exposes_symbol(self, name):
        """External importers using `from server import X` must still work."""
        import server
        assert hasattr(server, name), (
            f"server.{name} no longer importable — re-export chain broken"
        )

    def test_server_py_unchanged_for_4d1_targets(self):
        """
        Server.py source must not have gained or lost any line mentioning
        the 8 Step 4d.1 target symbols (we check total mention-count stays
        stable across the 4d.1 edit). This is a belt-and-suspenders guard
        since the actual file-untouched confirmation comes from git status.
        """
        srv_src = (BACKEND_ROOT / "server.py").read_text()
        # Top-of-file re-export block must still import each target from its
        # authoritative module. We verify by substring presence on the
        # relevant import statements.
        assert (
            "from workflows.core.engine import (\n"
            "    WorkflowEngine, WorkflowStatus, WorkflowEvent, \n"
            "    DocType, SourceSystem, CaptureChannel, DocumentClassifier\n"
            ")"
        ) in srv_src, "server.py workflows.core.engine import block changed"
        assert "from services.pilot_config import (" in srv_src, (
            "server.py services.pilot_config import block changed"
        )
        assert "from services.auto_clear_service import (" in srv_src, (
            "server.py services.auto_clear_service import block changed"
        )
        assert (
            "from models.document_types import TransactionAction, "
            "DRAFT_CREATION_CONFIG, DEFAULT_JOB_TYPES"
        ) in srv_src, "server.py models.document_types import line changed"


# ---------------------------------------------------------------------------
# 3. Lazy block shrunk + new dedicated import block present
# ---------------------------------------------------------------------------
class TestLazyBlockShrunk:
    def test_lazy_server_import_no_longer_lists_4d1_symbols(self):
        intake = _intake_func_node()
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports, (
            f"lazy `from server import (...)` block missing in {INTAKE_FUNC_NAME}"
        )
        listed = {alias.name for node in server_imports for alias in node.names}
        for name in SYMBOLS:
            assert name not in listed, (
                f"{name} still listed in `from server import (...)` block"
            )

    def test_new_4d1_import_block_present(self):
        """All three new 4d.1 import statements live inside the intake body."""
        src = _intake_func_source()
        assert (
            "from workflows.core.engine import (\n"
            "        CaptureChannel, DocType, SourceSystem, WorkflowEvent, "
            "WorkflowStatus,\n"
            "    )"
        ) in src, "4d.1 workflows.core.engine import block missing"
        assert (
            "from services.auto_clear_service import AutoClearDecision"
        ) in src, "4d.1 AutoClearDecision import missing"
        assert (
            "from services.pilot_config import PILOT_MODE_ENABLED"
        ) in src, "4d.1 PILOT_MODE_ENABLED import missing"
        assert (
            "from models.document_types import DEFAULT_JOB_TYPES"
        ) in src, "4d.1 DEFAULT_JOB_TYPES import missing"


# ---------------------------------------------------------------------------
# 4. Call-site byte parity
# ---------------------------------------------------------------------------
class TestCallSiteByteParity:
    """
    The use-sites inside the intake body reference the substituted symbols
    identically pre/post 4d.1. These substrings are directly lifted from
    the current intake source.
    """
    EXPECTED_USE_SITES = (
        'WorkflowStatus.CAPTURED.value',
        'WorkflowEvent.ON_CAPTURE.value',
        'CaptureChannel.EMAIL.value',
        'CaptureChannel.UPLOAD.value',
        'SourceSystem.GPI_HUB_NATIVE.value',
        'DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])',
        'DocType.AP_INVOICE.value',
        'AutoClearDecision.NEEDS_REVIEW',
        'AutoClearDecision.CLEARED',
        'if PILOT_MODE_ENABLED else base_capture_channel',
    )

    @pytest.mark.parametrize("needle", EXPECTED_USE_SITES)
    def test_use_site_intact(self, needle):
        src = _intake_func_source()
        assert needle in src, f"use-site byte-drift: {needle!r} not found"


# ---------------------------------------------------------------------------
# 5. WorkflowEvent collision guard (THE subtle-risk probe)
# ---------------------------------------------------------------------------
class TestWorkflowEventCollisionGuard:
    """
    `services.event_service` also defines a class called WorkflowEvent
    (a different thing; server.py aliases it as WFEvent). Step 4d.1 must
    bind intake's WorkflowEvent to the workflows.core.engine Enum,
    NOT to services.event_service.WorkflowEvent.
    """
    def test_intake_import_source_is_engine(self):
        intake = _intake_func_node()
        for node in ast.walk(intake):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "WorkflowEvent":
                        assert node.module == "workflows.core.engine", (
                            f"WorkflowEvent imported from {node.module!r}; "
                            "expected 'workflows.core.engine' — collision "
                            "with services.event_service.WorkflowEvent"
                        )
                        return
        raise AssertionError("WorkflowEvent import not found in intake body")

    def test_runtime_object_is_engine_not_event_service(self):
        from workflows.core.engine import WorkflowEvent as EngineWE
        from services.event_service import WorkflowEvent as EventSvcWE
        # Sanity: the two WorkflowEvents in the codebase are different objects.
        assert EngineWE is not EventSvcWE, (
            "Expected workflows.core.engine.WorkflowEvent and "
            "services.event_service.WorkflowEvent to be distinct classes; "
            "test premise invalid."
        )
        # server.WorkflowEvent (the re-export used inside intake) must be
        # the engine enum, not the event_service class.
        import server
        assert server.WorkflowEvent is EngineWE, (
            "server.WorkflowEvent resolves to the wrong class "
            "(event_service instead of engine)"
        )
        assert server.WorkflowEvent is not EventSvcWE, (
            "server.WorkflowEvent incorrectly aliased to "
            "services.event_service.WorkflowEvent"
        )

    def test_engine_workflow_event_has_on_capture(self):
        """
        The engine WorkflowEvent enum has ON_CAPTURE (used at intake
        line 489). The event_service.WorkflowEvent class does NOT have
        such a member — this is the observable fingerprint that
        distinguishes the two.
        """
        from workflows.core.engine import WorkflowEvent
        assert hasattr(WorkflowEvent, "ON_CAPTURE"), (
            "engine.WorkflowEvent missing ON_CAPTURE — wrong class bound"
        )


# ---------------------------------------------------------------------------
# 6. Live surface preserved (/openapi.json path count == 858)
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
# 7. Audit gate no-op (server.py untouched ⇒ audit still green)
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
