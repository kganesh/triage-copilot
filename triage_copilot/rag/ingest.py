"""Load runbooks and postmortems from markdown and split them into section chunks.

Chunk ids are `<doc-id>#<section-slug>`, e.g. `runbook-db-pool#steps`. They are what the
agents cite, and what retrieval evals are labeled against.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DOCS = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    heading: str
    text: str


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def chunk_markdown(doc_id: str, markdown: str) -> list[Chunk]:
    title, heading, body, chunks = doc_id, "overview", [], []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            chunks.append(Chunk(f"{doc_id}#{slug(heading)}", doc_id, title, heading, text))
        body.clear()

    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading = line[3:].strip()
        else:
            body.append(line)
    flush()
    return chunks


def load_chunks(docs_dir: Path | str | None = None) -> list[Chunk]:
    root = Path(docs_dir or os.getenv("TRIAGE_DOCS_DIR") or DEFAULT_DOCS)
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*.md")):
        chunks.extend(chunk_markdown(path.stem, path.read_text()))
    if not chunks:
        raise FileNotFoundError(f"no markdown docs found under {root}")
    return chunks
