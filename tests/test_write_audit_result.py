import json
from src.auditmcp import write_audit_result


def test_write_creates_file_with_correct_name(tmp_path):
    res = write_audit_result(
        output_dir=str(tmp_path / "results" / "auditing"),
        agent_name="claude-code",
        filing_name="10k",
        ticker="zions",
        issue_time="20231231",
        id="mr_1",
        model="claude-sonnet-4-6",
        extracted_value="-1234567000",
        calculated_value="1234567000",
    )
    expected = tmp_path / "results" / "auditing" / \
        "claude-code_auditing_10k_zions_20231231_mr_1_claude-sonnet-4-6.json"
    assert res.output_path == str(expected)
    assert expected.exists()
    content = expected.read_text()
    assert content.endswith("\n")
    payload = json.loads(content)
    assert payload == {"extracted_value": "-1234567000", "calculated_value": "1234567000"}


def test_write_sanitizes_model_name(tmp_path):
    res = write_audit_result(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x",
        model="weird/model name:v2",
        extracted_value="0", calculated_value="0",
    )
    assert "weird-model-name-v2" in res.output_path


def test_write_overwrites(tmp_path):
    kwargs = dict(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x", model="m",
    )
    write_audit_result(**kwargs, extracted_value="1", calculated_value="1")
    res = write_audit_result(**kwargs, extracted_value="2", calculated_value="2")
    content = json.loads(open(res.output_path).read())
    assert content == {"extracted_value": "2", "calculated_value": "2"}


def test_write_preserves_value_strings(tmp_path):
    res = write_audit_result(
        output_dir=str(tmp_path), agent_name="a", filing_name="10k",
        ticker="t", issue_time="20231231", id="x", model="m",
        extracted_value="00123.4500", calculated_value="-1.2e6",
    )
    payload = json.loads(open(res.output_path).read())
    assert payload["extracted_value"] == "00123.4500"
    assert payload["calculated_value"] == "-1.2e6"
