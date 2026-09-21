"""Gamer Azure OpenAI transport for GPI Document Hub.

This module is the single V117 LLM transport boundary. It talks only to the
GamerLLM Azure OpenAI v1 endpoint and authenticates with the Azure VM/container
managed identity through IMDS. It has no Emergent dependency and no API-key
fallback.

The routing model/deployment remains a caller concern; this module only handles
identity, endpoint validation, Azure Responses API calls, and output extraction.
"""

from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

DEFAULT_GAMER_AZURE_OPENAI_ENDPOINT = (
    "https://gamerllm.openai.azure.com/openai/v1/"
)
DEFAULT_GAMER_AZURE_OPENAI_DEPLOYMENT = "gpt-5.6-sol"
DEFAULT_GAMER_AZURE_TOKEN_RESOURCE = "https://cognitiveservices.azure.com/"
DEFAULT_AZURE_IMDS_ENDPOINT = (
    "http://169.254.169.254/metadata/identity/oauth2/token"
)

_ALLOWED_GAMER_AZURE_HOSTS = {
    "gamerllm.openai.azure.com",
    "gamerllm.services.ai.azure.com",
}

_token_cache: Dict[str, Any] = {
    "access_token": "",
    "expires_on": 0,
}


def gamer_azure_endpoint() -> str:
    raw = str(
        os.environ.get("GAMER_AZURE_OPENAI_ENDPOINT")
        or DEFAULT_GAMER_AZURE_OPENAI_ENDPOINT
    ).strip()
    if not raw:
        raise RuntimeError("GAMER_AZURE_OPENAI_ENDPOINT is empty")

    parsed = urlparse(raw)
    host = str(parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in _ALLOWED_GAMER_AZURE_HOSTS:
        raise RuntimeError(
            "Gamer Azure endpoint must target the approved GamerLLM Azure host"
        )

    normalized = raw.rstrip("/")
    if not normalized.lower().endswith("/openai/v1"):
        normalized += "/openai/v1"
    return normalized + "/"


def gamer_azure_deployment(model: Optional[str] = None) -> str:
    configured = str(
        os.environ.get("GAMER_AZURE_OPENAI_DEPLOYMENT")
        or DEFAULT_GAMER_AZURE_OPENAI_DEPLOYMENT
    ).strip()
    requested = str(model or "").strip()
    if requested and requested != configured:
        raise RuntimeError(
            "Gamer Azure deployment/model mismatch: "
            f"requested={requested}; configured_deployment={configured}"
        )
    if not configured:
        raise RuntimeError("GAMER_AZURE_OPENAI_DEPLOYMENT is empty")
    return configured


def _token_resource() -> str:
    return str(
        os.environ.get("GAMER_AZURE_TOKEN_RESOURCE")
        or DEFAULT_GAMER_AZURE_TOKEN_RESOURCE
    ).strip()


def _managed_identity_client_id() -> str:
    return str(
        os.environ.get("GAMER_AZURE_MANAGED_IDENTITY_CLIENT_ID")
        or os.environ.get("AZURE_CLIENT_ID")
        or ""
    ).strip()


def clear_token_cache() -> None:
    _token_cache["access_token"] = ""
    _token_cache["expires_on"] = 0


async def _managed_identity_access_token(*, force_refresh: bool = False) -> str:
    now = int(time.time())
    cached = str(_token_cache.get("access_token") or "")
    expires_on = int(_token_cache.get("expires_on") or 0)
    if not force_refresh and cached and expires_on > now + 120:
        return cached

    endpoint = str(
        os.environ.get("GAMER_AZURE_IMDS_ENDPOINT")
        or DEFAULT_AZURE_IMDS_ENDPOINT
    ).strip()
    params = {
        "api-version": "2018-02-01",
        "resource": _token_resource(),
    }
    client_id = _managed_identity_client_id()
    if client_id:
        params["client_id"] = client_id

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        trust_env=False,
    ) as client:
        response = await client.get(
            endpoint,
            params=params,
            headers={"Metadata": "true"},
        )
    if response.status_code != 200:
        raise RuntimeError(
            "Gamer Azure managed-identity token request failed: "
            f"status={response.status_code}; body={response.text[:500]}"
        )

    payload = response.json()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Gamer Azure managed-identity token response had no access_token")

    raw_expiry = payload.get("expires_on") or payload.get("expiresOn") or 0
    try:
        expiry = int(raw_expiry)
    except (TypeError, ValueError):
        expiry = now + 300

    _token_cache["access_token"] = token
    _token_cache["expires_on"] = expiry
    return token


def _response_output_text(payload: Dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "") not in {"output_text", "text"}:
                continue
            value = part.get("text")
            if isinstance(value, str) and value:
                chunks.append(value)
            elif isinstance(value, dict):
                nested = value.get("value")
                if isinstance(nested, str) and nested:
                    chunks.append(nested)
    text = "\n".join(chunks).strip()
    if not text:
        raise RuntimeError("Gamer Azure Responses API returned no output text")
    return text


async def _responses_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = gamer_azure_endpoint() + "responses"

    token = await _managed_identity_access_token()
    for attempt in range(2):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=15.0),
            trust_env=True,
        ) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "x-ms-client-request-id": str(uuid.uuid4()),
                },
                json=payload,
            )

        if response.status_code == 401 and attempt == 0:
            token = await _managed_identity_access_token(force_refresh=True)
            continue

        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                "Gamer Azure Responses API request failed: "
                f"status={response.status_code}; body={response.text[:1200]}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Gamer Azure Responses API returned a non-object response")
        return data

    raise RuntimeError("Gamer Azure Responses API authentication retry exhausted")


async def gamer_azure_text_completion(
    prompt: str,
    *,
    model: str,
    system_message: str,
) -> str:
    deployment = gamer_azure_deployment(model)
    payload = {
        "model": deployment,
        "instructions": str(system_message),
        "input": str(prompt),
        "store": False,
    }
    return _response_output_text(await _responses_request(payload))


async def gamer_azure_pdf_completion(
    pdf_path: str,
    *,
    prompt: str,
    model: str,
    system_message: str,
) -> str:
    deployment = gamer_azure_deployment(model)
    path = Path(pdf_path)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "model": deployment,
        "instructions": str(system_message),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": path.name,
                        "file_data": "data:application/pdf;base64," + data,
                    },
                    {
                        "type": "input_text",
                        "text": str(prompt),
                    },
                ],
            }
        ],
        "store": False,
    }
    return _response_output_text(await _responses_request(payload))
