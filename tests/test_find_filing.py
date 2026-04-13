import pytest
from src.auditmcp import find_filing


def test_find_filing_happy_path(monkeypatch, tmp_path, fixtures_dir):
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
