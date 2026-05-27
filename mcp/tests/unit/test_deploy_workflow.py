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
