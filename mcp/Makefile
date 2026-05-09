# ─────────────────────────────────────────────────────────────
# kg-mcp — MCP gateway over the shrine-diet-bioactivity LightRAG KG
# ─────────────────────────────────────────────────────────────
#
# Two forms of operation:
#   1. STDIO (local agent spawns the server as a subprocess)
#        $ make dev
#   2. STREAMABLE-HTTP (Railway-style hosted endpoint)
#        $ make dev-http              # no auth (insecure — dev-only)
#        $ make dev-http-auth         # with MCP_API_KEY enforced
#
# Test variants:
#   make test                     # everything that's CI-safe
#   make test-unit                # pure-logic + mocked-client
#   make test-integration         # in-memory MCP-client SDK round-trip
#   make test-smoke               # fast subset: smoke + registration
#   make test-coverage            # coverage report
#   make test-e2e-local           # against a locally running HTTP server
#   make test-e2e-staging         # against the deployed Railway server
#
# Quality gates:
#   make lint                     # ruff (lint + format check)
#   make typecheck                # pyright (best-effort; pinned 3.10+)
#   make ci                       # the full check the CI workflow runs
#
# Help:
#   make help                     # this list, generated from `## ` annotations
# ─────────────────────────────────────────────────────────────

.PHONY: help install dev dev-http dev-http-auth \
        test test-unit test-integration test-smoke test-coverage \
        test-e2e-local test-e2e-staging \
        lint lint-fix format typecheck ci clean

# ─── Tunables (override on the command line) ─────────────────
MCP_HOST          ?= 127.0.0.1
MCP_PORT          ?= 8080
MCP_API_KEY       ?= dev-key-do-not-use-in-prod
KG_MCP_E2E_URL    ?= http://127.0.0.1:$(MCP_PORT)
STAGING_URL       ?= https://kg-mcp.up.railway.app
PYTHON            ?= python3
PYTEST            ?= $(PYTHON) -m pytest
RUFF              ?= $(PYTHON) -m ruff

help: ## Show all targets with descriptions
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ─── Install ─────────────────────────────────────────────────

install: ## Install package + test deps from pyproject
	$(PYTHON) -m pip install -e '.[test]' || $(PYTHON) -m pip install -e .

# ─── Dev servers ─────────────────────────────────────────────

dev: ## Run server in STDIO mode (default; how local agents spawn it)
	MCP_TRANSPORT=stdio $(PYTHON) -m kg_mcp.server

dev-http: ## Run server in streamable-HTTP mode WITHOUT auth (dev-only, insecure)
	MCP_TRANSPORT=streamable-http \
	MCP_HOST=$(MCP_HOST) \
	MCP_PORT=$(MCP_PORT) \
	MCP_DISABLE_DNS_REBINDING_PROTECTION=1 \
	$(PYTHON) -m kg_mcp.server

dev-http-auth: ## Run streamable-HTTP with MCP_API_KEY bearer enforcement (matches prod auth path 1)
	MCP_TRANSPORT=streamable-http \
	MCP_HOST=$(MCP_HOST) \
	MCP_PORT=$(MCP_PORT) \
	MCP_API_KEY=$(MCP_API_KEY) \
	MCP_DISABLE_DNS_REBINDING_PROTECTION=1 \
	$(PYTHON) -m kg_mcp.server

# ─── Tests ───────────────────────────────────────────────────

test: test-unit test-integration ## Run all CI-safe tests (unit + in-memory integration)

test-unit: ## Pure-logic and mocked-client unit tests (fast; no transport)
	$(PYTEST) tests/unit -v

test-integration: ## In-memory MCP-client SDK round-trip smoke + registration
	$(PYTEST) tests/integration -v

test-smoke: ## Smallest set that proves the server boots + tools are reachable
	$(PYTEST) tests/integration/test_mcp_client_smoke.py tests/unit/test_server_registration.py -v

test-coverage: ## Coverage report (target ≥ 80%)
	$(PYTEST) --cov=kg_mcp --cov-report=term-missing --cov-report=html tests/

test-e2e-local: ## Drive HTTP endpoints of a LOCAL running dev-http-auth server
	@echo "Make sure 'make dev-http-auth' is running in another terminal."
	KG_MCP_E2E_URL=$(KG_MCP_E2E_URL) \
	MCP_API_KEY=$(MCP_API_KEY) \
	$(PYTEST) tests/e2e -v

test-e2e-staging: ## Drive HTTP endpoints of the deployed staging server (needs MCP_API_KEY)
	@test -n "$$MCP_API_KEY" || (echo "MCP_API_KEY env var required" && exit 1)
	KG_MCP_E2E_URL=$(STAGING_URL) \
	$(PYTEST) tests/e2e -v

# ─── Quality gates ───────────────────────────────────────────

lint: ## Ruff lint + format check (no writes)
	$(RUFF) check src tests
	$(RUFF) format --check src tests

lint-fix: ## Ruff fix + format (writes)
	$(RUFF) check --fix src tests
	$(RUFF) format src tests

format: lint-fix ## Alias for lint-fix

typecheck: ## Pyright type check (best-effort; non-blocking)
	$(PYTHON) -m pyright src || true

ci: lint test ## What CI runs: lint + all tests

clean: ## Remove caches and coverage artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
