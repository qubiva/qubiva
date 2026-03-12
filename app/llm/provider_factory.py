"""LLM provider factory — creates provider instances from config."""
import logging
from typing import Dict, Type

from app.llm.base_provider import BaseLLMProvider, LLMProviderConfig

logger = logging.getLogger('uvicorn.error')

# Provider registry: name -> class
_PROVIDERS: Dict[str, Type[BaseLLMProvider]] = {}


def register_provider(name: str, cls: Type[BaseLLMProvider]):
    """Register a provider class under a given name."""
    _PROVIDERS[name.lower()] = cls


def _register_defaults():
    """Lazy-import and register all built-in providers."""
    if _PROVIDERS:
        return

    from app.llm.openai_provider import OpenAIProvider
    from app.llm.anthropic_provider import AnthropicProvider
    from app.llm.azure_openai_provider import AzureOpenAIProvider

    register_provider("openai", OpenAIProvider)
    register_provider("anthropic", AnthropicProvider)
    register_provider("azure_openai", AzureOpenAIProvider)


def create_provider(config: LLMProviderConfig) -> BaseLLMProvider:
    """Create a provider instance from config.

    Args:
        config: Provider configuration. ``config.provider`` must match
                a registered provider name (e.g. "openai", "anthropic").

    Returns:
        An initialised BaseLLMProvider subclass.

    Raises:
        ValueError: If the provider name is not registered.
    """
    _register_defaults()

    name = config.provider.lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(sorted(_PROVIDERS.keys()))
        raise ValueError(
            f"Unknown LLM provider '{config.provider}'. "
            f"Available: {available}"
        )

    logger.info("Creating LLM provider: %s (model=%s)", name, config.model)
    return cls(config)
