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

const SearchBySymptomSchema = z.object({
  query: z.string().min(1, 'Symptom search query is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(10),
});

const GetCompoundTargetsSchema = z.object({
  compound_id: z.string().min(1, 'Compound ID is required'),
});

const FindFunctionalFoodsSchema = z.object({
  query: z.string().min(1, 'Search query is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(20),
});

const SearchDiseasesSchema = z.object({
  query: z.string().min(1, 'Disease search query is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(20),
});

const GetTargetDiseasesSchema = z.object({
  target_id: z.string().min(1, 'Target ID is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(20),
});

const GetChemicalDiseasesSchema = z.object({
  compound_id: z.string().min(1, 'Compound ID is required'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(20),
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function errorContent(error: unknown): { content: Array<{ type: 'text'; text: string }>; isError: true } {
  const message = error instanceof Error ? error.message : 'Internal database error';
  return { content: [{ type: 'text', text: message }], isError: true };
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------

class HerbalBotanicalsMCPServer {
  private readonly server = new McpServer(
    {
      name: 'mcp-herbal-botanicals',
      version: '1.0.0',
      description: `Phytochemical knowledge graph MCP server. Bridges herbal medicine → active compounds → foods → health benefits using Dr. Duke's Phytochemical Database and FooDB, with symptom mapping derived from bioactivity data.

Use this server when a query involves:
- Health concerns or symptoms ("I'm tired", "chronic inflammation", "can't sleep")
- Herbal supplements, botanicals, or medicinal plants
- Phytochemical compounds (flavonoids, alkaloids, terpenoids, etc.)
- Finding which foods share active compounds with specific herbs
- Functional foods — food plants with therapeutic properties
- Bioactivities (anti-inflammatory, antioxidant, adaptogenic, etc.)

Example queries this server answers:
- "What helps with inflammation?" → search-by-symptom
- "What compounds are in ashwagandha?" → get-herb-compounds
- "What foods contain quercetin?" → get-compound-foods
- "What foods have similar actives as turmeric?" → get-herb-food-overlap
- "Which food plants help with stress?" → find-functional-foods
- "Give me a full profile of ginseng" → get-herb-profile

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
        try {
          const result = this.db.searchHerbs(args.query, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
          const result = this.db.getHerbCompounds(args.herb_id);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { compounds: result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
          const result = this.db.searchCompounds(args.query, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
          const result = this.db.getCompoundFoods(args.compound_id, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
          const result = this.db.getHerbFoodOverlap(args.herb_id, args.limit);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { foods: result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
          const result = this.db.searchByBioactivity(args.activity, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
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
        try {
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
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === search-by-symptom ===
    this.server.tool(
      'search-by-symptom',
      `Find herbs, compounds, and foods for a health concern or symptom. Returns matched symptoms, associated herbs (with food-plant flags), key compounds, and functional foods.

Use when: User describes a health issue ("I'm tired", "chronic inflammation", "can't sleep") and wants to find herbal and food-based solutions.

Examples:
- search-by-symptom("inflammation") → Turmeric (curcumin), Ginger (gingerol) + foods with shared compounds
- search-by-symptom("insomnia") → Valerian, Chamomile + calming foods
- search-by-symptom("fatigue") → Ashwagandha, Ginseng + energy-supporting foods`,
      SearchBySymptomSchema.shape,
      { title: 'Search by symptom/health concern', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.searchBySymptom(args.query, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === get-compound-targets ===
    this.server.tool(
      'get-compound-targets',
      `Get molecular targets for a specific compound. Returns target proteins with activity values and interaction types.

Use when: User wants to understand WHY a compound has a particular health benefit, or needs molecular-level detail about a phytochemical's mechanism of action.

Note: Target data is populated from CMAUP database. Returns empty array if no target data is available for the compound.`,
      GetCompoundTargetsSchema.shape,
      { title: 'Get compound molecular targets', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.getCompoundTargets(args.compound_id);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { targets: result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === find-functional-foods ===
    this.server.tool(
      'find-functional-foods',
      `Search for food plants and edible herbs with therapeutic compound profiles. Returns herbs that are also foods (turmeric, ginger, garlic, etc.) along with common foods that share their active compounds.

Use when: User wants food-based alternatives to supplements, asks about "functional foods", or wants to know which everyday foods have therapeutic compounds.

Examples:
- find-functional-foods("turmeric") → Turmeric (312 compounds) + foods sharing curcumin
- find-functional-foods("ginger") → Ginger (245 compounds) + foods sharing gingerol
- find-functional-foods("anti-inflammatory") → Food plants with anti-inflammatory compounds`,
      FindFunctionalFoodsSchema.shape,
      { title: 'Find functional food plants', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.findFunctionalFoods(args.query, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === search-diseases ===
    this.server.tool(
      'search-diseases',
      `Search diseases by name across all data sources (CMAUP plant-disease, TTD drug-disease). Returns diseases with associated targets and druggability status.

Use when: User asks about diseases, conditions, or wants to find which targets/compounds are associated with a specific disease.

Examples:
- search-diseases("diabetes") → targets and compounds linked to diabetes
- search-diseases("cancer") → oncology-related targets with druggability status`,
      SearchDiseasesSchema.shape,
      { title: 'Search diseases by name', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.searchDiseases(args.query, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === get-target-diseases ===
    this.server.tool(
      'get-target-diseases',
      `Get diseases associated with a specific molecular target. Returns disease names with evidence type and druggability status.

Use when: User wants to know what diseases a specific protein target is involved in, or wants to understand the therapeutic relevance of a target.

Requires a target_id from get-compound-targets results.`,
      GetTargetDiseasesSchema.shape,
      { title: 'Get diseases for a target', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.getTargetDiseases(args.target_id, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === get-chemical-diseases ===
    this.server.tool(
      'get-chemical-diseases',
      `Get disease associations for a compound from CTD (Comparative Toxicogenomics Database). Returns curated chemical-disease relationships with direct evidence and inference scores.

Use when: User wants to know what diseases a specific compound is linked to, based on toxicogenomics literature.

Note: Requires CTD data to be loaded. Returns empty if CTD data is not available.`,
      GetChemicalDiseasesSchema.shape,
      { title: 'Get CTD disease associations for a compound', readOnlyHint: true },
      async (args) => {
        try {
          const result = this.db.getChemicalDiseases(args.compound_id, args.page, args.pageSize);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            structuredContent: { result },
          };
        } catch (error: unknown) {
          return errorContent(error);
        }
      }
    );

    // === semantic-search (LightRAG bridge) ===
    this.server.tool(
      'semantic-search',
      `Semantic knowledge graph search powered by LightRAG.
Queries the unified diet KG (Neo4j) using natural language — supports multi-hop reasoning
across herbs, compounds, foods, targets, diseases, and symptoms.

Best for:
- Natural language questions: "What foods help with inflammation?"
- Multi-hop traversal: "Which herbs contain compounds that target COX-2?"
- Discovery queries: "What dietary sources have anti-cancer bioactivity?"
- Cross-domain: "Foods high in vitamin C that also contain antioxidant compounds?"

Query modes:
- local: Entity-focused retrieval (best for specific lookups)
- global: Community-based broad knowledge (best for summarization)
- hybrid: Combines local + global (best general-purpose)
- mix: KG + vector retrieval with reranker (highest quality, requires reranker)

Requires LightRAG server running (make lightrag-server).`,
      {
        query: z.string().min(3).describe('Natural language query about herbs, compounds, foods, diseases, or their relationships'),
        mode: z.enum(['local', 'global', 'hybrid', 'mix', 'naive']).default('hybrid').describe('Retrieval mode'),
        top_k: z.number().min(1).max(200).default(60).describe('Number of entities/relations to retrieve'),
      },
      { title: 'Semantic knowledge graph search', readOnlyHint: true },
      async (args) => {
        try {
          const lightragUrl = process.env.LIGHTRAG_API_URL || 'http://localhost:9621';
          const response = await fetch(`${lightragUrl}/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: args.query,
              mode: args.mode,
              top_k: args.top_k,
            }),
          });

          if (!response.ok) {
            const errText = await response.text();
            return {
              content: [{ type: 'text', text: `LightRAG query failed (${response.status}): ${errText}` }],
              isError: true,
            };
          }

          const result = await response.json();
          return {
            content: [{ type: 'text', text: typeof result === 'string' ? result : JSON.stringify(result, null, 2) }],
            structuredContent: result,
          };
        } catch (error: unknown) {
          const msg = error instanceof Error ? error.message : String(error);
          return {
            content: [{ type: 'text', text: `LightRAG server not reachable: ${msg}\nStart it with: make lightrag-server` }],
            isError: true,
          };
        }
      }
    );

    // === get-health ===
    this.server.tool(
      'get-health',
      'Health check: returns database statistics (table row counts, bridge compound count).',
      {},
      { title: 'Health check', readOnlyHint: true },
      async () => {
        try {
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
        } catch (error: unknown) {
          return errorContent(error);
        }
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
