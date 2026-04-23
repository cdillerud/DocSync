"""Phase 3 Step 4b — pre-move baseline capture script.

Captures the authoritative pre-move source of ``server._internal_intake_document``
using AST, into a deterministic JSON fixture used as the post-move parity
reference.

Run BEFORE landing the Step 4b body move:

    python -m backend.tests.capture_intake_body_baseline

Writes: ``backend/tests/fixtures/intake_body_move_baseline.json``

Stability: running this script twice in a row MUST produce byte-identical
output. Any drift means the source is unstable and the move MUST NOT proceed.

The fixture captures:
  - The function body source code (statements only, excluding the `async def`
    signature line and excluding leading docstring). Used for strict
    source-text post-move equivalence.
  - The ordered list of simple-name identifiers the body references
    (filtered to server.py module-scope names used at load time) — used by
    the Step 4b parity test Class D guardrails.
  - The function's signature parameter list + defaults.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import textwrap
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURE_PATH = BACKEND_DIR / "tests" / "fixtures" / "intake_body_move_baseline.json"


def _get_function_body_source(src_text: str, fn_name: str) -> str:
    """Return the body of ``async def fn_name`` as normalized source text.

    - Strips the signature line(s).
    - Strips the leading docstring (if any).
    - Preserves everything else verbatim (whitespace, comments, indentation).
    """
    tree = ast.parse(src_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            # body[0] may be a docstring Expr node — skip if so.
            body_nodes = node.body
            if (
                body_nodes
                and isinstance(body_nodes[0], ast.Expr)
                and isinstance(body_nodes[0].value, ast.Constant)
                and isinstance(body_nodes[0].value.value, str)
            ):
                body_nodes = body_nodes[1:]
            if not body_nodes:
                return ""
            first = body_nodes[0]
            last = body_nodes[-1]
            # Use ast end_lineno (exclusive end) + raw text extraction by line.
            lines = src_text.splitlines(keepends=True)
            # first.lineno and last.end_lineno are 1-indexed.
            start = first.lineno - 1
            end = last.end_lineno
            body = "".join(lines[start:end])
            return textwrap.dedent(body)
    raise LookupError(f"function {fn_name!r} not found")


def _collect_referenced_names(src_text: str, fn_name: str) -> list[str]:
    """Return sorted list of Name loads inside the function body."""
    tree = ast.parse(src_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            refs: set[str] = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    refs.add(n.id)
            return sorted(refs)
    raise LookupError(f"function {fn_name!r} not found")


def _signature_spec(src_text: str, fn_name: str) -> dict:
    tree = ast.parse(src_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fn_name:
            args = node.args
            positional = [a.arg for a in args.args]
            defaults = [ast.unparse(d) for d in args.defaults]
            kwonly = [a.arg for a in args.kwonlyargs]
            kwonly_defaults = [
                ast.unparse(d) if d else None for d in args.kw_defaults
            ]
            return {
                "positional": positional,
                "positional_defaults": defaults,
                "kwonly": kwonly,
                "kwonly_defaults": kwonly_defaults,
            }
    raise LookupError(f"function {fn_name!r} not found")


def capture() -> dict:
    server_py = BACKEND_DIR / "server.py"
    src = server_py.read_text()

    fn_name = "_internal_intake_document"
    body = _get_function_body_source(src, fn_name)
    refs = _collect_referenced_names(src, fn_name)
    sig = _signature_spec(src, fn_name)

    return {
        "pre_move_source_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "pre_move_body_line_count": len(body.splitlines()),
        "pre_move_body_char_count": len(body),
        "pre_move_body_source": body,
        "pre_move_body_referenced_names": refs,
        "pre_move_signature": sig,
        "pre_move_source_function_name": fn_name,
        "pre_move_source_module": "server",
    }


def main() -> int:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot_a = capture()
    snapshot_b = capture()
    # Stability check: running twice must produce identical output.
    if snapshot_a != snapshot_b:
        print("ERROR: baseline capture is unstable across runs.", file=sys.stderr)
        print("Step 4b MUST NOT proceed until the instability is understood.", file=sys.stderr)
        return 2
    FIXTURE_PATH.write_text(json.dumps(snapshot_a, indent=2, sort_keys=True) + "\n")
    print(f"wrote baseline fixture: {FIXTURE_PATH}")
    print(f"  body lines: {snapshot_a['pre_move_body_line_count']}")
    print(f"  body chars: {snapshot_a['pre_move_body_char_count']}")
    print(f"  body sha256: {snapshot_a['pre_move_source_sha256']}")
    print(f"  referenced names: {len(snapshot_a['pre_move_body_referenced_names'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
