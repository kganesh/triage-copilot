"""Typed contracts between agents. Sub-agents never hand each other free text."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RootCause = Literal[
    "deploy_regression",
    "db_connection_exhaustion",
    "resource_saturation",
    "memory_exhaustion",
    "dependency_failure",
    "config_error",
    "unknown",
]


class Finding(BaseModel):
    signal: str = Field(description="What was looked at, e.g. 'latency_p99_ms' or 'ERROR logs'")
    observation: str = Field(description="What the data showed, with numbers and times")
    source_tool: str = Field(description="MCP tool that produced this finding")


class Evidence(BaseModel):
    """Output of the Telemetry agent (MCP)."""
    service: str
    findings: list[Finding]
    suspected_cause: str = Field(description="One-sentence hypothesis from telemetry alone")
    data_gaps: list[str] = Field(default_factory=list, description="Signals that were unavailable or failed")


class Step(BaseModel):
    action: str
    citation: str | None = Field(default=None, description="Chunk id the step comes from, e.g. 'runbook-rollback#steps'")


class Guidance(BaseModel):
    """Output of the Knowledge agent (RAG)."""
    summary: str
    recommended_steps: list[Step]
    citations: list[str] = Field(default_factory=list)
    no_relevant_docs: bool = False
    # Filled by code, not the model: what the retriever actually returned.
    retrieved_ids: list[str] = Field(default_factory=list)


class TriageReport(BaseModel):
    """Output of the Synthesizer agent — the final deliverable."""
    title: str
    severity: Literal["sev1", "sev2", "sev3", "sev4"]
    root_cause_category: RootCause
    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)
    key_evidence: list[str]
    next_steps: list[Step]
    citations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list, description="Where telemetry and docs disagree")
    data_gaps: list[str] = Field(default_factory=list)
    # Filled by code: deterministic guardrail notes (dropped citations, confidence caps).
    validation_notes: list[str] = Field(default_factory=list)


class OrchestratorDecision(BaseModel):
    status: Literal["triaged", "declined"]
    reason: str = Field(description="Why the investigation is complete, or why the request is out of scope")


class TriageResult(BaseModel):
    status: Literal["triaged", "declined"]
    report: TriageReport | None = None
    declined_reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    guidance: list[Guidance] = Field(default_factory=list)
