"""OpenAI LLM provider implementation."""
import json
import logging
import re
from typing import AsyncIterator, List, Optional

from openai import AsyncOpenAI, APIError

from app.llm.base_provider import (
    BaseLLMProvider, LLMMessage, LLMTool, LLMToolCall,
    LLMResponse, LLMStreamChunk, LLMProviderConfig,
)

logger = logging.getLogger('uvicorn.error')


def _parse_failed_generation(body: dict) -> Optional[List[LLMToolCall]]:
    """Extract tool calls from a failed_generation field.

    Some models (e.g. Llama on Groq) emit tool calls in their native
    ``<function=name>{"arg": "val"}</function>`` format which the API
    cannot parse.  We recover the call here so the conversation can
    continue.
    """
    raw = body.get("failed_generation", "")
    if not raw:
        return None
    # Pattern: <function=func_name>{"key": "val"}</function>
    pattern = r'<function=(\w+)\s*>(.*?)</function>'
    matches = re.findall(pattern, raw, re.DOTALL)
    if not matches:
        return None
    results = []
    for func_name, args_str in matches:
        try:
            args = json.loads(args_str.strip())
        except (json.JSONDecodeError, TypeError):
            args = {"raw": args_str.strip()}
        results.append(LLMToolCall(
            id=f"recovered_{func_name}_{len(results)}",
            name=func_name,
            arguments=args,
        ))
    logger.info("Recovered %d tool call(s) from failed_generation: %s",
                len(results), [r.name for r in results])
    return results or None


class OpenAIProvider(BaseLLMProvider):

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def _convert_messages(self, messages: List[LLMMessage]) -> List[dict]:
        result = []
        for msg in messages:
            m = {"role": msg.role}
            if msg.content is not None:
                m["content"] = msg.content
            if msg.tool_calls:
                converted_tcs = []
                for tc in msg.tool_calls:
                    # Handle both LLMToolCall dataclass and dict (from MongoDB)
                    if isinstance(tc, dict):
                        tc_id, tc_name, tc_args = tc["id"], tc["name"], tc["arguments"]
                    else:
                        tc_id, tc_name, tc_args = tc.id, tc.name, tc.arguments
                    converted_tcs.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc_name,
                            "arguments": json.dumps(tc_args) if isinstance(tc_args, dict) else (tc_args or "{}"),
                        },
                    })
                m["tool_calls"] = converted_tcs
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.name:
                m["name"] = msg.name
            result.append(m)
        return result

    def _convert_tools(self, tools: List[LLMTool]) -> List[dict]:
        result = []
        for tool in tools:
            params = dict(tool.parameters)
            # Ensure required is always present (Groq strict mode needs this)
            if "required" not in params:
                params["required"] = []
            # Ensure additionalProperties is set (Groq strict mode)
            if "additionalProperties" not in params:
                params["additionalProperties"] = False
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": params,
                },
            })
        return result

    def _parse_tool_calls(self, openai_tool_calls) -> List[LLMToolCall]:
        result = []
        for tc in openai_tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {"raw": tc.function.arguments}
            result.append(LLMToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=args,
            ))
        return result

    async def chat_completion(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> LLMResponse:
        kwargs = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["parallel_tool_calls"] = False

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except APIError as e:
            body = e.body if isinstance(e.body, dict) else {}
            recovered = _parse_failed_generation(body)
            if recovered:
                return LLMResponse(
                    content=None,
                    tool_calls=recovered,
                    finish_reason="tool_calls",
                    usage=None,
                )
            raise

        choice = response.choices[0]

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = self._parse_tool_calls(choice.message.tool_calls)

        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            } if response.usage else None,
        )

    async def chat_completion_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMTool]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        kwargs = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["parallel_tool_calls"] = False

        # Accumulate tool call deltas
        tool_call_accumulators: dict = {}

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except APIError as e:
            # Recover tool calls from failed_generation (Llama native format)
            body = e.body if isinstance(e.body, dict) else {}
            recovered = _parse_failed_generation(body)
            if recovered:
                yield LLMStreamChunk(
                    tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in recovered],
                    finish_reason="tool_calls",
                )
                return
            raise

        try:
            chunks_iter = stream.__aiter__()
        except AttributeError:
            chunks_iter = stream

        while True:
            try:
                chunk = await chunks_iter.__anext__()
            except StopAsyncIteration:
                break
            except APIError as e:
                # Recover tool calls from failed_generation mid-stream
                body = e.body if isinstance(e.body, dict) else {}
                recovered = _parse_failed_generation(body)
                if recovered:
                    yield LLMStreamChunk(
                        tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in recovered],
                        finish_reason="tool_calls",
                    )
                    return
                raise

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # Text content
            if delta.content:
                yield LLMStreamChunk(content=delta.content)

            # Tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_accumulators:
                        tool_call_accumulators[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments": "",
                        }
                    acc = tool_call_accumulators[idx]
                    if tc_delta.id:
                        acc["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc["arguments"] += tc_delta.function.arguments

            # Stream finished
            if finish_reason:
                if finish_reason == "tool_calls" and tool_call_accumulators:
                    completed = []
                    for acc in tool_call_accumulators.values():
                        try:
                            args = json.loads(acc["arguments"])
                        except (json.JSONDecodeError, TypeError):
                            args = {"raw": acc["arguments"]}
                        completed.append({
                            "id": acc["id"],
                            "name": acc["name"],
                            "arguments": args,
                        })
                    yield LLMStreamChunk(
                        tool_calls=completed,
                        finish_reason="tool_calls",
                    )
                else:
                    yield LLMStreamChunk(finish_reason=finish_reason)

    async def close(self):
        await self.client.close()
