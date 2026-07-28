from pathlib import Path
import ast
import inspect
from types import SimpleNamespace
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


def test_server_delegates_all_polling_task_ownership():
    startup = _startup_tree()

    imports = [
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
    ]

    observed = [
        node.func.id
        for node in calls
        if node.func.id in {
            "start_email_polling_tasks",
            "start_inside_sales_pilot_tasks",
        }
    ]

    assert observed.count(
        "start_email_polling_tasks"
    ) == 1
    assert observed.count(
        "start_inside_sales_pilot_tasks"
    ) == 1

    assert imports.count(
        "start_email_polling_tasks"
    ) == 1
    assert imports.count(
        "start_inside_sales_pilot_tasks"
    ) == 1

    direct_create_tasks = [
        node
        for node in ast.walk(startup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "create_task"
    ]

    assert direct_create_tasks == []

    assigned = {
        target.id
        for node in ast.walk(startup)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert {
        "_dynamic_mailbox_polling_task",
        "_email_polling_task",
        "_sales_polling_task",
        "_inside_sales_pilot_task",
        "_pilot_summary_task",
    } <= assigned


def test_email_polling_helper_enabled_runtime(
    monkeypatch,
):
    import services.lifecycle_scheduler_service as scheduler

    markers = {
        "dynamic": object(),
        "email": object(),
        "sales": object(),
    }

    svc = SimpleNamespace(
        dynamic_mailbox_polling_worker=Mock(
            return_value=markers["dynamic"]
        ),
        email_polling_worker=Mock(
            return_value=markers["email"]
        ),
        _sales_email_polling_worker=Mock(
            return_value=markers["sales"]
        ),
        _dynamic_mailbox_polling_task=None,
    )

    monkeypatch.setattr(
        scheduler.asyncio,
        "create_task",
        lambda coroutine: ("task", coroutine),
    )

    registered = []

    def register(task, *, name):
        handle = ("registered", name, task)
        registered.append(handle)
        return handle

    logger = Mock()

    result = scheduler.start_email_polling_tasks(
        logger=logger,
        register_background_task=register,
        email_polling_svc=svc,
        email_polling_enabled=True,
        email_polling_interval_minutes=5,
        email_polling_user="ap@example.com",
        sales_email_polling_enabled=True,
        sales_email_polling_interval_minutes=7,
        sales_email_polling_user="sales@example.com",
    )

    assert [
        item[1]
        for item in registered
    ] == [
        "dynamic_mailbox_polling",
        "email_polling",
        "sales_polling",
    ]

    assert result == {
        "dynamic": registered[0],
        "email": registered[1],
        "sales": registered[2],
    }

    assert (
        svc._dynamic_mailbox_polling_task
        is registered[0]
    )

    svc.dynamic_mailbox_polling_worker                .assert_called_once_with()
    svc.email_polling_worker                .assert_called_once_with()
    svc._sales_email_polling_worker                .assert_called_once_with()

    assert [
        call.args
        for call in logger.info.call_args_list
    ] == [
        (
            "Dynamic mailbox polling worker started",
        ),
        (
            "AP email polling worker started "
            "(interval: %d min, user: %s)",
            5,
            "ap@example.com",
        ),
        (
            "Sales email polling worker started "
            "(interval: %d min, user: %s)",
            7,
            "sales@example.com",
        ),
    ]


def test_email_polling_helper_disabled_runtime(
    monkeypatch,
):
    import services.lifecycle_scheduler_service as scheduler

    dynamic_marker = object()
    svc = SimpleNamespace(
        dynamic_mailbox_polling_worker=Mock(
            return_value=dynamic_marker
        ),
        email_polling_worker=Mock(),
        _sales_email_polling_worker=Mock(),
        _dynamic_mailbox_polling_task=None,
    )

    monkeypatch.setattr(
        scheduler.asyncio,
        "create_task",
        lambda coroutine: ("task", coroutine),
    )

    registered = []

    def register(task, *, name):
        handle = ("registered", name, task)
        registered.append(handle)
        return handle

    logger = Mock()

    result = scheduler.start_email_polling_tasks(
        logger=logger,
        register_background_task=register,
        email_polling_svc=svc,
        email_polling_enabled=False,
        email_polling_interval_minutes=5,
        email_polling_user="ap@example.com",
        sales_email_polling_enabled=False,
        sales_email_polling_interval_minutes=7,
        sales_email_polling_user="",
    )

    assert [
        item[1]
        for item in registered
    ] == [
        "dynamic_mailbox_polling",
    ]

    assert result == {
        "dynamic": registered[0],
        "email": None,
        "sales": None,
    }

    svc.email_polling_worker.assert_not_called()
    svc._sales_email_polling_worker                .assert_not_called()

    logger.info.assert_called_once_with(
        "Dynamic mailbox polling worker started"
    )


def test_inside_sales_helper_runtime(
    monkeypatch,
):
    import services.lifecycle_scheduler_service as scheduler

    marker = object()
    worker = Mock(return_value=marker)

    monkeypatch.setattr(
        scheduler.asyncio,
        "create_task",
        lambda coroutine: ("task", coroutine),
    )

    register = Mock(return_value="inside-task")
    logger = Mock()

    result = scheduler.start_inside_sales_pilot_tasks(
        logger=logger,
        register_background_task=register,
        inside_sales_pilot_enabled=True,
        inside_sales_pilot_worker=worker,
        inside_sales_pilot_mailboxes=[
            "mkoch",
            "nhannover",
        ],
        inside_sales_pilot_interval_minutes=10,
    )

    assert result == "inside-task"
    worker.assert_called_once_with()
    register.assert_called_once_with(
        ("task", marker),
        name="inside_sales_pilot",
    )
    logger.info.assert_called_once_with(
        "Inside Sales Pilot worker started "
        "(mailboxes=%s, interval=%dm)",
        ["mkoch", "nhannover"],
        10,
    )

    disabled_worker = Mock()
    disabled_register = Mock()
    disabled_logger = Mock()

    disabled_result = (
        scheduler.start_inside_sales_pilot_tasks(
            logger=disabled_logger,
            register_background_task=disabled_register,
            inside_sales_pilot_enabled=False,
            inside_sales_pilot_worker=disabled_worker,
            inside_sales_pilot_mailboxes=[],
            inside_sales_pilot_interval_minutes=10,
        )
    )

    assert disabled_result is None
    disabled_worker.assert_not_called()
    disabled_register.assert_not_called()
    disabled_logger.info.assert_called_once_with(
        "Inside Sales Pilot disabled "
        "(INSIDE_SALES_PILOT_ENABLED=false)"
    )


def test_polling_helper_signatures():
    import services.lifecycle_scheduler_service as scheduler

    email_signature = inspect.signature(
        scheduler.start_email_polling_tasks
    )
    inside_signature = inspect.signature(
        scheduler.start_inside_sales_pilot_tasks
    )

    assert list(email_signature.parameters) == [
        "logger",
        "register_background_task",
        "email_polling_svc",
        "email_polling_enabled",
        "email_polling_interval_minutes",
        "email_polling_user",
        "sales_email_polling_enabled",
        "sales_email_polling_interval_minutes",
        "sales_email_polling_user",
    ]

    assert list(inside_signature.parameters) == [
        "logger",
        "register_background_task",
        "inside_sales_pilot_enabled",
        "inside_sales_pilot_worker",
        "inside_sales_pilot_mailboxes",
        "inside_sales_pilot_interval_minutes",
    ]

    assert all(
        parameter.kind
        is inspect.Parameter.KEYWORD_ONLY
        for parameter
        in email_signature.parameters.values()
    )

    assert all(
        parameter.kind
        is inspect.Parameter.KEYWORD_ONLY
        for parameter
        in inside_signature.parameters.values()
    )
