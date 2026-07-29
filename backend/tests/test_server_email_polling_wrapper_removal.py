# Guardrails for removal of dead server email-polling wrappers.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
SERVICE_PATH = (
    BACKEND_DIR
    / "services"
    / "email_polling_service.py"
)
EXPECTED_SERVER_MAX = 2991
WRAPPER_NAMES = {
    "record_mail_intake_log",
    "check_duplicate_mail_intake",
    "should_skip_attachment",
    "poll_mailbox_for_attachments",
    "poll_mailbox_for_documents",
}

WRAPPER_GLOBALS = {
    "_email_polling_lock",
    "SKIP_CONTENT_TYPES",
    "SKIP_FILENAME_PATTERNS",
}


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_functions(path: Path):
    return {
        node.name
        for node in _tree(path).body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }


def _top_level_assignments(path: Path):
    names = set()

    for node in _tree(path).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )

        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)

    return names


def test_dead_server_email_wrappers_and_globals_are_absent():
    functions = _top_level_functions(SERVER_PATH)
    assignments = _top_level_assignments(SERVER_PATH)

    assert not (WRAPPER_NAMES & functions)
    assert not (WRAPPER_GLOBALS & assignments)
    assert "_email_polling_task" in assignments


def test_authoritative_email_service_owns_all_functions():
    service_functions = _top_level_functions(SERVICE_PATH)

    assert not (WRAPPER_NAMES - service_functions)


def test_no_production_module_uses_removed_server_surface():
    violations = []

    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue

        try:
            tree = _tree(path)
        except (SyntaxError, UnicodeDecodeError):
            continue

        if path == SERVER_PATH:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id
                    in WRAPPER_NAMES | WRAPPER_GLOBALS
                ):
                    violations.append(
                        "server.py loads removed symbol "
                        f"{node.id} at line {node.lineno}"
                    )

            continue

        aliases = {"server"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server":
                        aliases.add(alias.asname or "server")

            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "server"
            ):
                for alias in node.names:
                    if (
                        alias.name
                        in WRAPPER_NAMES | WRAPPER_GLOBALS
                    ):
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)} "
                            f"imports {alias.name} from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr
                in WRAPPER_NAMES | WRAPPER_GLOBALS
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}.{node.attr}"
                )

    assert not violations, "\n".join(
        sorted(set(violations))
    )


def test_server_line_count_matches_cleanup_band():
    total = sum(
        1
        for _ in SERVER_PATH.open(
            "r",
            encoding="utf-8",
        )
    )

    assert total <= EXPECTED_SERVER_MAX
