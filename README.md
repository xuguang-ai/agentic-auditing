# agentic-auditing

MCP server + skill for auditing XBRL numeric facts in SEC-style filings.

The server (`src/auditmcp.py`) exposes five primitives that any MCP-capable
agent (Claude Code, Cursor, Continue, …) calls instead of writing inline
XML-parsing code. The skill at [`auditing/SKILL.md`](auditing/SKILL.md)
orchestrates those primitives into a single-fact audit workflow.

---

## Quick start

### 1. Install

Requires Python ≥ 3.11.

```bash
uv sync                     # runtime deps: fastmcp, pydantic
uv sync --extra dev         # + pytest
uv sync --extra logfire     # + optional logfire telemetry
```

### 2. Lay out your data

The server reads from a single root pointed to by the `AUDITMCP_DATA_ROOT`
environment variable. Inside that root it expects:

```
$AUDITMCP_DATA_ROOT/
├── XBRL/
│   └── {filing_name}-{ticker}-{issue_time}/      # e.g. 10k-rdvt-20211231/
│       ├── *_htm.xml      # instance document  (REQUIRED)
│       ├── *_cal.xml      # calculation linkbase (REQUIRED)
│       ├── *.xsd          # extension schema   (REQUIRED)
│       ├── *_def.xml      # definition linkbase
│       ├── *_lab.xml      # label linkbase
│       └── *_pre.xml      # presentation linkbase
└── US_GAAP_Taxonomy/
    └── gaap_chunks_{year}/                      # year derived from issue_time
        └── chunks_core.jsonl                    # one concept per line
```

Naming rules `find_filing` enforces:

- Folder name is exactly `{filing_name}-{ticker}-{issue_time}` — all
  lowercase; `issue_time` in `YYYYMMDD` form.
- All six XBRL files must be present and unique within the folder.
- The extension `.xsd` is the one whose stem has no underscore (so
  `rdvt-20211231.xsd` wins over `rdvt-20211231_pre.xsd` etc.).

### 3. Wire it into your MCP client

For Claude Code, drop a `.mcp.json` at your project root:

```json
{
  "mcpServers": {
    "auditmcp": {
      "command": "uv",
      "args": ["run", "--directory", "/abs/path/to/agentic-auditing",
               "python", "src/auditmcp.py"],
      "env": {
        "AUDITMCP_DATA_ROOT": "/abs/path/to/data/auditing"
      }
    }
  }
}
```

Restart the client; the five tools appear under the `auditmcp` namespace
(`mcp__auditmcp__find_filing`, etc.). To run the server directly without
a client:

```bash
AUDITMCP_DATA_ROOT=/abs/path/to/data/auditing uv run src/auditmcp.py
```

---

## Tools

All return Pydantic models (clients see structured JSON Schema). All paths
are absolute. `concept_id` accepts either colon (`us-gaap:Liabilities`) or
underscore (`us-gaap_Liabilities`) form — both normalize to the colon form
internally.

### `find_filing(ticker, filing_name, issue_time) → FilingLocation`

Resolves the filing folder under `$AUDITMCP_DATA_ROOT/XBRL/`.

| Field | Type | Notes |
|---|---|---|
| `filing_path` | `str` | Absolute folder path |
| `filing_year` | `int` | Derived from `issue_time[:4]` |
| `files` | `dict[str,str]` | Keys: `htm`, `cal`, `xsd`, `def`, `lab`, `pre` |
| `found` | `bool` | |
| `message` | `str` | Diagnostic when `found=false` |

### `get_facts(filing_path, concept_id, period) → FactsResult`

Returns numeric facts whose context period **exactly** matches `period`.
Period grammar:

| Form | Example | Resolves to |
|---|---|---|
| Instant | `2023-12-31` | instant context on that date |
| Explicit duration | `2023-01-01 to 2023-12-31` | duration context with these bounds |
| Calendar fiscal year | `FY2023` | `2023-01-01 to 2023-12-31` (non-Dec fiscal years must use the explicit form) |
| Calendar quarter | `Q3 2023` | `2023-07-01 to 2023-09-30` |

Facts are deduplicated on `(value, contextRef, dimensions, unit, decimals)`
— inline-XBRL flattening commonly emits the same fact twice when the
human-readable HTML reports the same number in two places. Facts that
share everything except `decimals` are kept separate (different precision
claims must be surfaced).

Result fields:

