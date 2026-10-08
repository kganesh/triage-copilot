"""BaseAgent: the tool-use loop shared by every agent.

Subclasses declare a prompt, an output model and (optionally) tools. The loop:
call LLM -> run requested tools -> feed results back -> repeat until the model calls
the submit tool with output that validates against `output_model`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from ..llm import LLM, ToolCall
from ..trace import Trace

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
MAX_TOOL_OUTPUT = 8000


class ToolFailure(Exception):
    """A tool ran but failed; the message is shown to the model as an error result."""


class AgentError(Exception):
    """The agent could not produce a valid result within its step budget."""


class BaseAgent:
    name: ClassVar[str]
    prompt_file: ClassVar[str]
    output_model: ClassVar[type[BaseModel]]
    code_filled_fields: ClassVar[set[str]] = set()  # hidden from the model's submit schema
    submit_tool: ClassVar[str] = "submit_result"
    submit_description: ClassVar[str] = "Submit your final structured result. Call once, when done."
    max_steps: ClassVar[int] = 8

    def __init__(self, llm: LLM, trace: Trace):
        self.llm, self.trace = llm, trace
        self.system = (PROMPTS / self.prompt_file).read_text()

    # ---- hooks for subclasses ----
    async def tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        raise ToolFailure(f"unknown tool '{name}'")

    def validate_output(self, output: BaseModel) -> str | None:
        """Return an error message to make the model try again, or None to accept."""
        return None

    def finalize(self, output: BaseModel) -> BaseModel:
        return output

    # ---- the loop ----
    async def run(self, task: str) -> BaseModel:
        with self.trace.span(self.name, "agent", self.name, {"task": task[:300]}):
            return await self._loop(task)

    async def _loop(self, task: str) -> BaseModel:
        tools = await self.tools() + [self._submit_spec()]
        messages: list[dict] = [{"role": "user", "content": task}]
        for step in range(self.max_steps):
            with self.trace.span(self.name, "llm", f"step_{step}") as ev:
                resp = await self.llm.complete(agent=self.name, system=self.system, messages=messages, tools=tools)
                ev.input_tokens, ev.output_tokens = resp.input_tokens, resp.output_tokens
            messages.append({"role": "assistant", "content": resp.content_blocks() or [{"type": "text", "text": "…"}]})
            if not resp.tool_calls:
                messages.append({"role": "user", "content": f"Continue. When done, call `{self.submit_tool}`."})
                continue
            results, final = [], None
            for call in resp.tool_calls:
                if call.name == self.submit_tool:
                    content, is_error, final = self._try_submit(call.input, final)
                else:
                    content, is_error = await self._run_tool(call)
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error})
            if final is not None:
                return self.finalize(final)
            messages.append({"role": "user", "content": results})
        raise AgentError(f"{self.name}: no valid result after {self.max_steps} steps")

    def _try_submit(self, data: dict, current: BaseModel | None) -> tuple[str, bool, BaseModel | None]:
        try:
            output = self.output_model.model_validate(data)
        except ValidationError as e:
            return f"Invalid result, fix and resubmit:\n{e}", True, current
        if err := self.validate_output(output):
            return f"Result rejected: {err}", True, current
        return "accepted", False, output

    async def _run_tool(self, call: ToolCall) -> tuple[str, bool]:
        with self.trace.span(self.name, "tool", call.name, call.input) as ev:
            try:
                content = await self.call_tool(call.name, call.input)
            except ToolFailure as e:
                ev.is_error = True
                return f"ERROR: {e}", True
        return content[:MAX_TOOL_OUTPUT], False

    def _submit_spec(self) -> dict:
        schema = inline_refs(self.output_model.model_json_schema())
        for f in self.code_filled_fields:
            schema["properties"].pop(f, None)
            if f in schema.get("required", []):
                schema["required"].remove(f)
        return {"name": self.submit_tool, "description": self.submit_description, "input_schema": schema}


def inline_refs(schema: dict) -> dict:
    """Resolve local $refs so the tool schema is self-contained."""
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def as_json(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=2)
    return json.dumps(obj, indent=2, default=str)
