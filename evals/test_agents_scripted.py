"""Layer 3 — agent plumbing and guardrail evals, with a scripted model (no API key needed).

The scripted model plays each agent's part, so these tests check what the *code* does:
routing, tool execution over MCP, citation enforcement, schema retries, budgets and
confidence caps. Whether a real model makes good decisions is Layer 4 (test_e2e_live.py).
"""
import asyncio
import re

import pytest

from triage_copilot.agents import AgentError, SynthesizerAgent, TelemetryAgent
from triage_copilot.app import mcp_client, triage
from triage_copilot.llm import LLMResponse, ScriptedLLM, text, tool_call
from triage_copilot.schemas import Evidence, Finding, Guidance, Step
from triage_copilot.trace import Trace

CHUNK_ID = re.compile(r"\[([a-z0-9-]+#[a-z0-9-]+)\]")

EVIDENCE = dict(
    service="checkout-svc",
    findings=[dict(signal="latency_p99_ms", observation="310ms -> 2600ms after v2.14.0", source_tool="query_metrics")],
    suspected_cause="v2.14.0 retry policy change",
)
REPORT = dict(
    title="checkout-svc latency regression", severity="sev2", root_cause_category="deploy_regression",
    hypothesis="v2.14.0 removed retry jitter, causing a retry storm against pricing-svc.", confidence=0.85,
    key_evidence=["p99 310ms -> 2600ms starting 20 min ago"],
    next_steps=[dict(action="Roll back checkout-svc to v2.13.4", citation="runbook-rollback#steps")],
    citations=["runbook-rollback#steps"],
)


def cite_first_retrieved(messages: list[dict]) -> LLMResponse:
    """Knowledge step: cite the first chunk id the search actually returned."""
    last = messages[-1]["content"][0]["content"]
    cid = CHUNK_ID.findall(last)[0]
    return tool_call("submit_guidance", summary="Roll back the deploy.",
                     recommended_steps=[{"action": "Roll back", "citation": cid}], citations=[cid])


def happy_scripts(**overrides) -> dict:
    scripts = {
        "orchestrator": [
            tool_call("investigate_telemetry", service="checkout-svc", question="What changed?"),
            tool_call("consult_knowledge", question="Fix?", context="latency up after deploy, retries"),
            tool_call("finish", status="triaged", reason="evidence and guidance gathered"),
        ],
        "telemetry": [
            tool_call("query_metrics", service="checkout-svc", metric="latency_p99_ms"),
            tool_call("get_recent_deploys", service="checkout-svc"),
            tool_call("submit_evidence", **EVIDENCE),
        ],
        "knowledge": [tool_call("search_runbooks", query="latency spike after deploy rollback"), cite_first_retrieved],
        "synthesizer": [tool_call("submit_report", **REPORT)],
    }
    scripts.update(overrides)
    return scripts


def run(scripts: dict, scenario: str = "bad_deploy", request: str = "checkout-svc p99 > 2s"):
    llm = ScriptedLLM(scripts)
    result, trace = asyncio.run(triage(request, scenario=scenario, llm=llm, transport="inproc"))
    return result, trace, llm


def tool_results_seen_by(llm: ScriptedLLM, agent: str) -> list[dict]:
    """Every tool result the agent's model was shown, in order (each call replays history, so dedupe)."""
    seen: dict[str, dict] = {}
    for a, msgs in llm.calls:
        if a != agent:
            continue
        for m in msgs:
            if isinstance(m["content"], list):
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        seen.setdefault(b["tool_use_id"], b)
    return list(seen.values())


# ---------- routing ----------

def test_full_pipeline_routes_through_all_four_agents():
    result, trace, _ = run(happy_scripts())
    assert result.status == "triaged"
    assert trace.agents_invoked() == ["telemetry", "knowledge", "orchestrator", "synthesizer"]
    assert trace.tool_names("telemetry") == ["query_metrics", "get_recent_deploys"]
    assert not any(e.is_error for e in trace.tool_calls("telemetry"))
    assert result.guidance[0].retrieved_ids, "retrieved ids must be recorded by code"


def test_real_mcp_data_reaches_the_model():
    _, _, llm = run(happy_scripts())
    seen = " ".join(r["content"] for r in tool_results_seen_by(llm, "telemetry"))
    assert "2600" in seen and "v2.14.0" in seen
    assert '<tool_output untrusted="true">' in seen


def test_out_of_scope_request_is_declined_without_subagents():
    result, trace, _ = run({"orchestrator": [tool_call("finish", status="declined", reason="not an incident")]},
                           request="write a poem")
    assert result.status == "declined" and result.report is None
    assert trace.agents_invoked() == ["orchestrator"]


