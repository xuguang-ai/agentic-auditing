# Auditing MCP Design — Claude Code Skill Accelerator

**Date:** 2026-04-12
**Status:** Spec — awaiting user review before plan

## Purpose

Replace the "write inline Python to parse XBRL XML" part of
[`auditing/SKILL.md`](../../../auditing/SKILL.md) with a small set of typed MCP
tools. The goal is to let Claude Code (or any MCP-capable agent) audit a single
XBRL numeric fact faster and with fewer XML-parsing mistakes, while keeping the
Case A/B/C/D reasoning in the agent.

**This is not a benchmarking MCP**, and **not an end-to-end `audit_concept`
tool.** The MCP exposes *semantic primitives* — clean, typed access to the
information the skill already requires, with period filtering and locator
resolution handled once in Python instead of re-derived by the agent each time.

## Non-Goals

- Do not perform Case A/B/C/D selection or arithmetic inside tools. The agent
  decides which case applies and computes the `calculated_value`.
- Do not summarize or LLM-interpret XBRL data (unlike `finmcp.py`). Auditing
  requires numeric precision; LLM summarization would destroy it.
- Do not introduce heavy XBRL libraries (Arelle, etc.). Standard-library
  `xml.etree.ElementTree` is sufficient and matches the skill's "short Python
  script" ethos.
- Do not persist cache to disk. XBRL files are local; in-process `lru_cache`
  is the right tier.

## Architecture

- **Server:** FastMCP, stdio transport.
- **Entry point:** `src/auditmcp.py` with `mcp.run()` at the bottom.
- **Launch:** `AUDITMCP_DATA_ROOT=<abs path> uv run src/auditmcp.py`.
- **Data root layout (convention — unchanged from existing repo):**
  ```
  $AUDITMCP_DATA_ROOT/
    XBRL/{filing_name}-{ticker}-{issue_time}/*.{xml,xsd,htm}
    US_GAAP_Taxonomy/gaap_chunks_{year}/{chunks_core.jsonl, chunks_relations.jsonl, meta.json}
  ```
- **Dependencies:** `fastmcp`, `pydantic`. Optional: `logfire` (parity with
  `finmcp.py`; wrap in try/except so it is optional).
- **Caching:** each parser (`_parse_instance`, `_parse_cal`, `_parse_xsd`,
  `_load_taxonomy_core`) decorated with `@functools.lru_cache(maxsize=32)`.
  Keys are absolute paths (or `taxonomy_year`). The decorators are internal;
  tool signatures do not expose cache behavior.
- **Logging:** `logfire.instrument_mcp()` if logfire is installed, else no-op.

## Tool Contracts

All tools return pydantic models; FastMCP serializes them to JSON.

### `find_filing(ticker, filing_name, issue_time) -> FilingLocation`

Locate the filing folder under `$AUDITMCP_DATA_ROOT/XBRL/`.

```python
class FilingLocation(BaseModel):
    filing_path: str            # absolute path; "" if not found
    filing_year: int            # derived from issue_time (int(issue_time[:4])); 0 if not found
    files: dict[str, str]       # keys: "htm", "cal", "xsd", "def", "lab", "pre"; absolute paths
    found: bool
    message: str                # "" on success; diagnostic otherwise
```

**Resolution rules:**
- Folder name: `f"{filing_name}-{ticker}-{issue_time}"`, case-sensitive lowercase as the skill specifies.
- For each pattern `*_htm.xml`, `*_cal.xml`, `*_def.xml`, `*_lab.xml`,
  `*_pre.xml`, pick the unique match. For `*.xsd`, pick the unique non-generated schema.
- If the folder is missing: `found=false`, `message="folder not found: <path>"`.
- If a required file pattern has zero or multiple matches: `found=false`,
  `message` names the offending pattern.
- Ambiguity (multiple folders match) is **not possible** given the folder
  template is exact — but if the canonical folder is missing and similar ones
  exist, list nearest neighbors in `message` for debugging.

### `get_facts(filing_path, concept_id, period) -> FactsResult`

Extract all numeric facts of `concept_id` whose resolved period matches `period`.

