"""Unit tests for .github/workflows/deploy-mcp.yml CI logic.

Two pieces of behavior locked in here:

1. Env detection — branch → environment mapping. Until the kg-mcp Railway
   service exists in the prod environment, pushes to main MUST deploy to
   test (not prod); otherwise the Deploy step fails on every merge to main.
2. URL resolution — when ``railway status --json`` returns no domain (CLI
   shape drift, auth lag, fresh service), fall back to the known
   ``${SERVICE}-${ENV}.up.railway.app`` pattern. Otherwise a healthy live
   deploy gets reported as failed CI.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy-mcp.yml"
MCP_CI_PATH = REPO_ROOT / ".github/workflows/mcp-ci.yml"
COMPLETENESS_TEST = (
    REPO_ROOT
    / "shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py"
)
RESOLVE_SCRIPT = REPO_ROOT / "scripts/ci/resolve_railway_domain.sh"


def _detect_env_run() -> str:
    """Pull the bash from the detect-environment step's ``run:`` block."""
    data = yaml.safe_load(WORKFLOW_PATH.read_text())
    return data["jobs"]["detect-environment"]["steps"][0]["run"]


def _exec_with_github_output(script: str, env: dict[str, str]) -> str:
    """Run a bash snippet with ``$GITHUB_OUTPUT`` pointing at a temp file.

    Returns the file's contents (the ``key=value`` lines the step writes).
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        out_path = f.name
    try:
        full_env = {**os.environ, **env, "GITHUB_OUTPUT": out_path}
        proc = subprocess.run(
            ["bash", "-c", script],
            env=full_env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return f"::nonzero({proc.returncode})::{proc.stderr}"
        return Path(out_path).read_text()
    finally:
        os.unlink(out_path)


# ─── Env detection ────────────────────────────────────────────────────────


class TestDetectEnv:
    def test_main_branch_routes_to_test(self):
        """Until the prod Railway env has a kg-mcp service, main→test."""
        out = _exec_with_github_output(
            _detect_env_run(),
            {
                "GH_EVENT_NAME": "push",
                "GH_REF": "refs/heads/main",
                "GH_DISPATCH_ENV": "",
            },
        )
        assert "environment=test" in out, f"main should route to test, got: {out!r}"

    def test_test_branch_routes_to_test(self):
        out = _exec_with_github_output(
            _detect_env_run(),
            {
                "GH_EVENT_NAME": "push",
                "GH_REF": "refs/heads/test",
                "GH_DISPATCH_ENV": "",
            },
        )
        assert "environment=test" in out

    def test_dev_branch_routes_to_test(self):
        out = _exec_with_github_output(
            _detect_env_run(),
            {
                "GH_EVENT_NAME": "push",
                "GH_REF": "refs/heads/dev-feature-x",
                "GH_DISPATCH_ENV": "",
            },
        )
        assert "environment=test" in out

    def test_workflow_dispatch_honors_input_prod(self):
        """Manual deploy to prod stays available — only the push-from-main
        default changes."""
        out = _exec_with_github_output(
            _detect_env_run(),
            {
                "GH_EVENT_NAME": "workflow_dispatch",
                "GH_REF": "refs/heads/main",
                "GH_DISPATCH_ENV": "prod",
            },
        )
        assert "environment=prod" in out

    def test_workflow_dispatch_honors_input_test(self):
        out = _exec_with_github_output(
            _detect_env_run(),
            {
                "GH_EVENT_NAME": "workflow_dispatch",
                "GH_REF": "refs/heads/main",
                "GH_DISPATCH_ENV": "test",
            },
        )
        assert "environment=test" in out


# ─── URL resolution ───────────────────────────────────────────────────────


class TestResolveRailwayDomain:
    """``scripts/ci/resolve_railway_domain.sh`` — reads railway status JSON
    on stdin; outputs a domain on stdout. Falls back to
    ``${service}-${env}.up.railway.app`` when JSON has no domain."""

    def _run(
        self,
        json_in: str,
        service: str = "kg-mcp",
        env: str = "test",
    ) -> tuple[int, str]:
        assert RESOLVE_SCRIPT.exists(), f"missing helper: {RESOLVE_SCRIPT}"
        proc = subprocess.run(
            ["bash", str(RESOLVE_SCRIPT), service, env],
            input=json_in,
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout.strip()

    def test_extracts_domain_from_valid_json(self):
        js = '{"service":{"serviceDomains":[{"domain":"kg-mcp-test.up.railway.app"}]}}'
        rc, out = self._run(js)
        assert rc == 0
        assert out == "kg-mcp-test.up.railway.app"

    def test_falls_back_when_json_empty(self):
        rc, out = self._run("{}", service="kg-mcp", env="test")
        assert rc == 0
        assert out == "kg-mcp-test.up.railway.app"

    def test_falls_back_when_serviceDomains_missing(self):
        rc, out = self._run('{"service":{}}', service="kg-mcp", env="test")
        assert rc == 0
        assert out == "kg-mcp-test.up.railway.app"

    def test_falls_back_when_input_is_garbage(self):
        rc, out = self._run("not json at all", service="kg-mcp", env="prod")
        assert rc == 0
        assert out == "kg-mcp-prod.up.railway.app"

    def test_uses_env_in_fallback_pattern(self):
        """Fallback respects the env arg — kg-mcp-prod for prod, etc."""
        rc, out = self._run("{}", service="kg-mcp", env="prod")
        assert rc == 0
        assert out == "kg-mcp-prod.up.railway.app"


# ─── Stale promotion guard (issue #46) ────────────────────────────────────


class TestNoStalePromotionGuard:
    """The test→main promotion guard predates the live workflow: the `test`
    branch is hundreds of commits behind main and effectively dead, so the
    guard fails on every PR for no operational reason. Lock its removal in
    so it can't quietly come back."""

    def _workflow(self) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text())

    def test_pr_promotion_guard_job_is_absent(self):
        jobs = self._workflow()["jobs"]
        assert "pr-promotion-guard" not in jobs, (
            "The pr-promotion-guard job has been removed (see #46) — "
            "do not reintroduce it without also reactivating the test branch."
        )

    def test_no_other_job_depends_on_promotion_guard(self):
        """Sanity: even after removal, ensure nothing in `needs:` still
        names the deleted job (which would silently fail to schedule)."""
        jobs = self._workflow()["jobs"]
        for name, body in jobs.items():
            needs = body.get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            assert "pr-promotion-guard" not in needs, (
                f"job {name!r} still has pr-promotion-guard in its needs"
            )

    def test_no_step_step_references_promotion_guard(self):
        """Catch leftover step-name strings (e.g., `name: PR Promotion Guard`).
        Stronger than the job-key check because step-name strings are easy
        to copy-paste."""
        text = WORKFLOW_PATH.read_text()
        assert "PR Promotion Guard" not in text
        assert "pr-promotion-guard" not in text


