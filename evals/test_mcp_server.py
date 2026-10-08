"""Layer 2 — MCP tool contract evals. Deterministic: exercises the server through a real
MCP client (in-process), plus one test over stdio to cover the wire protocol."""
import asyncio
import json

import pytest

from triage_copilot.app import mcp_client
from triage_copilot.mcp_server import list_scenarios

EXPECTED_TOOLS = {"list_services", "query_metrics", "search_logs", "get_recent_deploys"}


async def call(scenario: str, tool: str, args: dict, transport: str = "inproc"):
    async with mcp_client(scenario, transport) as client:
        return await client.call_tool(tool, args)


def text(result) -> str:
    return "\n".join(c.text for c in result.content if c.type == "text")


@pytest.mark.parametrize("scenario", list_scenarios())
def test_every_scenario_exposes_the_tool_contract(scenario):
    async def go():
        async with mcp_client(scenario, "inproc") as client:
            return (await client.list_tools()).tools

    tools = asyncio.run(go())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.description and t.input_schema.get("type") == "object" for t in tools)


def test_stdio_transport_round_trip():
    result = asyncio.run(call("bad_deploy", "list_services", {}, transport="stdio"))
    assert not result.is_error
    assert "checkout-svc" in text(result)


def test_unknown_service_is_a_helpful_error():
    result = asyncio.run(call("bad_deploy", "search_logs", {"service": "nope-svc"}))
    assert result.is_error
    assert "unknown service" in text(result) and "checkout-svc" in text(result)


def test_invalid_metric_is_rejected_by_schema():
    result = asyncio.run(call("bad_deploy", "query_metrics", {"service": "checkout-svc", "metric": "vibes"}))
    assert result.is_error


def test_backend_failure_is_surfaced_not_hidden():
    result = asyncio.run(call("metrics_unavailable", "query_metrics",
                              {"service": "inventory-svc", "metric": "latency_p99_ms"}))
    assert result.is_error
    assert "timeout" in text(result).lower()


def test_metrics_window_filters_points():
    result = asyncio.run(call("bad_deploy", "query_metrics",
                              {"service": "checkout-svc", "metric": "latency_p99_ms", "window_minutes": 20}))
    data = json.loads(text(result))
    assert [p["minutes_ago"] for p in data["points"]] == [20, 10, 0]
    assert data["baseline"] == 310 and data["current"] == 2600


def test_logs_are_newest_first_and_level_filtered():
    result = asyncio.run(call("bad_deploy", "search_logs", {"service": "checkout-svc", "level": "ERROR"}))
    logs = json.loads(text(result))["logs"]
    assert logs and all(entry["level"] == "ERROR" for entry in logs)
    assert [entry["minutes_ago"] for entry in logs] == sorted(entry["minutes_ago"] for entry in logs)


def test_injection_text_reaches_the_agent_as_data():
    """The server must not sanitize logs; defending against them is the agents' job."""
    result = asyncio.run(call("prompt_injection", "search_logs", {"service": "search-svc"}))
    assert "ignore all previous instructions" in text(result)
