import ast
from unittest.mock import MagicMock, patch

import pytest


SPEC_BLOCKS = [
    {"transform_id": "source_orders", "transform_type": "source_read"},
    {"transform_id": "join_customers", "transform_type": "join"},
]


def _make_generator():
    with patch("anthropic.Anthropic"):
        from tool.stage2.layers.l5_tests import L5TestGenerator

        g = L5TestGenerator.__new__(L5TestGenerator)
        g.client = MagicMock()
        import yaml
        from jinja2 import Environment, FileSystemLoader

        with open("tool/config/llm_prompts.yaml") as f:
            g.prompts = yaml.safe_load(f)
        g.env = Environment(loader=FileSystemLoader("tool/templates"), keep_trailing_newline=True)
        return g


def test_generates_one_file_per_job():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    assert len(result) == 1
    assert "tests/test_etl_orders_daily.py" in result


def test_three_functions_per_transform():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    content = list(result.values())[0]
    for block in SPEC_BLOCKS:
        tid = block["transform_id"]
        assert f"def test_{tid}_standard(" in content
        assert f"def test_{tid}_null_input(" in content
        assert f"def test_{tid}_empty_input(" in content


def test_all_functions_marked_xfail():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    content = list(result.values())[0]
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("def test_"):
            # The line before should be @pytest.mark.xfail
            preceding = lines[i - 1].strip() if i > 0 else ""
            assert "xfail" in preceding, f"Test {line.strip()} missing @pytest.mark.xfail"


def test_valid_python_syntax():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    content = list(result.values())[0]
    # Should parse without SyntaxError
    ast.parse(content)


def test_api_failure_generates_stub():
    g = _make_generator()
    with patch.object(g, "_call_fixture_api", side_effect=RuntimeError("API down")):
        with patch("tool.stage2.layers.l5_tests.time.sleep"):
            result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    content = list(result.values())[0]
    assert "TODO" in content
    # Must still produce valid Python
    ast.parse(content)


def test_api_failure_never_raises():
    g = _make_generator()
    with patch.object(g, "_call_fixture_api", side_effect=Exception("boom")):
        with patch("tool.stage2.layers.l5_tests.time.sleep"):
            result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    assert isinstance(result, dict)


def test_spark_fixture_in_output():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("etl_orders_daily", SPEC_BLOCKS)
    content = list(result.values())[0]
    assert "SparkSession.builder.master" in content
    assert 'scope="session"' in content


def test_job_name_in_output():
    g = _make_generator()
    with patch.object(g, "_generate_fixture_data", return_value={}):
        result = g.generate("my_custom_job", SPEC_BLOCKS)
    content = list(result.values())[0]
    assert "my_custom_job" in content


def test_qa6_warns_for_missing_transform():
    from tool.stage2.qa.qa_pipeline import QAPipeline

    pipeline = QAPipeline()
    spec_blocks = [{"transform_id": "missing_transform", "transform_type": "derive"}]
    generated_tests = {"tests/test_job.py": "def test_other_transform_standard(): pass"}
    findings = pipeline._run_qa6_test_coverage(spec_blocks, generated_tests)
    assert len(findings) == 1
    assert findings[0]["gate"] == "QA-6"
    assert findings[0]["severity"] == "WARNING"
    assert "missing_transform" in findings[0]["message"]


def test_qa6_no_warning_when_covered():
    from tool.stage2.qa.qa_pipeline import QAPipeline

    pipeline = QAPipeline()
    spec_blocks = [{"transform_id": "source_orders", "transform_type": "source_read"}]
    generated_tests = {"tests/test_job.py": "def test_source_orders_standard(spark): pass"}
    findings = pipeline._run_qa6_test_coverage(spec_blocks, generated_tests)
    assert findings == []


def test_qa6_wired_into_qa_pipeline():
    from tool.stage2.qa.qa_pipeline import QAPipeline

    pipeline = QAPipeline()
    spec_blocks = [{"transform_id": "uncovered_t", "transform_type": "join"}]
    result = pipeline.run({}, spec_blocks, {"generated_tests": {}})
    assert "QA-6" in result.findings


def test_empty_spec_blocks_produces_valid_output():
    g = _make_generator()
    result = g.generate("empty_job", [])
    content = list(result.values())[0]
    ast.parse(content)
    assert "test_empty_job" in content
