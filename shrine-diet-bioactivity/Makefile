# ─────────────────────────────────────────────────────────────
# shrine-diet-bioactivity — Phytochemical Knowledge Graph (Python + TypeScript thin adapter)
# ─────────────────────────────────────────────────────────────
#
# Usage:
#   make help              Show all targets
#   make setup             Full pipeline: download → build → migrate → bridge
#   make lightrag-dry-run  Preview LightRAG ingestion (no writes)
#   make lightrag-ingest   Ingest unified KG into LightRAG/Neo4j
#   make neo4j-check       Test Neo4j connection and show KG stats
#
# Prerequisites:
#   - Node.js 18+, npm
#   - Python 3.10+ (for LightRAG)
#   - Ollama running on :11434 with bge-m3 model (for local LightRAG)
#
# Neo4j (Railway):
#   Bolt proxy:  bolt://metro.proxy.rlwy.net:22971
#   Credentials: neo4j / demodemo
#   View in Neo4j Desktop: connect to bolt://metro.proxy.rlwy.net:22971
#   Or use: make neo4j-shell
# ─────────────────────────────────────────────────────────────

.PHONY: help setup download build migrate download-cmaup download-ttd \
        migrate-multi test build-ts check-types \
        food-bridge enrich-nutrition \
        download-symmap load-symmap \
        download-herb2 load-herb2 \
        lightrag-setup lightrag-dry-run lightrag-ingest-local lightrag-ingest-prod \
        lightrag-benchmark lightrag-server lightrag-server-upstream \
        lightrag-bootstrap-scope lightrag-bootstrap-scope-dry-run \
        lightrag-bootstrap-scope-prod lightrag-test-scope \
        lightrag-canary-test lightrag-test-integration audit-recent \
        neo4j-check neo4j-shell neo4j-stats neo4j-status neo4j-watch neo4j-clear \
        embedding-check lms-models clean \
        eval-smoke eval-run eval-report eval-embed-ingest

# Default Neo4j connection (Railway proxy)
NEO4J_URI    ?= bolt://metro.proxy.rlwy.net:22971
NEO4J_USER   ?= neo4j
NEO4J_PASS   ?= demodemo

# ─── Prototype KG subsample configuration ───────────────────
# These MAX_* limits define the reproducible prototype KG shape.
# Sampling is deterministic (SQL LIMIT with stable ORDER BY) — no RNG
# is in use today. SUBSAMPLE_SEED is reserved for future random sampling
# and plumbed through to ingest_unified.py via env.
MAX_HERBS        ?= 2376
MAX_COMPOUNDS    ?= 5000
MAX_FOODS        ?= 0
MAX_RELATIONSHIPS?= 0          # 0 = unlimited (full-scale); override for prototype reruns
BATCH_SIZE       ?= 500
SUBSAMPLE_SEED   ?= 42

help: ## Show all targets with descriptions
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Full Pipeline ──────────────────────────────────────────

setup: download build migrate food-bridge enrich-nutrition ## Full pipeline: download → build → migrate → bridge → enrich
	@echo "✅ Setup complete. Run 'make lightrag-dry-run' to preview, then 'make lightrag-ingest-local'."

# ─── Data Download ──────────────────────────────────────────

download: ## Download Duke + FooDB source data (~960 MB)
	npm run download-data

download-cmaup: ## Download CMAUP v2.0 data files (~10 MB)
	npm run download-cmaup

download-ttd: ## Download TTD target data (~5 MB)
	npm run download-ttd

download-all: download download-cmaup download-ttd ## Download all auto-downloadable datasets

download-symmap: ## Download SymMap v2.0 xlsx files (SMHB, SMTS, SMMS, SMIT, SMTT) into data/symmap/
	npx tsx scripts/download-symmap.ts

load-symmap: ## Load SymMap v2.0 xlsx → 5 SQLite tables (herbs, tcm/modern symptoms, ingredients, genes)
	npx tsx scripts/load-symmap.ts

download-herb2: ## Fetch HERB 2.0 via chedi JSON-RPC API into data/herb2/ (herbs.json + herb_details.json)
	npx tsx scripts/download-herb2.ts

