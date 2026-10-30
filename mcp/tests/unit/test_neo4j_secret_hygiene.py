"""CTO #17617/#17618: Neo4j and Infisical credentials never reach a process's argv
or a tracked file, and the destructive neo4j-clear target cannot reach a remote DB.

argv is readable by every user on the host (`ps -o command`, `pgrep -fl`), so a
password passed as a flag is a leak for as long as the process runs. `make -n` is
NOT evidence here: it prints `$NEO4J_PASSWORD` unexpanded, so a runtime expansion
onto argv is invisible to it. These tests run the real targets with fake
`docker` / `python3` / `sleep` that record their argv, and look for a sentinel.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
KG_DIR = REPO_ROOT / "shrine-diet-bioactivity"
SENTINEL = "SENTINELpw-0123456789"

needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")

SHIM = """#!/bin/sh
printf '%s\\n' "$@" > "$OUT/{name}.$$.argv"
{tail}
"""


def _shims(tmp_path: Path, docker_rc: int) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tails = {
        "docker": f"exit {docker_rc}",
        # Record argv only: never run the admin script, so nothing can connect.
        "python3": "exit 0",
        "sleep": "exit 1",  # ends the neo4j-watch loop after one poll
    }
    for name, tail in tails.items():
        p = bindir / name
        p.write_text(SHIM.format(name=name, tail=tail))
        p.chmod(0o755)
    return bindir


def _run(tmp_path: Path, target: str, env_extra: dict, docker_rc: int = 0, stdin: bytes = b""):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    bindir = _shims(tmp_path, docker_rc)
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "OUT": str(out),
        **env_extra,
    }
    proc = subprocess.run(
        ["make", "-s", "-C", str(KG_DIR), target],
        env=env, input=stdin, capture_output=True, timeout=30,
    )
    argv = {p.name: p.read_text() for p in out.glob("*.argv")}
    return proc, argv


CREDS = {"NEO4J_URI": "bolt://127.0.0.1:1", "NEO4J_USERNAME": "neo4j", "NEO4J_PASSWORD": SENTINEL}

TARGETS = [
    ("neo4j-check", 0),
    ("neo4j-stats", 0),
    ("neo4j-status", 0),
    ("neo4j-watch", 0),
    ("neo4j-clear", 0),
    ("neo4j-shell", 0),
    ("neo4j-shell", 1),  # docker fails -> python fallback
]


@needs_make
@pytest.mark.parametrize(("target", "docker_rc"), TARGETS)
def test_password_never_on_any_child_argv(tmp_path, target, docker_rc) -> None:
    proc, argv = _run(tmp_path, target, CREDS, docker_rc, stdin=b"no\n")
    assert argv, f"{target}: no child process ran, so the check proved nothing ({proc.stderr!r})"
    leaked = sorted(name for name, text in argv.items() if SENTINEL in text)
    assert not leaked, f"{target}: password on argv of {leaked}"
    assert SENTINEL.encode() not in proc.stdout + proc.stderr


@needs_make
@pytest.mark.parametrize("target", ["neo4j-check", "neo4j-shell", "neo4j-clear"])
@pytest.mark.parametrize("missing", ["NEO4J_URI", "NEO4J_PASSWORD"])
@pytest.mark.parametrize("value", [None, ""])
def test_guard_fails_closed_before_any_connection(tmp_path, target, missing, value) -> None:
    env = dict(CREDS)
    if value is None:
        env.pop(missing)
    else:
        env[missing] = value
    proc, argv = _run(tmp_path, target, env)
    assert proc.returncode != 0
    assert b"must be set" in proc.stdout + proc.stderr
    assert not argv, f"{target} reached {sorted(argv)} without credentials"


@needs_make
def test_make_does_not_export_empty_neo4j_vars_to_other_targets(tmp_path) -> None:
    """An exported-but-empty NEO4J_URI blocks python-dotenv (override=False) from
    loading the real URI out of .env, which broke every lightrag-* target."""
    mk = tmp_path / "probe.mk"
    mk.write_text(
        f"include {KG_DIR / 'Makefile'}\n"
        "probe-env:\n\t@env | grep -c '^NEO4J_' || true\n"
    )
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["make", "-s", "-C", str(KG_DIR), "-f", str(mk), "probe-env"],
        env=env, capture_output=True, timeout=30, text=True,
    )
    assert proc.stdout.strip().splitlines()[-1] == "0", proc.stdout + proc.stderr


ADMIN = KG_DIR / "scripts" / "neo4j_admin.py"


@pytest.mark.parametrize(
    "uri",
    [
        "neo4j+s://abcd1234.databases.neo4j.io",
        "bolt://metro.proxy.rlwy.net:22971",
        "bolt://10.0.0.5:7687",
        "neo4j://127.0.0.1.evil.example:7687",
    ],
)
def test_clear_refuses_non_loopback(uri) -> None:
    env = {"PATH": os.environ["PATH"], "NEO4J_URI": uri, "NEO4J_PASSWORD": SENTINEL}
    proc = subprocess.run(
        ["python3", str(ADMIN), "clear"], env=env, input="yes\n",
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "loopback" in proc.stdout + proc.stderr
    assert SENTINEL not in proc.stdout + proc.stderr


FLAG_ON_ARGV = re.compile(r"--client-secret|--client-id|--token=|\s-p\s+\S*NEO4J_PASS")


def _code_lines(path: Path):
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.lstrip().startswith("#"):
            yield n, line


def test_flag_regex_matches_the_old_patterns() -> None:
    # Positive control: the regex really catches what it guards against.
    assert FLAG_ON_ARGV.search('infisical login --client-secret="$X" --plain')
    assert FLAG_ON_ARGV.search("cypher-shell -a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASS)")


def test_no_tracked_script_passes_credentials_as_flags() -> None:
    files = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "*.sh", "*Makefile"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    hits = [
        f"{f}:{n}"
        for f in files
        for n, line in _code_lines(REPO_ROOT / f)
        if FLAG_ON_ARGV.search(line)
    ]
    assert not hits, f"credential passed as a flag: {hits}"
