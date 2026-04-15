import os
import pytest
from src.auditmcp import get_concept_metadata


@pytest.fixture(autouse=True)
def setup_taxonomy(monkeypatch, fixtures_dir):
    """Set AUDITMCP_DATA_ROOT and create US_GAAP_Taxonomy symlink."""
    monkeypatch.setenv("AUDITMCP_DATA_ROOT", str(fixtures_dir))
    target = fixtures_dir / "US_GAAP_Taxonomy"
    target.mkdir(exist_ok=True)
    link = target / "gaap_chunks_2023"
    if not link.exists():
        os.symlink(fixtures_dir / "gaap_chunks_2023", link)


def test_metadata_from_xsd(mini_filing_dir):
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:LossOnDisposal",
        taxonomy_year=2023,
    )
    assert md.source == "xsd"
    assert md.balance == "debit"
    assert md.period_type == "duration"
    assert md.is_directional_hint is True


def test_metadata_from_taxonomy_fallback(mini_filing_dir):
    # NonCalcItem not in xsd but present in chunks_core.jsonl
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:NonCalcItem",
        taxonomy_year=2023,
    )
    assert md.source == "taxonomy"
    assert md.balance == "none"
    assert md.is_directional_hint is False


def test_metadata_not_found(mini_filing_dir):
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:DoesNotExist",
        taxonomy_year=2023,
    )
    assert md.source == "not_found"
    assert md.balance == "unknown"
    assert md.period_type == "unknown"
    assert md.is_directional_hint is False


def test_directional_hint_liabilities_is_false(mini_filing_dir):
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Liabilities",
        taxonomy_year=2023,
    )
    assert md.is_directional_hint is False


def test_taxonomy_fallback_resolves_standard_gaap_concept(mini_filing_dir):
    """Regression for the smoke-test bug: a standard GAAP concept that is
    NOT in the filing's extension xsd must be resolved via the taxonomy
    chunks (which use `concept_id` + `periodType` field names in the
    real-world JSONL), not silently fall through to `not_found`."""
    # Liabilities is a standard GAAP concept; the mini filing's xsd defines
    # an extension `Liabilities` but here we pin behaviour for a concept
    # that ONLY exists in the taxonomy fallback path.
    md = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:LossOnDisposal",
        taxonomy_year=2023,
    )
    # LossOnDisposal IS in the xsd, so the xsd path should win — but the
    # taxonomy lookup must independently work too. Verify via NonCalcItem
    # which is taxonomy-only:
    md2 = get_concept_metadata(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:NonCalcItem",
        taxonomy_year=2023,
    )
    assert md2.source == "taxonomy"
    assert md2.label == "Non Calc Item"
    assert md2.period_type == "duration"