| Field | Notes |
|---|---|
| `matched` | List of facts; non-dimensional first |
| `all_periods_found` | Every distinct period this concept appears under — useful for diagnosing period misses |

### `get_calculation_network(filing_path, concept_id) → CalculationNetwork`

Walks the calculation linkbase. Locator labels are scoped per
`calculationLink` (per role) — locators with identical labels in
different roles do not bleed across.

| Field | Notes |
|---|---|
| `as_parent` | Roles where the concept is the summation parent, with weighted children — the input to **Case A** sums |
| `as_child` | Roles where it appears as a child, with the parent and full sibling list (own concept included) — the input to **Case C** algebraic derivation |
| `is_isolated` | `true` ⇒ no calculation relationships at all → **Case D** |
| `roles_scanned` | Every role URI seen, for diagnostics |

### `get_concept_metadata(filing_path, concept_id, taxonomy_year) → ConceptMetadata`

Looks up the concept's balance type, period type, and a Case B directional
hint. Resolution order:

1. The filing's extension `*.xsd` (handles company-specific concepts).
2. `chunks_core.jsonl` under `gaap_chunks_{taxonomy_year}/`.

| Field | Values | Notes |
|---|---|---|
| `balance` | `debit` / `credit` / `none` / `unknown` | `none` for non-monetary or abstract concepts |
| `period_type` | `instant` / `duration` / `unknown` | Sanity-check this against the period you're querying |
| `label` | `str?` | Human-readable concept label |
| `source` | `xsd` / `taxonomy` / `not_found` | |
| `is_directional_hint` | `bool` | Heuristic: `True` when balance + label suggest a Case B (loss/expense/contra-style concept that must be filed positive). Matches whole-word terms against `label + camel-split local_name` — e.g. `Decrease`/`Loss`/`Impairment`/`Withholding` with `balance=debit`, or `Treasury`/`Contra` with `balance=credit`. Excludes `IncreaseDecreaseInX` change-of-balance items and `AdjustmentsToReconcile*` summation parents. Label is always returned so the agent can make the final Case B call. |

### `write_audit_result(output_dir, agent_name, filing_name, ticker, issue_time, id, model, extracted_value, calculated_value) → WriteResult`

Writes a single-line JSON to:

```
{output_dir}/{agent_name}_auditing_{filing_name}_{ticker}_{issue_time}_{id}_{model}.json
```

The model name is sanitized (any character outside `[A-Za-z0-9._-]` becomes
`-`). Numeric values are written verbatim as strings. Overwrites if the
file already exists.

```json
{"extracted_value": "4947000", "calculated_value": "4947000"}
```

---

## Typical audit workflow

The skill at [`auditing/SKILL.md`](auditing/SKILL.md) drives this. For
auditing one fact:

```
1. find_filing(ticker, filing_name, issue_time)
       → filing_path

2. get_concept_metadata(filing_path, concept_id, taxonomy_year)
       → balance, period_type, is_directional_hint
                                    │
                                    ▼ guides which Case applies

3. get_facts(filing_path, concept_id, period)
       → matched[0] = extracted_value

4. get_calculation_network(filing_path, concept_id)
       → as_parent  → Case A (sum weighted children — call get_facts on each)
       → as_child   → Case C (parent − Σ siblings, then ÷ own_weight)
       → is_isolated → Case D
       (combine with Case B sign rule from step 2 if directional)

5. write_audit_result(..., extracted_value, calculated_value)
```

Audit results are written to `results/auditing/` (gitignored locally).

---

## Development

```bash
uv sync --extra dev
uv run pytest -v          # 50 tests, ~1s
```

Tests live in [`tests/`](tests/) with a self-contained mini filing under
[`tests/fixtures/mini-filing/`](tests/fixtures/mini-filing/) and a
production-shape `chunks_core.jsonl` excerpt under
[`tests/fixtures/gaap_chunks_2023/`](tests/fixtures/gaap_chunks_2023/).

---

## Ground truth

[`ground_truth/agentic_audit_with_answer.csv`](ground_truth/agentic_audit_with_answer.csv)
contains labelled audit cases for evaluation. Columns: `id`, `query`,
`filing_name`, `ticker`, `issue_time`, `usgaap_concept`, `period`, `gt_answer`.

---

## Skills

- [`auditing/SKILL.md`](auditing/SKILL.md) — XBRL audit workflow (uses the MCP)
