"""Orchestrator: decides which sub-agents to call, in what order, and when to stop.

Sub-agents are exposed to the orchestrator's model as tools:
  investigate_telemetry -> TelemetryAgent (MCP)
  consult_knowledge     -> KnowledgeAgent (RAG)
When the model calls `finish` with status "triaged", the SynthesizerAgent writes the
report from everything gathered. Status "declined" ends the run without a report.
"""
from __future__ import annotations

from typing import Any

from ..schemas import Evidence, Guidance, OrchestratorDecision, TriageResult
from .base import AgentError, BaseAgent, ToolFailure, as_json
from .knowledge_agent import KnowledgeAgent
from .synthesizer_agent import SynthesizerAgent
from .telemetry_agent import TelemetryAgent

MAX_CALLS_PER_SUBAGENT = 3

SUBAGENT_TOOLS = [
    {
        "name": "investigate_telemetry",
        "description": (
            "Delegate to the Telemetry agent: it queries metrics, logs and deploys for one service "
            "and returns structured evidence. Call once per service you need to inspect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name, e.g. 'checkout-svc'"},
                "question": {"type": "string", "description": "What to find out about this service"},
            },
            "required": ["service", "question"],
        },
    },
    {
        "name": "consult_knowledge",
        "description": (
            "Delegate to the Knowledge agent: it searches runbooks and past postmortems and returns "
            "cited guidance. Pass the telemetry findings as context so it searches for the real symptoms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What guidance is needed"},
                "context": {"type": "string", "description": "Key telemetry findings so far, if any"},
            },
            "required": ["question"],
        },
    },
]


class Orchestrator(BaseAgent):
    name = "orchestrator"
    prompt_file = "orchestrator.md"
    output_model = OrchestratorDecision
    submit_tool = "finish"
    submit_description = (
        "End the investigation. status='triaged' once you have telemetry evidence and runbook guidance "
        "(a report is then written from them); status='declined' if the request is not incident triage."
    )
    max_steps = 10

    def __init__(self, llm, trace, telemetry: TelemetryAgent, knowledge: KnowledgeAgent,
                 synthesizer: SynthesizerAgent):
        super().__init__(llm, trace)
        self.telemetry, self.knowledge, self.synthesizer = telemetry, knowledge, synthesizer
        self._reset("")

    def _reset(self, request: str) -> None:
        self.request = request
        self.evidence: list[Evidence] = []
        self.guidance: list[Guidance] = []
        self.calls: dict[str, int] = {"investigate_telemetry": 0, "consult_knowledge": 0}

    async def triage(self, request: str) -> TriageResult:
        self._reset(request)
        decision = await self.run(request)
        if decision.status == "declined":
            return TriageResult(status="declined", declined_reason=decision.reason)
        report = await self.synthesizer.synthesize(request, self.evidence, self.guidance)
        return TriageResult(status="triaged", report=report, evidence=self.evidence, guidance=self.guidance)

    async def tools(self) -> list[dict]:
        return SUBAGENT_TOOLS

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        if name not in self.calls:
            raise ToolFailure(f"unknown tool '{name}'")
        if self.calls[name] >= MAX_CALLS_PER_SUBAGENT:
            raise ToolFailure(f"{name} budget ({MAX_CALLS_PER_SUBAGENT} calls) used up; call finish now")
        self.calls[name] += 1
        try:
            if name == "investigate_telemetry":
                return await self._investigate(args)
            return await self._consult(args)
        except AgentError as e:
            raise ToolFailure(f"sub-agent failed: {e}") from e

    async def _investigate(self, args: dict[str, Any]) -> str:
        task = (f"Incident request: {self.request}\n"
                f"Service to investigate: {args.get('service', '')}\n"
                f"Question: {args.get('question', '')}")
        evidence = await self.telemetry.run(task)
        self.evidence.append(evidence)
        return as_json(evidence)

    async def _consult(self, args: dict[str, Any]) -> str:
        task = (f"Incident request: {self.request}\n"
                f"Question: {args.get('question', '')}\n"
                f"Telemetry context: {args.get('context') or 'none yet'}")
        guidance = await self.knowledge.run(task)
        self.guidance.append(guidance)
        return as_json(guidance.model_dump(exclude={"retrieved_ids"}))

    def validate_output(self, decision: OrchestratorDecision) -> str | None:
        if decision.status == "triaged" and not self.evidence:
            return "investigate telemetry for the affected service before finishing"
        if decision.status == "triaged" and not self.guidance:
            return "consult the knowledge base before finishing"
        return None