```python
class Fact(BaseModel):
    value: str                  # exact string as it appears in the XML (may be negative, may have decimals)
    context_ref: str
    period_type: Literal["instant", "duration"]
    period: str                 # canonical: "YYYY-MM-DD" (instant) or "YYYY-MM-DD/YYYY-MM-DD" (duration)
    dimensions: dict[str, str]  # {} if non-dimensional; otherwise {axis_qname: member_qname}
    unit_ref: Optional[str]
    decimals: Optional[str]

class FactsResult(BaseModel):
    concept_id: str             # normalized to colon form, e.g. "us-gaap:AssetsCurrent"
    requested_period: str       # echoed back
    requested_period_canonical: str  # the parsed canonical form used for matching
    matched: list[Fact]         # period-filtered candidates, ranked per Step 2 of SKILL.md
    all_periods_found: list[str]  # all distinct canonical periods for this concept (for miss diagnostics)
```

**Concept matching:**
- Normalize `concept_id`: accept `us-gaap:X` or `us-gaap_X`, treat as equivalent.
- Match by local name (strip namespace prefix) in the instance document.

**Period parsing (`period` input grammar):**
- `YYYY-MM-DD` → instant.
- `YYYY-MM-DD to YYYY-MM-DD` → duration (inclusive; canonical uses slash).
- `FYYYYY` → duration. Canonical calendar-year assumption: `YYYY-01-01/YYYY-12-31`.
  **Known limitation:** non-December fiscal years are not inferred. If the
  filing's fiscal year ends on a different date, agent must pass an explicit
  `YYYY-MM-DD to YYYY-MM-DD` range. This is documented and raises no error.
- `QN YYYY` where `N ∈ {1..4}` → duration for that calendar quarter.
- Any other format → `ValueError` with a message listing accepted formats.

**Matching:** exact equality on canonical period form. No fuzzy/nearest matching.

**Ranking within `matched`** (SKILL.md Step 2, applied in order):
1. Exact concept match (all entries satisfy this by construction).
2. Exact period match (all entries satisfy this by construction).
3. Non-dimensional before dimensional (`len(dimensions) == 0` ranks higher).
4. Numeric-parseable value before non-numeric (guard against text facts).

### `get_calculation_network(filing_path, concept_id) -> CalculationNetwork`

Parse `*_cal.xml` once, return the target concept's role as parent and/or child.

```python
class CalChild(BaseModel):
    concept: str            # colon-normalized
    weight: float
    order: Optional[float]

class ParentRole(BaseModel):
    role: str               # xlink:role URI of the enclosing calculationLink
    children: list[CalChild]

class ChildRole(BaseModel):
    role: str
    parent: str             # colon-normalized
    siblings: list[CalChild]  # includes every child of `parent` under `role`,
                              #   including the target concept itself (so own_weight is available)

class CalculationNetwork(BaseModel):
    concept_id: str
    as_parent: list[ParentRole]   # Case A candidate roles
    as_child: list[ChildRole]     # Case C candidate roles
    is_isolated: bool             # true iff as_parent == [] and as_child == [] (Case D hint)
    roles_scanned: list[str]      # all calculationLink roles found in the file (diagnostic)
```

**Resolution:**
- Build locator table per `calculationLink` (role-scoped, not global —
  calculation linkbases can have the same label in different roles).
- Each arc's `xlink:from`/`xlink:to` labels resolve to concept names via
  `xlink:href` fragments (`...#us-gaap_Foo` → `us-gaap:Foo`).
- Arc direction: `from` = parent (sum), `to` = child (component). Documented
  in the skill and mirrored here to avoid confusion.
- Missing `order` → `None` (preserve ordering by document order as a fallback,
  but do not fabricate an order value).

### `get_concept_metadata(filing_path, concept_id, taxonomy_year) -> ConceptMetadata`

Look up balance type, period type, and label for a concept.

```python
class ConceptMetadata(BaseModel):
    concept_id: str
    balance: Literal["debit", "credit", "none", "unknown"]
    period_type: Literal["instant", "duration", "unknown"]
    label: Optional[str]
    source: Literal["xsd", "taxonomy", "not_found"]
    is_directional_hint: bool   # heuristic; NOT authoritative — see below
```

**Lookup order:**
1. Filing's `*.xsd` (extension schema): if concept has an element with
   `xbrli:balance` / `xbrli:periodType`, use those. `source="xsd"`.
2. Else, `gaap_chunks_{taxonomy_year}/chunks_core.jsonl`: one JSON object per
   line, look up by concept name. `source="taxonomy"`.
