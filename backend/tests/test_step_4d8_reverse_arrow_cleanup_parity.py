"""
Phase 3 Step 4d.8 — Reverse-Arrow Cleanup Parity Suite

Closes the temporary architectural debt introduced by Step 4d.7. Two
sub-tasks:

A. ``AUTO_CREATE_SALES_ORDER_ENABLED`` re-homed: the canonical home is
   ``services.auto_post_service:477`` (server.py:248 only re-exports it).
   Pure import-source swap in ``workflow_status.py`` prelude — no code
   move.

B. ``_run_pilot_enrichment`` cluster co-migrated: this server-private
   helper plus its only callee ``_maybe_stage_inventory_xls`` (which is
   referenced by bare name in ``_run_pilot_enrichment``'s verbatim body)
   are moved to a new sibling module
   ``workflows/document_capture/rules/pilot_enrichment.py``. Both
   server.py sites are retained as 4-statement compatibility shims.

Architectural milestone: post-4d.8, ``workflow_status.py`` has ZERO
``from server import ...`` lines.

18 probes.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

WORKFLOW_STATUS_PATH = (
    BACKEND_ROOT / "workflows" / "document_capture" / "rules"
    / "workflow_status.py"
)
PILOT_ENRICHMENT_PATH = (
    BACKEND_ROOT / "workflows" / "document_capture" / "rules"
    / "pilot_enrichment.py"
)

PILOT_ENRICHMENT_MODULE = "workflows.document_capture.rules.pilot_enrichment"
AUTO_POST_MODULE = "services.auto_post_service"

# Goldens captured immediately before the 4d.8 cluster move.
RUN_PILOT_ENRICHMENT_PRE_4D8_SHA256 = (
    "5df7ab45abd6c089efdf134da84ab6d0ed8711ddc85626ffc4187486fa7ea9c9"
)
RUN_PILOT_ENRICHMENT_PRE_4D8_LEN = 1563

MAYBE_STAGE_INVENTORY_XLS_PRE_4D8_SHA256 = (
    "268aec99cab54c346599999985dc6d2aa2afb4f0dadeb31f1a3d80e832047a73"
)
MAYBE_STAGE_INVENTORY_XLS_PRE_4D8_LEN = 3613

# Re-checked golden of the moved 4d.7 body (must remain stable through
# Step 4d.8 — only the prelude line changes; the function body is
# untouched). Captured at 4d.7 close.
UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_SHA256 = (
    "21c2a1ca5418d0b54048c85841dd96e59b573e4827697709016ff9251f8dc7f2"
)
UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_LEN = 21160

# Declared minimal prelude for the new pilot_enrichment.py module.
PILOT_PRELUDE_IMPORT_FROMS = {
    ("deps", frozenset({"get_db"})),
}
PILOT_PRELUDE_PLAIN_IMPORTS = {"logging"}


# ---------------------------------------------------------------------------
# 1. workflow_status.py has zero `from server` imports
# ---------------------------------------------------------------------------
class TestWorkflowStatusZeroReverseArrows:
    def test_no_from_server_imports_in_workflow_status(self):
        tree = ast.parse(WORKFLOW_STATUS_PATH.read_text())
        server_imports = [
            n for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports == [], (
            f"workflow_status.py still has {len(server_imports)} "
            f"`from server import ...` line(s); 4d.8 milestone not met."
        )


# ---------------------------------------------------------------------------
# 2. workflow_status.py prelude updated correctly (replacement imports)
# ---------------------------------------------------------------------------
class TestWorkflowStatusPreludeUpdated:
    def _collect_froms(self):
        tree = ast.parse(WORKFLOW_STATUS_PATH.read_text())
        return {
            (n.module, frozenset((a.name, a.asname) for a in n.names))
            for n in tree.body if isinstance(n, ast.ImportFrom)
        }

    def test_auto_post_service_includes_AUTO_CREATE_SALES_ORDER_ENABLED(self):
        froms = self._collect_froms()
        for mod, name_alias_pairs in froms:
            if mod == AUTO_POST_MODULE:
                names = {n for (n, _) in name_alias_pairs}
                assert "AUTO_CREATE_SALES_ORDER_ENABLED" in names, (
                    f"`from {AUTO_POST_MODULE} import ...` does not include "
                    f"AUTO_CREATE_SALES_ORDER_ENABLED; got {sorted(names)}"
                )
                return
        raise AssertionError(
            f"no `from {AUTO_POST_MODULE} import ...` line found"
        )

    def test_pilot_enrichment_alias_import_present(self):
        froms = self._collect_froms()
        for mod, name_alias_pairs in froms:
            if mod == PILOT_ENRICHMENT_MODULE:
                assert ("run_pilot_enrichment", "_run_pilot_enrichment") in name_alias_pairs, (
                    f"expected `run_pilot_enrichment as _run_pilot_enrichment`, "
                    f"got {sorted(name_alias_pairs)}"
                )
                return
        raise AssertionError(
            f"no `from {PILOT_ENRICHMENT_MODULE} import ...` line found"
        )


# ---------------------------------------------------------------------------
# 3. workflow_status.py call site at line ~304 byte-identical
# ---------------------------------------------------------------------------
class TestWorkflowStatusCallSiteByteParity:
    def test_pilot_enrichment_call_site_intact(self):
        src = WORKFLOW_STATUS_PATH.read_text()
        assert "asyncio.create_task(_run_pilot_enrichment(doc_id))" in src, (
            "call site to `_run_pilot_enrichment` byte-parity lost"
        )


# ---------------------------------------------------------------------------
# 4. AUTO_CREATE_SALES_ORDER_ENABLED resolves to the canonical value
# ---------------------------------------------------------------------------
class TestAutoCreateFlagRuntimeIdentity:
    def test_workflow_status_flag_matches_canonical(self):
        from workflows.document_capture.rules import workflow_status as wf
        from services.auto_post_service import (
            AUTO_CREATE_SALES_ORDER_ENABLED as canonical,
        )
        assert wf.AUTO_CREATE_SALES_ORDER_ENABLED == canonical


# ---------------------------------------------------------------------------
# 5. _run_pilot_enrichment in workflow_status resolves to canonical
# ---------------------------------------------------------------------------
class TestRunPilotEnrichmentRuntimeIdentity:
    def test_workflow_status_alias_is_canonical(self):
        from workflows.document_capture.rules import workflow_status as wf
        from workflows.document_capture.rules import pilot_enrichment as pe
        assert wf._run_pilot_enrichment is pe.run_pilot_enrichment


# ---------------------------------------------------------------------------
# 6. New module exists with declared minimal prelude
# ---------------------------------------------------------------------------
class TestPilotEnrichmentModulePrelude:
    def test_module_file_exists(self):
        assert PILOT_ENRICHMENT_PATH.exists(), (
            f"{PILOT_ENRICHMENT_PATH} not created"
        )

    def test_imports_match_declared_minimal_prelude(self):
        tree = ast.parse(PILOT_ENRICHMENT_PATH.read_text())
        module_level = [
            n for n in tree.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        observed_froms = {
            (n.module, frozenset(a.name for a in n.names))
            for n in module_level if isinstance(n, ast.ImportFrom)
        }
        observed_plain = {
            a.name for n in module_level
            if isinstance(n, ast.Import) for a in n.names
        }
        assert observed_froms == PILOT_PRELUDE_IMPORT_FROMS, (
            f"pilot_enrichment.py `from` import drift:\n"
            f"  observed: {sorted(observed_froms)}\n"
            f"  declared: {sorted(PILOT_PRELUDE_IMPORT_FROMS)}"
        )
        assert observed_plain == PILOT_PRELUDE_PLAIN_IMPORTS, (
            f"pilot_enrichment.py plain import drift:\n"
            f"  observed: {sorted(observed_plain)}\n"
            f"  declared: {sorted(PILOT_PRELUDE_PLAIN_IMPORTS)}"
        )

    def test_pilot_enrichment_has_zero_from_server_imports(self):
        tree = ast.parse(PILOT_ENRICHMENT_PATH.read_text())
        server_imports = [
            n for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert server_imports == [], (
            f"pilot_enrichment.py contains {len(server_imports)} reverse-arrow"
            f" `from server` import line(s); should be zero"
        )


# ---------------------------------------------------------------------------
# 7. New module surface — exactly one public callable + one private helper
# ---------------------------------------------------------------------------
class TestPilotEnrichmentSurface:
    def test_exactly_one_public_callable(self):
        from workflows.document_capture.rules import pilot_enrichment as pe
        publics = [
            n for n in dir(pe)
            if not n.startswith("_")
            and callable(getattr(pe, n, None))
            and getattr(getattr(pe, n), "__module__", "") == PILOT_ENRICHMENT_MODULE
        ]
        assert publics == ["run_pilot_enrichment"], (
            f"unexpected publics in pilot_enrichment: {publics}"
        )

    def test_private_helper_present(self):
        from workflows.document_capture.rules import pilot_enrichment as pe
        assert hasattr(pe, "_maybe_stage_inventory_xls")
        assert inspect.iscoroutinefunction(pe._maybe_stage_inventory_xls)
        assert pe._maybe_stage_inventory_xls.__module__ == PILOT_ENRICHMENT_MODULE


# ---------------------------------------------------------------------------
# 8. run_pilot_enrichment body byte-identical to golden modulo def rename
# ---------------------------------------------------------------------------
class TestRunPilotEnrichmentBodyByteIdentical:
    def test_source_matches_golden(self):
        from workflows.document_capture.rules import pilot_enrichment as pe
        new_src = inspect.getsource(pe.run_pilot_enrichment)
        reverted = new_src.replace(
            "async def run_pilot_enrichment(",
            "async def _run_pilot_enrichment(",
            1,
        )
        assert len(reverted) == RUN_PILOT_ENRICHMENT_PRE_4D8_LEN, (
            f"length drift: got {len(reverted)}, "
            f"expected {RUN_PILOT_ENRICHMENT_PRE_4D8_LEN}"
        )
        sha = hashlib.sha256(reverted.encode()).hexdigest()
        assert sha == RUN_PILOT_ENRICHMENT_PRE_4D8_SHA256, (
            f"SHA drift: {sha}"
        )


# ---------------------------------------------------------------------------
# 9. _maybe_stage_inventory_xls body byte-identical to golden (no rename)
# ---------------------------------------------------------------------------
class TestMaybeStageInventoryXlsBodyByteIdentical:
    def test_source_matches_golden(self):
        from workflows.document_capture.rules import pilot_enrichment as pe
        new_src = inspect.getsource(pe._maybe_stage_inventory_xls)
        assert len(new_src) == MAYBE_STAGE_INVENTORY_XLS_PRE_4D8_LEN, (
            f"length drift: got {len(new_src)}, "
            f"expected {MAYBE_STAGE_INVENTORY_XLS_PRE_4D8_LEN}"
        )
        sha = hashlib.sha256(new_src.encode()).hexdigest()
        assert sha == MAYBE_STAGE_INVENTORY_XLS_PRE_4D8_SHA256, (
            f"SHA drift: {sha}"
        )


# ---------------------------------------------------------------------------
# 10+11+12. server.py shims
# ---------------------------------------------------------------------------
def _server_shim_node(name):
    import server
    tree = ast.parse(inspect.getsource(server))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"server.{name} not found")


class TestServerShimsStructurallyIntact:
    def test_run_pilot_enrichment_shim_is_async_def_with_correct_body(self):
        node = _server_shim_node("_run_pilot_enrichment")
        assert isinstance(node, ast.AsyncFunctionDef)
        executable = [
            s for s in node.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        kinds = [type(s).__name__ for s in executable]
        assert kinds == ["ImportFrom", "Return"], (
            f"_run_pilot_enrichment shim drift: {kinds}"
        )

    def test_maybe_stage_inventory_xls_shim_is_async_def_with_correct_body(self):
        node = _server_shim_node("_maybe_stage_inventory_xls")
        assert isinstance(node, ast.AsyncFunctionDef)
        executable = [
            s for s in node.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        kinds = [type(s).__name__ for s in executable]
        assert kinds == ["ImportFrom", "Return"], (
            f"_maybe_stage_inventory_xls shim drift: {kinds}"
        )


class TestServerShimsRetained:
    def test_server_still_exposes_both_names(self):
        import server
        assert hasattr(server, "_run_pilot_enrichment")
        assert hasattr(server, "_maybe_stage_inventory_xls")
        assert inspect.iscoroutinefunction(server._run_pilot_enrichment)
        assert inspect.iscoroutinefunction(server._maybe_stage_inventory_xls)


# ---------------------------------------------------------------------------
# 13. Reverse-arrow safety — subprocess imports succeed in either order
# ---------------------------------------------------------------------------
class TestReverseArrowImportSafety:
    def test_pilot_first_then_server(self):
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            import workflows.document_capture.rules.pilot_enrichment as pe
            import server
            assert hasattr(pe, 'run_pilot_enrichment')
            assert hasattr(server, '_run_pilot_enrichment')
            print('OK')
        """) % str(BACKEND_ROOT)
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert r.returncode == 0, (
            f"import order pilot→server failed:\n{r.stderr[-500:]}"
        )
        assert "OK" in r.stdout

    def test_server_first_then_pilot(self):
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, %r)
            import server
            import workflows.document_capture.rules.pilot_enrichment as pe
            assert hasattr(pe, 'run_pilot_enrichment')
            assert hasattr(server, '_run_pilot_enrichment')
            print('OK')
        """) % str(BACKEND_ROOT)
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert r.returncode == 0, (
            f"import order server→pilot failed:\n{r.stderr[-500:]}"
        )
        assert "OK" in r.stdout


# ---------------------------------------------------------------------------
# 14. workflow_status.py 4d.7 body still byte-identical (only prelude changed)
# ---------------------------------------------------------------------------
class TestWorkflowStatusBodyUnchanged:
    def test_update_standard_workflow_status_body_byte_identical_to_4d7_golden(
        self,
    ):
        from workflows.document_capture.rules import workflow_status as wf
        new_src = inspect.getsource(wf.update_standard_workflow_status)
        reverted = new_src.replace(
            "async def update_standard_workflow_status(",
            "async def _update_standard_workflow_status(",
            1,
        )
        assert len(reverted) == UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_LEN
        sha = hashlib.sha256(reverted.encode()).hexdigest()
        assert sha == UPDATE_STD_WORKFLOW_STATUS_PRE_4D7_SHA256, (
            f"4d.7 body byte-identity broken by 4d.8 prelude edit: {sha}"
        )


# ---------------------------------------------------------------------------
# 15. AP-Invoice siblings untouched
# ---------------------------------------------------------------------------
class TestAPInvoiceSiblingsUntouched:
    def test_ap_invoice_rule_modules_unchanged(self):
        from workflows.ap_invoice.rules import vendor_profile, workflow_status as ap_wf
        for mod, expected_name, mod_path in [
            (vendor_profile, "update_vendor_profile_incremental",
                "workflows.ap_invoice.rules.vendor_profile"),
            (ap_wf, "update_ap_workflow_status",
                "workflows.ap_invoice.rules.workflow_status"),
        ]:
            publics = [
                n for n in dir(mod)
                if not n.startswith("_")
                and callable(getattr(mod, n, None))
                and getattr(getattr(mod, n), "__module__", "") == mod_path
            ]
            assert publics == [expected_name], (
                f"AP sibling {mod_path} drift: {publics}"
            )


# ---------------------------------------------------------------------------
# 16. document_handlers.py lazy `from server` tuple unchanged at 2 entries
# ---------------------------------------------------------------------------
class TestIntakeLazyTupleUnchanged:
    def test_lazy_tuple_still_two_entries(self):
        from services import document_handlers
        tree = ast.parse(inspect.getsource(document_handlers))
        intake = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "intake_document_from_bytes"
        )
        server_imports = [
            n for n in ast.walk(intake)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert len(server_imports) == 1
        names = {a.name for a in server_imports[0].names}
        assert names == {
            "_attempt_llm_vendor_ranking",
            "_build_vendor_resolution",
        }, f"intake lazy tuple drift: {sorted(names)}"


# ---------------------------------------------------------------------------
# 17. Live surface
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "http://localhost:8001"
).rstrip("/")


class TestLiveSurfaceAndAudit:
    def test_backend_reachable(self):
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=5)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200

    def test_openapi_path_count_858(self):
        try:
            r = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
        except requests.exceptions.RequestException as exc:
            pytest.skip(f"backend not reachable: {exc}")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert len(paths) == 858, f"OpenAPI path count drift: {len(paths)}"

    def test_audit_script_reports_eight_passing(self):
        script = BACKEND_ROOT / "tests" / "audit_shim_substitution.py"
        if not script.exists():
            pytest.skip("audit script missing")
        env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(BACKEND_ROOT),
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0
        assert "Passing (8):" in r.stdout


# ---------------------------------------------------------------------------
# 18. Architectural milestone — workflow_status.py has zero `from server`
# ---------------------------------------------------------------------------
class TestArchitecturalMilestone:
    def test_workflow_status_is_reverse_arrow_free(self):
        """
        The architectural goal of Step 4d.8: the canonical
        ``workflow_status.py`` module must contain ZERO ``from server
        import ...`` statements at module level. The two reverse-arrow
        names introduced by 4d.7 (``_run_pilot_enrichment``,
        ``AUTO_CREATE_SALES_ORDER_ENABLED``) are now bound from their
        canonical homes (``services.auto_post_service`` for the flag,
        ``workflows.document_capture.rules.pilot_enrichment`` for the
        helper).
        """
        tree = ast.parse(WORKFLOW_STATUS_PATH.read_text())
        offending = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module == "server"
        ]
        assert offending == [], (
            f"workflow_status.py still imports from server at {len(offending)} "
            f"site(s); 4d.8 milestone not met."
        )
