from pathlib import Path
import ast
import inspect
from unittest.mock import Mock

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_server_delegates_startup_maintenance_tasks():
    tree = ast.parse((BACKEND_DIR / "server.py").read_text())
    startup = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "startup"
    )
    imports = [
        alias.name
        for node in ast.walk(startup)
        if isinstance(node, ast.ImportFrom)
        and node.module == "services.lifecycle_scheduler_service"
        for alias in node.names
    ]
    calls = [
        node.func.id
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    ]

    for helper in (
        "start_startup_requeue_tasks",
        "start_pi_backfill_tasks",
    ):
        assert imports.count(helper) == 1
        assert calls.count(helper) == 1

    for scheduler in (
        "startup_requeue_not_run",
        "startup_backfill_pi_no",
    ):
        assert scheduler not in imports
        assert scheduler not in calls

    lines = {
        name: next(
            node.lineno
            for node in ast.walk(startup)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        )
        for name in (
            "start_startup_requeue_tasks",
            "start_status_sync_tasks",
            "start_startup_repair_tasks",
            "start_pi_backfill_tasks",
        )
    }
    assert (
        lines["start_startup_requeue_tasks"]
        < lines["start_status_sync_tasks"]
        < lines["start_startup_repair_tasks"]
        < lines["start_pi_backfill_tasks"]
    )


def test_startup_maintenance_runtime_ownership(monkeypatch):
    import services.lifecycle_scheduler_service as scheduler

    db = object()
    logger = Mock()
    resolver = object()
    registered = []

    requeue_marker = object()
    backfill_marker = object()
    requeue = Mock(return_value=requeue_marker)
    backfill = Mock(return_value=backfill_marker)

    monkeypatch.setattr(
        scheduler, "startup_requeue_not_run", requeue
    )
    monkeypatch.setattr(
        scheduler, "startup_backfill_pi_no", backfill
    )
    monkeypatch.setattr(
        scheduler.asyncio,
        "create_task",
        lambda coroutine: ("task", coroutine),
    )

    def register(task, *, name):
        registered.append((task, name))
        return task

    scheduler.start_startup_requeue_tasks(
        db=db,
        logger=logger,
        register_background_task=register,
        get_auto_resolve_service=resolver,
    )
    scheduler.start_pi_backfill_tasks(
        db=db,
        logger=logger,
        register_background_task=register,
    )

    assert registered == [
        (("task", requeue_marker), "startup_requeue_not_run"),
        (("task", backfill_marker), "startup_backfill_pi_no"),
    ]
    requeue.assert_called_once_with(
        db=db,
        logger=logger,
        get_auto_resolve_service=resolver,
    )
    backfill.assert_called_once_with(db=db, logger=logger)

    expected = {
        "start_startup_requeue_tasks": [
            "db",
            "logger",
            "register_background_task",
            "get_auto_resolve_service",
        ],
        "start_pi_backfill_tasks": [
            "db",
            "logger",
            "register_background_task",
        ],
    }
    for name, parameters in expected.items():
        signature = inspect.signature(getattr(scheduler, name))
        assert list(signature.parameters) == parameters
        assert all(
            value.kind is inspect.Parameter.KEYWORD_ONLY
            for value in signature.parameters.values()
        )
