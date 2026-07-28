from pathlib import Path
import ast
import inspect
from unittest.mock import Mock

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _startup_tree():
    tree = ast.parse(
        (BACKEND_DIR / "server.py").read_text()
    )
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "startup"
    )


def test_server_delegates_pilot_summary_task_ownership():
    startup = _startup_tree()

    lifecycle_imports = [
        alias.name
        for node in ast.walk(startup)
        if isinstance(node, ast.ImportFrom)
        and node.module
        == "services.lifecycle_scheduler_service"
        for alias in node.names
    ]

    calls = [
        node
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "start_pilot_summary_tasks"
    ]

    assert lifecycle_imports.count(
        "start_pilot_summary_tasks"
    ) == 1
    assert len(calls) == 1

    assert {
        keyword.arg: keyword.value.id
        for keyword in calls[0].keywords
    } == {
        "register_background_task":
            "register_background_task",
        "_daily_pilot_summary_scheduler":
            "_daily_pilot_summary_scheduler",
    }

    direct_create_tasks = [
        node
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "create_task"
        and node.args
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
        and node.args[0].func.id
        == "_daily_pilot_summary_scheduler"
    ]

    assert direct_create_tasks == []

    assignments = [
        node
        for node in ast.walk(startup)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_pilot_summary_task"
            for target in node.targets
        )
    ]

    assert len(assignments) == 1
    assert assignments[0].value is calls[0]


def test_service_owns_and_returns_pilot_summary_task():
    tree = ast.parse(
        (
            BACKEND_DIR
            / "services"
            / "lifecycle_scheduler_service.py"
        ).read_text()
    )

    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "start_pilot_summary_tasks"
    )

    wrappers = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "register_background_task"
    ]

    assert len(wrappers) == 1

    wrapper = wrappers[0]
    create_task = wrapper.args[0]
    coroutine = create_task.args[0]

    assert create_task.func.attr == "create_task"
    assert coroutine.func.id                 == "_daily_pilot_summary_scheduler"

    assert {
        keyword.arg: keyword.value.value
        for keyword in wrapper.keywords
    } == {
        "name": "pilot_summary",
    }

    returns = [
        node
        for node in helper.body
        if isinstance(node, ast.Return)
    ]
    assert len(returns) == 1
    assert returns[0].value is wrapper


def test_pilot_summary_helper_runtime_and_signature(
    monkeypatch,
):
    import services.lifecycle_scheduler_service as scheduler

    marker = object()
    task = object()
    registered = object()

    pilot_summary = Mock(return_value=marker)
    create_task = Mock(return_value=task)
    register = Mock(return_value=registered)

    monkeypatch.setattr(
        scheduler.asyncio,
        "create_task",
        create_task,
    )

    result = scheduler.start_pilot_summary_tasks(
        register_background_task=register,
        _daily_pilot_summary_scheduler=pilot_summary,
    )

    assert result is registered
    pilot_summary.assert_called_once_with()
    create_task.assert_called_once_with(marker)
    register.assert_called_once_with(
        task,
        name="pilot_summary",
    )

    signature = inspect.signature(
        scheduler.start_pilot_summary_tasks
    )

    assert list(signature.parameters) == [
        "register_background_task",
        "_daily_pilot_summary_scheduler",
    ]

    assert all(
        parameter.kind
        is inspect.Parameter.KEYWORD_ONLY
        for parameter
        in signature.parameters.values()
    )
