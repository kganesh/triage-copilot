"""Layer 1 — RAG retrieval evals. Deterministic: no LLM involved.

Run these first when grounding looks wrong: they tell you whether the right document
was ever retrieved, or whether generation went off the rails afterwards.
"""
import pytest

from evals.checks import load_cases
from triage_copilot.rag import BM25Retriever, load_chunks

K = 4
CASES = load_cases("retrieval.jsonl")
ANSWERABLE = [c for c in CASES if c["relevant"]]
UNANSWERABLE = [c for c in CASES if not c["relevant"]]


@pytest.fixture(scope="module")
def retriever():
    return BM25Retriever.from_dir()


def first_relevant_rank(retriever, case):
    docs = [h.chunk.doc_id for h in retriever.search(case["query"], k=K)]
    return next((i + 1 for i, d in enumerate(docs) if d in case["relevant"]), None)


def test_chunk_ids_are_unique():
    ids = [c.id for c in load_chunks()]
    assert len(ids) == len(set(ids))


def test_recall_at_k(retriever):
    misses = [c["query"] for c in ANSWERABLE if first_relevant_rank(retriever, c) is None]
    recall = 1 - len(misses) / len(ANSWERABLE)
    assert recall >= 0.95, f"recall@{K}={recall:.2f}; misses: {misses}"


def test_mean_reciprocal_rank(retriever):
    ranks = [first_relevant_rank(retriever, c) for c in ANSWERABLE]
    mrr = sum(1 / r for r in ranks if r) / len(ranks)
    assert mrr >= 0.85, f"MRR={mrr:.2f}"


@pytest.mark.parametrize("case", UNANSWERABLE, ids=lambda c: c["query"][:40])
def test_off_topic_queries_return_nothing(retriever, case):
    hits = retriever.search(case["query"], k=K)
    assert hits == [], f"expected no results, got {[(h.chunk.id, h.score) for h in hits]}"


def test_answerable_queries_return_something(retriever):
    empty = [c["query"] for c in ANSWERABLE if not retriever.search(c["query"], k=K)]
    assert not empty, f"threshold too high; no results for: {empty}"
