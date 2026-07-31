from __future__ import annotations

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent
SERVER = BACKEND / "server.py"
FACADE = BACKEND / "services" / "document_handlers.py"
DOCUMENTS = BACKEND / "routers" / "documents.py"
WORKFLOWS = BACKEND / "routers" / "workflows.py"
MAX_SERVER_LINES = 1773

REMOVED = {
    "upload_document",
    "retry_document",
    "resubmit_document",
    "link_document",
    "intake_document",
    "list_workflows",
    "get_workflow",
    "retry_workflow",
}


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def test_duplicate_server_handlers_are_absent():
    names = {
        node.name
        for node in parse(SERVER).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (names & REMOVED)


def test_document_facade_ownership_is_preserved():
    owners = {}
    for node in parse(FACADE).body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exposed = alias.asname or alias.name
                if exposed in REMOVED:
                    owners[exposed] = (node.module, alias.name)

    assert owners == {
        "upload_document": (
            "services.document_upload_service",
            "upload_document",
        ),
        "retry_document": (
            "services.document_retry_service",
            "retry_document",
        ),
        "resubmit_document": (
            "services.document_resubmit_service",
            "resubmit_document",
        ),
        "link_document": (
            "services.document_link_service",
            "link_document",
        ),
        "intake_document": (
            "services.document_intake_service",
            "intake_document",
        ),
    }


def test_workflow_router_ownership_is_preserved():
    routes = {}
    for node in parse(WORKFLOWS).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in {
            "list_workflows",
            "get_workflow",
            "retry_workflow",
        }:
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
                and decorator.func.attr in {"get", "post"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                routes[node.name] = (
                    decorator.func.attr.upper(),
                    decorator.args[0].value,
                )

    assert routes == {
        "list_workflows": ("GET", ""),
        "get_workflow": ("GET", "/{wf_id}"),
        "retry_workflow": ("POST", "/{wf_id}/retry"),
    }


def test_server_line_count_is_monotonic():
    count = sum(1 for _ in SERVER.open("r", encoding="utf-8"))
    assert count <= MAX_SERVER_LINES
