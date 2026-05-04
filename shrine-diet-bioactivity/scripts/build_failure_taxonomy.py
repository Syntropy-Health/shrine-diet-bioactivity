"""Failure-mode taxonomy from the full-40 eval run.

Iterates over diet_os predictions, scores each scenario success/failure
by gold-vs-predicted verdict, and emits a markdown document with 10
case studies (3 successes + 7 failures) classified by agent-role
failure mode.

Failure mode taxonomy:
  - retrieval_empty: bundle had 0 chains for the scenario's intervention
  - panel_mis_vote: panel verdict diverged from gold on a well-retrieved scenario
  - calibrator_under_confidence: confidence < 0.1 on a clearly-supported case
  - json_validation_failure: prediction has runner-error placeholder

(retrieval_off_target and moderator_hallucination deferred to v2 — they
require fuzzy entity matching and consensus-vs-summary diff respectively.)

Per Paper 1 §E4. Output is a Results-section appendix subsection.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent  # shrine-diet-bioactivity/
_GIT_ROOT = _REPO.parent


def _classify_failure(pred: dict, gold: dict) -> str | None:
    """Return failure mode tag, or None if scenario was successful."""
    triage_rationale = pred.get("triage", {}).get("rationale", "")
    if "runner-error" in triage_rationale:
        return "json_validation_failure"

    candidate_chains = pred.get("candidate_chains", [])
    if not candidate_chains:
        return "retrieval_empty"

    pred_verdict = None
    verdicts = pred.get("panel", {}).get("verdicts", [])
    if verdicts:
        ctr = Counter(v.get("verdict") for v in verdicts)
        pred_verdict = ctr.most_common(1)[0][0] if ctr else None

    gold_verdict = gold.get("expected_panel_verdict")

    if pred_verdict != gold_verdict:
        return "panel_mis_vote"

    confidence = pred.get("confidence", 0)
    if confidence < 0.1:
        return "calibrator_under_confidence"

    return None  # success


def _build_taxonomy_md(
    classified: list[dict],
    selected_failures: list[dict],
    selected_successes: list[dict],
    by_mode: dict[str, list[dict]],
    run_dir_name: str,
) -> str:
    n_classified = len(classified)
    n_failures = sum(1 for c in classified if c["mode"])
    n_successes = n_classified - n_failures

    md = [
        "# diet_os failure-mode taxonomy",
        f"_Generated from {run_dir_name}. n_classified={n_classified}, "
        f"n_failures={n_failures}, n_successes={n_successes}._",
        "",
        "## Summary by failure mode",
        "",
        "| Mode | Count |",
        "|---|---:|",
    ]
    for mode_name, items in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        md.append(f"| {mode_name} | {len(items)} |")
    md.extend(["", "## Selected case studies", ""])

    for c in selected_failures + selected_successes:
        scen_id = c["id"]
        mode = c["mode"] or "success"
        gold_v = c["gold"].get("expected_panel_verdict", "?")
        verdicts = c["pred"].get("panel", {}).get("verdicts", [])
        pred_v = (Counter(v.get("verdict") for v in verdicts).most_common(1)[0][0]
                  if verdicts else "(no verdicts)")
        n_chains = len(c["pred"].get("candidate_chains", []))
        confidence = c["pred"].get("confidence", 0)
        md.extend([
            f"### {scen_id} — {mode}",
            "",
            f"- Gold verdict: `{gold_v}`",
            f"- Predicted majority verdict: `{pred_v}`",
            f"- candidate_chains: {n_chains}",
            f"- Confidence: {confidence:.3f}",
            f"- Triage rationale: {c['pred'].get('triage', {}).get('rationale', '')[:120]}",
            f"- Source rationale: {c['rationale'][:120]}",
            "",
        ])
    return "\n".join(md)


def main(run_dir: str | None = None) -> int:
    if run_dir:
        results_dir = Path(run_dir)
    else:
        # Pick latest
        root = _GIT_ROOT / "research-journal" / "shared" / "results"
        candidates = sorted([p for p in root.glob("2026*") if p.is_dir()],
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("ERROR: no run dirs found", file=sys.stderr)
            return 1
        results_dir = candidates[0]

    diet_os_dir = results_dir / "diet_os"
    if not diet_os_dir.is_dir():
        print(f"ERROR: {diet_os_dir} missing", file=sys.stderr)
        return 1

    bench_path = _GIT_ROOT / "research-journal" / "shared" / "datasets" / "dietresearchbench_v1.json"
    if not bench_path.exists():
        print(f"ERROR: bench not found at {bench_path}", file=sys.stderr)
        return 1

    bench = json.loads(bench_path.read_text())
    gold_by_id = {s["id"]: s.get("gold", {}) for s in bench.get("scenarios", [])}
    rationale_by_id = {s["id"]: s.get("rationale", "") for s in bench.get("scenarios", [])}

    classified: list[dict] = []
    for pred_path in sorted(diet_os_dir.glob("*.json")):
        scen_id = pred_path.stem
        if scen_id not in gold_by_id:
            continue
        pred = json.loads(pred_path.read_text())
        mode = _classify_failure(pred, gold_by_id[scen_id])
        classified.append({
            "id": scen_id,
            "mode": mode,
            "pred": pred,
            "gold": gold_by_id[scen_id],
            "rationale": rationale_by_id.get(scen_id, ""),
        })

    failures = [c for c in classified if c["mode"]]
    successes = [c for c in classified if not c["mode"]]

    by_mode: dict[str, list[dict]] = {}
    for f in failures:
        by_mode.setdefault(f["mode"], []).append(f)

    selected_failures: list[dict] = []
    if by_mode:
        per_mode_quota = max(1, 7 // len(by_mode))
        for mode_name, items in by_mode.items():
            if len(selected_failures) >= 7:
                break
            selected_failures.extend(items[:per_mode_quota])
    selected_failures = selected_failures[:7]

    selected_successes = successes[:3]

    md = _build_taxonomy_md(
        classified, selected_failures, selected_successes, by_mode, results_dir.name,
    )
    out_path = results_dir / "failure_taxonomy.md"
    out_path.write_text(md)
    print(f"wrote {out_path}")
    print(f"n_failures={len(failures)} n_successes={len(successes)}")
    print("Mode counts:")
    for m, items in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        print(f"  {m}: {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
