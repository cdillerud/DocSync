"""
GPI Document Hub - Azure OpenAI (GamerLLM) LLM Provider

Text-completion provider matching BaseLLMProvider's interface, using the
same genuine Azure OpenAI route already proven working in
document_intel_helpers._call_llm_for_extraction() and
classification_pipeline.stage_classify_llm() - LlmChat with_model("azure", ...)
against AZURE_OPENAI_ENDPOINT/KEY, no Emergent proxy involved.

Added 2026-09-23: llm_router.py previously only supported "emergent" and
"ollama" - any of the 6+ services routed through get_provider() (vendor
resolution, AP invoice advisory, sales order readiness review, decision
explanations, template value injection) were unconditionally stuck on the
Emergent proxy's shared budget pool, with no way to switch even though
GPI_LLM_PROVIDER=azure was already set globally for the main pipeline.
"""

import logging
from services.providers.base_provider import BaseLLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


class AzureProvider(BaseLLMProvider):

    def __init__(self, model_name: str = None):
        from services.azure_openai_classifier import (
            AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, is_azure_configured,
        )
        if not is_azure_configured():
            raise LLMProviderError("Azure OpenAI is not fully configured")
        self._api_key = AZURE_OPENAI_KEY
        self._api_base = AZURE_OPENAI_ENDPOINT
        if model_name:
            self._model_name = model_name
        else:
            from services.llm_model_config import get_llm_model
            self._model_name = get_llm_model()

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
        expect_json: bool = True,
    ) -> str:
        from services.azure_openai_classifier import AZURE_API_VERSION
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except ImportError as exc:
            raise LLMProviderError(f"emergentintegrations not available: {exc}") from exc

        try:
            chat = LlmChat(
                api_key=self._api_key,
                session_id=session_id,
                system_message=system_prompt,
            ).with_model("azure", self._model_name).with_params(
                api_base=self._api_base, api_version=AZURE_API_VERSION,
            )

            response = await chat.send_message(UserMessage(text=user_prompt))
            return str(response).strip()

        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"Azure OpenAI call failed: {exc}") from exc
