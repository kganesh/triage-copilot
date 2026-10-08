"""Run trace: every LLM call and tool call, per agent. Evals assert against this.
If OpenTelemetry is installed, each event is also emitted as a span."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

try:  # optional
    from opentelemetry import trace as otel

    _tracer = otel.get_tracer("triage_copilot")
except ImportError:  # pragma: no cover
    _tracer = None


@dataclass
class Event:
    agent: str
    kind: str  # "llm" | "tool" | "agent"
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Trace:
    events: list[Event] = field(default_factory=list)

    @contextmanager
    def span(self, agent: str, kind: str, name: str, args: dict | None = None):
        ev = Event(agent, kind, name, dict(args or {}))
        start = time.perf_counter()
        otel_cm = _tracer.start_as_current_span(f"{agent}.{kind}.{name}") if _tracer else None
        otel_span = otel_cm.__enter__() if otel_cm else None
        try:
            yield ev
        except Exception:
            ev.is_error = True
            raise
        finally:
            ev.latency_ms = (time.perf_counter() - start) * 1000
            self.events.append(ev)
            if otel_span is not None:
                otel_span.set_attribute("agent", agent)
                otel_span.set_attribute("is_error", ev.is_error)
                otel_cm.__exit__(None, None, None)

    # ---- queries used by evals ----
    def tool_calls(self, agent: str | None = None) -> list[Event]:
        return [e for e in self.events if e.kind == "tool" and (agent is None or e.agent == agent)]

    def tool_names(self, agent: str | None = None) -> list[str]:
        return [e.name for e in self.tool_calls(agent)]

    def agents_invoked(self) -> list[str]:
        return [e.name for e in self.events if e.kind == "agent"]

    def totals(self) -> dict[str, float]:
        llm = [e for e in self.events if e.kind == "llm"]
        return {
            "llm_calls": len(llm),
            "tool_calls": len(self.tool_calls()),
            "input_tokens": sum(e.input_tokens for e in llm),
            "output_tokens": sum(e.output_tokens for e in llm),
            "llm_latency_ms": round(sum(e.latency_ms for e in llm), 1),
        }

    def to_dicts(self) -> list[dict]:
        return [asdict(e) for e in self.events]
