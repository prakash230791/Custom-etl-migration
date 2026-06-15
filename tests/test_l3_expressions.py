import json
from unittest.mock import MagicMock, patch

import pytest

MOCK_HIGH = json.dumps({
    "expression": "when(col('CustomerName').isNull(), 'Unknown').otherwise(trim(col('CustomerName')))",
    "confidence": 88,
    "behaviour_notes": [],
    "manual_review_required": False,
})

MOCK_LOW = json.dumps({
    "expression": "col('SomeComplexField')",
    "confidence": 45,
    "behaviour_notes": ["Could not determine exact behaviour"],
    "manual_review_required": True,
})

CTX = {
    "source_system": "SSIS",
    "expression_type": "derive",
    "input_columns": ["CustomerName"],
    "expression": 'ISNULL([CustomerName]) ? "Unknown" : TRIM([CustomerName])',
    "business_rule_text": "Default customer name to Unknown if null",
}


def _make_translator():
    with patch("anthropic.Anthropic"):
        from tool.stage2.layers.l3_expressions import L3ExpressionTranslator
        t = L3ExpressionTranslator.__new__(L3ExpressionTranslator)
        t.client = MagicMock()
        import yaml
        with open("tool/config/llm_prompts.yaml") as f:
            t.prompts = yaml.safe_load(f)
        return t


def test_high_confidence_returns_expression():
    t = _make_translator()
    with patch.object(t, "_call_api", return_value=MOCK_HIGH):
        result = t.translate(CTX)
    assert result["confidence"] == 88
    assert result["manual_review_required"] is False
    assert "CustomerName" in result["expression"]


def test_low_confidence_sets_manual_flag():
    t = _make_translator()
    with patch.object(t, "_call_api", return_value=MOCK_LOW):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True


def test_confidence_below_70_forces_manual_review():
    t = _make_translator()
    response = json.dumps({"expression": "col('x')", "confidence": 69, "behaviour_notes": []})
    with patch.object(t, "_call_api", return_value=response):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True


def test_confidence_at_70_not_forced_manual():
    t = _make_translator()
    response = json.dumps({"expression": "col('x')", "confidence": 70, "behaviour_notes": [], "manual_review_required": False})
    with patch.object(t, "_call_api", return_value=response):
        result = t.translate(CTX)
    assert result["manual_review_required"] is False


def test_api_failure_falls_back_to_manual():
    t = _make_translator()
    with patch.object(t, "_call_api", side_effect=Exception("Timeout")):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True
    assert "[MANUAL: L3 FAILURE" in result["expression"]


def test_api_failure_retries_once():
    t = _make_translator()
    call_count = {"n": 0}

    def flaky(*args, **kwargs):
        call_count["n"] += 1
        raise Exception("flaky")

    with patch.object(t, "_call_api", side_effect=flaky):
        with patch("tool.stage2.layers.l3_expressions.time.sleep"):
            result = t.translate(CTX)
    assert call_count["n"] == 2
    assert result["manual_review_required"] is True


def test_invalid_json_response_falls_back():
    t = _make_translator()
    with patch.object(t, "_call_api", return_value="not valid json at all"):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True
    assert "L3 PARSE ERROR" in result["expression"]


def test_missing_expression_field_falls_back():
    t = _make_translator()
    bad = json.dumps({"confidence": 90, "behaviour_notes": []})
    with patch.object(t, "_call_api", return_value=bad):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True


def test_missing_confidence_field_falls_back():
    t = _make_translator()
    bad = json.dumps({"expression": "col('x')", "behaviour_notes": []})
    with patch.object(t, "_call_api", return_value=bad):
        result = t.translate(CTX)
    assert result["manual_review_required"] is True


def test_never_raises():
    t = _make_translator()
    with patch.object(t, "_call_api", side_effect=RuntimeError("boom")):
        with patch("tool.stage2.layers.l3_expressions.time.sleep"):
            result = t.translate(CTX)
    assert isinstance(result, dict)
    assert "manual_review_required" in result


def test_script_component_uses_extended_prompt():
    t = _make_translator()
    calls = []

    def capture_call(ctx):
        calls.append(ctx)
        return MOCK_HIGH

    ctx = {**CTX, "expression_type": "custom_logic", "expression": "public void Input0_ProcessInputRow(Input0Buffer Row) { Row.OutCol = Row.InCol.Trim(); }"}
    with patch.object(t, "_call_api", side_effect=capture_call):
        t.translate(ctx)
    assert len(calls) == 1


def test_prompts_loaded_from_yaml_not_hardcoded():
    t = _make_translator()
    assert "expression_translation" in t.prompts
    assert "script_component_translation" in t.prompts
    assert "system" in t.prompts["expression_translation"]
    assert "user" in t.prompts["expression_translation"]


def test_behaviour_notes_preserved():
    t = _make_translator()
    response = json.dumps({
        "expression": "col('x')",
        "confidence": 80,
        "behaviour_notes": ["null handling differs"],
        "manual_review_required": False,
    })
    with patch.object(t, "_call_api", return_value=response):
        result = t.translate(CTX)
    assert "null handling differs" in result["behaviour_notes"]


def test_qa3_flags_manual_with_high_confidence():
    from tool.stage2.qa.qa_pipeline import QAPipeline
    pipeline = QAPipeline()
    l3_results = [{"expression": "col('x')", "confidence": 75, "manual_review_required": True}]
    findings = pipeline._run_qa3_expression_confidence(l3_results)
    assert len(findings) == 1
    assert findings[0]["gate"] == "QA-3"


def test_qa3_no_finding_for_normal_manual():
    from tool.stage2.qa.qa_pipeline import QAPipeline
    pipeline = QAPipeline()
    l3_results = [{"expression": "[MANUAL: L3 FAILURE]", "confidence": 0, "manual_review_required": True}]
    findings = pipeline._run_qa3_expression_confidence(l3_results)
    assert findings == []


def test_qa3_wired_into_qa_pipeline():
    from tool.stage2.qa.qa_pipeline import QAPipeline
    pipeline = QAPipeline()
    l3_results = [{"expression": "col('x')", "confidence": 72, "manual_review_required": True}]
    result = pipeline.run({}, [], {"l3_results": l3_results})
    assert "QA-3" in result.findings
