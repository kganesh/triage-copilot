"""The Anthropic adapter: request shape in, normalized response out (SDK client stubbed)."""
import asyncio
from types import SimpleNamespace as NS

from triage_copilot.llm import AnthropicLLM


class FakeMessages:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return NS(
            usage=NS(input_tokens=120, output_tokens=30),
            content=[NS(type="text", text="Checking deploys."),
                     NS(type="tool_use", id="toolu_1", name="get_recent_deploys", input={"service": "a"})],
        )


def test_adapter_sends_tools_and_normalizes_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = AnthropicLLM(model="test-model")
    fake = FakeMessages()
    llm.client = NS(messages=fake)
    tools = [{"name": "get_recent_deploys", "description": "d", "input_schema": {"type": "object"}}]

    resp = asyncio.run(llm.complete(agent="telemetry", system="sys",
                                    messages=[{"role": "user", "content": "hi"}], tools=tools))

    assert fake.kwargs["model"] == "test-model" and fake.kwargs["tools"] == tools
    assert fake.kwargs["system"] == "sys" and fake.kwargs["temperature"] == 0.0
    assert resp.text == "Checking deploys."
    assert [(c.id, c.name, c.input) for c in resp.tool_calls] == [("toolu_1", "get_recent_deploys", {"service": "a"})]
    assert (resp.input_tokens, resp.output_tokens) == (120, 30)
    assert resp.content_blocks()[1] == {"type": "tool_use", "id": "toolu_1", "name": "get_recent_deploys",
                                        "input": {"service": "a"}}
