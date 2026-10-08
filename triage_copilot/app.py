"""Wires the system together: MCP client + retriever + four agents."""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from mcp import Client, StdioServerParameters

from .agents import KnowledgeAgent, Orchestrator, SynthesizerAgent, TelemetryAgent
from .llm import LLM, AnthropicLLM
from .mcp_server import build_server
from .rag import BM25Retriever
from .schemas import TriageResult
from .trace import Trace

Transport = Literal["inproc", "stdio"]
REPO_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def mcp_client(scenario: str, transport: Transport = "stdio") -> AsyncIterator[Client]:
    """`stdio` spawns the server as a subprocess (the real MCP wire protocol);
    `inproc` runs it in-process, which is faster for eval loops."""
    if transport == "inproc":
        target = build_server(scenario)
    else:
        target = StdioServerParameters(
            command=sys.executable,
            args=["-m", "triage_copilot.mcp_server", scenario],
            cwd=str(REPO_ROOT),
        )
    try:
        async with Client(target) as client:
            yield client
    except BaseExceptionGroup as group:
        # The MCP client runs on (nested) anyio task groups, which wrap errors raised in the
        # body. Re-raise a lone error as itself so callers can `except AgentError`.
        inner: BaseException = group
        while isinstance(inner, BaseExceptionGroup) and len(inner.exceptions) == 1:
            inner = inner.exceptions[0]
        if inner is group:
            raise
        raise inner from None


async def triage(
    request: str,
    *,
    scenario: str,
    llm: LLM | None = None,
    retriever: BM25Retriever | None = None,
    transport: Transport = "stdio",
) -> tuple[TriageResult, Trace]:
    llm = llm or AnthropicLLM()
    retriever = retriever or BM25Retriever.from_dir()
    trace = Trace()
    async with mcp_client(scenario, transport) as client:
        orchestrator = Orchestrator(
            llm,
            trace,
            telemetry=TelemetryAgent(llm, trace, client),
            knowledge=KnowledgeAgent(llm, trace, retriever),
            synthesizer=SynthesizerAgent(llm, trace),
        )
        result = await orchestrator.triage(request)
    return result, trace
