"""
GPI Document Hub - LLM Router

Returns the correct provider instance for a given task based on env vars.

Environment variables:
    LLM_CLASSIFICATION_PROVIDER  (default: emergent)
    LLM_EXTRACTION_PROVIDER      (default: emergent)
    LLM_EXPLANATION_PROVIDER     (default: emergent)
    OLLAMA_BASE_URL              (default: http://localhost:11434)
    OLLAMA_MODEL                 (default: llama3.2)
    EMERGENT_LLM_KEY             (required when provider=emergent)
"""

import os
import logging
from services.providers.base_provider import BaseLLMProvider, LLMProviderError
from services.providers.emergent_provider import EmergentProvider
from services.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

_TASK_ENV_MAP = {
    "classification": "LLM_CLASSIFICATION_PROVIDER",
    "extraction": "LLM_EXTRACTION_PROVIDER",
    "explanation": "LLM_EXPLANATION_PROVIDER",
}

_VALID_PROVIDERS = {"emergent", "ollama"}


def get_provider(task: str) -> BaseLLMProvider:
    """
    Return a provider instance for the given task.

    Args:
        task: one of "classification", "extraction", "explanation"

    Raises:
        LLMProviderError if configuration is invalid.
    """
    env_key = _TASK_ENV_MAP.get(task)
    if env_key is None:
        raise LLMProviderError(f"Unknown task '{task}'. Valid: {sorted(_TASK_ENV_MAP)}")

    provider_name = os.environ.get(env_key, "emergent").lower().strip()

    if provider_name not in _VALID_PROVIDERS:
        raise LLMProviderError(
            f"{env_key}={provider_name!r} is not supported. Valid: {sorted(_VALID_PROVIDERS)}"
        )

    if provider_name == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.2")
        logger.info("LLM router: task=%s → ollama (%s @ %s)", task, model, base_url)
        return OllamaProvider(base_url=base_url, model_name=model)

    # emergent (default)
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise LLMProviderError("EMERGENT_LLM_KEY is not set but provider=emergent")
    logger.info("LLM router: task=%s → emergent", task)
    return EmergentProvider(api_key=api_key)
