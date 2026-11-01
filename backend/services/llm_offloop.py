"""
GPI Document Hub - keep LLM calls off the event loop

emergentintegrations' LlmChat._execute_completion is an async method that
calls the synchronous litellm.completion(): every AI call in the Hub (AI
routing, extraction, classification, explanations) froze the whole backend
for as long as Azure took to answer. On 2026-11-01 19:20 one call hung 600s
(LiteLLM's default timeout) during the learning cycle's AI routing step and
every request, health checks included, timed out - the 504s of 10-29 and
11-01. The callers' own asyncio.wait_for(..., 60) could not fire either.

install() runs the original method in a worker thread of its own pool, with
a timeout, so the loop keeps serving while Azure answers.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 300
_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm")


def install() -> bool:
    try:
        from emergentintegrations.llm.chat import LlmChat
    except ImportError:
        return False
    if getattr(LlmChat, "_gpi_off_loop", False):
        return True
    original = LlmChat._execute_completion

    async def _execute_completion(self, messages):
        self.extra_params.setdefault("timeout", LLM_TIMEOUT_SECONDS)
        # The original awaits nothing: it runs to completion on a private
        # loop in the worker thread.
        return await asyncio.get_running_loop().run_in_executor(
            _pool, lambda: asyncio.run(original(self, messages)))

    LlmChat._execute_completion = _execute_completion
    LlmChat._gpi_off_loop = True
    logger.info("[LLM] LlmChat completions run off the event loop (timeout %ss)", LLM_TIMEOUT_SECONDS)
    return True
