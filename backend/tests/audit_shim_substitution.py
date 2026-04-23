"""Shim-substitution classifier — reusable pre-sign audit for Step 4c tiers.

Invoked by:
  - Per-tier pre-change declarations (manual run) to produce empirical proof
    before asking for sign-off.
  - The per-tier parity test suites (Class A + Class F) to re-prove the
    result at test time.

Invocation:
  python -m backend.tests.audit_shim_substitution

CLI returns:
  exit 0 — every helper in HELPERS classifies as IDENTITY or THIN_SHIM with
           resolves_to_svc=True.
  exit 1 — at least one helper is DRIFTED; tier must be split before sign-off.

Classifier verdicts:
  IDENTITY   — ``from server import X is services.<home>.X`` (same object).
  THIN_SHIM  — server.py version is a 1-statement-after-docstring function
               of shape ``return [await] <call>`` where <call> resolves
               (either via eval in module globals or via a local
               ``from services.<home> import Y [as alias]``) to ``svc_fn``.
  DRIFTED    — neither; do NOT substitute.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from typing import Any


# Default helper list — the full Step 4c audit set. Tier consumers import
# HELPERS_TIER_N for their specific subset.
HELPERS_ALL: list[tuple[str, str]] = [
    # Tier 1 (Step 4c.1 — landed)
    ("compute_ap_normalized_fields", "services.document_intel_helpers"),
    ("compute_ap_validation", "services.ap_computation"),
    # Tier 2 (Step 4c.2)
    ("classify_document_with_ai", "services.document_intel_helpers"),
    ("make_automation_decision", "services.document_intel_helpers"),
    ("classify_document_type", "services.classification_helpers"),
    ("create_sharing_link", "services.sharepoint_service"),
    # Tier 3 (Step 4c.3 — future)
    ("lookup_vendor_alias", "services.vendor_matching"),
    ("check_duplicate_document", "services.vendor_matching"),
]

HELPERS_TIER_2: list[tuple[str, str]] = [
    ("classify_document_with_ai", "services.document_intel_helpers"),
    ("make_automation_decision", "services.document_intel_helpers"),
    ("classify_document_type", "services.classification_helpers"),
    ("create_sharing_link", "services.sharepoint_service"),
]


def classify_shim(srv_fn, svc_fn) -> tuple[str, dict[str, Any]]:
    """Return (verdict, details)."""
    if srv_fn is svc_fn:
        return "IDENTITY", {"same_object": True}

    try:
        src = inspect.getsource(srv_fn)
        tree = ast.parse(src)
    except Exception as e:
        return "DRIFTED", {"reason": f"ast parse: {e}"}

    fn_node = tree.body[0]
    if not isinstance(fn_node, (ast.AsyncFunctionDef, ast.FunctionDef)):
        return "DRIFTED", {"reason": "not a function def"}

    stmts = fn_node.body
    # Strip leading docstring.
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]

    # Collect locally-imported aliases.
    local_imports: dict[str, tuple[str, str]] = {}
    for s in stmts:
        if isinstance(s, ast.ImportFrom) and s.module:
            for alias in s.names:
                local_imports[alias.asname or alias.name] = (s.module, alias.name)

    non_import = [s for s in stmts if not isinstance(s, (ast.ImportFrom, ast.Import))]
    if len(non_import) != 1:
        return "DRIFTED", {
            "reason": f"non-shim: {len(non_import)} non-import statements (expected 1 return)"
        }

    ret = non_import[0]
    if not isinstance(ret, ast.Return):
        return "DRIFTED", {"reason": f"non-shim: last stmt is {type(ret).__name__}"}

    call = ret.value
    if isinstance(call, ast.Await):
        call = call.value
    if not isinstance(call, ast.Call):
        return "DRIFTED", {"reason": f"non-shim return: {type(call).__name__}"}

    call_name = ast.unparse(call.func)

    # Priority 1: local-import alias match.
    if call_name in local_imports:
        module_name, orig_name = local_imports[call_name]
        try:
            imp_mod = importlib.import_module(module_name)
            resolved = getattr(imp_mod, orig_name, None)
        except Exception as e:
            return "DRIFTED", {"reason": f"import {module_name} failed: {e}"}
        if resolved is svc_fn:
            return "THIN_SHIM", {
                "call_target": call_name,
                "local_alias_of": f"{module_name}.{orig_name}",
                "resolves_to_svc": True,
                "srv_body_line_count": len(src.splitlines()),
            }
        return "DRIFTED", {
            "reason": "shim imports but resolves to different object",
            "resolved_id": id(resolved),
            "svc_fn_id": id(svc_fn),
        }

    # Priority 2: module-global resolution.
    mod_globals = getattr(inspect.getmodule(srv_fn), "__dict__", {})
    try:
        obj = eval(
            compile(ast.Expression(body=call.func), "<audit>", "eval"),
            mod_globals,
        )
    except Exception as e:
        return "DRIFTED", {"reason": f"could not resolve callable: {e}"}
    if obj is svc_fn:
        return "THIN_SHIM", {
            "call_target": call_name,
            "resolves_to_svc": True,
            "srv_body_line_count": len(src.splitlines()),
        }
    return "DRIFTED", {
        "reason": "call target is not svc_fn",
        "called_id": id(obj),
        "svc_fn_id": id(svc_fn),
    }


def audit(helpers: list[tuple[str, str]] | None = None) -> list[tuple[str, str, str, dict]]:
    """Run the classifier for each helper; return list of
    (helper_name, authoritative_home, verdict, details)."""
    if helpers is None:
        helpers = HELPERS_ALL

    import server

    results: list[tuple[str, str, str, dict]] = []
    for fn_name, home in helpers:
        try:
            svc_mod = importlib.import_module(home)
            srv_fn = getattr(server, fn_name, None)
            svc_fn = getattr(svc_mod, fn_name, None)
            if srv_fn is None or svc_fn is None:
                results.append(
                    (fn_name, home, "DRIFTED", {"reason": "not found on one side"})
                )
                continue
            verdict, details = classify_shim(srv_fn, svc_fn)
            results.append((fn_name, home, verdict, details))
        except Exception as e:
            results.append((fn_name, home, "DRIFTED", {"reason": f"exception: {e!r}"}))
    return results


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    tier = argv[0] if argv else "all"
    if tier == "2":
        helpers = HELPERS_TIER_2
    else:
        helpers = HELPERS_ALL

    results = audit(helpers)

    print(f"{'Helper':<32} {'Home':<45} {'Verdict':<12} Details")
    print("-" * 140)
    for fn, home, verdict, details in results:
        print(f"{fn:<32} {home:<45} {verdict:<12} {json.dumps(details)}")

    failing = [r for r in results if r[2] == "DRIFTED"]
    passing = [r for r in results if r[2] in ("IDENTITY", "THIN_SHIM")]
    print()
    print("=== DECISION CONSEQUENCE ===")
    print(f"  Passing ({len(passing)}): {[r[0] for r in passing]}")
    print(f"  Failing ({len(failing)}): {[r[0] for r in failing]}")

    return 0 if not failing else 1


if __name__ == "__main__":
    sys.exit(main())
