# Contributing to `shrine-diet-bioactivity`

Thank you for your interest in contributing. This project aggregates
phytochemical, nutritional, and bioactivity data into a unified knowledge
graph and exposes it via the Model Context Protocol (MCP). Contributions
that improve the KG, data pipeline, MCP tooling, or developer experience
are welcome.

## Quick Start

1. [Fork the repo](https://github.com/Syntropy-Health/shrine-diet-bioactivity/fork)
2. Clone your fork **with submodules**:
   ```bash
   git clone --recurse-submodules https://github.com/<you>/shrine-diet-bioactivity.git
   cd shrine-diet-bioactivity
   ```
3. Follow the setup instructions in [`README.md`](./README.md) and
   [`CLAUDE.md`](./CLAUDE.md) to install dependencies and load local data.
4. Create a feature branch: `git checkout -b feat/your-change`
5. Make changes, commit, and open a pull request against `main`.

## Before You Start

- **Open an issue first** for non-trivial changes. This saves everyone time
  if the idea is out of scope or duplicates in-flight work.
- Check the [`.claude/PRPs/plans/active/`](./.claude/PRPs/plans/active/)
  directory — some areas are actively being rewritten and PRs against them
  will be held until the active plan merges.
- Read [`SECURITY.md`](./SECURITY.md) before reporting a vulnerability.

## What We're Looking For

- **Data source integrations** — additional phytochemical, nutritional, or
  bioactivity datasets (with clear licensing)
- **KG quality improvements** — entity disambiguation, relation
  enrichment, ontology mapping fixes
- **MCP tool additions** — new tools that compose the existing KG queries
  in useful ways for clinical/research workflows
- **Tests** — we accept isolated test additions even without a code change
- **Docs** — setup guides, API docs, architecture diagrams, tutorials

## What We'll Likely Decline

- Breaking changes to the MCP tool contract without a migration plan
- New submodules (we prefer direct pip/npm dependencies where possible)
- PRs that skip tests or bypass CI
- Data source integrations without licensing documentation
- Clinical decision support features (the KG provides context; clinical
  reasoning belongs to the consuming agent, not this project)

## Development Workflow

### Branch Naming

- `feat/<short-name>` — new features
- `fix/<short-name>` — bug fixes
- `docs/<short-name>` — documentation
- `chore/<short-name>` — tooling, CI, refactoring
- `data/<source-name>` — data source additions or updates

### Commits

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description

Longer body explaining *why*, not *what* (the diff shows what).
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`, `data`.

### Pull Requests

- **One logical change per PR**. Split unrelated changes into separate PRs.
- **Keep PRs small**. Under 500 lines of diff is easy to review; over 1000
  usually means splitting would help.
- **Fill out the PR template** — it asks about test coverage, breaking
  changes, and data-source licensing.
- **CI must pass**. PRs with red CI won't be reviewed until green. See the
  badges in the README for what CI runs.
- **Respond to review comments** promptly. Stale PRs get closed after
  30 days of inactivity; reopen anytime.

## CI Checks

Every PR runs:

- **Lint** — ESLint (TypeScript) + Ruff (Python)
- **Type check** — `tsc --noEmit` + `mypy`
- **Unit tests** — vitest (TS) + pytest (Python)
- **Coverage** — report uploaded to the PR; regressions flagged
- **Security audit** — `npm audit` + `pip-audit`
- **Build** — produces distributable artifacts for the MCP server

All of these must be green before merge. See
[`.github/workflows/`](./.github/workflows/) for the source.

## Code Style

### TypeScript

- Prettier + ESLint defaults
- Prefer named exports over default exports
- Use `zod` schemas at MCP tool boundaries
- No `any` without a justifying comment

### Python

- PEP 8 via Ruff
- Type hints on all function signatures
- `pytest` with descriptive test names (`test_should_X_when_Y`)
- No `print` — use `logging`

### SQL / Cypher

- One statement per query file in `scripts/` / `cypher_queries/`
- Named parameters (never string interpolation)
- Comments explain *what the data represents*, not *what SQL does*

## Testing Standards

- **New features** require tests. PRs without new tests will be asked to
  add them.
- **Bug fixes** should include a regression test proving the bug is fixed.
- **Refactors** shouldn't change test coverage — if coverage drops,
  explain why in the PR description.
- **Integration tests** that hit Neo4j or LightRAG are allowed; mark them
  with `@pytest.mark.integration` or a vitest tag so CI can opt in.

## Data Source Contributions

Adding a new dataset? The PR must include:

1. **License documentation** — source URL, license text link, usage terms
2. **Ingestion script** in `scripts/` with a dry-run mode
3. **Entity mapping** — how the source entities map onto the unified
   ontology (Herb / Compound / Food / Target / Disease / Symptom)
4. **Manifest entry** in `manifest.yaml` with version pin + checksum
5. **Metrics report** showing node/edge counts and data quality flags
6. **Attribution** in `LICENSE` third-party section

## Code of Conduct

By participating, you agree to abide by the
[Contributor Covenant Code of Conduct](./CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under
the [MIT License](./LICENSE).

## Getting Help

- **Questions**: open a GitHub Discussion
- **Bug reports**: open an issue with the `bug` label and a reproduction
- **Feature ideas**: open an issue with the `enhancement` label
- **Security**: see [SECURITY.md](./SECURITY.md) — do not open public issues

Thank you for contributing!
