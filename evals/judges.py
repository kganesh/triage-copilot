"""LLM-as-judge: is every claim in the report supported by the gathered evidence and docs?

Calibrate before trusting it: label ~20 reports yourself, run the judge on them and check
agreement (see README). An uncalibrated judge is a second unvalidated model.
"""
from __future__ import annotations

from pydantic import BaseModel

from triage_copilot.llm import LLM
from triage_copilot.rag import BM25Retriever
from triage_copilot.schemas import TriageResult

JUDGE_SYSTEM = """You are a strict reviewer of incident triage reports.
You receive SOURCES (telemetry evidence and runbook sections) and a REPORT.
List every factual claim in the report's hypothesis, key_evidence and next_steps.
For each, decide if the SOURCES support it. Numbers, times, service names and error messages
must match the sources. Recommended actions are supported if a cited runbook section contains them.
Call submit_verdict once."""

VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit the per-claim verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "supported": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["claim", "supported"],
                },
            }
        },
        "required": ["claims"],
    },
}


class Verdict(BaseModel):
    score: float
    unsupported: list[str]


async def judge_groundedness(llm: LLM, result: TriageResult, retriever: BM25Retriever) -> Verdict:
    chunks = {c.id: c for c in retriever.chunks}
    cited = sorted({cid for g in result.guidance for cid in g.retrieved_ids})
    sources = {
        "telemetry_evidence": [e.model_dump() for e in result.evidence],
        "runbook_sections": {cid: chunks[cid].text for cid in cited if cid in chunks},
    }
    report = result.report.model_dump(exclude={"validation_notes"}) if result.report else {}
    prompt = f"SOURCES:\n{sources}\n\nREPORT:\n{report}"
    resp = await llm.complete(agent="judge", system=JUDGE_SYSTEM,
                              messages=[{"role": "user", "content": prompt}], tools=[VERDICT_TOOL])
    claims = next((c.input["claims"] for c in resp.tool_calls if c.name == "submit_verdict"), [])
    if not claims:
        return Verdict(score=0.0, unsupported=["judge returned no verdict"])
    unsupported = [c["claim"] for c in claims if not c.get("supported")]
    return Verdict(score=round(1 - len(unsupported) / len(claims), 3), unsupported=unsupported)