def test_orchestrator_cannot_finish_before_investigating():
    scripts = happy_scripts()
    scripts["orchestrator"].insert(0, tool_call("finish", status="triaged", reason="guessing"))
    result, _, llm = run(scripts)
    assert result.status == "triaged"
    rejected = tool_results_seen_by(llm, "orchestrator")[0]
    assert rejected["is_error"] and "investigate telemetry" in rejected["content"]


def test_subagent_call_budget_is_enforced():
    probes = [tool_call("investigate_telemetry", service="checkout-svc", question=f"try {i}") for i in range(4)]
    scripts = happy_scripts(
        orchestrator=probes + happy_scripts()["orchestrator"][1:],
        telemetry=happy_scripts()["telemetry"] * 3,
    )
    _, trace, llm = run(scripts)
    assert [e.is_error for e in trace.tool_calls("orchestrator")][:4] == [False, False, False, True]
    assert any("budget" in r["content"] for r in tool_results_seen_by(llm, "orchestrator"))


# ---------- guardrails ----------

def test_knowledge_agent_rejects_citations_it_did_not_retrieve():
    fake = tool_call("submit_guidance", summary="x", recommended_steps=[{"action": "x", "citation": "runbook-made-up#x"}],
                     citations=["runbook-made-up#x"])
    scripts = happy_scripts(knowledge=[tool_call("search_runbooks", query="deploy rollback"), fake,
                                       lambda m: cite_first_retrieved(m[:-2])])
    result, _, llm = run(scripts)
    rejection = tool_results_seen_by(llm, "knowledge")[1]
    assert rejection["is_error"] and "runbook-made-up#x" in rejection["content"]
    assert all(c in result.guidance[0].retrieved_ids for c in result.guidance[0].citations)


def test_synthesizer_drops_invented_citations():
    bad = dict(REPORT, next_steps=[dict(action="Do the thing", citation="pm-invented#x")], citations=["pm-invented#x"])
    result, _, _ = run(happy_scripts(synthesizer=[tool_call("submit_report", **bad)]))
    assert result.report.citations == []
    assert result.report.next_steps[0].citation is None
    assert any("pm-invented#x" in n for n in result.report.validation_notes)


def test_schema_violation_gets_a_retry():
    broken = tool_call("submit_report", title="missing most fields")
    result, _, llm = run(happy_scripts(synthesizer=[broken, tool_call("submit_report", **REPORT)]))
    assert result.report.title == REPORT["title"]
    assert tool_results_seen_by(llm, "synthesizer")[0]["is_error"]


def test_mcp_failure_is_shown_to_the_model_as_an_error():
    scripts = happy_scripts(telemetry=[
        tool_call("query_metrics", service="inventory-svc", metric="memory_utilization_pct"),
        tool_call("submit_evidence", service="inventory-svc", findings=[], suspected_cause="unknown",
                  data_gaps=["metrics backend timed out"]),
    ])
    _, trace, llm = run(scripts, scenario="metrics_unavailable")
    assert trace.tool_calls("telemetry")[0].is_error
    err = tool_results_seen_by(llm, "telemetry")[0]
    assert err["is_error"] and "timeout" in err["content"].lower()


def test_agent_that_never_submits_fails_loudly():
    async def go():
        async with mcp_client("bad_deploy", "inproc") as client:
            agent = TelemetryAgent(ScriptedLLM({"telemetry": [text("thinking...")] * 10}), Trace(), client)
            await agent.run("investigate")

    with pytest.raises(AgentError):
        asyncio.run(go())


@pytest.mark.parametrize("evidence,report_extra,cap", [
    ([], {}, 0.3),                                                # no telemetry findings
    ([Evidence(**EVIDENCE, data_gaps=["no metrics"])], {}, 0.7),  # missing data
    ([Evidence(**EVIDENCE)], {"conflicts": ["deploy vs db"]}, 0.75),
    ([Evidence(**EVIDENCE)], {}, 0.95),                           # clean case: no cap
])
def test_confidence_caps(evidence, report_extra, cap):
    agent = SynthesizerAgent(ScriptedLLM({"synthesizer": [tool_call("submit_report", **dict(REPORT, **report_extra, confidence=0.95))]}), Trace())
    guidance = [Guidance(summary="s", recommended_steps=[Step(action="a")], retrieved_ids=["runbook-rollback#steps"])]
    report = asyncio.run(agent.synthesize("alert", evidence, guidance))
    assert report.confidence == pytest.approx(cap)


def test_findings_schema_is_typed():
    with pytest.raises(Exception):
        Finding(signal="x")  # observation and source_tool are required
