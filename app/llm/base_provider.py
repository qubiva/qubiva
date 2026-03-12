"""
Base LLM provider abstraction for pluggable AI backends.

All LLM providers (OpenAI, Anthropic, Azure OpenAI, etc.) implement
the BaseLLMProvider interface, allowing the Cloud Analyst feature to swap
providers via configuration without code changes.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class LLMTool:
    """Definition of a tool the LLM can call."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


@dataclass
class LLMToolCall:
    """A tool call made by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Complete (non-streaming) response from the LLM."""
    content: Optional[str] = None
    tool_calls: Optional[List[LLMToolCall]] = None
    finish_reason: str = "stop"  # "stop", "tool_calls", "length"
    usage: Optional[Dict[str, int]] = None


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response."""
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None


@dataclass
class LLMProviderConfig:
    """Configuration for an LLM provider instance."""
    provider: str  # "openai", "anthropic", "azure_openai"
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.1
    extra: Dict[str, Any] = field(default_factory=dict)
    # Azure-specific
    api_version: Optional[str] = None
    deployment_name: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, config: LLMProviderConfig):
        self.config = config

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> LLMResponse:
        """Non-streaming chat completion with optional tool definitions."""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Streaming chat completion. Yields chunks as they arrive."""
        ...

    @abstractmethod
    async def close(self):
        """Clean up client resources."""
        ...