# ─── Aura gate must not silently pass on missing secrets (issue #65) ──────


class TestAuraGateRequiresSecrets:
    """The aura-data-integrity job in mcp-ci.yml previously skipped on
    missing NEO4J_* secrets and still reported SUCCESS — a false-green
    that hides a misconfigured environment. Lock in a guard step that
    fails the job when the event is push/dispatch (i.e., a trusted run
    that should have secrets) and any required secret is empty."""

    def _aura_job_run_text(self) -> str:
        data = yaml.safe_load(MCP_CI_PATH.read_text())
        job = data["jobs"]["aura-data-integrity"]
        # Join all step `run:` blocks so the guard text can live in any of them.
        return "\n".join(
            step.get("run", "")
            for step in job["steps"]
            if isinstance(step, dict)
        )

    def test_aura_job_has_secret_presence_guard(self):
        """The job must error (exit 1) when invoked on a real push/dispatch
        without the secrets being set — not just warn."""
        text = self._aura_job_run_text()
        # The fix must explicitly fail when the event isn't a PR and a
        # NEO4J_* secret is empty. We match on the documented sentinel
        # phrase so the check is robust to bash style.
        assert "exit 1" in text, (
            "aura-data-integrity job has no `exit 1` — likely still "
            "warning-only on missing secrets (see #65)."
        )
        assert "GH_EVENT_NAME" in text or "github.event_name" in text or "EVENT_NAME" in text, (
            "Guard must condition on event type so PRs from forks "
            "still skip cleanly (they have no secrets by design)."
        )


# ─── Completeness gates test must declare a marker (issue #49) ────────────


class TestCompletenessGatesHasMarker:
    """``test_kg_completeness_gates.py`` requires a 5.5 GB local SQLite DB
    that CI doesn't ship, so it must be marked ``integration`` (or
    deselected by default) — otherwise the default pytest run picks it
    up, hits a skip cascade, and inflates the noise floor of test reports.
    """

    def test_file_declares_pytestmark(self):
        text = COMPLETENESS_TEST.read_text()
        # Either ``pytestmark = pytest.mark.X`` or
        # ``pytestmark = [pytest.mark.X, ...]`` — both syntaxes are valid.
        assert "pytestmark" in text, (
            f"{COMPLETENESS_TEST.name} has no pytestmark — add the "
            "`integration` marker so default runs deselect it (see #49)."
        )
        # Must mark with one of the catalogued markers from
        # shrine-diet-bioactivity/pytest.ini. ``integration`` is the
        # appropriate one because the gates need the local KG DB.
        assert "integration" in text, (
            "completeness gates need the local KG DB → mark `integration`."
        )
