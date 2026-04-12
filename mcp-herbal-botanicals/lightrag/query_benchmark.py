"""
Benchmark queries for the Unified Diet Knowledge Graph.

Runs 10 multi-hop queries against LightRAG in multiple modes (local, global,
hybrid, mix) and produces a comparison table with latency and result quality.

Usage:
    python query_benchmark.py --config local
    python query_benchmark.py --config production --modes hybrid,mix
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent

BENCHMARK_QUERIES = [
    # Single-hop: entity lookup
    {
        "id": "Q01",
        "query": "What compounds are found in turmeric?",
        "category": "single-hop",
        "expected_entities": ["Curcumin", "Turmeric"],
    },
    {
        "id": "Q02",
        "query": "What foods contain quercetin?",
        "category": "single-hop",
        "expected_entities": ["Quercetin"],
    },
    # Multi-hop: compound → target → disease
    {
        "id": "Q03",
        "query": "What foods help with inflammation through enzyme inhibition?",
        "category": "multi-hop",
        "expected_entities": ["COX-2", "Curcumin", "inflammation"],
    },
    {
        "id": "Q04",
        "query": "Which herbs contain compounds that target COX-2 enzyme?",
        "category": "multi-hop",
        "expected_entities": ["COX-2"],
    },
    # Multi-hop: symptom → herb → compound → food
    {
        "id": "Q05",
        "query": "What dietary sources contain compounds with anti-cancer bioactivity?",
        "category": "multi-hop",
        "expected_entities": [],
    },
    {
        "id": "Q06",
        "query": "Which foods are rich in compounds that target the NF-kB pathway?",
        "category": "multi-hop",
        "expected_entities": ["NF-kB"],
    },
    # Nutrition + phytochemical crossover
    {
        "id": "Q07",
        "query": "What foods high in vitamin C also contain antioxidant compounds?",
        "category": "crossover",
        "expected_entities": [],
    },
    {
        "id": "Q08",
        "query": "Which herbs used for diabetes are also rich in protein?",
        "category": "crossover",
        "expected_entities": [],
    },
    # TCM / multilingual
    {
        "id": "Q09",
        "query": "What are the medicinal compounds in ginger used in traditional medicine?",
        "category": "tcm",
        "expected_entities": ["Ginger", "Zingiber officinale"],
    },
    {
        "id": "Q10",
        "query": "Compare the bioactive compounds in green tea versus black tea",
        "category": "comparison",
        "expected_entities": ["Green tea", "Black tea"],
    },
]


async def run_benchmark(config: str, modes: list[str]) -> None:
    """Run all benchmark queries and print results."""
    config_path = SCRIPT_DIR / f"config_{config}.env"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return
    load_dotenv(config_path, override=True)

    embedding_binding = os.getenv("EMBEDDING_BINDING", "ollama")
    if embedding_binding == "ollama":
        from lightrag.llm.ollama import ollama_embed, ollama_model_complete
        llm_func = ollama_model_complete
        embed_func = ollama_embed
    else:
        from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed
        llm_func = gpt_4o_mini_complete
        embed_func = openai_embed

    from lightrag import LightRAG, QueryParam

    working_dir = os.getenv("WORKING_DIR", "./rag_storage_local")
    rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        embedding_func=embed_func,
    )
    await rag.initialize_storages()

    # Print header
    print(f"\n{'=' * 80}")
    print(f"  Unified Diet KG — Query Benchmark ({config} config)")
    print(f"  Modes: {', '.join(modes)}")
    print(f"{'=' * 80}\n")

    results = []

    for bq in BENCHMARK_QUERIES:
        print(f"[{bq['id']}] {bq['query']}")
        row = {"id": bq["id"], "query": bq["query"], "category": bq["category"]}

        for mode in modes:
            start = time.time()
            try:
                response = await rag.aquery(
                    bq["query"],
                    param=QueryParam(mode=mode),
                )
                elapsed = time.time() - start
                response_text = str(response)

                # Check expected entities
                found = sum(
                    1
                    for e in bq["expected_entities"]
                    if e.lower() in response_text.lower()
                )
                total_expected = len(bq["expected_entities"])

                row[f"{mode}_time"] = f"{elapsed:.1f}s"
                row[f"{mode}_len"] = len(response_text)
                row[f"{mode}_entities"] = (
                    f"{found}/{total_expected}" if total_expected > 0 else "n/a"
                )

                print(f"  {mode:8s}: {elapsed:.1f}s, {len(response_text)} chars, entities: {row[f'{mode}_entities']}")
            except Exception as e:
                elapsed = time.time() - start
                row[f"{mode}_time"] = f"{elapsed:.1f}s"
                row[f"{mode}_len"] = 0
                row[f"{mode}_entities"] = f"ERROR: {e}"
                print(f"  {mode:8s}: ERROR — {e}")

        results.append(row)
        print()

    # Print summary table
    print(f"\n{'=' * 80}")
    print("  SUMMARY TABLE")
    print(f"{'=' * 80}")
    header = f"{'ID':4s} {'Category':12s}"
    for mode in modes:
        header += f" | {mode:>8s} time  entities"
    print(header)
    print("-" * len(header))
    for row in results:
        line = f"{row['id']:4s} {row['category']:12s}"
        for mode in modes:
            t = row.get(f"{mode}_time", "?")
            e = row.get(f"{mode}_entities", "?")
            line += f" | {t:>8s}  {e:>8s}"
        print(line)

    await rag.finalize_storages()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark queries against unified diet KG")
    parser.add_argument("--config", choices=["local", "production"], default="local")
    parser.add_argument("--modes", default="local,global,hybrid,mix", help="Comma-separated query modes")
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",")]
    asyncio.run(run_benchmark(args.config, modes))


if __name__ == "__main__":
    main()
