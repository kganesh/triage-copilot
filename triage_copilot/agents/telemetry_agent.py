"""Telemetry agent: investigates one service through the MCP telemetry server.

It discovers tools from the server at runtime (list_tools), so adding a tool to the
server makes it available here with no code change.
"""
from __future__ import annotations

from typing import Any

from mcp import Client, MCPError

from ..schemas import Evidence
from .base import BaseAgent, ToolFailure


class TelemetryAgent(BaseAgent):
    name = "telemetry"
    prompt_file = "telemetry.md"
    output_model = Evidence
    submit_tool = "submit_evidence"
    submit_description = "Submit the evidence you gathered. Call once, after investigating."
    max_steps = 10

    def __init__(self, llm, trace, mcp: Client):
        super().__init__(llm, trace)
        self.mcp = mcp
        self._tool_specs: list[dict] | None = None

    async def tools(self) -> list[dict]:
        if self._tool_specs is None:
            listed = await self.mcp.list_tools()
            self._tool_specs = [
                {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in listed.tools
            ]
        return self._tool_specs

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        try:
            result = await self.mcp.call_tool(name, args)
        except MCPError as e:
            raise ToolFailure(str(e)) from e
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if result.is_error:
            raise ToolFailure(text or f"{name} failed")
        # Fence tool output: log lines can carry user-controlled text (prompt injection).
        return f"<tool_output untrusted=\"true\">\n{text}\n</tool_output>"

    def validate_output(self, output: Evidence) -> str | None:
        if not output.findings and not output.data_gaps:
            return "Include at least one finding, or explain in data_gaps why no data was available."
        return None
