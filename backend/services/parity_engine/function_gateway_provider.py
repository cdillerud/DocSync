# GPI Square9 Parity Engine - Azure Function gateway provider.
# V77: deliberately NOT registered in the live Hub LLM router.
# Authentication is a Function key supplied at execution time; no key is stored in source.

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


DEFAULT_FUNCTION_URL = (
    "https://func-gpi-commercial-ai-uat-c2fve9btf5ctcsht."
    "centralus-01.azurewebsites.net"
)
REQUEST_TIMEOUT_SECONDS = 180.0


class FunctionGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayResponse:
    result: Dict[str, Any]
    request_id: str
    response_id: str
    deployment: str
    latency_ms: Optional[float]


class FunctionGatewayProvider:
    def __init__(
        self,
        *,
        function_url: Optional[str] = None,
        function_key: Optional[str] = None,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ):
        self._function_url = (
            function_url
            or os.environ.get("GPI_PARITY_FUNCTION_URL")
            or DEFAULT_FUNCTION_URL
        ).rstrip("/")

        self._function_key = (
            function_key
            or os.environ.get("GPI_PARITY_FUNCTION_KEY")
            or ""
        ).strip()

        if not self._function_key:
            raise FunctionGatewayError(
                "GPI parity Function key is not configured"
            )

        self._timeout_seconds = float(timeout_seconds)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: Dict[str, Any],
        session_id: str,
    ) -> GatewayResponse:
        payload = {
            "system_prompt": str(system_prompt),
            "user_prompt": str(user_prompt),
            "json_schema": json_schema,
            "session_id": str(session_id),
        }

        headers = {
            "Content-Type": "application/json",
            "x-functions-key": self._function_key,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    self._function_url + "/api/parity_classify",
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise FunctionGatewayError(
                "parity Function gateway timed out"
            ) from exc
        except Exception as exc:
            raise FunctionGatewayError(
                f"parity Function gateway request failed: "
                f"{type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            safe_code = ""

            try:
                body = response.json()
                safe_code = str(
                    (body.get("error") or {}).get("code")
                    or body.get("stage")
                    or ""
                )
            except Exception:
                safe_code = ""

            raise FunctionGatewayError(
                f"parity Function gateway returned HTTP "
                f"{response.status_code}"
                + (f" ({safe_code})" if safe_code else "")
            )

        try:
            body = response.json()
        except Exception as exc:
            raise FunctionGatewayError(
                "parity Function gateway returned invalid JSON"
            ) from exc

        if body.get("status") != "PASS":
            raise FunctionGatewayError(
                "parity Function gateway did not return PASS"
            )

        if body.get("mode") != "shadow_only":
            raise FunctionGatewayError(
                "parity Function gateway is not shadow_only"
            )

        if body.get("authoritative") is not False:
            raise FunctionGatewayError(
                "parity Function gateway unexpectedly claims authority"
            )

        result = body.get("result")

        if not isinstance(result, dict):
            raise FunctionGatewayError(
                "parity Function gateway result is not an object"
            )

        telemetry = body.get("telemetry") or {}
        latency = telemetry.get("total_latency_ms")

        try:
            latency_ms = (
                float(latency)
                if latency is not None
                else None
            )
        except (TypeError, ValueError):
            latency_ms = None

        return GatewayResponse(
            result=result,
            request_id=str(body.get("request_id") or ""),
            response_id=str(body.get("response_id") or ""),
            deployment=str(body.get("deployment") or ""),
            latency_ms=latency_ms,
        )
