"""Anthropic (Claude) LLM provider implementation."""
import json
import logging
from typing import AsyncIterator, List, Optional

from anthropic import AsyncAnthropic

from app.llm.base_provider import (
    BaseLLMProvider, LLMMessage, LLMTool, LLMToolCall,
    LLMResponse, LLMStreamChunk, LLMProviderConfig,
)

logger = logging.getLogger('uvicorn.error')


class AnthropicProvider(BaseLLMProvider):

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self.client = AsyncAnthropic(api_key=config.api_key)

    def _convert_messages(self, messages: List[LLMMessage]):
        """Convert to Anthropic format. Extracts system prompt separately."""
        system_prompt = None
        converted = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
                continue

            if msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool use
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    args = tc["arguments"] if isinstance(tc["arguments"], dict) else json.loads(tc["arguments"])
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": args,
                    })
                converted.append({"role": "assistant", "content": content})

            elif msg.role == "tool":
                # Tool result
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content or "",
                        }
                    ],
                })

            elif msg.role == "user":
                converted.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                converted.append({"role": "assistant", "content": msg.content or ""})

        return system_prompt, converted

    def _convert_tools(self, tools: List[LLMTool]) -> List[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    async def chat_completion(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> LLMResponse:
        system_prompt, converted = self._convert_messages(messages)

        kwargs = {
            "model": self.config.model,
            "messages": converted,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self.client.messages.create(**kwargs)

        content_text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(LLMToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        return LLMResponse(
            content=content_text if content_text else None,
            tool_calls=tool_calls if tool_calls else None,
            finish_reason="tool_calls" if tool_calls else response.stop_reason or "stop",
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            } if response.usage else None,
        )

    async def chat_completion_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        system_prompt, converted = self._convert_messages(messages)

        kwargs = {
            "model": self.config.model,
            "messages": converted,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        # Track current tool use block being streamed
        current_tool_id = None
        current_tool_name = None
        current_tool_input = ""

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, 'type') and block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        current_tool_input = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, 'type'):
                        if delta.type == "text_delta":
                            yield LLMStreamChunk(content=delta.text)
                        elif delta.type == "input_json_delta":
                            current_tool_input += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_id:
                        try:
                            args = json.loads(current_tool_input) if current_tool_input else {}
                        except json.JSONDecodeError:
                            args = {"raw": current_tool_input}
                        yield LLMStreamChunk(
                            tool_calls=[{
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "arguments": args,
                            }],
                            finish_reason="tool_calls",
                        )
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_input = ""

                elif event.type == "message_stop":
                    yield LLMStreamChunk(finish_reason="stop")

    async def close(self):
        await self.client.close()
