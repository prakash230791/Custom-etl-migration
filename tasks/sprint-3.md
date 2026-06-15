# tasks/sprint-3.md
# Sprint 3: L3 — LLM Expression Translation

**Duration:** Week 4 (1 week)  
**Prerequisite:** Sprint 2 merged to main  
**Branch:** `feature/sprint-3-l3-expressions`  
**Requires:** Claude API key in GitHub Actions secrets as `ANTHROPIC_API_KEY`

---

## Read First

1. `CLAUDE.md`
2. `Custom_Tool_Implementation.docx` §5.3 (L3 — LLM Expression Translation)
3. `tool/stage2/layers/l4_idiom.py` — L3 output goes directly into L4 scan; understand the interface

---

## What to Build

- `tool/stage2/layers/l3_expressions.py` — Claude API integration for expression translation
- `tool/config/llm_prompts.yaml` — L3 prompt templates (load from file, not hardcoded)
- Update `tool/stage2/qa/qa_pipeline.py` — wire in QA-3 (expression confidence gate)

---

## Module: l3_expressions.py

### Input
```python
{
    "source_system": "SSIS",       # or "ADF"
    "expression_type": "derive",   # matches transform_type in etl-spec
    "input_columns": ["CustomerName", "OrderDate"],
    "expression": "ISNULL([CustomerName]) ? \"Unknown\" : TRIM([CustomerName])",
    "business_rule_text": "Default customer name to Unknown if not provided"
}
```

### Output
```python
{
    "expression": "when(col('CustomerName').isNull(), 'Unknown').otherwise(trim(col('CustomerName')))",
    "confidence": 88,
    "behaviour_notes": [],
    "manual_review_required": False
}
```

### L3 Rules (from §5.3)

