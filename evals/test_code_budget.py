"""Keeps the design constraint honest: every agent module stays under 200 lines."""
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[1] / "triage_copilot" / "agents"
MAX_LINES = 200


@pytest.mark.parametrize("path", sorted(AGENTS.glob("*.py")), ids=lambda p: p.name)
def test_agent_module_is_small(path):
    n = len(path.read_text().splitlines())
    assert n < MAX_LINES, f"{path.name} has {n} lines (limit {MAX_LINES})"
