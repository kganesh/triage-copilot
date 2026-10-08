"""BM25 retriever. Dependency-free and deterministic, which keeps retrieval evals stable.

Swap in an embedding retriever by implementing the same `search()` signature; the
Knowledge agent and the retrieval evals don't change.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .ingest import Chunk, load_chunks

STOPWORDS = set(
    "a an and are as at be by for from has have in is it its of on or that the this to was were with "
    "what when which who why how do does did not no our we you your i".split()
)


def tokenize(text: str) -> list[str]:
    tokens = []
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if t in STOPWORDS or len(t) < 2:
            continue
        for suffix in ("ing", "ed", "es", "s"):  # crude stemming is enough for runbooks
            if len(t) > 4 and t.endswith(suffix):
                t = t[: -len(suffix)]
                break
        tokens.append(t)
    return tokens


@dataclass
class Hit:
    chunk: Chunk
    score: float


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        # Title and heading are indexed with the body: they carry most of the topic signal.
        self.docs = [Counter(tokenize(f"{c.title} {c.heading} {c.text}")) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / len(self.lengths)
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_dir(cls, docs_dir: str | None = None) -> "BM25Retriever":
        return cls(load_chunks(docs_dir))

    def score(self, query_terms: list[str], i: int) -> float:
        doc, length, s = self.docs[i], self.lengths[i], 0.0
        for t in query_terms:
            if t in doc:
                tf = doc[t]
                s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return s

    def search(self, query: str, k: int = 4, min_score: float = 5.0) -> list[Hit]:
        """Top-k chunks scoring at least `min_score`. An empty list means 'nothing relevant'.

        min_score is tuned on evals/datasets/retrieval.jsonl: off-topic queries topped out
        at ~4.8 and the weakest relevant query scored ~5.1. That margin is thin; re-tune
        (or switch to embeddings) when the corpus grows.
        """
        terms = tokenize(query)
        hits = [Hit(c, round(self.score(terms, i), 3)) for i, c in enumerate(self.chunks)]
        hits = [h for h in hits if h.score >= min_score]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:k]
