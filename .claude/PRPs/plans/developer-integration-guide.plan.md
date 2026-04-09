# Feature: Developer Integration Guide for Nutritional Agents

## Summary

Create comprehensive developer documentation enabling external developers to build their own nutritional agents by: (1) exposing open-diet-data as an MCP server for AI assistants, (2) integrating with LangGraph/LangChain agents as tools, and (3) duplicating the project structure for custom data sources. Documentation includes working code examples, step-by-step guides, and architecture diagrams.

## User Story

As a developer building AI health applications
I want clear documentation and example code for integrating open-diet-data
So that I can build my own nutritional agents using MCP or LangGraph

## Problem Statement

Developers lack guidance on how to:
- Duplicate/extend this project for their own nutritional data needs
- Build nutritional agents using LangGraph that consume this data
- Expose the data as MCP tools for Claude and other AI assistants
- Use the data programmatically as local tools through Python agents

## Solution Statement

Add a comprehensive `CONTRIBUTING.md` guide with three integration pathways:
1. **MCP Server**: Configure the existing TypeScript MCP server for any AI assistant
2. **LangGraph Agent**: Use `langchain-mcp-adapters` to wrap MCP tools in LangGraph agents
3. **Local Python Tool**: Direct Python wrapper functions for embedding in custom agents

Plus example code in `examples/` directory and updated README with integration section.

## Metadata

| Field            | Value                                             |
| ---------------- | ------------------------------------------------- |
| Type             | NEW_CAPABILITY                                    |
| Complexity       | MEDIUM                                            |
| Systems Affected | README.md, CONTRIBUTING.md (new), examples/ (new) |
| Dependencies     | langchain-mcp-adapters, mcp[cli] (Python 3.10+)   |
| Estimated Tasks  | 8                                                 |

---

## UX Design

### Before State

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                              BEFORE STATE                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐            ║
║   │  Developer  │ ──────► │  README.md  │ ──────► │   Setup     │            ║
║   │  discovers  │         │  (basic)    │         │   scripts   │            ║
║   │  open-diet  │         │             │         │             │            ║
║   └─────────────┘         └─────────────┘         └─────────────┘            ║
║          │                                                │                   ║
║          │                                                ▼                   ║
║          │                                        ┌─────────────┐            ║
║          └──────────────────────────────────────► │  ???        │            ║
║                     "How do I build               │  No agent   │            ║
║                      an agent with this?"         │  examples   │            ║
║                                                   └─────────────┘            ║
║                                                                               ║
║   USER_FLOW: Developer clones → Reads README → Sets up data → STUCK          ║
║   PAIN_POINT: No guidance on agent integration, MCP configuration, or        ║
║               LangGraph usage. Developer must reverse-engineer from code.    ║
║   DATA_FLOW: Data exists but no clear path to agent consumption              ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### After State

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                               AFTER STATE                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐            ║
║   │  Developer  │ ──────► │  README.md  │ ──────► │ CONTRIBUTING│            ║
║   │  discovers  │         │  (enhanced) │         │    .md      │            ║
║   │  open-diet  │         │             │         │             │            ║
║   └─────────────┘         └─────────────┘         └─────────────┘            ║
║                                   │                      │                    ║
║                                   │                      ▼                    ║
║                                   │               ┌─────────────┐            ║
║                                   │               │  examples/  │            ║
║                                   │               │  directory  │            ║
║                                   │               └──────┬──────┘            ║
║                                   │                      │                    ║
║                                   ▼                      ▼                    ║
║   ┌───────────────────────────────────────────────────────────────────────┐  ║
║   │                     THREE INTEGRATION PATHWAYS                         │  ║
║   ├───────────────────┬─────────────────────┬─────────────────────────────┤  ║
║   │  1. MCP SERVER    │  2. LANGGRAPH AGENT │  3. LOCAL PYTHON TOOL       │  ║
║   │  (Claude/Cline)   │  (langchain-mcp)    │  (Direct wrapper)           │  ║
║   │                   │                     │                             │  ║
║   │  mcp-config.json  │  langgraph_agent.py │  nutrition_tool.py          │  ║
║   │  ───────────────  │  ──────────────────-│  ─────────────────          │  ║
║   │  Ready-to-paste   │  Full agent example │  @tool decorator            │  ║
║   │  configurations   │  with state mgmt    │  Sync/async methods         │  ║
║   └───────────────────┴─────────────────────┴─────────────────────────────┘  ║
║                                                                               ║
║   USER_FLOW: Developer clones → Reads README → Chooses pathway →             ║
║              Copies example → Customizes → Running agent                     ║
║   VALUE_ADD: Clear integration paths with working code                       ║
║   DATA_FLOW: Data → MCP Server → LangGraph/LangChain → User's Agent          ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| README.md | Basic setup only | + "Building Agents" section with links | Clear entry point to integration docs |
| CONTRIBUTING.md | Does not exist | Full guide with 3 pathways | Step-by-step agent building instructions |
| examples/ | Does not exist | Working code examples | Copy-paste starting points |
| MCP config | Scattered in README | Consolidated examples | One place for all MCP configs |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `README.md` | 1-384 | Existing structure to extend |
| P0 | `AGENT.md` | 1-256 | Agent specification patterns |
| P0 | `mcp-opennutrition/src/index.ts` | 1-215 | MCP tool registration pattern |
| P1 | `mcp-opennutrition/src/SQLiteDBAdapter.ts` | 1-111 | Database interface pattern |
| P1 | `scripts/query-nih-dsld.py` | 1-220 | Python API client pattern |
| P2 | `PRD.md` | 1-141 | Architecture documentation style |

