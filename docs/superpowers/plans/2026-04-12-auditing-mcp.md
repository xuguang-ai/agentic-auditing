# Auditing MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastMCP server (`src/auditmcp.py`) that exposes 5 semantic-primitive tools for XBRL fact auditing, so Claude Code can replace inline XML parsing in `auditing/SKILL.md` with typed tool calls.

**Architecture:** Single Python module, stdio MCP server, 5 tools (`find_filing`, `get_facts`, `get_calculation_network`, `get_concept_metadata`, `write_audit_result`). Stdlib `xml.etree.ElementTree` parses XBRL. `@functools.lru_cache` memoizes parsed trees by path. Data root comes from `AUDITMCP_DATA_ROOT` env var. Agent keeps Case A/B/C/D reasoning; MCP only handles mechanical extraction + period filtering + locator resolution + output formatting.

**Tech Stack:** Python ≥ 3.11, `fastmcp`, `pydantic` v2, `pytest` (dev), `uv` for dependency management. `logfire` optional.

**Spec:** [docs/superpowers/specs/2026-04-12-auditing-mcp-design.md](../specs/2026-04-12-auditing-mcp-design.md)

---

## File Structure

```
src/
  __init__.py                       # empty
  auditmcp.py                       # FastMCP server + tools (single file, ~500 LOC)
tests/
  __init__.py                       # empty
  conftest.py                       # fixture path helper
  fixtures/
    mini-filing/
      mini_htm.xml                  # hand-crafted instance with a handful of facts + contexts
      mini_cal.xml                  # cal linkbase with one parent-children network + multi-role concept
      mini.xsd                      # extension schema declaring balance + periodType for a few concepts
      mini_def.xml                  # minimal empty def linkbase (presence test only)
      mini_lab.xml                  # minimal empty lab linkbase
      mini_pre.xml                  # minimal empty pre linkbase
    gaap_chunks_2023/
      chunks_core.jsonl             # three taxonomy concept entries
  test_normalize_concept.py
  test_period_parsing.py
  test_find_filing.py
  test_get_facts.py
  test_get_calculation_network.py
  test_get_concept_metadata.py
  test_write_audit_result.py
pyproject.toml                      # new
README.md                           # append MCP launch instructions
```

