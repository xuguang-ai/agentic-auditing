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