**External Documentation:**

| Source | Section | Why Needed |
|--------|---------|------------|
| [MCP Build Server](https://modelcontextprotocol.io/docs/develop/build-server) | Core concepts | MCP server creation patterns |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | FastMCP | Python MCP server examples (Python 3.10+) |
| [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters) | Integration | MCP-to-LangGraph bridge |
| [LangGraph Tools](https://docs.langchain.com/oss/python/langgraph/overview) | ToolNode | Agent tool integration |

---

## Patterns to Mirror

**README_STRUCTURE:**
```markdown
// SOURCE: README.md:1-36
// COPY THIS PATTERN - hierarchical overview with tables:

# Open Diet Data

Open-source nutrition and dietary supplement data sources...

## Overview

This repository aggregates authoritative open-source nutrition databases...

## Data Sources

| Source | Description | Items | API Key Required |
| --- | --- | --- | --- |
| **USDA FoodData Central** | Gold-standard US nutrition database | 900k+ foods | ❌ No |
```

**MCP_CONFIG_EXAMPLE:**
```json
// SOURCE: README.md:176-202
// COPY THIS PATTERN - MCP configuration blocks:

{
  "mcpServers": {
    "mcp-opennutrition": {
      "command": "/usr/bin/node",
      "args": ["/path/to/open-diet-data/mcp-opennutrition/build/index.js"]
    }
  }
}
```

**PYTHON_CLI_DOCSTRING:**
```python
# SOURCE: scripts/query-nih-dsld.py:1-16
# COPY THIS PATTERN - docstring header with usage examples:

#!/usr/bin/env python3
"""
NIH Dietary Supplement Label Database (DSLD) - Query Script
=============================================================================
Queries the NIH Office of Dietary Supplements API for supplement information.

API Documentation: https://dsld.od.nih.gov/api-guide
No API key required - public API with rate limits.

Usage:
    python scripts/query-nih-dsld.py --ingredient "vitamin d"
    python scripts/query-nih-dsld.py --product "multivitamin"
=============================================================================
"""
```

**MCP_TOOL_REGISTRATION:**
```typescript
// SOURCE: mcp-opennutrition/src/index.ts:58-93
// COPY THIS PATTERN - MCP tool definition with Zod schema:

this.server.tool(
  "search-food-by-name",
  `Description with use cases and examples...`,
  SearchFoodByNameRequestSchema.shape,
  {
    title: "Search food by name",
    readOnlyHint: true,
  },
  async (args, extra) => {
    const foods = await this.db.searchByName(args.query, args.page, args.pageSize);
    return {
      content: [{type: "text", text: JSON.stringify(foods, null, 2)}],
      structuredContent: {foods},
    };
  }
);
```

**AGENT_DATA_MODEL:**
```python
# SOURCE: AGENT.md:77-106
# COPY THIS PATTERN - Pydantic data models for agent interfaces:

class NutrientProfile(BaseModel):
    food_id: str
    food_name: str
    source: Literal["usda", "opennutrition", "shopify"]
    nutrients: Dict[str, NutrientValue]
    serving_size: Optional[str]
    barcode: Optional[str]
```

---

## Files to Change

| File                                    | Action | Justification                                      |
| --------------------------------------- | ------ | -------------------------------------------------- |
| `README.md`                             | UPDATE | Add "Building Nutritional Agents" section          |
| `CONTRIBUTING.md`                       | CREATE | Main developer integration guide                   |
| `examples/README.md`                    | CREATE | Examples directory overview                        |
| `examples/mcp-configs/claude.json`      | CREATE | Claude Desktop MCP config example                  |
| `examples/mcp-configs/vscode.json`      | CREATE | VS Code/Cline MCP config example                   |
| `examples/langgraph_agent.py`           | CREATE | LangGraph agent with MCP tools example             |
| `examples/langchain_tool.py`            | CREATE | LangChain @tool decorator wrapper example          |
| `examples/requirements.txt`             | CREATE | Python dependencies for examples                   |

---

## NOT Building (Scope Limits)

Explicit exclusions to prevent scope creep:

- **Python MCP Server implementation**: Only documenting how to use existing TypeScript server; Python MCP SDK requires 3.10+ which conflicts with project's 3.8+ target
- **Custom data source templates**: Not creating template repos for new data sources; just documenting the pattern
- **CI/CD integration**: Not adding GitHub Actions for examples; manual verification only
- **Docker packaging**: Not containerizing examples; local development focus
- **Web UI**: Not building any frontend components
- **Testing infrastructure for examples**: Examples are documentation, not production code

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: UPDATE `README.md` - Add Agent Integration Section

- **ACTION**: ADD "Building Nutritional Agents" section after "Integration" section
- **IMPLEMENT**:
  - Add section header at line ~310 (after "Integration" section)
  - Add overview paragraph explaining three integration pathways
  - Add table linking to CONTRIBUTING.md sections
  - Add quick-start code snippet for each pathway
- **MIRROR**: `README.md:36-56` - follow existing section structure with tables
- **CONTENT**:
```markdown
## Building Nutritional Agents

This data can power AI agents via three integration pathways:

| Pathway | Best For | Guide |
| --- | --- | --- |
| **MCP Server** | Claude Desktop, Cline, VS Code | [CONTRIBUTING.md#mcp-integration](./CONTRIBUTING.md#mcp-integration) |
| **LangGraph Agent** | Custom agent workflows | [CONTRIBUTING.md#langgraph-integration](./CONTRIBUTING.md#langgraph-integration) |
| **Local Python Tool** | Direct embedding in agents | [CONTRIBUTING.md#python-tool-integration](./CONTRIBUTING.md#python-tool-integration) |

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed guides and [examples/](./examples/) for working code.
```
- **VALIDATE**: Visual inspection - section appears correctly in README

### Task 2: CREATE `CONTRIBUTING.md` - Main Integration Guide

- **ACTION**: CREATE comprehensive developer guide
- **IMPLEMENT**: Full document with:
  - Table of contents
  - Prerequisites section (Node.js 18+, Python 3.10+ for LangGraph)
  - MCP Integration section with Claude/Cline/VS Code configs
  - LangGraph Integration section with `langchain-mcp-adapters`
  - Python Tool Integration section with @tool decorator
  - Extending the Project section (adding data sources)
  - Troubleshooting section
- **MIRROR**: `README.md:1-384` - hierarchical structure with code blocks
- **MIRROR**: `AGENT.md:108-128` - MCP configuration patterns
- **GOTCHA**: Python MCP SDK requires 3.10+; document this clearly
- **GOTCHA**: STDIO servers must never use print() - use logging to stderr
- **VALIDATE**: All code blocks have syntax highlighting, all links work

### Task 3: CREATE `examples/README.md` - Examples Overview

- **ACTION**: CREATE directory overview and usage guide
- **IMPLEMENT**:
  - List all example files with descriptions
  - Quick-start instructions
  - Prerequisites for running examples
  - Links back to CONTRIBUTING.md for context
- **MIRROR**: `README.md:18-34` - repository structure format
- **VALIDATE**: File renders correctly on GitHub

### Task 4: CREATE `examples/mcp-configs/claude.json` - Claude Desktop Config

- **ACTION**: CREATE ready-to-use Claude Desktop configuration
- **IMPLEMENT**:
  - Full mcpServers configuration object
  - Comments explaining each field (JSON5 style or separate README)
  - Placeholder paths with clear instructions
- **MIRROR**: `README.md:176-189` - exact format used in existing docs
- **CONTENT**:
```json
{
  "mcpServers": {
    "mcp-opennutrition": {
      "command": "node",
      "args": ["/absolute/path/to/open-diet-data/mcp-opennutrition/build/index.js"]
    }
  }
}
```
- **VALIDATE**: JSON is valid, no syntax errors

### Task 5: CREATE `examples/mcp-configs/vscode.json` - VS Code/Cline Config

- **ACTION**: CREATE VS Code MCP configuration
- **IMPLEMENT**:
  - Configuration for .vscode/mcp.json format
  - Relative path version (works from workspace root)
- **MIRROR**: `README.md:191-202` - VS Code config format
- **VALIDATE**: JSON is valid

### Task 6: CREATE `examples/langgraph_agent.py` - LangGraph Agent Example

- **ACTION**: CREATE working LangGraph agent with MCP tools
- **IMPLEMENT**:
  - Docstring header with usage examples (MIRROR scripts/query-nih-dsld.py:1-16)
  - Import langchain-mcp-adapters
  - MultiServerMCPClient configuration
  - create_react_agent with loaded tools
  - Example invocation with nutritional query
  - Async main function with proper cleanup
- **MIRROR**: `scripts/query-nih-dsld.py:1-220` - CLI script structure
- **GOTCHA**: Must use absolute path for MCP server
- **GOTCHA**: Client requires async context manager
- **CONTENT STRUCTURE**:
```python
#!/usr/bin/env python3
"""
LangGraph Agent with OpenNutrition MCP Tools
=============================================================================
Example agent using LangGraph and langchain-mcp-adapters to query nutrition data.

Requirements:
    pip install langchain-mcp-adapters langchain-anthropic langgraph

Usage:
    export ANTHROPIC_API_KEY='your-key'
    python examples/langgraph_agent.py "Find foods high in iron"
=============================================================================
"""
```
- **VALIDATE**: `python -m py_compile examples/langgraph_agent.py`

### Task 7: CREATE `examples/langchain_tool.py` - LangChain Tool Wrapper

- **ACTION**: CREATE direct Python tool wrapper using @tool decorator
- **IMPLEMENT**:
  - Docstring header with usage examples
  - Direct database access option (SQLite query)
  - HTTP subprocess option (spawn MCP server, communicate via stdio)
  - Example usage with LangChain agent
- **MIRROR**: `scripts/generate-embeddings.py:78-131` - function patterns with try/except
- **GOTCHA**: For direct DB access, must handle JSON column deserialization
- **CONTENT STRUCTURE**:
```python
#!/usr/bin/env python3
"""
LangChain Custom Tool for Nutrition Data
=============================================================================
Wraps nutrition database as a LangChain tool for direct agent integration.

Two approaches:
1. Direct SQLite access (no MCP server required)
2. MCP subprocess communication

Requirements:
    pip install langchain langchain-anthropic

Usage:
    from langchain_tool import search_nutrition_tool
    # Use with any LangChain agent
=============================================================================
"""
```
- **VALIDATE**: `python -m py_compile examples/langchain_tool.py`

### Task 8: CREATE `examples/requirements.txt` - Python Dependencies

- **ACTION**: CREATE requirements file for examples
- **IMPLEMENT**:
  - Pin versions for reproducibility
  - Include all dependencies for all examples
  - Add comments explaining which example needs which dep
- **MIRROR**: `usda-fdc-data/requirements.txt:1-5` - pinned version format
- **CONTENT**:
```
# LangGraph agent example
langchain-mcp-adapters>=0.1.0
langchain-anthropic>=0.3.0
langgraph>=0.2.0

# LangChain tool example
langchain>=0.3.0

# Direct SQLite access (langchain_tool.py)
# No additional dependencies - uses stdlib sqlite3
```
- **VALIDATE**: `pip install --dry-run -r examples/requirements.txt` (no errors)

---

## Testing Strategy

### Manual Verification Checklist

| Example File | Verification Steps |
| --- | --- |
| `examples/langgraph_agent.py` | 1. Syntax check passes 2. Imports resolve 3. Docstring complete |
| `examples/langchain_tool.py` | 1. Syntax check passes 2. Imports resolve 3. Both approaches documented |
| `examples/mcp-configs/*.json` | 1. Valid JSON 2. Correct structure for target app |
| `CONTRIBUTING.md` | 1. All internal links work 2. Code blocks render 3. TOC matches content |
| `README.md` | 1. New section integrates seamlessly 2. Links to CONTRIBUTING.md work |

### Edge Cases Checklist

- [ ] Python 3.8/3.9 users see clear error about 3.10+ requirement for LangGraph
- [ ] MCP server path placeholder is clearly marked as requiring modification
- [ ] Missing ANTHROPIC_API_KEY shows helpful error message in examples
- [ ] Examples work without building MCP server first (with clear error)
- [ ] Relative vs absolute path usage is clear in each config

---

## Validation Commands

### Level 1: STATIC_ANALYSIS

```bash
# Markdown lint (if available)
npx markdownlint-cli2 README.md CONTRIBUTING.md examples/README.md

# Python syntax check
python -m py_compile examples/langgraph_agent.py
python -m py_compile examples/langchain_tool.py

# JSON validation
python -c "import json; json.load(open('examples/mcp-configs/claude.json'))"
python -c "import json; json.load(open('examples/mcp-configs/vscode.json'))"
```

**EXPECT**: Exit 0, no syntax errors

### Level 2: LINK_VERIFICATION

```bash
# Check internal links in markdown files
grep -oE '\[.*\]\(\.\/[^)]+\)' README.md CONTRIBUTING.md | while read link; do
  path=$(echo "$link" | grep -oE '\./[^)#]+' | head -1)
  [ -f "$path" ] || echo "BROKEN: $path"
done
```

**EXPECT**: No "BROKEN" output

### Level 3: DEPENDENCY_CHECK

```bash
# Verify example dependencies are installable
pip install --dry-run -r examples/requirements.txt
```

**EXPECT**: No package resolution errors

### Level 6: MANUAL_VALIDATION

1. Open README.md in GitHub preview - verify new section renders correctly
2. Navigate CONTRIBUTING.md TOC links - all should jump to correct sections
3. Copy Claude config to actual Claude Desktop - verify format is accepted
4. Run `python examples/langgraph_agent.py --help` (after deps installed) - should show usage

---

## Acceptance Criteria

- [ ] README.md contains "Building Nutritional Agents" section with pathway table
- [ ] CONTRIBUTING.md exists with MCP, LangGraph, and Python tool sections
- [ ] All example files have proper docstring headers following project patterns
- [ ] MCP config examples are valid JSON and match documented formats
- [ ] Python examples pass syntax validation
- [ ] Internal markdown links resolve correctly
- [ ] Python 3.10+ requirement is clearly documented for LangGraph examples
- [ ] No regressions in existing README sections

---

## Completion Checklist

- [ ] All tasks completed in dependency order
- [ ] Each task validated immediately after completion
- [ ] Level 1: Static analysis passes
- [ ] Level 2: Link verification passes
- [ ] Level 3: Dependency check passes
- [ ] Level 6: Manual validation passes
- [ ] All acceptance criteria met

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Python version confusion (3.8 vs 3.10) | HIGH | MEDIUM | Clear callout boxes in CONTRIBUTING.md with version requirements per feature |
| MCP server not built before running examples | HIGH | LOW | Examples include clear prerequisites and error messages |
| langchain-mcp-adapters API changes | MEDIUM | MEDIUM | Pin versions in requirements.txt, document tested version |
| Absolute path confusion in MCP configs | MEDIUM | LOW | Include both relative and absolute path examples with explanations |
| Examples become outdated | MEDIUM | MEDIUM | Keep examples minimal; link to official docs for advanced usage |

---

## Notes

### Design Decisions

1. **Three Pathways**: Covers the most common integration scenarios without overwhelming developers
2. **TypeScript MCP Only**: Python MCP SDK requires 3.10+, which conflicts with project's 3.8+ target; documented as future enhancement
3. **Examples as Documentation**: Examples are illustrative, not production-ready; keeps maintenance burden low
4. **No Tests for Examples**: Examples are documentation; testing would require mocking MCP server

### Future Enhancements

1. **Python MCP Server**: When project upgrades to Python 3.10+, add Python MCP server example
2. **Docker Compose**: Add containerized example with MCP server + agent
3. **RAG Integration**: Add example combining embeddings with LangGraph agent
4. **Streaming Responses**: Add streaming example for real-time nutrition queries

### Key External Documentation

- MCP Protocol: https://modelcontextprotocol.io/docs
- LangChain MCP Adapters: https://github.com/langchain-ai/langchain-mcp-adapters
- LangGraph: https://langchain-ai.github.io/langgraph/