3. Else, `source="not_found"`, all fields fall back to `unknown`/`None`.

**`is_directional_hint`:** true iff the concept's label or local name contains
any of `{expense, expenses, loss, losses, impairment, depreciation, amortization,
deduction, contra, writedown, writeoff}` AND balance is `debit`, **OR** the
name/label indicates a contra-account and balance is `credit`. This is a *hint*;
the agent makes the final Case B determination. Documented explicitly in the
return type description so the agent knows not to trust it blindly.

### `write_audit_result(output_dir, agent_name, filing_name, ticker, issue_time, id, model, extracted_value, calculated_value) -> WriteResult`

Write the final single-line JSON output per SKILL.md's format rules.

```python
class WriteResult(BaseModel):
    output_path: str
    bytes_written: int
```

**Filename template:**
```
{output_dir}/{agent_name}_auditing_{filing_name}_{ticker}_{issue_time}_{id}_{sanitized_model}.json
```

- `sanitized_model`: replace any character not in `[A-Za-z0-9._-]` with `-`.
- `extracted_value` / `calculated_value`: written verbatim as strings — no
  reformatting, no rounding, no numeric conversion. `"0"` sentinel preserved.
- File content: exactly one line `{"extracted_value": "...", "calculated_value": "..."}\n`.
- If file exists, **overwrite** (matches SKILL.md "Write the file once").
- Creates `output_dir` if missing (`mkdir -p` semantics).

## Typical Call Sequence

For a request like the SKILL.md example (audit `us-gaap:AdjustmentsRelatedToTaxWithholdingForShareBasedCompensation`
for `FY2023` in `10k-rrr-20231231`):

1. Agent parses request → pulls `ticker=rrr`, `filing_name=10k`, `issue_time=20231231`,
   `concept_id=...`, `period=FY2023`, `id=mr_1`.
2. `find_filing("rrr", "10k", "20231231")` → `FilingLocation`. Agent reads
   `filing_path` and `filing_year=2023`.
3. `get_facts(filing_path, concept_id, "FY2023")` → `FactsResult`. Agent
   picks the top-ranked `matched` fact → `extracted_value`.
4. `get_calculation_network(filing_path, concept_id)` → inspects
   `as_parent`/`as_child`/`is_isolated` to decide Case A / C / D.
5. `get_concept_metadata(filing_path, concept_id, 2023)` → inspects
   `balance` and `is_directional_hint` to decide whether Case B applies.
6. Agent performs the arithmetic in its head (with the structured data above
   it does not need to re-parse XML):
   - Case A: for each `ParentRole.children`, call `get_facts(...)` for each
     child, compute `sum(weight × value)`. Note partial if any child fact
     is missing.
   - Case B: `calculated_value = abs(extracted_value)` (or `abs` of the Case
     A sum if both apply).
   - Case C: fetch parent + sibling facts via `get_facts`, solve algebraically.
   - Case D: `calculated_value = extracted_value`.
7. `write_audit_result(...)` → writes the final JSON.

## Ambiguity Handling

Ambiguity surfaces in **returned data**, never as exceptions (except
unparseable input):

| Situation | Surfaces in |
|---|---|
| Concept appears in multiple calculation roles as parent | `CalculationNetwork.as_parent` has multiple entries; agent decides |
| Multiple facts match period (dimensional + non-dimensional) | `FactsResult.matched` ranked, agent inspects top-k |
| Fact not found for requested period | `FactsResult.matched == []`; `all_periods_found` helps agent diagnose |
| Balance type not in xsd and not in taxonomy | `ConceptMetadata.source="not_found"`, fields `unknown` |
| Non-December fiscal year with `FYYYYY` period | Documented limitation — agent passes explicit date range |
| `cal.xml` missing entirely | `find_filing` rejects with `found=false` (cal.xml is required). If an agent constructs a `filing_path` without a cal.xml and calls `get_calculation_network` anyway, the tool raises `FileNotFoundError`. |

**What is an error (raises):**
- `AUDITMCP_DATA_ROOT` not set → startup error.
- `filing_path` from caller does not exist → `FileNotFoundError`.
- Unparseable `period` string → `ValueError` with accepted-formats message.
- Malformed XML → propagated from `ElementTree`.