**Internal layout of `src/auditmcp.py`**, top to bottom:
1. Imports + env-var read + optional logfire.
2. Pydantic return models.
3. Helper: `_normalize_concept`, `_to_underscore_form`, `_parse_period`.
4. Cached parsers: `_parse_instance`, `_parse_cal`, `_parse_xsd`, `_load_taxonomy_core`.
5. Five `@mcp.tool` functions.
6. `if __name__ == "__main__": mcp.run()`.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "agentic-auditing"
version = "0.1.0"
description = "MCP server for XBRL fact auditing"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=0.2.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
logfire = [
    "logfire>=0.40",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Create empty `src/__init__.py` and `tests/__init__.py`**

Both files contain a single newline.

- [ ] **Step 3: Create `tests/conftest.py`**

```python
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES

@pytest.fixture
def mini_filing_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "mini-filing"

@pytest.fixture
def taxonomy_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir
```

- [ ] **Step 4: Install dependencies**

Run: `uv sync --extra dev`
Expected: resolves fastmcp + pydantic + pytest, creates `.venv`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold auditing MCP project"
```

---

## Task 2: Test fixtures

**Files:**
- Create: `tests/fixtures/mini-filing/mini_htm.xml`
- Create: `tests/fixtures/mini-filing/mini_cal.xml`
- Create: `tests/fixtures/mini-filing/mini.xsd`
- Create: `tests/fixtures/mini-filing/mini_def.xml`
- Create: `tests/fixtures/mini-filing/mini_lab.xml`
- Create: `tests/fixtures/mini-filing/mini_pre.xml`
- Create: `tests/fixtures/gaap_chunks_2023/chunks_core.jsonl`

These fixtures model: a parent concept `Liabilities` = `Deposits` + `OtherLiabilities` (calc role), a directional concept `LossOnDisposal` filed as negative, and a concept `NonCalcItem` with no calc relationships.

- [ ] **Step 1: Create `mini_htm.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023"
      xmlns:dei="http://xbrl.sec.gov/dei/2023"
      xmlns:xlink="http://www.w3.org/1999/xlink">
  <context id="c_2023">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><startDate>2023-01-01</startDate><endDate>2023-12-31</endDate></period>
  </context>
  <context id="c_inst_20231231">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><instant>2023-12-31</instant></period>
  </context>
  <context id="c_inst_20221231">
    <entity><identifier scheme="http://www.sec.gov/CIK">0000000001</identifier></entity>
    <period><instant>2022-12-31</instant></period>
  </context>

  <us-gaap:Liabilities contextRef="c_inst_20231231" unitRef="usd" decimals="-3">1000000</us-gaap:Liabilities>
  <us-gaap:Deposits contextRef="c_inst_20231231" unitRef="usd" decimals="-3">600000</us-gaap:Deposits>
  <us-gaap:OtherLiabilities contextRef="c_inst_20231231" unitRef="usd" decimals="-3">400000</us-gaap:OtherLiabilities>

  <us-gaap:Liabilities contextRef="c_inst_20221231" unitRef="usd" decimals="-3">900000</us-gaap:Liabilities>

  <us-gaap:LossOnDisposal contextRef="c_2023" unitRef="usd" decimals="-3">-50000</us-gaap:LossOnDisposal>
  <us-gaap:NonCalcItem contextRef="c_2023" unitRef="usd" decimals="-3">12345</us-gaap:NonCalcItem>
</xbrl>
```

- [ ] **Step 2: Create `mini_cal.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:calculationLink xlink:type="extended"
                        xlink:role="http://example.com/role/BalanceSheet">
    <link:loc xlink:type="locator"
              xlink:label="loc_us-gaap_Liabilities"
              xlink:href="https://xbrl.fasb.org/us-gaap-2023.xsd#us-gaap_Liabilities"/>
    <link:loc xlink:type="locator"
              xlink:label="loc_us-gaap_Deposits"
              xlink:href="https://xbrl.fasb.org/us-gaap-2023.xsd#us-gaap_Deposits"/>
    <link:loc xlink:type="locator"
              xlink:label="loc_us-gaap_OtherLiabilities"
              xlink:href="https://xbrl.fasb.org/us-gaap-2023.xsd#us-gaap_OtherLiabilities"/>
    <link:calculationArc xlink:type="arc"
                         xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
                         xlink:from="loc_us-gaap_Liabilities"
                         xlink:to="loc_us-gaap_Deposits"
                         weight="1.0" order="1"/>
    <link:calculationArc xlink:type="arc"
                         xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
                         xlink:from="loc_us-gaap_Liabilities"
                         xlink:to="loc_us-gaap_OtherLiabilities"
                         weight="1.0" order="2"/>
  </link:calculationLink>
</link:linkbase>
```

- [ ] **Step 3: Create `mini.xsd`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:xbrli="http://www.xbrl.org/2003/instance"
           xmlns:us-gaap="http://fasb.org/us-gaap/2023"
           targetNamespace="http://example.com/ext">
  <xs:element name="Liabilities" xbrli:balance="credit" xbrli:periodType="instant" type="xs:decimal"/>
  <xs:element name="Deposits" xbrli:balance="credit" xbrli:periodType="instant" type="xs:decimal"/>
  <xs:element name="OtherLiabilities" xbrli:balance="credit" xbrli:periodType="instant" type="xs:decimal"/>
  <xs:element name="LossOnDisposal" xbrli:balance="debit" xbrli:periodType="duration" type="xs:decimal"/>
</xs:schema>
```

- [ ] **Step 4: Create the three linkbase stubs (`mini_def.xml`, `mini_lab.xml`, `mini_pre.xml`)**

Each file contains:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"/>
```

- [ ] **Step 5: Create `tests/fixtures/gaap_chunks_2023/chunks_core.jsonl`**

```jsonl
{"concept": "us-gaap:Liabilities", "balance": "credit", "period_type": "instant", "label": "Liabilities"}
{"concept": "us-gaap:LossOnDisposal", "balance": "debit", "period_type": "duration", "label": "Loss On Disposal Of Assets"}
{"concept": "us-gaap:NonCalcItem", "balance": "none", "period_type": "duration", "label": "Non Calc Item"}
```

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/
git commit -m "test: add hand-crafted XBRL fixtures for auditing MCP tests"
```

---

## Task 3: Concept ID normalization helper

**Files:**
- Create: `tests/test_normalize_concept.py`
- Modify: `src/auditmcp.py` (create new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_normalize_concept.py`:

```python
from src.auditmcp import _normalize_concept, _to_underscore_form

def test_colon_form_stays_colon():
    assert _normalize_concept("us-gaap:AssetsCurrent") == "us-gaap:AssetsCurrent"

def test_underscore_form_becomes_colon():
    assert _normalize_concept("us-gaap_AssetsCurrent") == "us-gaap:AssetsCurrent"

def test_already_bare_local_name_is_unchanged():
    # No prefix at all; we leave it alone.
    assert _normalize_concept("AssetsCurrent") == "AssetsCurrent"

def test_to_underscore_form():
    assert _to_underscore_form("us-gaap:AssetsCurrent") == "us-gaap_AssetsCurrent"
    assert _to_underscore_form("us-gaap_AssetsCurrent") == "us-gaap_AssetsCurrent"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_normalize_concept.py -v`
Expected: ImportError — `src/auditmcp.py` does not exist yet.

- [ ] **Step 3: Create `src/auditmcp.py` with the helpers**

```python
"""FastMCP server exposing XBRL auditing primitives."""
from __future__ import annotations


def _normalize_concept(concept_id: str) -> str:
    """Normalize a concept ID to `prefix:LocalName` form.

    Accepts `us-gaap_AssetsCurrent` (underscore form used in XBRL locator
    hrefs) or `us-gaap:AssetsCurrent` (QName form used in the instance
    document). Bare local names are returned unchanged.
    """
    if ":" in concept_id:
        return concept_id
    # Convert first underscore after prefix to a colon, but only if it looks
    # like a QName prefix (letters / digits / hyphens before the first '_').
    idx = concept_id.find("_")
    if idx <= 0:
        return concept_id
    prefix = concept_id[:idx]
    if not all(ch.isalnum() or ch == "-" for ch in prefix):
        return concept_id
    return f"{prefix}:{concept_id[idx + 1 :]}"


def _to_underscore_form(concept_id: str) -> str:
    """Return the `prefix_LocalName` form used in XBRL href fragments."""
    return _normalize_concept(concept_id).replace(":", "_", 1)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_normalize_concept.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_normalize_concept.py
git commit -m "feat: add concept ID normalization helpers"
```

---

## Task 4: Period parsing helper

**Files:**
- Create: `tests/test_period_parsing.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from src.auditmcp import _parse_period, ParsedPeriod

def test_instant_date():
    p = _parse_period("2023-12-31")
    assert p == ParsedPeriod(kind="instant", start="2023-12-31", end="2023-12-31")
    assert p.canonical == "2023-12-31"

def test_explicit_duration():
    p = _parse_period("2023-01-01 to 2023-12-31")
    assert p == ParsedPeriod(kind="duration", start="2023-01-01", end="2023-12-31")
    assert p.canonical == "2023-01-01/2023-12-31"

def test_fiscal_year_calendar():
    p = _parse_period("FY2023")
    assert p == ParsedPeriod(kind="duration", start="2023-01-01", end="2023-12-31")

@pytest.mark.parametrize("q,expected_start,expected_end", [
    ("Q1 2023", "2023-01-01", "2023-03-31"),
    ("Q2 2023", "2023-04-01", "2023-06-30"),
    ("Q3 2023", "2023-07-01", "2023-09-30"),
    ("Q4 2023", "2023-10-01", "2023-12-31"),
])
def test_quarters(q, expected_start, expected_end):
    p = _parse_period(q)
    assert p.kind == "duration"
    assert p.start == expected_start
    assert p.end == expected_end

def test_invalid_format_raises():
    with pytest.raises(ValueError) as exc:
        _parse_period("next quarter")
    assert "Accepted formats" in str(exc.value)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_period_parsing.py -v`
Expected: ImportError — `_parse_period`/`ParsedPeriod` not defined.

- [ ] **Step 3: Implement in `src/auditmcp.py`**

Add to `src/auditmcp.py` (below the existing helpers):

```python
import re
from calendar import monthrange
from dataclasses import dataclass
from typing import Literal

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})$")
_FY_RE = re.compile(r"^FY(\d{4})$")
_Q_RE = re.compile(r"^Q([1-4])\s+(\d{4})$")


