"""
GPI Document Hub - Ollama LLM Provider

Calls a local Ollama instance via its OpenAI-compatible /api/chat endpoint.
"""

import logging
import httpx
from services.providers.base_provider import BaseLLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
REQUEST_TIMEOUT = 120.0


class OllamaProvider(BaseLLMProvider):

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model_name: str = DEFAULT_MODEL):
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
        expect_json: bool = True,
    ) -> str:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model_name,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if expect_json:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                if not content:
                    raise LLMProviderError(f"Ollama returned empty content: {data}")
                return content.strip()

        except httpx.ConnectError as exc:
            raise LLMProviderError(
                f"Cannot reach Ollama at {self._base_url} — is the server running? ({exc})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                f"Ollama request timed out after {REQUEST_TIMEOUT}s ({exc})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"Ollama call failed: {exc}") from exc
