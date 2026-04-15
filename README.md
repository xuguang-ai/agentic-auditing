# agentic-auditing

MCP server + skills for auditing XBRL numeric facts in SEC-style filings.

## Auditing MCP

A FastMCP server at `src/auditmcp.py` exposes five semantic primitives that
Claude Code (or any MCP-capable agent) can use to audit a single XBRL fact
without writing inline XML-parsing code. See
[docs/superpowers/specs/2026-04-12-auditing-mcp-design.md](docs/superpowers/specs/2026-04-12-auditing-mcp-design.md)
for the design rationale.

### Launch

```bash
AUDITMCP_DATA_ROOT=/absolute/path/to/data/auditing \
  uv run src/auditmcp.py
```

### Tools

| Tool | Purpose |
|---|---|
| `find_filing(ticker, filing_name, issue_time)` | Resolve filing folder + the six XBRL files |
| `get_facts(filing_path, concept_id, period)` | Period-filtered facts for a concept |
| `get_calculation_network(filing_path, concept_id)` | Concept's role as parent/child in the calculation linkbase |
| `get_concept_metadata(filing_path, concept_id, taxonomy_year)` | Balance type, period type, directional hint |
| `write_audit_result(...)` | Write single-line JSON result with the canonical filename |

### Dev

```bash
uv sync --extra dev
uv run pytest -v
```

### Smoke test

After launching the MCP against `data/auditing`, ask Claude Code to audit
`10k-aep-20211231` for a known concept and compare the emitted JSON to
`results/auditing/claude-code_auditing_10k_aep_20211231_demo_1_*.json`.

## Skills

- [`auditing/SKILL.md`](auditing/SKILL.md) — audit workflow (will be updated in a
  follow-up to call the MCP tools instead of writing inline Python)
- Other skills: `trading/`, `pair_trading/`, `report_generation/`, `report_evaluation/`