@dataclass(frozen=True)
class ParsedPeriod:
    kind: Literal["instant", "duration"]
    start: str   # ISO date
    end: str     # ISO date; equal to start for instants

    @property
    def canonical(self) -> str:
        return self.start if self.kind == "instant" else f"{self.start}/{self.end}"


def _parse_period(period: str) -> ParsedPeriod:
    """Parse a user-supplied period string into a canonical ParsedPeriod.

    Accepted grammar:
      - `YYYY-MM-DD`              → instant
      - `YYYY-MM-DD to YYYY-MM-DD` → duration
      - `FYYYYY`                  → duration YYYY-01-01..YYYY-12-31 (calendar year; see spec)
      - `QN YYYY` with N in 1..4   → calendar-quarter duration
    """
    period = period.strip()
    if m := _DATE_RE.match(period):
        return ParsedPeriod(kind="instant", start=period, end=period)
    if m := _RANGE_RE.match(period):
        return ParsedPeriod(kind="duration", start=m.group(1), end=m.group(2))
    if m := _FY_RE.match(period):
        year = m.group(1)
        return ParsedPeriod(kind="duration", start=f"{year}-01-01", end=f"{year}-12-31")
    if m := _Q_RE.match(period):
        q = int(m.group(1))
        year = int(m.group(2))
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        end_day = monthrange(year, end_month)[1]
        return ParsedPeriod(
            kind="duration",
            start=f"{year:04d}-{start_month:02d}-01",
            end=f"{year:04d}-{end_month:02d}-{end_day:02d}",
        )
    raise ValueError(
        f"Unparseable period {period!r}. Accepted formats: "
        "'YYYY-MM-DD', 'YYYY-MM-DD to YYYY-MM-DD', 'FYYYYY', 'QN YYYY'."
    )
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `uv run pytest tests/test_period_parsing.py -v`
Expected: all pass (7 tests including the 4 parametrized quarter cases).

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_period_parsing.py
git commit -m "feat: add period string parser"
```

---

## Task 5: Pydantic return models

**Files:**
- Modify: `src/auditmcp.py` (append)

No tests — pydantic models are covered by tool-level tests.

- [ ] **Step 1: Append models to `src/auditmcp.py`**

```python
from typing import Optional
from pydantic import BaseModel, Field


class FilingLocation(BaseModel):
    filing_path: str = ""
    filing_year: int = 0
    files: dict[str, str] = Field(default_factory=dict)
    found: bool = False
    message: str = ""


class Fact(BaseModel):
    value: str
    context_ref: str
    period_type: Literal["instant", "duration"]
    period: str  # canonical
    dimensions: dict[str, str] = Field(default_factory=dict)
    unit_ref: Optional[str] = None
    decimals: Optional[str] = None


class FactsResult(BaseModel):
    concept_id: str
    requested_period: str
    requested_period_canonical: str
    matched: list[Fact]
    all_periods_found: list[str]


class CalChild(BaseModel):
    concept: str
    weight: float
    order: Optional[float] = None


class ParentRole(BaseModel):
    role: str
    children: list[CalChild]


class ChildRole(BaseModel):
    role: str
    parent: str
    siblings: list[CalChild]


class CalculationNetwork(BaseModel):
    concept_id: str
    as_parent: list[ParentRole]
    as_child: list[ChildRole]
    is_isolated: bool
    roles_scanned: list[str]


class ConceptMetadata(BaseModel):
    concept_id: str
    balance: Literal["debit", "credit", "none", "unknown"]
    period_type: Literal["instant", "duration", "unknown"]
    label: Optional[str] = None
    source: Literal["xsd", "taxonomy", "not_found"]
    is_directional_hint: bool


class WriteResult(BaseModel):
    output_path: str
    bytes_written: int
```

- [ ] **Step 2: Verify import still works**

Run: `uv run python -c "from src.auditmcp import FilingLocation, Fact, CalculationNetwork, ConceptMetadata, WriteResult; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/auditmcp.py
git commit -m "feat: add pydantic return models for auditing MCP tools"
```

---

## Task 6: Instance-document parser

**Files:**
- Modify: `src/auditmcp.py`
- Test: tests are exercised via Task 8 (`get_facts`). This task adds the parser used by both `get_facts` and `get_calculation_network` child-fact lookup.

- [ ] **Step 1: Write the parser in `src/auditmcp.py`**

Append:

```python
import functools
import xml.etree.ElementTree as ET
from pathlib import Path


# Namespace URIs that appear in instance documents we need to recognize.
_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XBRLDI_NS = "http://xbrl.org/2006/xbrldi"


