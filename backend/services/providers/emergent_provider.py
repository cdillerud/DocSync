"""
GPI Document Hub - Emergent / Gemini LLM Provider

Wraps the existing emergentintegrations.llm.chat.LlmChat pattern
used throughout the codebase (ai_classifier.py, decision_explainer_service.py).
"""

import logging
from services.providers.base_provider import BaseLLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

# Defaults matching the existing codebase convention
DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.0-flash"


class EmergentProvider(BaseLLMProvider):

    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL):
        if not api_key:
            raise LLMProviderError("EMERGENT_LLM_KEY is empty or not set")
        self._api_key = api_key
        self._model_name = model_name

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
        expect_json: bool = True,
    ) -> str:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except ImportError as exc:
            raise LLMProviderError(f"emergentintegrations not available: {exc}") from exc

        try:
            chat = LlmChat(
                api_key=self._api_key,
                session_id=session_id,
                system_message=system_prompt,
            ).with_model(DEFAULT_PROVIDER, self._model_name)

            response = await chat.send_message(UserMessage(text=user_prompt))
            return str(response).strip()

        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"Emergent LLM call failed: {exc}") from exc
