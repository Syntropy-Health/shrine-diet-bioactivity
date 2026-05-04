"""Tests for the cost_tracker — captures per-call token usage + latency."""
from unittest.mock import MagicMock

from agents.cost_tracker import CostTracker, attach_to_agent  # type: ignore[import-not-found]


def test_cost_tracker_records_call_with_token_usage():
    tracker = CostTracker()
    agent = MagicMock()
    agent.name = "Dietitian"
    # The agent's generate_reply returns either a str or dict
    agent.generate_reply = MagicMock(return_value='{"role":"Dietitian","verdict":"prefer"}')
    # Simulate a side channel returning {prompt: 100, completion: 50}
    agent._test_last_usage = {"prompt_tokens": 100, "completion_tokens": 50}

    attach_to_agent(agent, tracker, usage_extractor=lambda a: a._test_last_usage)

    out = agent.generate_reply(messages=[{"role": "user", "content": "hi"}])
    assert "Dietitian" in out

    rows = tracker.rows()
    assert len(rows) == 1
    assert rows[0]["agent"] == "Dietitian"
    assert rows[0]["prompt_tokens"] == 100
    assert rows[0]["completion_tokens"] == 50
    assert rows[0]["latency_ms"] >= 0


def test_cost_tracker_to_csv(tmp_path):
    tracker = CostTracker()
    tracker._record("Dietitian", 100, 50, 1234.5, "case-001")
    tracker._record("Pharmacologist", 80, 40, 999.0, "case-001")

    csv_path = tmp_path / "cost.csv"
    tracker.to_csv(csv_path)
    text = csv_path.read_text()

    assert "agent,prompt_tokens,completion_tokens,latency_ms,scenario_id" in text
    assert "Dietitian,100,50,1234.5,case-001" in text
    assert "Pharmacologist,80,40,999.0,case-001" in text


def test_cost_tracker_handles_extractor_failure():
    """If the usage extractor raises, the tracker logs zero tokens but
    still records the call."""
    tracker = CostTracker()
    agent = MagicMock()
    agent.name = "Pharmacologist"
    agent.generate_reply = MagicMock(return_value="ok")

    def boom(_a):
        raise RuntimeError("usage path missing")

    attach_to_agent(agent, tracker, usage_extractor=boom)
    agent.generate_reply(messages=[])

    rows = tracker.rows()
    assert len(rows) == 1
    assert rows[0]["prompt_tokens"] == 0
    assert rows[0]["completion_tokens"] == 0
