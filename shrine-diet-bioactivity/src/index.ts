#!/usr/bin/env node

/**
 * shrine-diet-bioactivity — thin-adapter MCP over the scoped LightRAG
 * wrapper.  All 5 tools are domain-agnostic pass-throughs; clinical /
 * culinary reasoning lives in the agent layer.
 *
 * Catalog:
 *   semantic-search     POST /query
 *   get-entity          GET  /graphs?max_depth=0
 *   get-subgraph        GET  /graphs?max_depth=N
 *   list-labels         GET  /graph/label/popular
 *   ingest-knowledge    POST /documents/custom_kg (tenant-scoped)
 *   get-health          server-only
 *
 * Env:
 *   LIGHTRAG_API_URL  default http://localhost:9621
 *   MCP_AUDIT_DB      default ./audit/mcp_audit.db
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { resolve } from 'node:path';
import { AuditLog } from './audit_log.js';
import { LightRagClient } from './lightrag_proxy.js';
import { buildToolDefs } from './tools.js';

const SERVER_DESCRIPTION = `LightRAG-backed knowledge graph MCP. Exposes 5 domain-agnostic primitives for retrieval and tenant-private ingestion. Every call is scope-filtered (shared + caller tenant) and audit-logged.

Retrieval modes available in semantic-search:
- local   — entity-focused context
- global  — community summaries
- hybrid  — both (default)
- mix     — KG + vector
- naive   — vector only

Tools:
- semantic-search    — natural-language retrieval, scope-filtered
- get-entity         — single node by id
- get-subgraph       — connected neighborhood, N hops
- list-labels        — popular entity labels visible in scope
- ingest-knowledge   — tenant-private custom_kg write (requires _meta.tenant_id)
- get-health         — server status`;

class ShrineDietBioactivityMcp {
  private readonly server = new McpServer(
    {
      name: 'shrine-diet-bioactivity',
      version: '2.0.0',
      description: SERVER_DESCRIPTION,
    },
    {
      capabilities: { logging: {} },
    },
  );

  constructor(
    private readonly transport: StdioServerTransport,
    private readonly deps: { client: LightRagClient; audit: AuditLog },
  ) {
    this.registerTools();
  }

  private registerTools(): void {
    for (const def of buildToolDefs(this.deps)) {
      this.server.tool(
        def.name,
        def.description,
        def.schema,
        { title: def.title, readOnlyHint: def.readOnlyHint },
        async (args, extra) => {
          const meta = (extra as { _meta?: Record<string, unknown> } | undefined)
            ?._meta;
          return def.handler(args as Record<string, unknown>, meta);
        },
      );
    }
  }

  async connect(): Promise<void> {
    return this.server.connect(this.transport);
  }
}

async function main(): Promise<void> {
  const baseUrl = process.env.LIGHTRAG_API_URL ?? 'http://localhost:9621';
  const auditPath = resolve(
    process.env.MCP_AUDIT_DB ?? './audit/mcp_audit.db',
  );
  const client = new LightRagClient({ baseUrl });
  const audit = new AuditLog(auditPath);
  const transport = new StdioServerTransport();
  const server = new ShrineDietBioactivityMcp(transport, { client, audit });
  await server.connect();
  process.stderr.write(
    `shrine-diet-bioactivity MCP running on stdio → ${baseUrl} (audit: ${auditPath})\n`,
  );
}

main().catch((err: unknown) => {
  const msg = err instanceof Error ? err.stack ?? err.message : String(err);
  process.stderr.write(`Fatal error in main(): ${msg}\n`);
  process.exit(1);
});
