"""Per-call token + latency tracker for AG2 ConversableAgents.

Wraps `agent.generate_reply` so each invocation records:
  - agent.name
  - prompt_tokens, completion_tokens (extracted via caller-provided callable)
  - latency_ms (wall-clock around generate_reply)
  - scenario_id (caller-set via tracker.set_scenario(...))

Usage:
    tracker = CostTracker()
    for agent in panel_agents:
        attach_to_agent(agent, tracker)
    tracker.set_scenario("case-001")
    # ... run panel ...
    tracker.to_csv("cost_latency.csv")

Per Paper 1 §E6: produces the cost+latency table for the paper's
Experimental Setup section.
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import Any, Callable

_log = logging.getLogger(__name__)


def _default_usage_extractor(agent: Any) -> dict[str, int]:
    """Best-effort AG2 usage extraction. AG2 v0.12 stores per-call usage
    on `client_cost_summary` (a list of dicts). We sum prompt+completion
    across the most recent entry, falling back to zeros on any error.
    """
    try:
        summary = getattr(agent, "client_cost_summary", None)
        if not summary:
            return {"prompt_tokens": 0, "completion_tokens": 0}
        last = summary[-1] if isinstance(summary, list) else summary
        return {
            "prompt_tokens": int(last.get("prompt_tokens", 0)),
            "completion_tokens": int(last.get("completion_tokens", 0)),
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0}


class CostTracker:
    """Accumulator for per-call cost + latency."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._scenario_id: str = ""

    def set_scenario(self, scenario_id: str) -> None:
        self._scenario_id = scenario_id

    def _record(
        self, agent_name: str, prompt: int, completion: int,
        latency_ms: float, scenario_id: str,
    ) -> None:
        self._rows.append({
            "agent": agent_name,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "latency_ms": latency_ms,
            "scenario_id": scenario_id,
        })

    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def to_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["agent", "prompt_tokens", "completion_tokens",
                            "latency_ms", "scenario_id"],
            )
            w.writeheader()
            w.writerows(self._rows)


def attach_to_agent(
    agent: Any,
    tracker: CostTracker,
    usage_extractor: Callable[[Any], dict[str, int]] | None = None,
) -> None:
    """Wrap agent.generate_reply so every call appends a row to tracker."""
    extractor = usage_extractor or _default_usage_extractor
    original = agent.generate_reply

    def wrapped(*args, **kwargs):
        t0 = time.monotonic()
        try:
            out = original(*args, **kwargs)
        finally:
            t1 = time.monotonic()
        try:
            usage = extractor(agent)
        except Exception as exc:
            _log.warning("cost_tracker: usage extractor failed for %s: %s",
                         getattr(agent, "name", "<unknown>"), exc)
            usage = {"prompt_tokens": 0, "completion_tokens": 0}
        tracker._record(
            agent_name=getattr(agent, "name", "<unknown>"),
            prompt=usage.get("prompt_tokens", 0),
            completion=usage.get("completion_tokens", 0),
            latency_ms=(t1 - t0) * 1000.0,
            scenario_id=tracker._scenario_id,
        )
        return out

    agent.generate_reply = wrapped