Errors are raised as exceptions (FastMCP wraps them into tool-error responses).
We do not return "soft" error objects for truly unrecoverable cases — that
blurs the failure signal.

## Project Structure

```
/Users/xai/Desktop/agentic-auditing/
├── src/
│   ├── __init__.py
│   └── auditmcp.py              # FastMCP server; ~400-500 lines
├── tests/
│   ├── __init__.py
│   ├── test_find_filing.py
│   ├── test_get_facts.py
│   ├── test_get_calculation_network.py
│   ├── test_get_concept_metadata.py
│   ├── test_write_audit_result.py
│   └── fixtures/                 # tiny hand-crafted XBRL fragments (not real filings)
│       ├── mini_htm.xml
│       ├── mini_cal.xml
│       ├── mini.xsd
│       └── mini_chunks_core.jsonl
├── pyproject.toml                # new: declare fastmcp, pydantic, pytest, logfire(optional)
├── auditing/SKILL.md             # unchanged (update in a follow-up PR; this spec is MCP-only)
├── data/auditing/                # unchanged
└── docs/superpowers/specs/2026-04-12-auditing-mcp-design.md
```

**Internal module layout inside `auditmcp.py`** (single file is fine at this size):

```
# --- imports, env, logfire, FastMCP init ---
# --- pydantic return models ---
# --- helpers: concept normalization, period parsing ---
# --- parsers (cached): _parse_instance, _parse_cal, _parse_xsd, _load_taxonomy_core ---
# --- tool 1: find_filing ---
# --- tool 2: get_facts ---
# --- tool 3: get_calculation_network ---
# --- tool 4: get_concept_metadata ---
# --- tool 5: write_audit_result ---
# --- if __name__ == "__main__": mcp.run() ---
```

If the parsers grow past ~150 lines each, split into `src/parsers.py`. Premature
splitting is not required.

## Testing Strategy

All tests run against hand-crafted XBRL fixtures under `tests/fixtures/` — not
real filings — so they are fast, deterministic, and do not depend on the
user's local data. Real-filing smoke tests are a *separate* manual check, not
part of the automated suite.

**Unit coverage:**

- `find_filing`: folder present / absent / partial file set.
- Concept-id normalization: `us-gaap:X` and `us-gaap_X` are equivalent.
- Period parsing: `FY2023`, `Q2 2022`, `2023-12-31`, `2023-01-01 to 2023-12-31`,
  invalid formats raise `ValueError`.
- `get_facts`: single match, multi-match with ranking, dimensional vs
  non-dimensional, period-not-found surfaces `all_periods_found`.
- `get_calculation_network`: concept as parent (single + multi-role), as
  child, isolated (no relationships), missing `cal.xml`.
- `get_concept_metadata`: xsd hit, taxonomy fallback, not found,
  `is_directional_hint` heuristic across a handful of labels.
- `write_audit_result`: filename template correct, model-string sanitization,
  overwrite, directory auto-create, values preserved verbatim.

**Manual smoke test** (documented in README, not automated):
Point `AUDITMCP_DATA_ROOT` at `data/auditing`, launch the MCP, have Claude
Code audit `10k-aep-20211231` for a known concept, compare JSON output to
the existing `results/auditing/claude-code_auditing_10k_aep_20211231_demo_1_*.json`.

## Open Questions / Risks

- **Fiscal-year inference**: We punt on non-December fiscal years. If too
  many filings in the dataset have shifted fiscal years, we will need to read
  the `dei:DocumentFiscalYearFocus` + `dei:CurrentFiscalYearEndDate` from the
  instance document and use them to interpret `FYYYYY`. Defer to v2.
- **`DocumentPeriodEndDate` fact as a cross-check**: we do not currently
  return or use it. If period-matching bugs surface, consider adding it to
  `FilingLocation` as a convenience.
- **`chunks_relations.jsonl`**: not used in v1. If agents need taxonomy-level
  parent/child relationships (e.g., to sanity-check an isolated filing concept
  against the taxonomy), add a `get_taxonomy_relations` tool in v2.
- **SKILL.md update**: this spec does not modify `auditing/SKILL.md`. Once the
  MCP lands, a follow-up should rewrite the "Implementation approach" section
  of SKILL.md to instruct agents to use these tools instead of writing inline
  Python.
