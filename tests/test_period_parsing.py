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
