"""
GPI Document Hub - LLM Provider Base Class

Abstract interface that every LLM provider must implement.
"""

from abc import ABC, abstractmethod


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails."""
    pass


class BaseLLMProvider(ABC):

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        session_id: str,
        expect_json: bool = True,
    ) -> str:
        """
        Send a prompt pair to the model and return the raw string response.
        Raises LLMProviderError on any failure.
        """
        ...
