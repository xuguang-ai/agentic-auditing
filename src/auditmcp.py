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