1. One API call per expression — never batch multiple expressions in one call
2. Confidence < 70 → set `manual_review_required: True`; Stage 2 inserts [MANUAL] placeholder
3. API call fails → retry once after 5 seconds; if second call fails → treat as confidence < 70
4. Invalid JSON response → log to conversion_notes.md → [MANUAL: L3 PARSE ERROR]
5. expression_type = `custom_logic` → use extended prompt (Script Component C# translation)
6. Never block Stage 2 execution on L3 failure — always fall back to [MANUAL]

### L3 Prompt (stored in config/llm_prompts.yaml, key: expression_translation)

Load the prompt from `config/llm_prompts.yaml` at runtime — never hardcode it in the module.

The prompt must instruct the model to:
- Return ONLY valid JSON, no prose, no markdown fences
- Use PySpark Column API only — no function definitions, no imports
- Prefer built-ins over UDF
- Add `# BEHAVIOUR NOTE:` comment above expression when semantics differ
- Set `manual_review_required: true` when confidence < 70

The JSON response schema:
```json
{
  "expression": "<PySpark Column API expression string>",
  "confidence": 85,
  "behaviour_notes": ["note 1"],
  "manual_review_required": false
}
```

### Implementation Pattern

```python
import anthropic
import json
import time
import yaml
from pathlib import Path

class L3ExpressionTranslator:
    def __init__(self, prompts_path: str = "tool/config/llm_prompts.yaml"):
        self.client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
        with open(prompts_path) as f:
            self.prompts = yaml.safe_load(f)

    def translate(self, expression_context: dict) -> dict:
        """
        Translate a single ETL expression to PySpark Column API.
        Never raises — always returns a result dict (with manual_review_required=True on failure).
        """
        for attempt in range(2):
            try:
                result = self._call_api(expression_context)
                return self._parse_response(result)
            except Exception as e:
                if attempt == 0:
                    time.sleep(5)
                    continue
                return self._manual_fallback(expression_context, str(e))

    def _call_api(self, ctx: dict) -> str:
        prompt_template = self.prompts["expression_translation"]
        user_message = prompt_template["user"].format(**ctx)
        system_message = prompt_template["system"]

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system_message,
            messages=[{"role": "user", "content": user_message}]
        )
        return response.content[0].text

    def _parse_response(self, raw: str) -> dict:
        try:
            result = json.loads(raw.strip())
            # Validate required fields
            assert "expression" in result
            assert "confidence" in result
            assert isinstance(result["confidence"], int)
            return result
        except (json.JSONDecodeError, AssertionError, KeyError) as e:
            return {"expression": None, "confidence": 0, "behaviour_notes": [str(e)], "manual_review_required": True}

    def _manual_fallback(self, ctx: dict, error: str) -> dict:
        return {
            "expression": f"[MANUAL: L3 FAILURE — original: {ctx.get('expression', '')}]",
            "confidence": 0,
            "behaviour_notes": [error],
            "manual_review_required": True
        }
```

---

## config/llm_prompts.yaml

Create this file. L3 will fail if it doesn't exist.

```yaml
expression_translation:
  system: |
    You are a PySpark code generation engine. Translate a single ETL expression
    into a PySpark Column API expression. You produce ONLY a JSON object.
    
    RULES (non-negotiable):
    1. Produce ONLY a valid Python expression compatible with PySpark Column API.
       No function definitions. No imports. No prose inside the expression.
    2. Use PySpark built-in functions wherever possible.
       Prefer: when/otherwise over if/else; date_format over strftime;
       regexp_replace over re.sub; coalesce over isnull checks.
       Do NOT generate udf() unless the logic is genuinely non-vectorisable.
    3. If the PySpark expression differs in behaviour from the source expression
       (null handling, precision, timezone, case sensitivity, row order),
       add a BEHAVIOUR NOTE as a Python comment inside the expression field.
    4. Output ONLY this JSON object — no other text, no markdown backticks:
       {"expression": "...", "confidence": 85, "behaviour_notes": ["..."], "manual_review_required": false}
    5. confidence < 70 -> set manual_review_required: true.

  user: |
    Source system: {source_system}
    Expression type: {expression_type}
    Input columns available: {input_columns}
    Original expression: {expression}
    Business rule description (if available): {business_rule_text}
    
    Translate to PySpark Column API expression.

script_component_translation:
  system: |
    You are a Python code migration engine. Translate a C# Script Component
    body from SSIS into equivalent Python code suitable for a PySpark Glue job.
    
    RULES:
    1. Translate the algorithm faithfully — do not simplify business logic.
    2. Use PySpark DataFrame API where possible.
    3. For row-by-row logic that cannot be vectorised: use df.rdd.map() with a clear comment.
    4. Output ONLY a JSON object:
       {"expression": "...", "confidence": 70, "behaviour_notes": ["..."], "manual_review_required": false}

  user: |
    C# Script Component source code to translate to Python:
    
    {expression}
    
    Input columns: {input_columns}
    Business rule description (if available): {business_rule_text}

# Placeholder for L5 (Sprint 4)
test_fixture_generation:
  system: |
    You generate pytest fixture data for PySpark DataFrame tests.
    Output ONLY a JSON array of row dicts matching the schema provided.
    
  user: |
    Schema: {schema}
    Transform type: {transform_type}
    Business rule: {business_rule_text}
    Generate 5 representative test rows (including edge cases: nulls, boundaries).
```

---

## Update QA Pipeline (QA-3)

Wire QA-3 into `tool/stage2/qa/qa_pipeline.py`:

```python
def _run_qa3_expression_confidence(self, l3_results: list[dict]) -> list[dict]:
    """
    QA-3: Check all L3 expression results have confidence >= 70.
    Low-confidence expressions must already be replaced with [MANUAL] by L3 before reaching here.
    This gate verifies no high-confidence expression has behaviour notes that weren't surfaced.
    """
    findings = []
    for result in l3_results:
        if result.get("manual_review_required") and result.get("confidence", 100) >= 70:
            findings.append({
                "gate": "QA-3",
                "severity": "WARNING",
                "message": f"Expression marked manual_review_required despite confidence {result['confidence']}"
            })
    return findings
```

---

## Mock Pattern for Tests

**L3 must never make live API calls in tests.** Use `unittest.mock.patch`:

```python
# tests/test_l3_expressions.py

from unittest.mock import patch, MagicMock
from tool.stage2.layers.l3_expressions import L3ExpressionTranslator

MOCK_HIGH_CONFIDENCE_RESPONSE = json.dumps({
    "expression": "when(col('CustomerName').isNull(), 'Unknown').otherwise(trim(col('CustomerName')))",
    "confidence": 88,
    "behaviour_notes": [],
    "manual_review_required": False
})

MOCK_LOW_CONFIDENCE_RESPONSE = json.dumps({
    "expression": "col('SomeComplexField')",
    "confidence": 45,
    "behaviour_notes": ["Could not determine exact behaviour"],
    "manual_review_required": True
})

def test_high_confidence_returns_expression():
    with patch.object(L3ExpressionTranslator, '_call_api', return_value=MOCK_HIGH_CONFIDENCE_RESPONSE):
        translator = L3ExpressionTranslator()
        result = translator.translate({
            "source_system": "SSIS",
            "expression_type": "derive",
            "input_columns": ["CustomerName"],
            "expression": "ISNULL([CustomerName]) ? \"Unknown\" : TRIM([CustomerName])",
            "business_rule_text": ""
        })
    assert result["confidence"] == 88
    assert result["manual_review_required"] == False
    assert "CustomerName" in result["expression"]

def test_low_confidence_sets_manual_flag():
    with patch.object(L3ExpressionTranslator, '_call_api', return_value=MOCK_LOW_CONFIDENCE_RESPONSE):
        translator = L3ExpressionTranslator()
        result = translator.translate({...})
    assert result["manual_review_required"] == True

def test_api_failure_falls_back_to_manual():
    with patch.object(L3ExpressionTranslator, '_call_api', side_effect=Exception("Timeout")):
        translator = L3ExpressionTranslator()
        result = translator.translate({...})
    assert result["manual_review_required"] == True
    assert "[MANUAL: L3 FAILURE" in result["expression"]

def test_invalid_json_response_falls_back():
    with patch.object(L3ExpressionTranslator, '_call_api', return_value="not valid json"):
        translator = L3ExpressionTranslator()
        result = translator.translate({...})
    assert result["manual_review_required"] == True

def test_never_raises():
    """L3 must never propagate an exception — always returns a dict."""
    with patch.object(L3ExpressionTranslator, '_call_api', side_effect=RuntimeError("boom")):
        translator = L3ExpressionTranslator()
        result = translator.translate({...})
    assert isinstance(result, dict)
    assert "manual_review_required" in result
```

---

## Acceptance Criteria — Sprint 3 Complete When ALL Pass

- [ ] `l3_expressions.py` loads prompt from `config/llm_prompts.yaml` — not hardcoded
- [ ] High confidence (≥70) → returns expression string
- [ ] Low confidence (<70) → returns [MANUAL] placeholder with `manual_review_required: True`
- [ ] API failure → retries once → falls back to [MANUAL]; never raises exception
- [ ] Invalid JSON response → [MANUAL: L3 PARSE ERROR]; never raises exception
- [ ] `config/llm_prompts.yaml` contains both `expression_translation` and `script_component_translation` keys
- [ ] QA-3 wired into qa_pipeline.py
- [ ] All tests use mocked API — no live API calls in CI
- [ ] `pytest tests/ -v` → 100% pass
- [ ] `ruff check tool/` → zero errors
- [ ] PR opened against main
