#!/usr/bin/env python3
"""Helper to add file-level `pytestmark = pytest.mark.<marker>` declarations
to Python test files. Used when a new test file lands without a marker and
shows up in `scripts/test_coverage_ratio.py`'s "untagged" warning.

Insertion uses Python's `ast` to find the correct insertion point (after the
last top-level `import` / `from ... import` statement, after any `__future__`
imports, before the first non-import statement). The result is re-parsed with
`ast.parse` before write to guarantee syntactic validity. The script is
idempotent — files that already carry a `pytestmark` are skipped.

The CLASSIFICATIONS map is the single audit record of which file got which
marker, assembled from manual inspection (network/mock signals + docstring
intent + Makefile invocation context).

Usage:
    python scripts/dev/tag_test_files.py            # apply
    python scripts/dev/tag_test_files.py --dry-run  # print plan, no writes
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (relative_path, [markers]) — one entry per file requiring file-level
# pytestmark. Existing tags are detected and skipped; only listed files that
# lack pytestmark are touched. Add new entries here when new test files
# land without a marker (the ratio script will warn).
CLASSIFICATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Untagged on main as of 2026-05-18 — Mock-based unit tests for the
    # PostHog analytics layer (singleton patched via monkeypatch) and
    # for kg_mcp.tools error paths (AsyncMock-based; analytics-error contract).
    ("mcp/tests/unit/test_analytics.py", ("unit",)),
    ("mcp/tests/unit/test_tools_error_paths.py", ("unit",)),
)


def find_insertion_line(source: str) -> int:
    """Return the 1-indexed line number to insert pytestmark on.

    Insertion goes immediately after the last top-level `import` / `from X
    import Y` statement (including a trailing `__future__` import). If the
    file has no imports, insert after the module docstring (if any), else
    at line 1.
    """
    tree = ast.parse(source)
    last_import_end = 0
    docstring_end = 0
    for i, stmt in enumerate(tree.body):
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            docstring_end = stmt.end_lineno or stmt.lineno
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            last_import_end = stmt.end_lineno or stmt.lineno
    return max(last_import_end, docstring_end)


def has_pytest_import(tree: ast.Module) -> bool:
    for stmt in tree.body:
        if isinstance(stmt, ast.Import) and any(a.name == "pytest" for a in stmt.names):
            return True
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "pytest":
            return True
    return False


def has_existing_pytestmark(tree: ast.Module) -> bool:
    for stmt in tree.body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target] if stmt.target is not None else []
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "pytestmark":
                return True
    return False


def render_marker(markers: tuple[str, ...]) -> str:
    if len(markers) == 1:
        return f"pytest.mark.{markers[0]}"
    inner = ", ".join(f"pytest.mark.{m}" for m in markers)
    return f"[{inner}]"


def tag_file(path: Path, markers: tuple[str, ...], dry_run: bool) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    if has_existing_pytestmark(tree):
        return "skip-existing"
    insert_line = find_insertion_line(source)
    lines = source.splitlines(keepends=True)
    needs_pytest_import = not has_pytest_import(tree)
    block: list[str] = []
    if needs_pytest_import:
        block.append("import pytest\n")
    block.append(f"pytestmark = {render_marker(markers)}\n")
    block_text = "\n" + "".join(block)
    if insert_line == 0:
        new_source = block_text.lstrip("\n") + source
    else:
        before = "".join(lines[:insert_line])
        after = "".join(lines[insert_line:])
        new_source = before + block_text + ("" if after.startswith("\n") else "\n") + after
    # Verify the result is still parseable.
    ast.parse(new_source, filename=str(path))
    if not dry_run:
        path.write_text(new_source, encoding="utf-8")
    return "tagged"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    tagged = 0
    skipped = 0
    missing = 0
    for rel, markers in CLASSIFICATIONS:
        path = REPO_ROOT / rel
        if not path.is_file():
            print(f"MISSING: {rel}", file=sys.stderr)
            missing += 1
            continue
        try:
            result = tag_file(path, markers, args.dry_run)
        except SyntaxError as e:
            print(f"SYNTAX ERROR after tagging {rel}: {e}", file=sys.stderr)
            return 2
        marker_str = "+".join(markers)
        if result == "skip-existing":
            skipped += 1
            print(f"SKIP  {rel}  (already has pytestmark)")
        else:
            tagged += 1
            print(f"TAG   {rel}  → pytestmark = {marker_str}")
    verb = "would tag" if args.dry_run else "tagged"
    print(
        f"\nSummary: {verb} {tagged} files, skipped {skipped} (pre-existing), missing {missing}.",
        file=sys.stderr,
    )
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
