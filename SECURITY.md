# Security Policy

## Supported Versions

`shrine-diet-bioactivity` is pre-1.0. Security fixes are only backported to
the `main` branch and the most recent release tag. Older tags are not
maintained.

| Version | Supported |
|---|---|
| `main` (HEAD) | ✅ |
| Latest release tag | ✅ |
| Older tags | ❌ |

## Reporting a Vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately via one of these channels:

- **GitHub Security Advisories** (preferred):
  https://github.com/Syntropy-Health/shrine-diet-bioactivity/security/advisories/new
- **Email**: `security@syntropyhealth.bio`

Include:

1. A description of the issue and the impact
2. Steps to reproduce (or a proof-of-concept)
3. Affected versions / commit SHA
4. Your contact info (for follow-up questions)
5. Optional: your preferred disclosure timeline

## What to Expect

- **Acknowledgement**: within 72 hours of report
- **Triage + severity assessment**: within 7 days
- **Fix or mitigation timeline**:
  - Critical (RCE, auth bypass, data exfiltration): target ≤ 14 days
  - High: target ≤ 30 days
  - Medium / Low: target ≤ 90 days
- **Coordinated disclosure**: we prefer a 90-day window from report to public
  disclosure, extensible by mutual agreement
- **Credit**: we will credit reporters in the release notes unless you
  request anonymity

## Scope

### In Scope

- The `shrine-diet-bioactivity` MCP server and thin-adapter code
- The data ingestion scripts in `scripts/`
- The LightRAG integration layer (our wrapper, not upstream LightRAG itself)
- CI/CD workflows defined in `.github/workflows/`
- Dependency pinning and supply-chain concerns in our `package.json` /
  `pyproject.toml`

### Out of Scope

- Upstream vulnerabilities in submodule code (`lightrag/`, `graphiti/`,
  `mcp-opennutrition/`) — report to those projects directly; we'll update
  our pin when they ship a fix
- Issues in the integrated public datasets themselves (USDA, NIH, FooDB,
  CTD, TTD, etc.)
- Vulnerabilities in the user's self-hosted deployment infrastructure
  (Neo4j, Ollama, reverse proxies, container runtime)
- Social engineering or physical attacks

## Sensitive-Data Handling

This repository does not commit live credentials. If you find any such leak
in git history, report it via the channels above — do not publish the
finding. We will rotate affected credentials before any disclosure.

Template files (`.env.example`, `config_*.env`) use `${VAR}` references or
clearly-marked demo values (e.g., `NEO4J_PASSWORD=demodemo` for local
Docker). These are intentionally tracked; they are not considered secrets.

## Dependency Security

- CI runs `npm audit --audit-level=high` on every PR
- CI runs `pip-audit` on every PR
- Dependabot is configured for weekly updates on high-severity advisories
- We pin major + minor versions; patch-level updates via lockfile renewals

## Responsible Use

The MCP tools return biochemical and dietary-science context. The output
is **not medical advice** and must not be the sole basis for clinical
decisions. If your integration surfaces this data to end users, ensure
you have an appropriate "not medical advice" disclosure in place.

---

*Last updated: 2026-04-20*
