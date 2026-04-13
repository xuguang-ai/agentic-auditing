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
