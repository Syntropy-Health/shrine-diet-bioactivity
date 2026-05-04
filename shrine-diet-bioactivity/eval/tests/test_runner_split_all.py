"""Test for the --split=all CLI option that combines train/val/test."""
import json
import subprocess
import sys


def test_runner_split_all_combines_all_scenario_ids(tmp_path):
    """When --split=all, the runner must use the union of train+val+test
    scenario_ids from the splits manifest."""
    splits = {
        "seed": 42, "benchmark_version": "v1", "ratios": [0.6, 0.2, 0.2],
        "leakage_guard": {"enforced": False},
        "train_ids": ["case-001", "case-002"],
        "val_ids": ["case-003"],
        "test_ids": ["case-004", "case-005"],
    }
    splits_path = tmp_path / "splits.json"
    splits_path.write_text(json.dumps(splits))

    bench = {
        "name": "TestBench",
        "version": "v1",
        "scenarios": [
            {"id": f"case-{i:03d}", "category": "herbal_single_symptom",
             "research_question": f"Q{i}",
             "gold": {"expected_complexity": "low",
                      "expected_panel_verdict": "abstain",
                      "expected_evidence_tier": "unknown",
                      "expected_min_chains": 0,
                      "expected_defer": False, "expected_red_flags": [],
                      "languages": ["en"]},
             "rationale": "test", "source_citations": []}
            for i in range(1, 6)
        ],
    }
    bench_path = tmp_path / "bench.json"
    bench_path.write_text(json.dumps(bench))

    # Use --systems=nonexistent to trigger ValueError BEFORE any run loop;
    # this lets us assert the pre-flight scenario-count line was emitted.
    result = subprocess.run(
        [sys.executable, "-m", "eval.runner",
         "--bench", str(bench_path), "--splits", str(splits_path),
         "--out", str(tmp_path / "out"), "--split", "all",
         "--systems", "definitely_not_a_real_system"],
        capture_output=True, text=True,
    )
    # The pre-flight log line should mention scenarios=5 (all 5 ids)
    assert "scenarios=5" in result.stderr, (
        f"--split=all should select all 5 scenario ids; got stderr:\n{result.stderr}"
    )
