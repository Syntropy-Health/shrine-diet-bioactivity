#!/usr/bin/env node

/**
 * mcp-herbal-botanicals — MCP server bridging herbal medicine to food nutrition.
 *
 * First-of-kind herb→compound→food bridge for AI dietitians.
 * Data backbone: Dr. Duke's Phytochemical DB + FooDB, pre-joined in SQLite.
 *
 * Tools:
 *   search-herbs          — fuzzy search herbs by common/scientific name
 *   get-herb-compounds    — active compounds for a given herb
 *   search-compounds      — search compounds by name, see herb + food associations
 *   get-compound-foods    — foods containing a specific compound
 *   get-herb-food-overlap — foods sharing the most compounds with a herb
 *   search-by-bioactivity — herbs/compounds by health benefit tag
 *   get-herb-profile      — full herb monograph (compounds, bioactivities, food overlap)
 *   get-health            — database stats and health check
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { HerbalDBAdapter } from './HerbalDBAdapter.js';

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const SearchHerbsSchema = z.object({
  query: z.string().min(1, 'Search query must not be empty'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(10),
});

const GetHerbCompoundsSchema = z.object({
  herb_id: z.string().min(1, 'Herb ID is required'),
});

const SearchCompoundsSchema = z.object({
  query: z.string().min(1, 'Search query must not be empty'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(10),
});

const GetCompoundFoodsSchema = z.object({
  compound_id: z.string().min(1, 'Compound ID is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(20),
});

const GetHerbFoodOverlapSchema = z.object({
  herb_id: z.string().min(1, 'Herb ID is required'),
  limit: z.number().min(1).max(50).optional().default(20),
});

const SearchByBioactivitySchema = z.object({
  activity: z.string().min(1, 'Bioactivity search term is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(10),
});

const GetHerbProfileSchema = z.object({
  herb_id: z.string().min(1, 'Herb ID is required'),
});

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

class HerbalBotanicalsMCPServer {
  private readonly server = new McpServer(
    {
      name: 'mcp-herbal-botanicals',
      version: '1.0.0',
      description: `The first MCP server for dietary and phytochemical compound data. Bridges herbal medicine to food nutrition using Dr. Duke's Phytochemical Database and FooDB.

Use this server when a query involves:
- Herbal supplements, botanicals, or medicinal plants
- Phytochemical compounds (flavonoids, alkaloids, terpenoids, etc.)
- Finding which foods share active compounds with specific herbs
- Looking up bioactivities (anti-inflammatory, antioxidant, adaptogenic, etc.)
- Connecting traditional herbal medicine to evidence-based food nutrition

Example queries this server answers:
- "What compounds are in ashwagandha?"
- "What foods contain quercetin?"
- "What foods have similar actives as turmeric?"
- "Which herbs have anti-inflammatory compounds?"
- "Give me a full profile of ginseng"

Composable with mcp-opennutrition for complete food + herbal nutrition coverage.`,
    },
    {
      capabilities: {
        logging: {},
      },
    }
  );

  constructor(
    private readonly transport: StdioServerTransport,
    private readonly db: HerbalDBAdapter
  ) {
    this.registerTools();
  }

  private registerTools(): void {
    // === search-herbs ===
    this.server.tool(
      'search-herbs',
      `Search herbs and botanicals by common name, scientific name, or synonym. Returns paginated results sorted by relevance.

Use when: User mentions an herb name, asks about plants, or wants to find herbs by name.

Examples:
- search-herbs("ashwagandha") → Withania somnifera
- search-herbs("ginseng") → Panax ginseng + other ginseng species
- search-herbs("mint") → multiple Mentha species`,
      SearchHerbsSchema.shape,
      { title: 'Search herbs by name', readOnlyHint: true },
      async (args) => {
        const result = this.db.searchHerbs(args.query, args.page, args.pageSize);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { result },
        };
      }
    );

    // === get-herb-compounds ===
    this.server.tool(
      'get-herb-compounds',
      `Get all active compounds found in a specific herb, with concentrations (PPM) and plant parts. Returns compounds sorted by concentration (highest first).

Use when: User wants to know what's in a specific herb, asks about active ingredients, or needs compound details.

Requires a herb_id from search-herbs results. Example: get-herb-compounds("2169") for Ashwagandha.`,
      GetHerbCompoundsSchema.shape,
      { title: 'Get compounds for a herb', readOnlyHint: true },
      async (args) => {
        const result = this.db.getHerbCompounds(args.herb_id);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { compounds: result },
        };
      }
    );

    // === search-compounds ===
    this.server.tool(
      'search-compounds',
      `Search phytochemical compounds by name. Returns compound details, bioactivities, and counts of associated herbs and foods.

Use when: User asks about a specific compound (quercetin, curcumin, withanolides), wants to find compounds by name, or needs compound details.

Examples:
- search-compounds("quercetin") → flavonoid found in 50+ herbs, 100+ foods
- search-compounds("curcumin") → found in turmeric, anti-inflammatory`,
      SearchCompoundsSchema.shape,
      { title: 'Search compounds by name', readOnlyHint: true },
      async (args) => {
        const result = this.db.searchCompounds(args.query, args.page, args.pageSize);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { result },
        };
      }
    );

    // === get-compound-foods ===
    this.server.tool(
      'get-compound-foods',
      `Get foods that contain a specific compound, with content amounts and units. Returns foods sorted by content value (highest first).

Use when: User asks "what foods contain X?", wants food sources of a compound, or needs to find dietary sources of phytochemicals.

Requires a compound_id from search-compounds results.`,
      GetCompoundFoodsSchema.shape,
      { title: 'Get foods containing a compound', readOnlyHint: true },
      async (args) => {
        const result = this.db.getCompoundFoods(args.compound_id, args.page, args.pageSize);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { result },
        };
      }
    );

    // === get-herb-food-overlap ===
    this.server.tool(
      'get-herb-food-overlap',
      `Find foods that share the most active compounds with a given herb. Returns foods ranked by overlap score (shared compounds / total herb compounds).

This is the flagship "what foods are like this herb?" query. Use when: User asks about food alternatives to a supplement, wants to know which foods have similar benefits, or asks "what foods give me the same benefits as X?"

Requires a herb_id from search-herbs results.`,
      GetHerbFoodOverlapSchema.shape,
      { title: 'Get food-herb compound overlap', readOnlyHint: true },
      async (args) => {
        const result = this.db.getHerbFoodOverlap(args.herb_id, args.limit);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { foods: result },
        };
      }
    );

    // === search-by-bioactivity ===
    this.server.tool(
      'search-by-bioactivity',
      `Search for compounds and herbs by health benefit or bioactivity tag (e.g., anti-inflammatory, antioxidant, adaptogenic, anxiolytic).

Use when: User describes symptoms or desired health effects and wants to find herbs/compounds that address them. Enables the symptom→compound→herb/food flow.

Examples:
- search-by-bioactivity("anti-inflammatory") → quercetin, curcumin, etc. + their herb sources
- search-by-bioactivity("adaptogenic") → withanolides (ashwagandha), ginsenosides (ginseng)`,
      SearchByBioactivitySchema.shape,
      { title: 'Search by bioactivity/health benefit', readOnlyHint: true },
      async (args) => {
        const result = this.db.searchByBioactivity(args.activity, args.page, args.pageSize);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { result },
        };
      }
    );

    // === get-herb-profile ===
    this.server.tool(
      'get-herb-profile',
      `Get a comprehensive herb profile: botanical info, top compounds with concentrations, bioactivity summary, and count of foods with shared compounds.

Use when: User wants a complete overview of a herb, asks for a "herb monograph", or needs a one-call summary.

Requires a herb_id from search-herbs results.`,
      GetHerbProfileSchema.shape,
      { title: 'Get full herb profile', readOnlyHint: true },
      async (args) => {
        const result = this.db.getHerbProfile(args.herb_id);
        if (!result) {
          return {
            content: [{ type: 'text', text: `Herb not found: ${args.herb_id}` }],
            isError: true,
          };
        }
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          structuredContent: { profile: result },
        };
      }
    );

    // === get-health ===
    this.server.tool(
      'get-health',
      'Health check: returns database statistics (table row counts, bridge compound count).',
      {},
      { title: 'Health check', readOnlyHint: true },
      async () => {
        const stats = this.db.getStats();
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify({ status: 'ok', ...stats }, null, 2),
            },
          ],
          structuredContent: { status: 'ok', ...stats },
        };
      }
    );
  }

  async connect(): Promise<void> {
    return this.server.connect(this.transport);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const db = new HerbalDBAdapter();
  const transport = new StdioServerTransport();
  const server = new HerbalBotanicalsMCPServer(transport, db);
  await server.connect();
  console.error('mcp-herbal-botanicals MCP Server running on stdio');
}

main().catch((error) => {
  console.error('Fatal error in main():', error);
  process.exit(1);
});