load-herb2: ## Load HERB 2.0 JSON → herb2_herbs + herb2_herb_disease with evidence tiers
	npx tsx scripts/load-herb2.ts

# ─── Build & Migrate ────────────────────────────────────────

build: ## Build SQLite DB from downloaded CSVs
	npm run convert-data

migrate: ## Run KG expansion migration (symptoms, targets, food plants)
	npm run migrate-kg

migrate-multi: ## Load CMAUP + CTD + TTD into existing DB
	npm run migrate-multi-source

# ─── TypeScript ─────────────────────────────────────────────

build-ts: ## Compile TypeScript → build/
	npm run build

check-types: ## Type-check without emitting
	npx tsc --noEmit

test: ## Run all tests (vitest)
	npx vitest run

# LM Studio (WSL2 → Windows host)
# LM Studio must listen on 0.0.0.0:1234 (not 127.0.0.1) for WSL2 access.
# In LM Studio: Settings → Server → Listen Address → 0.0.0.0
LMS_HOST ?= $(shell ip route show default 2>/dev/null | awk '{print $$3}')
LMS_URL  ?= http://$(LMS_HOST):1234/v1

# ─── Embedding Server ──────────────────────────────────────

embedding-check: ## Test LM Studio embedding endpoint via WSL2 host
	@echo "Testing $(LMS_URL)/embeddings ..."
	@curl -sf --connect-timeout 5 $(LMS_URL)/embeddings \
		-H "Content-Type: application/json" \
		-d '{"model": "text-embedding-embeddinggemma-300m-qat", "input": "test"}' \
		| python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✅ Embedding dim: {len(d[\"data\"][0][\"embedding\"])}')" \
		|| echo "❌ LM Studio not reachable at $(LMS_URL). Ensure it listens on 0.0.0.0:1234."

lms-models: ## List models loaded in LM Studio
	@curl -sf --connect-timeout 5 $(LMS_URL)/models \
		| python3 -c "import sys,json; [print(f'  {m[\"id\"]}') for m in json.load(sys.stdin).get('data',[])]" \
		|| echo "❌ LM Studio not reachable at $(LMS_URL)"

# ─── Neo4j ──────────────────────────────────────────────────

neo4j-check: ## Test Neo4j connection and show node/edge counts
	@python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('=== Neo4j KG Status ==='); \
print('URI: $(NEO4J_URI)'); \
[print(f\"  {r['type']}: {r['count']}\") for r in s.run('MATCH (n) RETURN labels(n) AS type, COUNT(n) AS count ORDER BY count DESC')]; \
[print(f\"  {r['rel']}: {r['count']}\") for r in s.run('MATCH ()-[r]->() RETURN type(r) AS rel, COUNT(r) AS count ORDER BY count DESC')]; \
total_n = s.run('MATCH (n) RETURN COUNT(n) AS c').single()['c']; \
total_r = s.run('MATCH ()-[r]->() RETURN COUNT(r) AS c').single()['c']; \
print(f'Total: {total_n} nodes, {total_r} relationships'); \
s.close(); d.close()"

neo4j-shell: ## Open interactive Cypher shell against Railway Neo4j
	@echo "Connecting to $(NEO4J_URI) ..."
	@docker run --rm -it neo4j:5-community cypher-shell \
		-a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASS) \
		2>/dev/null || \
	python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('Connected. Enter Cypher (empty line to quit):'); \
import sys; \
[None for _ in iter(lambda: (q:=input('> ').strip()) or None, None) if q and [print(r.data()) for r in s.run(q)]]; \
s.close(); d.close()"

neo4j-stats: ## Show detailed KG statistics via Cypher
	@python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('=== Detailed KG Stats ==='); \
for r in s.run('MATCH (n) RETURN labels(n)[0] AS label, COUNT(n) AS count ORDER BY count DESC'): print(f'  Nodes [{r[\"label\"]}]: {r[\"count\"]}'); \
for r in s.run('MATCH ()-[r]->() RETURN type(r) AS type, COUNT(r) AS count ORDER BY count DESC'): print(f'  Edges [{r[\"type\"]}]: {r[\"count\"]}'); \
s.close(); d.close()"

neo4j-status: ## Full KG analytics — node/edge breakdown by workspace
	@python3 -c "\
	from neo4j import GraphDatabase; \
	d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
	s = d.session(); \
	print('=== KG Status by Workspace ==='); \
	for r in s.run('MATCH (n) RETURN labels(n) AS labels, COUNT(n) AS count ORDER BY count DESC'): print(f'  Nodes {r[\"labels\"]}: {r[\"count\"]}'); \
	print(); \
	for r in s.run('MATCH ()-[r]->() RETURN type(r) AS type, COUNT(r) AS count ORDER BY count DESC'): print(f'  Edges [{r[\"type\"]}]: {r[\"count\"]}'); \
	total_n = s.run('MATCH (n) RETURN COUNT(n) AS c').single()['c']; \
	total_r = s.run('MATCH ()-[r]->() RETURN COUNT(r) AS c').single()['c']; \
	print(f'\nTotal: {total_n} nodes, {total_r} relationships'); \
	s.close(); d.close()"

neo4j-watch: ## Live-monitor KG growth (polls every 30s, Ctrl+C to stop)
	@echo "Watching KG growth at $(NEO4J_URI) — Ctrl+C to stop"
	@while true; do \
		python3 -c "\
	from neo4j import GraphDatabase; import datetime; \
	d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
	s = d.session(); \
	n = s.run('MATCH (n) RETURN COUNT(n) AS c').single()['c']; \
	r = s.run('MATCH ()-[r]->() RETURN COUNT(r) AS c').single()['c']; \
	print(f'{datetime.datetime.now():%H:%M:%S} — {n} nodes, {r} edges'); \
	s.close(); d.close()" 2>/dev/null || true; \
		sleep 30; \
	done

neo4j-clear: ## ⚠️  Delete ALL nodes and relationships in Neo4j
	@echo "⚠️  This will delete ALL data in Neo4j at $(NEO4J_URI)"
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] && \
	python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
s.run('MATCH (n) DETACH DELETE n'); \
print('✅ All nodes and relationships deleted.'); \
s.close(); d.close()" || echo "Cancelled."

# ─── Food Bridge & Nutrition Enrichment ─────────────────────

food-bridge: ## Build food name bridge between FooDB and OpenNutrition
	npm run build-food-bridge

enrich-nutrition: food-bridge ## Enrich compound_foods with OpenNutrition nutrition data
	npm run enrich-nutrition

# ─── LightRAG ─────────────────────────────────────────────

lightrag-setup: ## Install LightRAG Python dependencies
	cd lightrag && pip install -r requirements.txt

lightrag-dry-run: ## Dry-run ingestion — print entity/relationship counts (no writes)
	cd lightrag && python3 ingest_unified.py --config local --dry-run

lightrag-ingest-local: ## Ingest unified KG into LightRAG (local Ollama embeddings, full-scale)
	cd lightrag && python3 ingest_unified.py --config local --batch-size $(BATCH_SIZE)

lightrag-ingest-sampled: ## Sampled ingest — proves Duke+SymMap+HERB2+HDI wiring in ~30-60min on Ollama
	cd lightrag && python3 -u ingest_unified.py --config local \
		--batch-size 200 \
		--max-herbs 500 --max-compounds 1000 --max-foods 200 \
		--max-relationships 5000 \
		--max-extra-per-table 1000 \
		--herb2-experimental-cap 1000

lightrag-ingest-prototype: ## Reproduce the prototype KG with the exact subsample config
	cd lightrag && SUBSAMPLE_SEED=$(SUBSAMPLE_SEED) python3 ingest_unified.py \
		--config local \
		--batch-size $(BATCH_SIZE) \
		--max-herbs $(MAX_HERBS) \
		--max-compounds $(MAX_COMPOUNDS) \
		$(if $(filter-out 0,$(MAX_FOODS)),--max-foods $(MAX_FOODS),) \
		--max-relationships $(MAX_RELATIONSHIPS)
	@echo "✅ Prototype ingest complete. Config:"
	@echo "   MAX_HERBS=$(MAX_HERBS) MAX_COMPOUNDS=$(MAX_COMPOUNDS)"
	@echo "   MAX_FOODS=$(MAX_FOODS) MAX_RELATIONSHIPS=$(MAX_RELATIONSHIPS)"
	@echo "   SUBSAMPLE_SEED=$(SUBSAMPLE_SEED) BATCH_SIZE=$(BATCH_SIZE)"

lightrag-ingest-prod: ## Ingest unified KG into LightRAG (production API embeddings)
	cd lightrag && python3 ingest_unified.py --config production --batch-size 200

lightrag-benchmark: ## Run 10 benchmark queries against LightRAG
	cd lightrag && python3 query_benchmark.py --config local

lightrag-metrics: ## Print KG metrics report (entity/relationship counts, data quality)
	cd lightrag && python3 kg_metrics.py --config local

lightrag-metrics-save: ## Save KG metrics report to data/kg-reports/
	cd lightrag && python3 kg_metrics.py --config local --save --json

lightrag-server: ## Start the scoped LightRAG wrapper on port 9621 (Phase A2)
	cd lightrag && uvicorn scoped_server:app --host 0.0.0.0 --port 9621

lightrag-server-upstream: ## Start upstream LightRAG (NO tenant filtering — dev only)
	cd lightrag && lightrag-server

lightrag-bootstrap-scope-dry-run: ## Preview scope='shared' migration (no writes)
	cd lightrag && python3 bootstrap_scope.py --config local --dry-run

lightrag-bootstrap-scope: ## Tag legacy Neo4j nodes/edges with scope='shared' and create indexes
	cd lightrag && python3 bootstrap_scope.py --config local

lightrag-bootstrap-scope-prod: ## Run scope bootstrap against the production Neo4j
	cd lightrag && python3 bootstrap_scope.py --config production

lightrag-test-scope: ## Run all scope + audit unit tests (no live Neo4j required)
	cd lightrag && python3 -m pytest \
		test_scope_context.py test_bootstrap_scope.py \
		test_audit_log.py test_scope_enforcement.py -v

lightrag-canary-test: ## Run cross-tenant isolation canary (requires live Neo4j + scoped_server running)
	cd lightrag && python3 canary_smoke_test.py --config local

lightrag-test-integration: ## Run integration tests (live Neo4j + scoped_server on :9621)
	cd lightrag && LIGHTRAG_RUN_INTEGRATION=true python3 -m pytest test_scope_enforcement.py -v -m integration

audit-recent: ## Tail last 20 rows of the per-tenant audit log
	sqlite3 lightrag/audit/mcp_audit.db \
		"SELECT ts, tenant_id, tool, status, latency_ms, result_count \
		 FROM mcp_audit ORDER BY id DESC LIMIT 20"

# ─── Cleanup ────────────────────────────────────────────────

clean: ## Remove build artifacts and temp data
	rm -rf build data_local_temp

# ─── Evaluation harness (Subsystem F) ───────────────────────

eval-smoke: ## Confirm OpenRouter Nemotron is reachable + structural sanity
	python3 -m pytest eval/ -v

eval-embed-ingest: ## Backfill LightRAG embeddings against existing Aura graph
	@if [ -z "$$OPENROUTER_API_KEY" ]; then \
		echo "ERROR: OPENROUTER_API_KEY not set in environment"; exit 1; \
	fi
	set -a && . ./.env && set +a && make lightrag-ingest-local

eval-run: ## Run baselines × test split. Usage: make eval-run [SYSTEMS=diet_os,medagents]
	@if [ -z "$$OPENROUTER_API_KEY" ]; then \
		echo "ERROR: OPENROUTER_API_KEY not set in .env"; exit 1; \
	fi
	set -a && . ./.env && set +a && \
		python3 -m eval.runner \
			--bench ../research-journal/shared/datasets/dietresearchbench_v1.json \
			--splits ../research-journal/shared/datasets/splits_seed42.json \
			--out ../research-journal/shared/results/$$(date -u +%Y%m%dT%H%M%SZ) \
			$(if $(SYSTEMS),--systems $(SYSTEMS),)

eval-report: ## Render the most recent results dir into summary.md + reliability_diagram.png
	python3 -m eval.report \
		--latest ../research-journal/shared/results/