def _localname(tag: str) -> str:
    """Strip `{namespace}` from an ET tag, leaving the local name."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _prefix_for_uri(root: ET.Element, uri: str) -> Optional[str]:
    """Return a prefix registered on the root element for `uri`, or None."""
    for k, v in root.attrib.items():
        if k.startswith("xmlns:") and v == uri:
            return k.split(":", 1)[1]
    return None


@dataclass(frozen=True)
class _ContextInfo:
    period_kind: Literal["instant", "duration"]
    start: str
    end: str
    dimensions: tuple[tuple[str, str], ...]  # sorted (axis_qname, member_qname)

    @property
    def canonical_period(self) -> str:
        return self.start if self.period_kind == "instant" else f"{self.start}/{self.end}"


@dataclass(frozen=True)
class _ParsedInstance:
    facts: tuple[tuple[str, str, str, Optional[str], Optional[str]], ...]
    # fact tuple: (concept_qname_colon_form, value, context_ref, unit_ref, decimals)
    contexts: dict[str, _ContextInfo]


@functools.lru_cache(maxsize=32)
def _parse_instance(htm_path: str) -> _ParsedInstance:
    """Parse an XBRL instance document. Cached by absolute path."""
    tree = ET.parse(htm_path)
    root = tree.getroot()

    # Map namespace URIs → prefixes declared on the root so we can recover
    # `us-gaap:` style names. ET parses {uri}LocalName; we need prefix:LocalName.
    uri_to_prefix: dict[str, str] = {}
    for k, v in root.attrib.items():
        if k.startswith("xmlns:"):
            uri_to_prefix[v] = k.split(":", 1)[1]
        elif k == "xmlns":
            uri_to_prefix[v] = ""

    contexts: dict[str, _ContextInfo] = {}
    for ctx in root.findall(f"{{{_XBRLI_NS}}}context"):
        cid = ctx.get("id", "")
        period = ctx.find(f"{{{_XBRLI_NS}}}period")
        if period is None:
            continue
        instant = period.find(f"{{{_XBRLI_NS}}}instant")
        if instant is not None:
            start = end = (instant.text or "").strip()
            kind: Literal["instant", "duration"] = "instant"
        else:
            sd = period.find(f"{{{_XBRLI_NS}}}startDate")
            ed = period.find(f"{{{_XBRLI_NS}}}endDate")
            if sd is None or ed is None:
                continue
            start = (sd.text or "").strip()
            end = (ed.text or "").strip()
            kind = "duration"

        dims: list[tuple[str, str]] = []
        segment = ctx.find(f"{{{_XBRLI_NS}}}entity/{{{_XBRLI_NS}}}segment")
        scenario = ctx.find(f"{{{_XBRLI_NS}}}scenario")
        for container in (segment, scenario):
            if container is None:
                continue
            for member in container.findall(f"{{{_XBRLDI_NS}}}explicitMember"):
                axis = member.get("dimension", "")
                val = (member.text or "").strip()
                if axis and val:
                    dims.append((axis, val))
        contexts[cid] = _ContextInfo(
            period_kind=kind, start=start, end=end,
            dimensions=tuple(sorted(dims)),
        )

    fact_tuples: list[tuple[str, str, str, Optional[str], Optional[str]]] = []
    for elem in root:
        ns_uri = elem.tag.split("}", 1)[0][1:] if "}" in elem.tag else ""
        if ns_uri in (_XBRLI_NS, _LINK_NS):
            # contexts, units, schemaRefs, etc.
            continue
        context_ref = elem.get("contextRef")
        if not context_ref:
            continue
        prefix = uri_to_prefix.get(ns_uri)
        local = _localname(elem.tag)
        qname = f"{prefix}:{local}" if prefix else local
        value = (elem.text or "").strip()
        fact_tuples.append((qname, value, context_ref, elem.get("unitRef"), elem.get("decimals")))

    return _ParsedInstance(facts=tuple(fact_tuples), contexts=contexts)
```

- [ ] **Step 2: Sanity-check by printing the parsed fixture**

Run:
```bash
uv run python -c "from src.auditmcp import _parse_instance; \
  p = _parse_instance('tests/fixtures/mini-filing/mini_htm.xml'); \
  print(len(p.facts), 'facts;', len(p.contexts), 'contexts'); \
  print(p.facts[0]); print(list(p.contexts.items())[0])"
```
Expected: `6 facts; 3 contexts`, first fact is `('us-gaap:Liabilities', '1000000', 'c_inst_20231231', 'usd', '-3')`.

- [ ] **Step 3: Commit**

```bash
git add src/auditmcp.py
git commit -m "feat: add cached XBRL instance-document parser"
```

---

## Task 7: Calculation-linkbase parser

**Files:**
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Append the parser**

```python
@dataclass(frozen=True)
class _CalArc:
    role: str
    parent: str    # concept, colon form
    child: str     # concept, colon form
    weight: float
    order: Optional[float]


@functools.lru_cache(maxsize=32)
def _parse_cal(cal_path: str) -> tuple[_CalArc, ...]:
    """Parse a calculation linkbase, returning resolved arcs.

    Locator labels are scoped PER calculationLink (role), not globally.
    href fragments like `...#us-gaap_Liabilities` are converted to
    `us-gaap:Liabilities`.
    """
    tree = ET.parse(cal_path)
    root = tree.getroot()
    arcs: list[_CalArc] = []

    for link in root.findall(f"{{{_LINK_NS}}}calculationLink"):
        role = link.get(f"{{{_XLINK_NS}}}role", "")
        label_to_concept: dict[str, str] = {}
        for loc in link.findall(f"{{{_LINK_NS}}}loc"):
            label = loc.get(f"{{{_XLINK_NS}}}label", "")
            href = loc.get(f"{{{_XLINK_NS}}}href", "")
            frag = href.split("#", 1)[-1] if "#" in href else href
            label_to_concept[label] = _normalize_concept(frag)

        for arc in link.findall(f"{{{_LINK_NS}}}calculationArc"):
            from_label = arc.get(f"{{{_XLINK_NS}}}from", "")
            to_label = arc.get(f"{{{_XLINK_NS}}}to", "")
            parent = label_to_concept.get(from_label)
            child = label_to_concept.get(to_label)
            if not parent or not child:
                continue
            weight = float(arc.get("weight", "1.0"))
            order_str = arc.get("order")
            order = float(order_str) if order_str is not None else None
            arcs.append(_CalArc(role=role, parent=parent, child=child, weight=weight, order=order))

    return tuple(arcs)
```

- [ ] **Step 2: Sanity-check against fixture**

Run:
```bash
uv run python -c "from src.auditmcp import _parse_cal; \
  arcs = _parse_cal('tests/fixtures/mini-filing/mini_cal.xml'); \
  [print(a) for a in arcs]"
```
Expected: 2 arcs from `us-gaap:Liabilities` to `us-gaap:Deposits` / `us-gaap:OtherLiabilities`, weight 1.0, role `http://example.com/role/BalanceSheet`.

- [ ] **Step 3: Commit**

```bash
git add src/auditmcp.py
git commit -m "feat: add cached calculation-linkbase parser"
```

---

## Task 8: Extension-schema parser (`*.xsd`) and taxonomy loader

**Files:**
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Append schema parser + taxonomy loader**

```python
import json


@functools.lru_cache(maxsize=32)
def _parse_xsd(xsd_path: str) -> dict[str, dict[str, str]]:
    """Parse an extension schema, returning `{local_name: {balance, periodType}}`.

    Values are 'debit' | 'credit' | 'none' (for balance) and 'instant' |
    'duration' (for periodType). Missing attributes are omitted.
    """
    tree = ET.parse(xsd_path)
    root = tree.getroot()
    xbrli_balance = f"{{{_XBRLI_NS}}}balance"
    xbrli_period = f"{{{_XBRLI_NS}}}periodType"
    out: dict[str, dict[str, str]] = {}
    for elem in root.iter():
        if _localname(elem.tag) != "element":
            continue
        name = elem.get("name")
        if not name:
            continue
        info: dict[str, str] = {}
        if bal := elem.get(xbrli_balance):
            info["balance"] = bal
        if pt := elem.get(xbrli_period):
            info["periodType"] = pt
        if info:
            out[name] = info
    return out


@functools.lru_cache(maxsize=16)
def _load_taxonomy_core(taxonomy_dir: str) -> dict[str, dict]:
    """Load `chunks_core.jsonl` into a `{concept_id: row_dict}` map.

    `taxonomy_dir` is the full path to `gaap_chunks_{year}/`.
    """
    path = Path(taxonomy_dir) / "chunks_core.jsonl"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if concept := row.get("concept"):
                out[_normalize_concept(concept)] = row
    return out
```

- [ ] **Step 2: Sanity-check**

Run:
```bash
uv run python -c "from src.auditmcp import _parse_xsd, _load_taxonomy_core; \
  print(_parse_xsd('tests/fixtures/mini-filing/mini.xsd')['LossOnDisposal']); \
  print(_load_taxonomy_core('tests/fixtures/gaap_chunks_2023')['us-gaap:Liabilities'])"
```
Expected: `{'balance': 'debit', 'periodType': 'duration'}` and a dict with `balance: 'credit'`.

- [ ] **Step 3: Commit**

```bash
git add src/auditmcp.py
git commit -m "feat: add extension-schema parser and taxonomy loader"
```

---

## Task 9: Tool — `find_filing`

**Files:**
- Create: `tests/test_find_filing.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
import os
import pytest
from src.auditmcp import find_filing


@pytest.fixture(autouse=True)
def set_data_root(monkeypatch, fixtures_dir):
    # For find_filing tests we point the root at a tmp structure we build
    pass  # overridden per test


def test_find_filing_happy_path(monkeypatch, tmp_path, fixtures_dir):
    # Copy mini-filing into `<tmp>/XBRL/10k-mini-20231231/` using the filename pattern find_filing expects.
    import shutil
    xbrl_root = tmp_path / "XBRL"
    filing_dir = xbrl_root / "10k-mini-20231231"
    filing_dir.mkdir(parents=True)
    src = fixtures_dir / "mini-filing"
    for name in ["mini_htm.xml", "mini_cal.xml", "mini.xsd",
                 "mini_def.xml", "mini_lab.xml", "mini_pre.xml"]:
        shutil.copy(src / name, filing_dir / name)
    monkeypatch.setenv("AUDITMCP_DATA_ROOT", str(tmp_path))

    loc = find_filing(ticker="mini", filing_name="10k", issue_time="20231231")
    assert loc.found is True
    assert loc.filing_year == 2023
    assert loc.filing_path == str(filing_dir)
    assert set(loc.files) == {"htm", "cal", "xsd", "def", "lab", "pre"}
    assert loc.files["htm"].endswith("mini_htm.xml")
    assert loc.message == ""


def test_find_filing_missing_folder(monkeypatch, tmp_path):
    (tmp_path / "XBRL").mkdir()
    monkeypatch.setenv("AUDITMCP_DATA_ROOT", str(tmp_path))
    loc = find_filing(ticker="nope", filing_name="10k", issue_time="20231231")
    assert loc.found is False
    assert "not found" in loc.message


def test_find_filing_missing_cal(monkeypatch, tmp_path, fixtures_dir):
    import shutil
    filing_dir = tmp_path / "XBRL" / "10k-mini-20231231"
    filing_dir.mkdir(parents=True)
    for name in ["mini_htm.xml", "mini.xsd",
                 "mini_def.xml", "mini_lab.xml", "mini_pre.xml"]:
        shutil.copy(fixtures_dir / "mini-filing" / name, filing_dir / name)
    monkeypatch.setenv("AUDITMCP_DATA_ROOT", str(tmp_path))
    loc = find_filing(ticker="mini", filing_name="10k", issue_time="20231231")
    assert loc.found is False
    assert "_cal.xml" in loc.message
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_find_filing.py -v`
Expected: ImportError — `find_filing` not defined.

- [ ] **Step 3: Add FastMCP init + `find_filing` tool to `src/auditmcp.py`**

Append:

```python
import os
from fastmcp import FastMCP

try:  # optional
    import logfire
    logfire.configure(service_name="auditmcp")
    logfire.instrument_mcp()
except Exception:
    pass

mcp = FastMCP("XBRL Auditing Tools")


_REQUIRED_FILE_GLOBS = {
    "htm": "*_htm.xml",
    "cal": "*_cal.xml",
    "def": "*_def.xml",
    "lab": "*_lab.xml",
    "pre": "*_pre.xml",
    "xsd": "*.xsd",
}


def _data_root() -> Path:
    root = os.environ.get("AUDITMCP_DATA_ROOT")
    if not root:
        raise RuntimeError("AUDITMCP_DATA_ROOT is not set")
    return Path(root)


@mcp.tool(
    description="Locate the folder for a given XBRL filing under "
    "$AUDITMCP_DATA_ROOT/XBRL. Returns the absolute path, the derived filing "
    "year, and a map of the six XBRL files (htm, cal, xsd, def, lab, pre). "
    "Sets found=false with a diagnostic message if the folder or any required "
    "file is missing."
)
def find_filing(ticker: str, filing_name: str, issue_time: str) -> FilingLocation:
    folder_name = f"{filing_name}-{ticker}-{issue_time}"
    filing_dir = _data_root() / "XBRL" / folder_name
    if not filing_dir.is_dir():
        return FilingLocation(found=False, message=f"folder not found: {filing_dir}")

    files: dict[str, str] = {}
    for key, glob in _REQUIRED_FILE_GLOBS.items():
        matches = list(filing_dir.glob(glob))
        if key == "xsd":
            # Pick a schema that doesn't look like a generated one (heuristic: no underscore).
            matches = [m for m in matches if "_" not in m.stem] or matches
        if len(matches) != 1:
            return FilingLocation(
                found=False,
                message=f"expected exactly one file matching {glob} in {filing_dir}, found {len(matches)}",
            )
        files[key] = str(matches[0])

    try:
        filing_year = int(issue_time[:4])
    except ValueError:
        return FilingLocation(found=False, message=f"bad issue_time: {issue_time!r}")

    return FilingLocation(
        filing_path=str(filing_dir),
        filing_year=filing_year,
        files=files,
        found=True,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_find_filing.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_find_filing.py
git commit -m "feat: add find_filing tool"
```

---

## Task 10: Tool — `get_facts`

**Files:**
- Create: `tests/test_get_facts.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from src.auditmcp import get_facts


def test_get_facts_instant_match(mini_filing_dir):
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
        period="2023-12-31",
    )
    assert res.concept_id == "us-gaap:Liabilities"
    assert res.requested_period_canonical == "2023-12-31"
    assert len(res.matched) == 1
    assert res.matched[0].value == "1000000"
    assert res.matched[0].period_type == "instant"
    assert res.matched[0].dimensions == {}
    assert set(res.all_periods_found) >= {"2023-12-31", "2022-12-31"}


def test_get_facts_period_miss_returns_all_periods(mini_filing_dir):
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
        period="2021-12-31",
    )
    assert res.matched == []
    assert "2023-12-31" in res.all_periods_found


def test_get_facts_duration_match_fy(mini_filing_dir):
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:LossOnDisposal",
        period="FY2023",
    )
    assert len(res.matched) == 1
    assert res.matched[0].value == "-50000"
    assert res.matched[0].period_type == "duration"
    assert res.matched[0].period == "2023-01-01/2023-12-31"


def test_get_facts_accepts_underscore_concept_id(mini_filing_dir):
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap_Liabilities",
        period="2023-12-31",
    )
    assert res.concept_id == "us-gaap:Liabilities"
    assert len(res.matched) == 1


def test_get_facts_invalid_period_raises(mini_filing_dir):
    with pytest.raises(ValueError):
        get_facts(
            filing_path=str(mini_filing_dir),
            concept_id="us-gaap:Liabilities",
            period="sometime",
        )
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_get_facts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `get_facts` in `src/auditmcp.py`**

Append:

```python
@mcp.tool(
    description="Extract numeric facts for a concept whose context period exactly "
    "matches the requested period. Period grammar: 'YYYY-MM-DD' (instant), "
    "'YYYY-MM-DD to YYYY-MM-DD' (duration), 'FYYYYY' (calendar-year duration — "
    "non-December fiscal years must use explicit ranges), 'QN YYYY'. Returns "
    "matched facts ranked by non-dimensional first, plus all distinct periods "
    "found for this concept to help diagnose period misses."
)
def get_facts(filing_path: str, concept_id: str, period: str) -> FactsResult:
    normalized = _normalize_concept(concept_id)
    parsed_period = _parse_period(period)
    htm_path = _pick_file(filing_path, "*_htm.xml")
    instance = _parse_instance(htm_path)

    all_periods: set[str] = set()
    candidates: list[Fact] = []
    for qname, value, ctx_ref, unit_ref, decimals in instance.facts:
        if qname != normalized:
            continue
        ctx = instance.contexts.get(ctx_ref)
        if ctx is None:
            continue
        all_periods.add(ctx.canonical_period)
        if ctx.period_kind != parsed_period.kind:
            continue
        if ctx.start != parsed_period.start or ctx.end != parsed_period.end:
            continue
        candidates.append(Fact(
            value=value,
            context_ref=ctx_ref,
            period_type=ctx.period_kind,
            period=ctx.canonical_period,
            dimensions={a: m for a, m in ctx.dimensions},
            unit_ref=unit_ref,
            decimals=decimals,
        ))

    # Rank: non-dimensional first, then numeric-parseable first.
    def _numeric_ok(f: Fact) -> int:
        try:
            float(f.value)
            return 0
        except ValueError:
            return 1

    candidates.sort(key=lambda f: (len(f.dimensions) > 0, _numeric_ok(f)))

    return FactsResult(
        concept_id=normalized,
        requested_period=period,
        requested_period_canonical=parsed_period.canonical,
        matched=candidates,
        all_periods_found=sorted(all_periods),
    )


def _pick_file(filing_path: str, glob: str) -> str:
    """Pick the single file matching `glob` in `filing_path`, raising if not exactly one."""
    matches = list(Path(filing_path).glob(glob))
    if glob == "*.xsd":
        matches = [m for m in matches if "_" not in m.stem] or matches
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one file matching {glob} in {filing_path}, found {len(matches)}"
        )
    return str(matches[0])
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_get_facts.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_get_facts.py
git commit -m "feat: add get_facts tool"
```

---

## Task 11: Tool — `get_calculation_network`

**Files:**
- Create: `tests/test_get_calculation_network.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
from src.auditmcp import get_calculation_network


def test_concept_as_parent(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
    )
    assert net.is_isolated is False
    assert net.as_child == []
    assert len(net.as_parent) == 1
    role = net.as_parent[0]
    assert role.role == "http://example.com/role/BalanceSheet"
    concepts = sorted(c.concept for c in role.children)
    assert concepts == ["us-gaap:Deposits", "us-gaap:OtherLiabilities"]
    assert all(c.weight == 1.0 for c in role.children)


def test_concept_as_child(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Deposits",
    )
    assert net.is_isolated is False
    assert net.as_parent == []
    assert len(net.as_child) == 1
    cr = net.as_child[0]
    assert cr.parent == "us-gaap:Liabilities"
    sibling_names = sorted(s.concept for s in cr.siblings)
    assert sibling_names == ["us-gaap:Deposits", "us-gaap:OtherLiabilities"]


def test_isolated_concept(mini_filing_dir):
    net = get_calculation_network(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:NonCalcItem",
    )
    assert net.is_isolated is True
    assert net.as_parent == []
    assert net.as_child == []
    assert "http://example.com/role/BalanceSheet" in net.roles_scanned
```

- [ ] **Step 2: Run tests, verify they fail**

Expected: ImportError.

- [ ] **Step 3: Implement in `src/auditmcp.py`**

Append:

```python
@mcp.tool(
    description="Return the calculation-linkbase relationships for a concept: "
    "roles where it is the summation parent (with weighted children) and roles "
    "where it appears as a child (with parent and sibling weights, including "
    "its own weight). is_isolated=true when the concept has no calculation "
    "relationships at all — a Case D hint for the agent."
)
def get_calculation_network(filing_path: str, concept_id: str) -> CalculationNetwork:
    normalized = _normalize_concept(concept_id)
    cal_path = _pick_file(filing_path, "*_cal.xml")
    arcs = _parse_cal(cal_path)

    roles_scanned = sorted({a.role for a in arcs})

    # Group arcs by role.
    by_role: dict[str, list[_CalArc]] = {}
    for a in arcs:
        by_role.setdefault(a.role, []).append(a)

    as_parent: list[ParentRole] = []
    as_child: list[ChildRole] = []

    for role, role_arcs in by_role.items():
        # As parent in this role?
        parent_arcs = [a for a in role_arcs if a.parent == normalized]
        if parent_arcs:
            children = [CalChild(concept=a.child, weight=a.weight, order=a.order)
                        for a in parent_arcs]
            as_parent.append(ParentRole(role=role, children=children))

        # As child in this role?
        child_arcs = [a for a in role_arcs if a.child == normalized]
        for ca in child_arcs:
            # Collect all siblings under the same parent in this role
            sibling_arcs = [a for a in role_arcs if a.parent == ca.parent]
            siblings = [CalChild(concept=a.child, weight=a.weight, order=a.order)
                        for a in sibling_arcs]
            as_child.append(ChildRole(role=role, parent=ca.parent, siblings=siblings))

    return CalculationNetwork(
        concept_id=normalized,
        as_parent=as_parent,
        as_child=as_child,
        is_isolated=not as_parent and not as_child,
        roles_scanned=roles_scanned,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_get_calculation_network.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_get_calculation_network.py
git commit -m "feat: add get_calculation_network tool"
```

---

## Task 12: Tool — `get_concept_metadata`

**Files:**
- Create: `tests/test_get_concept_metadata.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from src.auditmcp import get_concept_metadata


@pytest.fixture
def taxonomy_root(monkeypatch, fixtures_dir):
    # get_concept_metadata expects $AUDITMCP_DATA_ROOT/US_GAAP_Taxonomy/gaap_chunks_{year}/
    monkeypatch.setenv("AUDITMCP_DATA_ROOT", str(fixtures_dir))
    # Set up symlink-like layout: fixtures/US_GAAP_Taxonomy/gaap_chunks_2023 -> fixtures/gaap_chunks_2023
    import os
    target = fixtures_dir / "US_GAAP_Taxonomy"
    target.mkdir(exist_ok=True)
    link = target / "gaap_chunks_2023"
    if not link.exists():
        try:
            os.symlink(fixtures_dir / "gaap_chunks_2023", link)
        except FileExistsError:
            pass
    yield


def test_metadata_from_xsd(taxonomy_root, mini_filing_dir):
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:LossOnDisposal",
        taxonomy_year=2023,
    )
    assert md.source == "xsd"
    assert md.balance == "debit"
    assert md.period_type == "duration"
    assert md.is_directional_hint is True


def test_metadata_from_taxonomy_fallback(taxonomy_root, mini_filing_dir):
    # NonCalcItem is in chunks_core.jsonl but not in the xsd (we only declared
    # Liabilities, Deposits, OtherLiabilities, LossOnDisposal in mini.xsd).
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:NonCalcItem",
        taxonomy_year=2023,
    )
    assert md.source == "taxonomy"
    assert md.balance == "none"
    assert md.is_directional_hint is False


def test_metadata_not_found(taxonomy_root, mini_filing_dir):
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:DoesNotExist",
        taxonomy_year=2023,
    )
    assert md.source == "not_found"
    assert md.balance == "unknown"
    assert md.period_type == "unknown"
    assert md.is_directional_hint is False


def test_directional_hint_heuristic(taxonomy_root, mini_filing_dir):
    # LossOnDisposal label matches "loss" and xsd says debit → hint = True.
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:LossOnDisposal",
        taxonomy_year=2023,
    )
    assert md.is_directional_hint is True

    # Liabilities is credit + name has no directional keyword → False.
    md2 = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
        taxonomy_year=2023,
    )
    assert md2.is_directional_hint is False
```

- [ ] **Step 2: Run tests, verify they fail**

Expected: ImportError.

- [ ] **Step 3: Implement in `src/auditmcp.py`**

Append:

```python
_DIRECTIONAL_KEYWORDS = (
    "expense", "expenses", "loss", "losses", "impairment", "depreciation",
    "amortization", "deduction", "contra", "writedown", "writeoff",
)


def _is_directional_hint(local_name: str, label: Optional[str], balance: str) -> bool:
    haystack = f"{local_name} {label or ''}".lower()
    if balance == "debit" and any(k in haystack for k in _DIRECTIONAL_KEYWORDS):
        return True
    if balance == "credit" and "contra" in haystack:
        return True
    return False


@mcp.tool(
    description="Return balance type, period type, label, and a directional "
    "hint for a concept. Looks up the filing's extension schema first, then "
    "falls back to gaap_chunks_{taxonomy_year}/chunks_core.jsonl under "
    "$AUDITMCP_DATA_ROOT/US_GAAP_Taxonomy/. is_directional_hint is a "
    "heuristic (expense/loss/contra-style keywords + balance); the agent "
    "makes the final Case B determination."
)
def get_concept_metadata(
    filing_path: str, concept_id: str, taxonomy_year: int
) -> ConceptMetadata:
    normalized = _normalize_concept(concept_id)
    local = normalized.split(":", 1)[-1]

    # 1) xsd lookup
    try:
        xsd_path = _pick_file(filing_path, "*.xsd")
        xsd_map = _parse_xsd(xsd_path)
    except FileNotFoundError:
        xsd_map = {}
    if local in xsd_map:
        info = xsd_map[local]
        bal = info.get("balance", "unknown")
        pt = info.get("periodType", "unknown")
        label = None
        return ConceptMetadata(
            concept_id=normalized,
            balance=bal if bal in ("debit", "credit", "none") else "unknown",
            period_type=pt if pt in ("instant", "duration") else "unknown",
            label=label,
            source="xsd",
            is_directional_hint=_is_directional_hint(local, label, bal),
        )

    # 2) taxonomy fallback
    tax_dir = _data_root() / "US_GAAP_Taxonomy" / f"gaap_chunks_{taxonomy_year}"
    tax_map = _load_taxonomy_core(str(tax_dir))
    row = tax_map.get(normalized)
    if row:
        bal = row.get("balance", "unknown")
        pt = row.get("period_type", "unknown")
        label = row.get("label")
        return ConceptMetadata(
            concept_id=normalized,
            balance=bal if bal in ("debit", "credit", "none") else "unknown",
            period_type=pt if pt in ("instant", "duration") else "unknown",
            label=label,
            source="taxonomy",
            is_directional_hint=_is_directional_hint(local, label, bal),
        )

    # 3) not found
    return ConceptMetadata(
        concept_id=normalized,
        balance="unknown",
        period_type="unknown",
        label=None,
        source="not_found",
        is_directional_hint=False,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_get_concept_metadata.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_get_concept_metadata.py
git commit -m "feat: add get_concept_metadata tool"
```

---

## Task 13: Tool — `write_audit_result`

**Files:**
- Create: `tests/test_write_audit_result.py`
- Modify: `src/auditmcp.py`

- [ ] **Step 1: Write failing tests**

```python
import json
from src.auditmcp import write_audit_result


def test_write_creates_file_with_correct_name(tmp_path):
    res = write_audit_result(
        output_dir=str(tmp_path / "results" / "auditing"),
        agent_name="claude-code",
        filing_name="10k",
        ticker="zions",
        issue_time="20231231",
        id="mr_1",
        model="claude-sonnet-4-6",
        extracted_value="-1234567000",
        calculated_value="1234567000",
    )
    expected = tmp_path / "results" / "auditing" / \
        "claude-code_auditing_10k_zions_20231231_mr_1_claude-sonnet-4-6.json"
    assert res.output_path == str(expected)
    assert expected.exists()
    content = expected.read_text()
    assert content.endswith("\n")
    payload = json.loads(content)
    assert payload == {"extracted_value": "-1234567000", "calculated_value": "1234567000"}


def test_write_sanitizes_model_name(tmp_path):
    res = write_audit_result(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x",
        model="weird/model name:v2",
        extracted_value="0", calculated_value="0",
    )
    assert "weird-model-name-v2" in res.output_path


def test_write_overwrites(tmp_path):
    kwargs = dict(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x", model="m",
    )
    write_audit_result(**kwargs, extracted_value="1", calculated_value="1")
    res = write_audit_result(**kwargs, extracted_value="2", calculated_value="2")
    content = json.loads(open(res.output_path).read())
    assert content == {"extracted_value": "2", "calculated_value": "2"}


def test_write_preserves_value_strings(tmp_path):
    # Values with leading zeros, decimals, and scientific notation must survive as-is.
    res = write_audit_result(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x", model="m",
        extracted_value="00123.4500", calculated_value="-1.2e6",
    )
    payload = json.loads(open(res.output_path).read())
    assert payload["extracted_value"] == "00123.4500"
    assert payload["calculated_value"] == "-1.2e6"
```

- [ ] **Step 2: Run tests, verify they fail**

Expected: ImportError.

- [ ] **Step 3: Implement in `src/auditmcp.py`**

Append:

```python
import re as _re


def _sanitize_model(model: str) -> str:
    return _re.sub(r"[^A-Za-z0-9._-]", "-", model)


@mcp.tool(
    description="Write the final single-line audit result JSON "
    "({extracted_value, calculated_value}) to "
    "{output_dir}/{agent_name}_auditing_{filing_name}_{ticker}_{issue_time}_{id}_{model}.json. "
    "Numeric values are written verbatim as strings (no rounding). Overwrites "
    "if the file exists; creates output_dir if missing."
)
def write_audit_result(
    output_dir: str,
    agent_name: str,
    filing_name: str,
    ticker: str,
    issue_time: str,
    id: str,
    model: str,
    extracted_value: str,
    calculated_value: str,
) -> WriteResult:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fname = (
        f"{agent_name}_auditing_{filing_name}_{ticker}_{issue_time}_"
        f"{id}_{_sanitize_model(model)}.json"
    )
    path = out / fname
    payload = json.dumps(
        {"extracted_value": extracted_value, "calculated_value": calculated_value},
        separators=(", ", ": "),
    )
    data = payload + "\n"
    path.write_text(data)
    return WriteResult(output_path=str(path), bytes_written=len(data.encode()))
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_write_audit_result.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/auditmcp.py tests/test_write_audit_result.py
git commit -m "feat: add write_audit_result tool"
```

---

## Task 14: Server entry point + full test run

**Files:**
- Modify: `src/auditmcp.py` (append main)

- [ ] **Step 1: Append main block**

Add the final block at the bottom of `src/auditmcp.py`:

```python
if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: every test passes (~20 tests across 6 test files).

- [ ] **Step 3: Sanity-launch the server (manual smoke)**

Run (in one terminal):
```bash
AUDITMCP_DATA_ROOT=/Users/xai/Desktop/agentic-auditing/data/auditing \
  uv run src/auditmcp.py
```
Expected: process stays alive waiting for stdio MCP frames; no exceptions on startup. Kill with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add src/auditmcp.py
git commit -m "feat: wire FastMCP server entry point"
```

---

## Task 15: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README contents**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document auditing MCP launch and tools"
```

---

## Done

Deliverables:
- `src/auditmcp.py` — FastMCP server exposing 5 tools.
- `tests/` — ~20 unit tests against hand-crafted XBRL fixtures.
- `pyproject.toml` — dependency declaration.
- `README.md` — launch + tools reference.
- Every task produces a clean commit; the spec's design constraints (agent retains Case A/B/C/D reasoning, no LLM in MCP, env-var root, process cache) are preserved throughout.

Follow-ups (out of scope for this plan, per spec):
- Update `auditing/SKILL.md` "Implementation approach" section to instruct the agent to use the MCP tools.
- v2: `DocumentFiscalYearFocus`/`CurrentFiscalYearEndDate` inference for non-December fiscal years.
- v2: `get_taxonomy_relations` tool reading `chunks_relations.jsonl`.
