"""Deterministic checks for one end-to-end run. Shared by the pytest live evals and run_evals.py.

Each check reads the final result and the trace only, so the same checks work no matter
which model or prompt produced the run.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from triage_copilot.schemas import TriageResult
from triage_copilot.trace import Trace

DATASETS = Path(__file__).resolve().parent / "datasets"
DEFAULT_MAX_TOOL_CALLS = 20


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def load_cases(name: str = "scenarios.jsonl") -> list[dict]:
    return [json.loads(line) for line in (DATASETS / name).read_text().splitlines() if line.strip()]


def run_checks(case: dict, result: TriageResult, trace: Trace) -> list[CheckResult]:
    exp = case["expect"]
    out = [CheckResult("status", result.status == exp["status"], f"got {result.status}")]
    if exp["status"] == "declined":
        subagents = [a for a in trace.agents_invoked() if a != "orchestrator"]
        out.append(CheckResult("no_subagents_when_declined", not subagents, f"invoked {subagents}"))
        return out
    if result.report is None:
        return out + [CheckResult("report_present", False, "no report")]

    r = result.report
    if "root_cause_category" in exp:
        out.append(CheckResult("root_cause", r.root_cause_category == exp["root_cause_category"],
                               f"got {r.root_cause_category}"))

    investigated = {e.args.get("service") for e in trace.tool_calls("orchestrator")
                    if e.name == "investigate_telemetry"}
    for svc in exp.get("must_investigate", []):
        out.append(CheckResult(f"investigated:{svc}", svc in investigated, f"investigated {sorted(investigated)}"))

    telemetry_tools = set(trace.tool_names("telemetry"))
    for tool in exp.get("must_call_tools", []):
        out.append(CheckResult(f"called:{tool}", tool in telemetry_tools, f"called {sorted(telemetry_tools)}"))

    if docs := exp.get("must_cite_any_doc"):
        cited_docs = {c.split("#")[0] for c in r.citations}
        out.append(CheckResult("cites_expected_doc", bool(cited_docs & set(docs)), f"cited {sorted(cited_docs)}"))

    # Guardrails catch invented citations; the check reports that the model tried.
    dropped = [n for n in r.validation_notes if n.startswith("dropped citation")]
    out.append(CheckResult("no_invented_citations", not dropped, "; ".join(dropped)))

    if phrases := exp.get("forbidden_phrases"):
        text = " ".join([r.title, r.hypothesis, *[s.action for s in r.next_steps]]).lower()
        hits = [p for p in phrases if p in text]
        out.append(CheckResult("no_forbidden_phrases", not hits, f"found {hits}"))

    if sev := exp.get("severity_in"):
        out.append(CheckResult("severity", r.severity in sev, f"got {r.severity}"))
    if "max_confidence" in exp:
        out.append(CheckResult("confidence_calibrated", r.confidence <= exp["max_confidence"],
                               f"got {r.confidence:.2f}"))
    if exp.get("expect_data_gaps"):
        out.append(CheckResult("reports_data_gaps", bool(r.data_gaps), f"{r.data_gaps}"))

    n_tools = len(trace.tool_calls())
    limit = exp.get("max_tool_calls", DEFAULT_MAX_TOOL_CALLS)
    out.append(CheckResult("tool_budget", n_tools <= limit, f"{n_tools} tool calls (limit {limit})"))

    repeats = [k for k, n in Counter(
        (e.agent, e.name, json.dumps(e.args, sort_keys=True)) for e in trace.tool_calls()).items() if n > 1]
    out.append(CheckResult("no_duplicate_tool_calls", not repeats, f"{len(repeats)} repeated calls"))
    return out
