import json
import time

import yaml


class L3ExpressionTranslator:
    def __init__(self, prompts_path: str = "tool/config/llm_prompts.yaml"):
        import anthropic
        self.client = anthropic.Anthropic()
        with open(prompts_path) as f:
            self.prompts = yaml.safe_load(f)

    def translate(self, expression_context: dict) -> dict:
        """Translate a single ETL expression to PySpark Column API.

        Never raises — always returns a result dict (manual_review_required=True on failure).
        """
        for attempt in range(2):
            try:
                raw = self._call_api(expression_context)
                return self._parse_response(raw, expression_context)
            except Exception as exc:
                if attempt == 0:
                    time.sleep(5)
                    continue
                return self._manual_fallback(expression_context, str(exc))
        return self._manual_fallback(expression_context, "unknown error")

    def _call_api(self, ctx: dict) -> str:
        expr_type = ctx.get("expression_type", "derive")
        prompt_key = "script_component_translation" if expr_type == "custom_logic" else "expression_translation"
        prompt_template = self.prompts[prompt_key]
        system_message = prompt_template["system"]
        user_message = prompt_template["user"].format(
            source_system=ctx.get("source_system", ""),
            expression_type=ctx.get("expression_type", ""),
            input_columns=ctx.get("input_columns", []),
            expression=ctx.get("expression", ""),
            business_rule_text=ctx.get("business_rule_text", ""),
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system_message,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _parse_response(self, raw: str, ctx: dict) -> dict:
        try:
            result = json.loads(raw.strip())
            assert "expression" in result
            assert "confidence" in result
            assert isinstance(result["confidence"], int)
            result.setdefault("behaviour_notes", [])
            result.setdefault("manual_review_required", result["confidence"] < 70)
            if result["confidence"] < 70:
                result["manual_review_required"] = True
            return result
        except (json.JSONDecodeError, AssertionError, KeyError) as exc:
            return {
                "expression": f"[MANUAL: L3 PARSE ERROR — original: {ctx.get('expression', '')}]",
                "confidence": 0,
                "behaviour_notes": [str(exc)],
                "manual_review_required": True,
            }

    def _manual_fallback(self, ctx: dict, error: str) -> dict:
        return {
            "expression": f"[MANUAL: L3 FAILURE — original: {ctx.get('expression', '')}]",
            "confidence": 0,
            "behaviour_notes": [error],
            "manual_review_required": True,
        }
