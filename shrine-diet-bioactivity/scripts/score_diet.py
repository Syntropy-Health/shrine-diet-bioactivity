"""Diet scoring CLI (Phase 5 / spec §4.1).

Takes a diet (JSON {food_name: grams}) and writes the predicted-effect
JSON output to stdout. See spec §2 for the output shape.

Usage:
  python scripts/score_diet.py \\
      --db data_local/herbal_botanicals.db \\
      --diet '{"Turmeric":5, "Ginger":10, "Broccoli":100}'

  python scripts/score_diet.py --db ... --diet-file diet.json

Exit codes:
  0 — success
  2 — bad input (malformed JSON, negative grams)
  3 — DB not found
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from diet_scorer import score_diet  # noqa: E402


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Diet scoring CLI").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--diet",
        type=str,
        help='Diet as JSON object: {"food_name": grams, ...}',
    )
    grp.add_argument(
        "--diet-file",
        type=Path,
        help="Path to a JSON file containing the diet object",
    )
    ap.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (default: compact one-line)",
    )
    return ap


def _parse_diet_input(args: argparse.Namespace) -> list[tuple[str, float]]:
    if args.diet:
        raw = args.diet
    else:
        if not args.diet_file.exists():
            raise FileNotFoundError(f"diet file not found: {args.diet_file}")
        raw = args.diet_file.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"diet input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            "diet input must be a JSON object {food_name: grams}, "
            f"got {type(data).__name__}"
        )
    diet: list[tuple[str, float]] = []
    for food, grams in data.items():
        if not isinstance(grams, (int, float)):
            raise ValueError(f"grams for {food!r} must be numeric, got {grams!r}")
        if grams < 0:
            raise ValueError(f"grams for {food!r} cannot be negative ({grams})")
        diet.append((food, float(grams)))
    return diet


def main() -> int:
    args = _build_argparser().parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 3

    try:
        diet = _parse_diet_input(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    try:
        result = score_diet(diet, conn=conn)
    finally:
        conn.close()

    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
