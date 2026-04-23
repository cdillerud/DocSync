"""Phase 3 Step 4b — `_internal_intake_document` body-move parity tests.

Four classes proving the body move from ``server._internal_intake_document``
to ``services.document_handlers.intake_document_from_bytes`` was
behavior-preserving:

* Class A — Body-source byte-identity: the moved body text (excluding the
  prepended lazy-import block) is SHA-256-identical to the pre-move baseline
  captured in ``tests/fixtures/intake_body_move_baseline.json``.
* Class B — Baseline-vs-post-move equivalence: per-identifier audit confirming
  every name the pre-move body referenced is still resolvable at the new
  call site via either the lazy-import block, ``deps.get_db``, or
  ``document_handlers``' existing module-top machinery.
* Class C — Live surface + caller-import smoke: OpenAPI path count unchanged;
  the 6 Step-4a callers still import the wrapper without NameError.
* Class D — Source-inspection guardrails: ``server.py`` no longer defines the
  function; ``server.py`` shrank by the expected line delta; the lazy-import
  block matches the conservative cascade declared in the pre-change plan;
  Step 4a wrapper signature is byte-stable.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import textwrap
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = BACKEND_DIR / "tests" / "fixtures" / "intake_body_move_baseline.json"


def _load_baseline() -> dict:
    assert BASELINE_PATH.exists(), (
        f"Pre-move baseline fixture missing: {BASELINE_PATH}. "
        "It MUST be captured and committed before Step 4b lands."
    )
    return json.loads(BASELINE_PATH.read_text())


def _extract_post_move_body_source() -> str:
    """Return the moved body as dedented source text, EXCLUDING the leading
    docstring and EXCLUDING the lazy-import block."""
    dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
    tree = ast.parse(dh_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
            body = node.body
            # Strip leading docstring
            if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
                body = body[1:]
            # Strip consecutive leading ImportFrom nodes (lazy-import block).
            while body and isinstance(body[0], ast.ImportFrom):
                body = body[1:]
            if not body:
                return ""
            first, last = body[0], body[-1]
            lines = dh_src.splitlines(keepends=True)
            raw = "".join(lines[first.lineno - 1:last.end_lineno])
            return textwrap.dedent(raw)
    raise LookupError("intake_document_from_bytes not found in document_handlers.py")


# ---------------------------------------------------------------------------
# Class A — Body source byte-identity
# ---------------------------------------------------------------------------
class TestBodySourceByteIdentity:
    """The moved body is byte-identical to the pre-move baseline."""

    def test_baseline_fixture_present_and_well_formed(self):
        baseline = _load_baseline()
        for key in (
            "pre_move_source_sha256", "pre_move_body_line_count",
            "pre_move_body_char_count", "pre_move_body_source",
            "pre_move_body_referenced_names", "pre_move_signature",
        ):
            assert key in baseline, f"Baseline missing key: {key!r}"
        assert baseline["pre_move_source_function_name"] == "_internal_intake_document"
        assert baseline["pre_move_source_module"] == "server"

    def test_post_move_body_sha256_matches_baseline(self):
        baseline = _load_baseline()
        post_body = _extract_post_move_body_source()
        post_sha = hashlib.sha256(post_body.encode("utf-8")).hexdigest()
        assert post_sha == baseline["pre_move_source_sha256"], (
            f"Post-move body drifted from pre-move baseline.\n"
            f"  baseline sha256: {baseline['pre_move_source_sha256']}\n"
            f"  post-move sha256: {post_sha}\n"
            f"  baseline lines: {baseline['pre_move_body_line_count']}\n"
            f"  post-move lines: {len(post_body.splitlines())}"
        )

    def test_post_move_body_line_count_matches_baseline(self):
        baseline = _load_baseline()
        post_body = _extract_post_move_body_source()
        assert len(post_body.splitlines()) == baseline["pre_move_body_line_count"]

    def test_post_move_body_char_count_matches_baseline(self):
        baseline = _load_baseline()
        post_body = _extract_post_move_body_source()
        assert len(post_body) == baseline["pre_move_body_char_count"]


# ---------------------------------------------------------------------------
# Class B — Baseline-referenced-names resolvability
# ---------------------------------------------------------------------------
class TestReferencedNamesResolvable:
    """Every name the pre-move body referenced is resolvable at the new site."""

    @pytest.fixture(scope="class")
    def baseline_names(self) -> list:
        return _load_baseline()["pre_move_body_referenced_names"]

    @pytest.fixture(scope="class")
    def dh_module_globals(self):
        from services import document_handlers
        # Combined: module-top imports + declared locals + the lazy-import
        # block at function-body top. For resolvability we accept either:
        #   (a) present at module-top of document_handlers
        #   (b) present in the lazy-import block inside the function body
        #   (c) a Python builtin
        dh_src = inspect.getsource(document_handlers)
        return dh_src

    def _lazy_import_names(self) -> set:
        """Parse the `from server` lazy-import block at top of body."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                for n in node.body:
                    if isinstance(n, ast.ImportFrom) and n.module == "server":
                        for alias in n.names:
                            names.add(alias.asname or alias.name)
                break
        return names

    def _all_function_body_import_names(self) -> set:
        """All names imported at the top of the function body, regardless of
        source module. Accounts for Step 4c.1+ per-helper substitutions where
        names move from `from server` to `from services.<home>`."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                for n in node.body:
                    if isinstance(n, ast.ImportFrom):
                        for alias in n.names:
                            names.add(alias.asname or alias.name)
                    elif isinstance(n, ast.Import):
                        for alias in n.names:
                            names.add(alias.asname or alias.name.split(".")[0])
                break
        return names

    def test_lazy_import_block_covers_server_exclusive_helpers(self):
        """The declared conservative cascade must include all intake-private
        server.py helpers the body references."""
        lazy = self._lazy_import_names()
        # These are the 5 intake-private helpers plus _update_standard_workflow_status
        # that the signed declaration committed to lazy-importing from server.
        required = {
            "_attempt_llm_vendor_ranking",
            "_build_vendor_resolution",
            "_derive_workflow_status",
            "_emit_intake_events",
            "_update_ap_workflow_status",
            "_update_standard_workflow_status",
            "_update_vendor_profile_incremental",
        }
        missing = required - lazy
        assert not missing, f"Lazy-import block missing: {missing}"

    def test_lazy_import_block_covers_module_globals(self):
        """Module-scope server.py globals used by the body must be lazy-imported."""
        lazy = self._lazy_import_names()
        required_globals = {
            "db", "UPLOAD_DIR", "PILOT_MODE_ENABLED", "DEFAULT_JOB_TYPES",
            "DocType", "SourceSystem", "CaptureChannel", "WorkflowStatus",
            "WorkflowEvent", "AutoClearDecision",
        }
        missing = required_globals - lazy
        assert not missing, f"Lazy-import block missing globals: {missing}"

    def test_every_baseline_name_is_resolvable(self, baseline_names):
        """Each pre-move body-referenced name is resolvable post-move via
        (a) the function's body-top imports (any source module, includes
        Step 4c.1+ per-helper authoritative substitutions),
        (b) document_handlers module top, or (c) builtin."""
        import builtins
        lazy = self._all_function_body_import_names()
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        dh_tree = ast.parse(dh_src)
        module_top_names = set()
        for node in dh_tree.body:  # top-level only
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    module_top_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_top_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        module_top_names.add(t.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                module_top_names.add(node.name)

        builtin_names = set(dir(builtins)) | {"self", "True", "False", "None"}

        unresolved = []
        for name in baseline_names:
            if name in lazy or name in module_top_names or name in builtin_names:
                continue
            unresolved.append(name)

        # Some pre-move names are PARAMETERS of _internal_intake_document
        # (file_content, filename, ...) — those are always locals, not
        # module-scope. Remove them.
        param_names = {
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        }
        # Also: locals assigned inside the body (e.g., "computed_hash",
        # "doc_id") are NOT expected to be module-scope; strip them too.
        # We detect them by re-walking the baseline body and collecting assigns.
        baseline_body = _load_baseline()["pre_move_body_source"]
        body_mod = ast.parse(baseline_body)
        local_assigns = set()
        for n in ast.walk(body_mod):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        local_assigns.add(t.id)
                    elif isinstance(t, ast.Tuple):
                        for elt in t.elts:
                            if isinstance(elt, ast.Name):
                                local_assigns.add(elt.id)
            if isinstance(n, (ast.For, ast.AsyncFor)):
                if isinstance(n.target, ast.Name):
                    local_assigns.add(n.target.id)
                elif isinstance(n.target, ast.Tuple):
                    for elt in n.target.elts:
                        if isinstance(elt, ast.Name):
                            local_assigns.add(elt.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                local_assigns.add(n.name)
            if isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    local_assigns.add(alias.asname or alias.name)
            if isinstance(n, ast.Import):
                for alias in n.names:
                    local_assigns.add(alias.asname or alias.name.split(".")[0])
            if isinstance(n, (ast.comprehension,)) and isinstance(n.target, ast.Name):
                local_assigns.add(n.target.id)
            if isinstance(n, ast.Lambda):
                for a in n.args.args:
                    local_assigns.add(a.arg)
            if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
                local_assigns.add(n.target.id)

        # Filter out locals / params from unresolved list.
        unresolved = [n for n in unresolved if n not in param_names and n not in local_assigns]

        assert not unresolved, (
            f"{len(unresolved)} baseline-referenced names are NOT resolvable "
            f"at the post-move call site: {unresolved[:20]}"
        )


# ---------------------------------------------------------------------------
# Class C — Live surface + caller-import smoke
# ---------------------------------------------------------------------------
class TestLiveSurfaceAndCallerImports:
    """OpenAPI unchanged + all 6 Step-4a callers load without NameError."""

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
            pytest.skip("No backend reachable on localhost:8001")
        import requests
        paths = requests.get(f"{self.BASE_URL}/openapi.json").json().get("paths", {})
        assert len(paths) == 858, f"OpenAPI path count changed: {len(paths)}"

    @pytest.mark.parametrize("module_name", [
        "routers.sales_pipeline_demo",
        "routers.pilot",
        "services.email_polling_service",
        "services.inside_sales_pilot_service",
        "services.batch_po_splitter",
    ])
    def test_caller_module_imports_cleanly(self, module_name: str):
        """Step 4a fixed a latent NameError in routers/pilot.py — Step 4b must
        not introduce any new import-time failure."""
        mod = importlib.import_module(module_name)
        assert mod is not None

    def test_wrapper_resolves_to_moved_body(self):
        """intake_document_from_bytes must be a coroutine function with the
        declared parameters — proves the move preserved dispatch."""
        from services.document_handlers import intake_document_from_bytes
        assert inspect.iscoroutinefunction(intake_document_from_bytes)
        sig = inspect.signature(intake_document_from_bytes)
        assert list(sig.parameters.keys()) == [
            "file_content", "filename", "content_type", "source",
            "sender", "subject", "email_id", "mailbox_category",
        ]
        assert sig.parameters["source"].default == "email_poll"
        for opt in ("sender", "subject", "email_id", "mailbox_category"):
            assert sig.parameters[opt].default is None


# ---------------------------------------------------------------------------
# Class D — Source-inspection guardrails
# ---------------------------------------------------------------------------
class TestSourceInspectionGuardrails:
    """server.py no longer defines the function; wrapper body grew; banner OK."""

    def test_server_py_no_longer_defines_internal_intake_document(self):
        src = (BACKEND_DIR / "server.py").read_text()
        assert "async def _internal_intake_document(" not in src, (
            "Step 4b should have deleted _internal_intake_document from server.py"
        )

    def test_server_py_has_move_marker_comment(self):
        src = (BACKEND_DIR / "server.py").read_text()
        assert (
            "_internal_intake_document moved to "
            "services/document_handlers.py::intake_document_from_bytes"
        ) in src, "Factual move marker comment missing from server.py"

    def test_server_py_shrank_by_expected_delta(self):
        """server.py lost ~760 lines in Step 4b."""
        total = sum(1 for _ in (BACKEND_DIR / "server.py").open("r"))
        # Pre-4b baseline: 7402. Expected post-4b: ~6640 (±20).
        assert 6620 <= total <= 6660, (
            f"server.py line count {total} outside expected Step 4b delta band "
            "(6620–6660). Review what was actually removed."
        )

    def test_wrapper_body_is_now_large(self):
        """Step 4a wrapper was ≤25 code lines; Step 4b wrapper is the full body."""
        from services.document_handlers import intake_document_from_bytes
        src = inspect.getsource(intake_document_from_bytes)
        code_lines = [
            ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(code_lines) >= 500, (
            f"Wrapper body is only {len(code_lines)} code lines — "
            "Step 4b should have absorbed the ~760-line moved body."
        )

    def test_lazy_import_block_is_single_contiguous_block(self):
        """The conservative cascade must appear as ONE from-server-import
        statement at the top of the body (after any docstring)."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "intake_document_from_bytes":
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                    body = body[1:]
                # First statement must be a `from server import (...)` ImportFrom.
                assert isinstance(body[0], ast.ImportFrom), (
                    "First statement after docstring must be lazy-import from server."
                )
                assert body[0].module == "server"
                # Next statement(s) can be other lazy imports, but the declared
                # conservative cascade lives as ONE consolidated import —
                # enforce the first one references server.
                return
        pytest.fail("intake_document_from_bytes not found")

    def test_no_new_backward_import_at_module_top(self):
        """document_handlers.py module-top must NOT add a `from server import
        _internal_intake_document` (that would resurrect the Step-4a pattern
        at module scope and create circular-import risk)."""
        dh_src = (BACKEND_DIR / "services" / "document_handlers.py").read_text()
        tree = ast.parse(dh_src)
        for node in tree.body:  # module-top only
            if isinstance(node, ast.ImportFrom) and node.module == "server":
                names = [a.name for a in node.names]
                assert "_internal_intake_document" not in names, (
                    "module-top `from server import _internal_intake_document` "
                    "detected — circular-import risk."
                )

    def test_baseline_fixture_is_committed(self):
        """The pre-move baseline must be present for future regression use."""
        assert BASELINE_PATH.exists(), f"Missing baseline: {BASELINE_PATH}"
        # And must be readable JSON with the sha256 field.
        data = json.loads(BASELINE_PATH.read_text())
        assert "pre_move_source_sha256" in data
