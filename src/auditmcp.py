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
      - `FYYYYY`                  → duration YYYY-01-01..YYYY-12-31 (calendar year)
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


# ---------------------------------------------------------------------------
# Pydantic return models (Task 5)
# ---------------------------------------------------------------------------
from typing import Literal, Optional
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


# ---------------------------------------------------------------------------
# Instance-document parser (Task 6)
# ---------------------------------------------------------------------------
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



@dataclass(frozen=True)
class _ContextInfo:
    period_kind: Literal["instant", "duration"]
    start: str
    end: str
    dimensions: tuple  # sorted (axis_qname, member_qname) pairs

    @property
    def canonical_period(self) -> str:
        return self.start if self.period_kind == "instant" else f"{self.start}/{self.end}"


@dataclass(frozen=True)
class _ParsedInstance:
    facts: tuple  # fact tuple: (concept_qname_colon_form, value, context_ref, unit_ref, decimals)
    contexts: dict


def _parse_instance(htm_path: str) -> _ParsedInstance:
    """Parse an XBRL instance document. Normalizes path to absolute before caching."""
    return _parse_instance_cached(str(Path(htm_path).resolve()))


@functools.lru_cache(maxsize=32)
def _parse_instance_cached(htm_path: str) -> _ParsedInstance:
    """Parse an XBRL instance document. Cached by absolute path."""
    # Collect namespace prefix → URI mappings before parsing the tree.
    # ET does not expose xmlns: attributes via root.attrib; iterparse with
    # "start-ns" events is the only reliable way to capture them.
    uri_to_prefix: dict[str, str] = {}
    for event, (prefix, uri) in ET.iterparse(htm_path, events=("start-ns",)):
        if prefix:  # skip the default namespace (empty prefix)
            uri_to_prefix[uri] = prefix

    tree = ET.parse(htm_path)
    root = tree.getroot()

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

    fact_tuples: list[tuple] = []
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


@dataclass(frozen=True)
class _CalArc:
    role: str
    parent: str    # concept, colon form
    child: str     # concept, colon form
    weight: float
    order: Optional[float]


@functools.lru_cache(maxsize=32)
def _parse_cal_cached(cal_path: str) -> tuple[_CalArc, ...]:
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


def _parse_cal(cal_path: str) -> tuple[_CalArc, ...]:
    """Parse a calculation linkbase. Cached via absolute path."""
    return _parse_cal_cached(str(Path(cal_path).resolve()))


import json


@functools.lru_cache(maxsize=32)
def _parse_xsd_cached(xsd_path: str) -> dict[str, dict[str, str]]:
    """Parse an extension schema, returning `{local_name: {balance, periodType}}`."""
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


def _parse_xsd(xsd_path: str) -> dict[str, dict[str, str]]:
    """Parse an extension schema. Cached via absolute path."""
    return _parse_xsd_cached(str(Path(xsd_path).resolve()))


@functools.lru_cache(maxsize=16)
def _load_taxonomy_core_cached(taxonomy_dir: str) -> dict[str, dict]:
    """Load `chunks_core.jsonl` from `gaap_chunks_{year}/` dir into `{concept_id: row}`."""
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


def _load_taxonomy_core(taxonomy_dir: str) -> dict[str, dict]:
    """Load taxonomy core chunks. Cached via absolute path."""
    return _load_taxonomy_core_cached(str(Path(taxonomy_dir).resolve()))


# ---------------------------------------------------------------------------
# FastMCP server init (Task 9)
# ---------------------------------------------------------------------------
import os
from fastmcp import FastMCP

try:
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

    by_role: dict[str, list[_CalArc]] = {}
    for a in arcs:
        by_role.setdefault(a.role, []).append(a)

    as_parent: list[ParentRole] = []
    as_child: list[ChildRole] = []

    for role, role_arcs in by_role.items():
        parent_arcs = [a for a in role_arcs if a.parent == normalized]
        if parent_arcs:
            children = [CalChild(concept=a.child, weight=a.weight, order=a.order)
                        for a in parent_arcs]
            as_parent.append(ParentRole(role=role, children=children))

        child_arcs = [a for a in role_arcs if a.child == normalized]
        for ca in child_arcs:
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


# ---------------------------------------------------------------------------
# Task 12: get_concept_metadata
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 13: write_audit_result
# ---------------------------------------------------------------------------
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
