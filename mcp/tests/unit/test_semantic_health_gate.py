"""#104 runtime pin: after a deploy, the gateway's /health must report that the
scoped server loaded the DEPLOYED profile, that semantic /query is enabled, and
(#121) that answer synthesis works (``llm == "ok"``).

The unit test on the Dockerfile line cannot see a Railway service variable that
overrides SHRINE_CONFIG (measured 2026-10-11: kg-mcp test had SHRINE_CONFIG=local),
so this check runs against the live plane in deploy-mcp.yml.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/ci/assert_semantic_health.sh"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy-mcp.yml"


def _run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], input=body, capture_output=True, text=True, check=False)


def _health(**scoped) -> str:
    return json.dumps({"status": "ok", "mcp": "ok", "scoped_server": {"status": "ok", **scoped}})


def test_deployed_and_enabled_passes() -> None:
    r = _run(_health(config="deployed", semantic="enabled", semantic_reason=None, llm="ok"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "llm=ok" in r.stdout


@pytest.mark.parametrize(
    "scoped,expect",
    [
        ({"config": "local", "semantic": "off"}, "config=local"),
        ({"config": "deployed", "semantic": "disabled", "semantic_reason": "embedding space mismatch: x"}, "embedding space mismatch"),
        ({"config": "deployed", "semantic": "off"}, "semantic=off"),
        ({"config": "deployed"}, "semantic="),
        # Field-collapse regression: an empty semantic must not let the next field
        # shift into its slot (reviewer MEASURED a false green on this input).
        ({"config": "deployed", "semantic": "", "semantic_reason": "enabled"}, "semantic="),
        # #121 / #14271: retrieval works but the LLM cannot synthesize. This is the
        # plane that answered kg_query with a 200 "None"; it must grade RED.
        (
            {"config": "deployed", "semantic": "enabled", "llm": "failing", "llm_reason": "ClientError"},
            "llm=failing, llm_reason=ClientError",
        ),
        # Retrieval-only is an explicit fallback, not a synthesizing plane (#14009 item 2).
        ({"config": "deployed", "semantic": "enabled", "llm": "disabled"}, "llm=disabled"),
        ({"config": "deployed", "semantic": "enabled", "llm": "untested"}, "llm=untested"),
        # A pre-#121 container (no llm field) still answering during a rolling deploy.
        ({"config": "deployed", "semantic": "enabled"}, "llm=<missing>"),
    ],
)
def test_anything_else_fails_and_names_what_it_saw(scoped, expect) -> None:
    r = _run(_health(**scoped))
    assert r.returncode == 1
    assert expect in r.stdout + r.stderr


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json",
        json.dumps({"status": "degraded", "mcp": "ok", "scoped_server_error": "503"}),
    ],
)
def test_unreadable_or_degraded_health_fails(body) -> None:
    assert _run(body).returncode == 1


def _steps() -> list[dict]:
    wf = yaml.safe_load(WORKFLOW_PATH.read_text())
    for job in wf["jobs"].values():
        names = [s.get("name", "") for s in job.get("steps", [])]
        if any("wait for /health" in n for n in names):
            return job["steps"]
    raise AssertionError("deploy job with the /health step not found")


def test_workflow_runs_the_semantic_gate_after_the_health_probe() -> None:
    steps = _steps()
    names = [s.get("name", "") for s in steps]
    health_i = next(i for i, n in enumerate(names) if "wait for /health" in n)
    gate_i = next(i for i, n in enumerate(names) if "semantic profile" in n.lower())
    assert gate_i > health_i
    gate = steps[gate_i]
    run = gate["run"]
    assert "scripts/ci/assert_semantic_health.sh" in run
    # Retries until stable: during a rolling deploy the OLD container can still
    # answer /health with config=local (root CLAUDE.md: health-200 is not evidence
    # the new process is live), so one read would be a false red.
    assert "for i in" in run and "sleep" in run
    # The whole retry budget must fit inside the step timeout, or the final
    # ::error:: naming what the plane reported is lost when the step is killed.
    import re

    tries = int(re.search(r"seq 1 (\d+)", run).group(1))
    curl_max = int(re.search(r"curl [^\n]*-m (\d+)", run).group(1))
    sleep_s = int(re.search(r"sleep (\d+)", run).group(1))
    assert tries * (curl_max + sleep_s) < gate["timeout-minutes"] * 60
    # The domain reaches bash through env, never by ${{ }} interpolation.
    assert "${{" not in run


def test_ci_runs_the_scoped_server_contract_tests() -> None:
    """#121 review F18: the synthesis-contract tests sit at the lightrag root, which
    no CI job used to run, so a regression in scoped_server.py shipped untested."""
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/mcp-ci.yml").read_text())
    on = ci.get("on", ci.get(True))
    paths = on["pull_request"]["paths"]
    assert "shrine-diet-bioactivity/lightrag/*.py" in paths
    assert "scripts/ci/**" in paths
    run = "\n".join(s.get("run", "") for s in ci["jobs"]["scoped-server-contract"]["steps"])
    for f in ("test_llm_synthesis.py", "test_semantic_vertex.py"):
        assert f in run
