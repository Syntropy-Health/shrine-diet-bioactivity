# ─────────────────────────────────────────────────────────────
# shrine-diet-bioactivity — top-level entry-point catalog
# ─────────────────────────────────────────────────────────────
#
# This is the canonical index of every `make` target across the repo.
# It does NOT duplicate logic — each target either delegates to a
# sub-Makefile or runs a one-line shell command.
#
# Sub-Makefiles:
#   shrine-diet-bioactivity/Makefile  → KG ingest, LightRAG, Neo4j ops, eval
#   mcp/Makefile                      → kg-mcp gateway: dev, test, lint
#
# Quick start (new clone):
#   make submodules       # init git submodules
#   make install          # install Python deps for both servers
#   make test             # run BOTH test suites
#   make ci               # everything CI runs
#
# Run a server locally:
#   make mcp-dev          # kg-mcp gateway in stdio mode
#   make mcp-dev-http     # kg-mcp gateway in streamable-HTTP mode (with auth)
#   make kg-server        # LightRAG FastAPI server (semantic KG)
# ─────────────────────────────────────────────────────────────

.PHONY: help submodules install \
        test test-mcp test-kg test-smoke \
        lint typecheck ci \
        mcp-dev mcp-dev-http kg-server kg-ingest kg-bench \
        score-diet docs-update clean

help: ## Show every target across the entire repo, grouped
	@echo ""
	@echo "  \033[1mTop-level (this file):\033[0m"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  \033[1mkg-mcp gateway (mcp/Makefile):\033[0m"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' mcp/Makefile 2>/dev/null | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36mmcp/%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  \033[1mKG ingest + ops (shrine-diet-bioactivity/Makefile):\033[0m"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' shrine-diet-bioactivity/Makefile 2>/dev/null | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36mkg/%-17s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─── Setup ───────────────────────────────────────────────────

submodules: ## git submodule update --init --recursive
	git submodule update --init --recursive

install: ## Install deps for both Python servers
	$(MAKE) -C mcp install
	@echo "(KG-side deps live in shrine-diet-bioactivity/lightrag/requirements.txt)"

# ─── Tests (top-level orchestration) ─────────────────────────

test: test-mcp test-kg ## Run BOTH test suites

test-mcp: ## kg-mcp gateway: unit + in-memory MCP-client integration
	$(MAKE) -C mcp test

test-kg: ## KG side: lightrag ingest tests (when present)
	@if [ -d shrine-diet-bioactivity/lightrag/tests ]; then \
		cd shrine-diet-bioactivity/lightrag && python -m pytest tests -v; \
	else \
		echo "no lightrag/tests dir found, skipping"; \
	fi

test-smoke: ## Smallest cross-server set: gateway boots + KG matchers work
	$(MAKE) -C mcp test-smoke
	@if [ -f shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py ]; then \
		cd shrine-diet-bioactivity/lightrag && python -m pytest tests/test_kg_completeness_gates.py -v; \
	fi

# ─── Quality gates ───────────────────────────────────────────

lint: ## Lint both Python projects
	$(MAKE) -C mcp lint

typecheck: ## Pyright on both
	$(MAKE) -C mcp typecheck

ci: lint test ## Everything CI runs (lint + all tests)

# ─── Servers ─────────────────────────────────────────────────

mcp-dev: ## kg-mcp gateway in stdio mode (for local agents)
	$(MAKE) -C mcp dev

mcp-dev-http: ## kg-mcp gateway in streamable-HTTP mode + bearer-token auth
	$(MAKE) -C mcp dev-http-auth

kg-server: ## LightRAG FastAPI server (semantic KG over Neo4j)
	$(MAKE) -C shrine-diet-bioactivity lightrag-server

# ─── KG data pipeline (delegates) ────────────────────────────

kg-ingest: ## Ingest unified KG into LightRAG/Neo4j (local Ollama embeddings)
	$(MAKE) -C shrine-diet-bioactivity lightrag-ingest-local

kg-bench: ## Run the 10-query LightRAG benchmark
	$(MAKE) -C shrine-diet-bioactivity lightrag-benchmark

score-diet: ## Diet scorer CLI sample run (Phase 5)
	$(MAKE) -C shrine-diet-bioactivity score-diet-sample

# ─── Housekeeping ────────────────────────────────────────────

docs-update: ## Regenerate codemaps + ADRs (when /update-docs hook is wired)
	@echo "Run \`/update-docs\` from inside Claude Code, or wire to your CI."

clean: ## Clean caches across both servers
	$(MAKE) -C mcp clean
	rm -rf .pytest_cache .ruff_cache 2>/dev/null || true
