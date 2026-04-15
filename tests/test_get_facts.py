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


def test_get_facts_dedups_identical_duplicates(mini_filing_dir):
    """Inline-XBRL flattening can emit the same fact twice. When qname,
    contextRef, value, dimensions, unitRef and decimals all match, the
    duplicates are the same fact and must collapse to one entry."""
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:Deposits",
        period="2024-03-31",
    )
    assert len(res.matched) == 1
    assert res.matched[0].value == "500000"
    assert res.matched[0].decimals == "-3"


def test_get_facts_keeps_facts_with_different_decimals(mini_filing_dir):
    """Conservative dedup: facts that share value/context/dimensions/unit
    but differ on `decimals` are NOT collapsed — different decimals encode
    different precision claims and must be surfaced to the agent."""
    res = get_facts(
        filing_path=str(mini_filing_dir),
        concept_id="us-gaap:OtherLiabilities",
        period="2024-03-31",
    )
    assert len(res.matched) == 2
    decimals_seen = {f.decimals for f in res.matched}
    assert decimals_seen == {"-3", "-6"}
