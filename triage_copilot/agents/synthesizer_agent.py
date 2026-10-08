"""Synthesizer agent: turns evidence + guidance into the final TriageReport.

The model writes the report; code then applies deterministic guardrails the model
cannot talk its way around:
  * citations must come from chunks the Knowledge agent actually retrieved
  * confidence is capped when there is no telemetry, missing data, or a conflict
"""
from __future__ import annotations

from ..schemas import Evidence, Guidance, TriageReport
from .base import BaseAgent, as_json

CAP_NO_FINDINGS = 0.3
CAP_DATA_GAPS = 0.7
CAP_CONFLICTS = 0.75


class SynthesizerAgent(BaseAgent):
    name = "synthesizer"
    prompt_file = "synthesizer.md"
    output_model = TriageReport
    code_filled_fields = {"validation_notes"}
    submit_tool = "submit_report"
    submit_description = "Submit the final triage report."
    max_steps = 4

    def __init__(self, llm, trace):
        super().__init__(llm, trace)
        self.allowed_citations: set[str] = set()
        self.evidence: list[Evidence] = []

    async def synthesize(self, request: str, evidence: list[Evidence], guidance: list[Guidance]) -> TriageReport:
        self.evidence = evidence
        self.allowed_citations = {cid for g in guidance for cid in g.retrieved_ids}
        task = (
            f"## Incident request\n{request}\n\n"
            f"## Telemetry evidence (from the Telemetry agent)\n{as_json([e.model_dump() for e in evidence])}\n\n"
            f"## Runbook guidance (from the Knowledge agent)\n"
            f"{as_json([g.model_dump() for g in guidance])}\n\n"
            f"Citable ids: {sorted(self.allowed_citations) or 'none'}"
        )
        return await self.run(task)

    def validate_output(self, report: TriageReport) -> str | None:
        if not report.next_steps:
            return "next_steps must contain at least one concrete action"
        if not report.key_evidence:
            return "key_evidence must reference the telemetry findings the hypothesis rests on"
        return None

    def finalize(self, report: TriageReport) -> TriageReport:
        notes: list[str] = []
        self._enforce_citations(report, notes)
        self._cap_confidence(report, notes)
        report.validation_notes = notes
        return report

    def _enforce_citations(self, report: TriageReport, notes: list[str]) -> None:
        for step in report.next_steps:
            if step.citation and step.citation not in self.allowed_citations:
                notes.append(f"dropped citation '{step.citation}' (not in retrieved docs)")
                step.citation = None
        kept = [c for c in report.citations if c in self.allowed_citations]
        for c in set(report.citations) - set(kept):
            notes.append(f"dropped citation '{c}' (not in retrieved docs)")
        # Every step citation should also appear in the report's citation list.
        report.citations = sorted(set(kept) | {s.citation for s in report.next_steps if s.citation})

    def _cap_confidence(self, report: TriageReport, notes: list[str]) -> None:
        caps = []
        if not any(e.findings for e in self.evidence):
            caps.append((CAP_NO_FINDINGS, "no telemetry findings"))
        if report.data_gaps or any(e.data_gaps for e in self.evidence):
            caps.append((CAP_DATA_GAPS, "telemetry data gaps"))
        if report.conflicts:
            caps.append((CAP_CONFLICTS, "conflicting signals"))
        for cap, reason in sorted(caps):
            if report.confidence > cap:
                notes.append(f"confidence capped {report.confidence:.2f} -> {cap:.2f} ({reason})")
                report.confidence = cap
