"""Knowledge agent: answers questions from runbooks and postmortems (RAG).

The model may search several times (query rewriting), but it can only cite chunk ids
that the retriever actually returned in this run; anything else is rejected.
"""
from __future__ import annotations

from typing import Any

from ..rag import BM25Retriever, Chunk
from ..schemas import Guidance
from .base import BaseAgent, ToolFailure

SEARCH_TOOL = {
    "name": "search_runbooks",
    "description": (
        "Keyword search over incident runbooks and past postmortems. Returns matching sections "
        "with ids like 'runbook-db-pool#steps'. Use specific symptoms, error strings and component "
        "names. Returns nothing when no document is relevant."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keywords"},
            "k": {"type": "integer", "description": "Max sections to return (1-8)", "default": 4},
        },
        "required": ["query"],
    },
}


class KnowledgeAgent(BaseAgent):
    name = "knowledge"
    prompt_file = "knowledge.md"
    output_model = Guidance
    code_filled_fields = {"retrieved_ids"}
    submit_tool = "submit_guidance"
    submit_description = "Submit guidance grounded in the sections you retrieved. Call once, when done."
    max_steps = 6

    def __init__(self, llm, trace, retriever: BM25Retriever):
        super().__init__(llm, trace)
        self.retriever = retriever
        self.retrieved: dict[str, Chunk] = {}

    async def run(self, task: str) -> Guidance:
        self.retrieved = {}  # citations are scoped to this run's retrievals
        return await super().run(task)

    async def tools(self) -> list[dict]:
        return [SEARCH_TOOL]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        if name != "search_runbooks":
            raise ToolFailure(f"unknown tool '{name}'")
        query = str(args.get("query", "")).strip()
        if not query:
            raise ToolFailure("query must not be empty")
        k = max(1, min(int(args.get("k", 4)), 8))
        hits = self.retriever.search(query, k=k)
        if not hits:
            return "No relevant runbooks or postmortems found for this query."
        for h in hits:
            self.retrieved[h.chunk.id] = h.chunk
        return "\n\n".join(
            f"[{h.chunk.id}] {h.chunk.title} / {h.chunk.heading} (score {h.score})\n{h.chunk.text}"
            for h in hits
        )

    def validate_output(self, output: Guidance) -> str | None:
        cited = set(output.citations) | {s.citation for s in output.recommended_steps if s.citation}
        unknown = sorted(c for c in cited if c not in self.retrieved)
        if unknown:
            return f"citations {unknown} were not returned by search_runbooks; cite only ids from results"
        if not output.no_relevant_docs and not cited:
            return "cite the sections your guidance comes from, or set no_relevant_docs=true"
        return None

    def finalize(self, output: Guidance) -> Guidance:
        output.retrieved_ids = sorted(self.retrieved)
        return output
