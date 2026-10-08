"""Tests for the eval harness itself: an eval that can't fail is worse than no eval.

Uses real pipeline outputs (scripted model) so the checks are exercised on genuine
TriageResult and Trace objects, not hand-built ones.
"""
import asyncio

from evals.checks import load_cases, run_checks
from evals.judges import judge_groundedness
from evals.test_agents_scripted import REPORT, happy_scripts, run
from triage_copilot.agents import KnowledgeAgent, Orchestrator, SynthesizerAgent, TelemetryAgent
from triage_copilot.llm import ScriptedLLM, tool_call
from triage_copilot.rag import BM25Retriever

CASES = {c["id"]: c for c in load_cases()}


def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_good_run_passes_every_check():
    result, trace, _ = run(happy_scripts())
    assert failed(run_checks(CASES["bad-deploy-01"], result, trace)) == set()


def test_decline_case_passes_and_wrong_routing_fails():
    declined, trace, _ = run({"orchestrator": [tool_call("finish", status="declined", reason="n/a")]})
    assert failed(run_checks(CASES["out-of-scope-01"], declined, trace)) == set()
    triaged, trace, _ = run(happy_scripts())
    assert "status" in failed(run_checks(CASES["out-of-scope-01"], triaged, trace))


def test_checks_catch_wrong_root_cause_and_missing_investigation():
    result, trace, _ = run(happy_scripts())
    assert {"root_cause", "investigated:batch-reconciler"} <= failed(run_checks(CASES["noisy-neighbor-01"], result, trace))


def test_checks_catch_invented_citations_and_forbidden_phrases():
    bad = dict(REPORT, title="Incident is resolved", citations=["runbook-fake#x"])
    result, trace, _ = run(happy_scripts(synthesizer=[tool_call("submit_report", **bad)]))
    case = dict(CASES["bad-deploy-01"], expect=dict(CASES["bad-deploy-01"]["expect"], forbidden_phrases=["is resolved"]))
    assert {"no_invented_citations", "no_forbidden_phrases"} <= failed(run_checks(case, result, trace))


def test_checks_catch_duplicate_tool_calls():
    dup = [tool_call("search_logs", service="checkout-svc"), tool_call("search_logs", service="checkout-svc")]
    scripts = happy_scripts()
    scripts["telemetry"] = dup + scripts["telemetry"]
    result, trace, _ = run(scripts)
    assert "no_duplicate_tool_calls" in failed(run_checks(CASES["bad-deploy-01"], result, trace))


def test_judge_score_is_fraction_of_supported_claims():
    result, _, _ = run(happy_scripts())
    verdict_llm = ScriptedLLM({"judge": [tool_call("submit_verdict", claims=[
        {"claim": "p99 rose to 2600ms", "supported": True},
        {"claim": "pricing-svc was down", "supported": False},
    ])]})
    verdict = asyncio.run(judge_groundedness(verdict_llm, result, BM25Retriever.from_dir()))
    assert verdict.score == 0.5 and verdict.unsupported == ["pricing-svc was down"]


def test_submit_schemas_are_self_contained():
    """Tool input schemas sent to the API must not contain unresolved $refs."""
    for agent_cls in (TelemetryAgent, KnowledgeAgent, SynthesizerAgent, Orchestrator):
        spec = agent_cls._submit_spec(agent_cls)  # classmethod-style use; no instance state needed
        assert "$ref" not in str(spec) and "$defs" not in str(spec)
        for hidden in agent_cls.code_filled_fields:
            assert hidden not in spec["input_schema"]["properties"]
