from __future__ import annotations

import json
import os
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException

from commercial_agent_contract import (
    CommercialEvaluationRequest,
    CommercialEvaluationResult,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
EVALUATION_VERSION = "1.0"


app = FastAPI(
    title="GPI Commercial AI Evaluation",
    version=EVALUATION_VERSION,
    description=(
        "Strict AI reasoning endpoint for GPI commercial-agent candidates. "
        "Business Central facts remain authoritative; the model may reason, "
        "prioritize, explain risk, and recommend review actions only."
    ),
)


def _configured_bearer() -> str:
    return os.getenv("GPI_COMMERCIAL_AI_ENDPOINT_BEARER", "").strip()


def _require_endpoint_bearer(authorization: str | None) -> None:
    expected = _configured_bearer()
    if not expected:
        return

    actual = str(authorization or "").strip()
    if actual != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _openai_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured.",
        )
    return key


def _model() -> str:
    return os.getenv("GPI_COMMERCIAL_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _result_schema() -> dict[str, Any]:
    schema = CommercialEvaluationResult.model_json_schema()
    # The endpoint itself fixes these fields from the trusted request/model.
    # They remain in the strict schema so the model must return a complete contract.
    return schema


def _instructions(request: CommercialEvaluationRequest) -> str:
    agent_guidance = {
        "incorrectItem": (
            "Assess whether the sales-order item warrants human review as a possible "
            "wrong SKU. A prior purchase does not prove the item is correct. Rare "
            "history, customer purchasing patterns, item description, deterministic "
            "similarity evidence, and missing catalog context should affect confidence."
        ),
        "lowMargin": (
            "Assess whether the margin condition warrants human review. Treat supplied "
            "Business Central prices, costs, quantities, and calculated margins as facts."
        ),
        "costChange": (
            "Assess whether the supplier cost change warrants human review based on "
            "magnitude, customer exposure, sales context, and supplied authoritative facts."
        ),
    }[request.agentType]

    return (
        "You are the reasoning layer for Gamer Packaging's Commercial Agent platform. "
        "Business Central and deterministic services are authoritative. Never invent, "
        "modify, or override supplied financial values, identifiers, history counts, or "
        "product facts. Do not execute writes or make pricing decisions. Your job is to "
        "decide whether this already-screened candidate should be surfaced for human "
        "review, explain why, assign calibrated risk/confidence, identify evidence used, "
        "name missing context, and recommend a review action. "
        + agent_guidance
        + " If evidence is incomplete, lower confidence and state the missing context. "
        "Return only the requested structured result."
    )


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    output = payload.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())

    if parts:
        return "\n".join(parts)

    raise RuntimeError("OpenAI Responses API returned no text output.")


def evaluate_request(
    request: CommercialEvaluationRequest,
    *,
    http_post=requests.post,
) -> CommercialEvaluationResult:
    model = _model()
    api_key = _openai_api_key()

    response = http_post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "instructions": _instructions(request),
            "input": json.dumps(request.model_dump(mode="json"), separators=(",", ":")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "commercial_evaluation_result",
                    "strict": True,
                    "schema": _result_schema(),
                }
            },
        },
        timeout=90,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            "OpenAI Responses API failed "
            f"with HTTP {response.status_code}: {response.text[:1000]}"
        )

    try:
        raw = response.json()
        model_payload = json.loads(_response_text(raw))
        result = CommercialEvaluationResult.model_validate(model_payload)
    except Exception as exc:
        raise RuntimeError(
            "OpenAI evaluation did not return the strict commercial result contract."
        ) from exc

    if result.agentType != request.agentType:
        raise RuntimeError("AI evaluation changed agentType.")
    if result.correlationId != request.correlationId:
        raise RuntimeError("AI evaluation changed correlationId.")
    if result.model != model:
        # Normalize model provenance to the configured model rather than trusting model text.
        result = result.model_copy(update={"model": model})
    if result.evaluationVersion != EVALUATION_VERSION:
        result = result.model_copy(update={"evaluationVersion": EVALUATION_VERSION})

    return result


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": _model(),
        "openaiConfigured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "endpointBearerRequired": bool(_configured_bearer()),
        "evaluationVersion": EVALUATION_VERSION,
    }


@app.post("/evaluate", response_model=CommercialEvaluationResult)
def evaluate(
    request: CommercialEvaluationRequest,
    authorization: str | None = Header(default=None),
) -> CommercialEvaluationResult:
    _require_endpoint_bearer(authorization)
    try:
        return evaluate_request(request)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
