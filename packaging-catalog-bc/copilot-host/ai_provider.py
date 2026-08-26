from __future__ import annotations

import os
from typing import Any

import requests

from commercial_agent_contract import (
    CommercialEvaluationRequest,
    CommercialEvaluationResult,
)


class CommercialAIConfigurationError(RuntimeError):
    pass


class CommercialAIEvaluationError(RuntimeError):
    pass


def ai_provider_configured() -> bool:
    return bool(os.getenv("GPI_AI_EVALUATION_ENDPOINT", "").strip())


def evaluate_with_ai(
    request: CommercialEvaluationRequest,
    *,
    timeout_seconds: int = 90,
) -> CommercialEvaluationResult:
    endpoint = os.getenv("GPI_AI_EVALUATION_ENDPOINT", "").strip()
    bearer = os.getenv("GPI_AI_EVALUATION_BEARER", "").strip()

    if not endpoint:
        raise CommercialAIConfigurationError(
            "GPI_AI_EVALUATION_ENDPOINT is not configured."
        )

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    response = requests.post(
        endpoint,
        headers=headers,
        json=request.model_dump(mode="json"),
        timeout=timeout_seconds,
    )

    if response.status_code >= 400:
        raise CommercialAIEvaluationError(
            "Commercial AI evaluation failed "
            f"with HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise CommercialAIEvaluationError(
            "Commercial AI evaluation returned invalid JSON."
        ) from exc

    try:
        result = CommercialEvaluationResult.model_validate(payload)
    except Exception as exc:
        raise CommercialAIEvaluationError(
            "Commercial AI evaluation response did not match "
            "the strict 1.0 contract."
        ) from exc

    if result.agentType != request.agentType:
        raise CommercialAIEvaluationError(
            "Commercial AI evaluation changed agentType."
        )

    if result.correlationId != request.correlationId:
        raise CommercialAIEvaluationError(
            "Commercial AI evaluation changed correlationId."
        )

    return result
