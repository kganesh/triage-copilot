"""CLI:  python -m triage_copilot "p99 latency on checkout-svc above 2s" --scenario bad_deploy"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .app import triage
from .mcp_server import list_scenarios
from .schemas import TriageResult


def render(result: TriageResult) -> str:
    if result.status == "declined":
        return f"Declined: {result.declined_reason}"
    r = result.report
    lines = [
        f"# {r.title}",
        f"**Severity:** {r.severity}   **Root cause:** {r.root_cause_category}   **Confidence:** {r.confidence:.2f}",
        "",
        f"**Hypothesis:** {r.hypothesis}",
        "",
        "## Key evidence",
        *[f"- {e}" for e in r.key_evidence],
        "",
        "## Next steps",
        *[f"{i}. {s.action}" + (f"  [{s.citation}]" if s.citation else "") for i, s in enumerate(r.next_steps, 1)],
    ]
    for heading, items in (("Conflicts", r.conflicts), ("Data gaps", r.data_gaps),
                           ("Guardrail notes", r.validation_notes)):
        if items:
            lines += ["", f"## {heading}", *[f"- {x}" for x in items]]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Incident triage copilot")
    p.add_argument("request", nargs="?", help="Alert text or question")
    p.add_argument("--scenario", default="bad_deploy", choices=list_scenarios(),
                   help="Which telemetry fixture the MCP server serves")
    p.add_argument("--transport", default="stdio", choices=["stdio", "inproc"])
    p.add_argument("--json", action="store_true", help="Print the full result and trace as JSON")
    p.add_argument("--list-scenarios", action="store_true")
    args = p.parse_args()

    if args.list_scenarios:
        print("\n".join(list_scenarios()))
        return
    if not args.request:
        p.error("request is required")

    result, trace = asyncio.run(triage(args.request, scenario=args.scenario, transport=args.transport))
    if args.json:
        print(json.dumps({"result": result.model_dump(), "trace": trace.to_dicts()}, indent=2))
    else:
        print(render(result))
        print(f"\n---\n{trace.totals()}", file=sys.stderr)


if __name__ == "__main__":
    main()
