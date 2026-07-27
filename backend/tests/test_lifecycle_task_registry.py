"""
Regression coverage for application task ownership.
"""

from __future__ import annotations

from pathlib import Path
import ast
import asyncio
from unittest.mock import Mock

import pytest


BACKEND_DIR = (
    Path(__file__).resolve().parent.parent
)

EXPECTED_DIRECT_STARTUP_TASKS = (
    24
)

COMPATIBILITY_HANDLES = {
    "_dynamic_mailbox_polling_task",
    "_email_polling_task",
    "_sales_polling_task",
    "_pilot_summary_task",
}


def _parent_map(tree):
    parents = {}

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(
            node
        ):
            parents[child] = node

    return parents


def _nearest_function(
    node,
    parents,
):
    current = parents.get(node)

    while current is not None:
        if isinstance(
            current,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            return current

        current = parents.get(current)

    return None


def _is_create_task(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and isinstance(
            node.func.value,
            ast.Name,
        )
        and node.func.value.id == "asyncio"
        and node.func.attr == "create_task"
    )


class TestSourceOwnership:
    def test_every_direct_startup_task_is_registered(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        parents = _parent_map(tree)

        direct_tasks = [
            node
            for node in ast.walk(startup)
            if (
                _is_create_task(node)
                and _nearest_function(
                    node,
                    parents,
                )
                is startup
            )
        ]

        assert len(direct_tasks) == (
            EXPECTED_DIRECT_STARTUP_TASKS
        )

        for task_call in direct_tasks:
            wrapper = parents.get(task_call)

            assert isinstance(
                wrapper,
                ast.Call,
            )

            assert isinstance(
                wrapper.func,
                ast.Name,
            )

            assert (
                wrapper.func.id
                == "register_background_task"
            )

            name_keywords = [
                keyword
                for keyword
                in wrapper.keywords
                if keyword.arg == "name"
            ]

            assert len(name_keywords) == 1

            assert isinstance(
                name_keywords[0].value,
                ast.Constant,
            )

            assert name_keywords[
                0
            ].value.value

    def test_compatibility_handles_remain_assigned(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR / "server.py"
            ).read_text()
        )

        startup = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name == "startup"
            )
        )

        assigned = {
            target.id
            for node in ast.walk(startup)
            if isinstance(
                node,
                ast.Assign,
            )
            for target in node.targets
            if isinstance(
                target,
                ast.Name,
            )
        }

        assert (
            COMPATIBILITY_HANDLES
            <= assigned
        )

    def test_shutdown_cancels_registry_once(
        self,
    ):
        tree = ast.parse(
            (
                BACKEND_DIR
                / "services"
                / "lifecycle_service.py"
            ).read_text()
        )

        shutdown = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.AsyncFunctionDef,
                )
                and node.name
                == "shutdown_application"
            )
        )

        calls = [
            node
            for node in ast.walk(shutdown)
            if (
                isinstance(node, ast.Call)
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id
                == "cancel_registered_tasks"
            )
        ]

        assert len(calls) == 1


class TestRuntimeRegistry:
    @pytest.mark.asyncio
    async def test_registered_task_is_named_and_cancelled(
        self,
    ):
        import services.lifecycle_service as lifecycle

        await lifecycle.cancel_registered_tasks(
            Mock()
        )

        started = asyncio.Event()
        cancelled = asyncio.Event()
        blocker = asyncio.Event()

        async def worker():
            started.set()

            try:
                await blocker.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = (
            lifecycle.register_background_task(
                asyncio.create_task(
                    worker()
                ),
                name="registry-test-worker",
            )
        )

        await started.wait()

        assert (
            task.get_name()
            == "registry-test-worker"
        )

        logger = Mock()

        await lifecycle.cancel_registered_tasks(
            logger
        )

        assert task.cancelled()
        assert cancelled.is_set()

        logger.info.assert_called_once_with(
            "Stopped %d registered "
            "background tasks",
            1,
        )

        assert (
            lifecycle._BACKGROUND_TASKS
            == set()
        )

    @pytest.mark.asyncio
    async def test_completed_task_leaves_registry(
        self,
    ):
        import services.lifecycle_service as lifecycle

        await lifecycle.cancel_registered_tasks(
            Mock()
        )

        async def complete():
            return "done"

        task = (
            lifecycle.register_background_task(
                asyncio.create_task(
                    complete()
                ),
                name="registry-complete",
            )
        )

        assert await task == "done"

        await asyncio.sleep(0)

        assert (
            task
            not in lifecycle._BACKGROUND_TASKS
        )
