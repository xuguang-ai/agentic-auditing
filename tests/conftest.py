from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES

@pytest.fixture
def mini_filing_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "mini-filing"

