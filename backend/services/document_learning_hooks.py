# Non-blocking hooks into the per-document learning engine.

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


async def record_document_learning(
    db: Any,
    doc_id: str,
    trigger: str,
) -> dict:
    'Run document learning without failing the primary workflow.'

    try:
        from services.per_document_learning_service import (
            learn_from_document,
        )

        result = await learn_from_document(
            db,
            doc_id,
            trigger=trigger,
        )

        if isinstance(result, dict):
            return result

        return {
            "learned": True,
            "trigger": trigger,
            "result": result,
        }

    except Exception as exc:
        logger.debug(
            "[DocumentLearning] trigger=%s doc=%s failed: %s",
            trigger,
            doc_id[:12],
            exc,
        )

        return {
            "learned": False,
            "trigger": trigger,
            "error": str(exc),
        }
