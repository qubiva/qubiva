"""Azure OpenAI LLM provider implementation.

Thin wrapper around the OpenAI provider using Azure-specific client.
"""
import logging
from openai import AsyncAzureOpenAI

from app.llm.openai_provider import OpenAIProvider
from app.llm.base_provider import LLMProviderConfig

logger = logging.getLogger('uvicorn.error')


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI uses the same API format as OpenAI, just different auth."""

    def __init__(self, config: LLMProviderConfig):
        # Skip OpenAIProvider.__init__ and call BaseLLMProvider.__init__ directly
        super(OpenAIProvider, self).__init__(config)

        self.client = AsyncAzureOpenAI(
            api_key=config.api_key,
            api_version=config.api_version or "2024-06-01",
            azure_endpoint=config.base_url,
            azure_deployment=config.deployment_name or config.model,
        )
