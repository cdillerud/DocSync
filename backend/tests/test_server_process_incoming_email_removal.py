# Guardrails for removal of the dead server incoming-email pipeline.

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
SERVER_PATH = BACKEND_DIR / "server.py"
EMAIL_SERVICE_PATH = (
    BACKEND_DIR
    / "services"
    / "email_polling_service.py"
)
BYTES_INTAKE_PATH = (
    BACKEND_DIR
    / "services"
    / "document_bytes_intake_service.py"
)
EXPECTED_SERVER_MIN = 3038
EXPECTED_SERVER_MAX = 3058


def _tree(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_names(path: Path):
    return {
        node.name
        for node in _tree(path).body
        if isinstance(
            node,
            (
                ast.ClassDef,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }


def test_dead_server_incoming_email_pipeline_is_absent():
    names = _top_level_names(SERVER_PATH)

    assert "process_incoming_email" not in names

    assert "record_mail_intake_log" in names
    assert "check_duplicate_mail_intake" in names
    assert "should_skip_attachment" in names
    assert "poll_mailbox_for_attachments" in names
    assert "poll_mailbox_for_documents" in names


def test_authoritative_email_service_is_complete():
    names = _top_level_names(EMAIL_SERVICE_PATH)

    required = {
        "fetch_email_with_attachments",
        "record_mail_intake_log",
        "check_duplicate_mail_intake",
        "should_skip_attachment",
        "poll_mailbox_for_attachments",
        "poll_mailbox_for_documents",
        "email_polling_worker",
        "dynamic_mailbox_polling_worker",
    }

    assert not (required - names)
    assert BYTES_INTAKE_PATH.exists()


def test_authoritative_email_service_uses_safe_intake_path():
    tree = _tree(EMAIL_SERVICE_PATH)

    imports = 0
    intake_calls = 0
    dedup_calls = 0
    filter_calls = 0
    log_calls = 0

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            == "services.document_bytes_intake_service"
        ):
            imports += sum(
                1
                for alias in node.names
                if alias.name
                == "intake_document_from_bytes"
            )

        if not isinstance(node, ast.Call):
            continue

        if (
            isinstance(node.func, ast.Name)
            and node.func.id
            == "intake_document_from_bytes"
        ):
            intake_calls += 1

        if (
            isinstance(node.func, ast.Name)
            and node.func.id
            == "check_duplicate_mail_intake"
        ):
            dedup_calls += 1

        if (
            isinstance(node.func, ast.Name)
            and node.func.id
            == "should_skip_attachment"
        ):
            filter_calls += 1

        if (
            isinstance(node.func, ast.Name)
            and node.func.id
            == "record_mail_intake_log"
        ):
            log_calls += 1

    assert imports >= 1
    assert intake_calls >= 1
    assert dedup_calls >= 1
    assert filter_calls >= 1
    assert log_calls >= 1


def test_no_production_module_imports_removed_function():
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
                    == "process_incoming_email"
                ):
                    violations.append(
                        "server.py loads process_incoming_email "
                        f"at line {node.lineno}"
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
                    if alias.name == "process_incoming_email":
                        violations.append(
                            f"{path.relative_to(BACKEND_DIR)} "
                            "imports process_incoming_email from server"
                        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and node.attr == "process_incoming_email"
            ):
                violations.append(
                    f"{path.relative_to(BACKEND_DIR)} "
                    f"references {node.value.id}."
                    "process_incoming_email"
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

    assert EXPECTED_SERVER_MIN <= total <= EXPECTED_SERVER_MAX
