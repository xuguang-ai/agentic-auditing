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
