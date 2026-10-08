"""LLM abstraction. Agents depend on the `LLM` protocol, never on the SDK directly,
so evals can swap in a scripted model for deterministic plumbing tests."""
from __future__ import annotations

import itertools
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = os.getenv("TRIAGE_MODEL", "claude-sonnet-5-5")
_ids = itertools.count(1)


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    def content_blocks(self) -> list[dict[str, Any]]:
        """Anthropic-format assistant content, used to extend the conversation."""
        blocks: list[dict[str, Any]] = [{"type": "text", "text": self.text}] if self.text else []
        blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in self.tool_calls]
        return blocks


class LLM(Protocol):
    async def complete(
        self, *, agent: str, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 2048, temperature: float = 0.0):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic()
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature

    async def complete(self, *, agent: str, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=messages,
            tools=tools,
        )
        out = LLMResponse(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        for block in resp.content:
            if block.type == "text":
                out.text += block.text
            elif block.type == "tool_use":
                out.tool_calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return out


# A script step is either a canned response or a function of the conversation so far.
ScriptStep = LLMResponse | Callable[[list[dict]], LLMResponse]


class ScriptedLLM:
    """Deterministic stand-in: each agent name gets its own queue of responses."""

    def __init__(self, scripts: dict[str, list[ScriptStep]]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[tuple[str, list[dict]]] = []

    async def complete(self, *, agent: str, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append((agent, [dict(m) for m in messages]))
        queue = self.scripts.get(agent)
        if not queue:
            raise AssertionError(f"ScriptedLLM: no scripted response left for agent '{agent}'")
        step = queue.pop(0)
        return step(messages) if callable(step) else step


def tool_call(name: str, **input: Any) -> LLMResponse:
    """Build a scripted response that calls one tool."""
    return LLMResponse(tool_calls=[ToolCall(f"call_{next(_ids)}", name, input)])


def text(t: str) -> LLMResponse:
    return LLMResponse(text=t)
