"""Layer 4 — end-to-end evals against the real model. Skipped without ANTHROPIC_API_KEY.

    pytest -m live                     # one run per scenario, deterministic checks + judge
    python -m evals.run_evals --k 3    # repeated runs with pass^k and cost/latency stats
"""
import asyncio
import os

import pytest

from evals.checks import load_cases, run_checks
from evals.judges import judge_groundedness
from triage_copilot.app import triage
from triage_copilot.llm import AnthropicLLM
from triage_copilot.rag import BM25Retriever

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"),
]
GROUNDEDNESS_MIN = 0.8


@pytest.fixture(scope="module")
def retriever():
    return BM25Retriever.from_dir()


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_scenario(case, retriever):
    llm = AnthropicLLM()
    result, trace = asyncio.run(
        triage(case["request"], scenario=case["scenario"], llm=llm, retriever=retriever, transport="inproc")
    )
    failed = [f"{c.name}: {c.detail}" for c in run_checks(case, result, trace) if not c.passed]
    assert not failed, "\n".join(failed)

    if result.report is not None:
        verdict = asyncio.run(judge_groundedness(llm, result, retriever))
        assert verdict.score >= GROUNDEDNESS_MIN, f"groundedness {verdict.score}: {verdict.unsupported}"
