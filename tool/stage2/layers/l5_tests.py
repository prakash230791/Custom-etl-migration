import json
import time

import yaml
from jinja2 import Environment, FileSystemLoader


_DEFAULT_SCHEMA_FIELDS = 'StructField("id", IntegerType(), True)'
_DEFAULT_INPUT = "[(1, ), (2, )]"
_DEFAULT_NULL = "[(None, )]"


class L5TestGenerator:
    def __init__(
        self,
        prompts_path: str = "tool/config/llm_prompts.yaml",
        templates_dir: str = "tool/templates",
    ):
        import anthropic

        self.client = anthropic.Anthropic()
        with open(prompts_path) as f:
            self.prompts = yaml.safe_load(f)
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            keep_trailing_newline=True,
        )

    def generate(self, job_name: str, spec_blocks: list) -> dict:
        """Generate one pytest file for job_name. Returns {filename: content}."""
        transforms = []
        for block in spec_blocks:
            transform_id = block.get("transform_id", "unknown")
            transform_type = block.get("transform_type", "unknown")
            fixture = self._generate_fixture_data(block)
            transforms.append(
                {
                    "transform_id": transform_id,
                    "transform_type": transform_type,
                    "natural_language_description": self._describe(block),
                    "input_schema_fields": fixture.get("input_schema_fields", _DEFAULT_SCHEMA_FIELDS),
                    "output_schema_fields": fixture.get("output_schema_fields", _DEFAULT_SCHEMA_FIELDS),
                    "input_fixture_data": fixture.get("input_fixture_data", _DEFAULT_INPUT),
                    "null_fixture_data": fixture.get("null_fixture_data", _DEFAULT_NULL),
                }
            )

        template = self.env.get_template("unit_test_skeleton.j2")
        content = template.render(job_name=job_name, transforms=transforms)
        filename = f"tests/test_{job_name}.py"
        return {filename: content}

    def _describe(self, block: dict) -> str:
        ttype = block.get("transform_type", "transform")
        tid = block.get("transform_id", "")
        descriptions = {
            "source_read": f"Read source data for {tid}",
            "target_write": f"Write to target table for {tid}",
            "join": f"Join operation: {tid}",
            "filter": f"Filter rows for {tid}",
            "aggregate": f"Aggregate data for {tid}",
            "derive": f"Derive column for {tid}",
            "sp_call": f"Stored procedure call: {block.get('sp_name', tid)}",
            "union": f"Union datasets for {tid}",
            "window": f"Window function for {tid}",
            "sort": f"Sort data for {tid}",
        }
        return descriptions.get(ttype, f"{ttype}: {tid}")

    def _generate_fixture_data(self, block: dict) -> dict:
        """Call Claude API for fixture data. Falls back to stub on any failure."""
        for attempt in range(2):
            try:
                return self._call_fixture_api(block)
            except Exception:
                if attempt == 0:
                    time.sleep(5)
                    continue
                return self._stub_fixture(block)
        return self._stub_fixture(block)

    def _call_fixture_api(self, block: dict) -> dict:
        prompt = self.prompts["test_fixture_generation"]
        schema = json.dumps({k: v for k, v in block.items() if k in ("transform_type", "transform_id")})
        user_msg = prompt["user"].format(
            schema=schema,
            transform_type=block.get("transform_type", ""),
            business_rule_text=block.get("business_rule_text", ""),
        )
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=prompt["system"],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        parsed = json.loads(raw)
        return {
            "input_schema_fields": parsed.get("input_schema_fields", _DEFAULT_SCHEMA_FIELDS),
            "output_schema_fields": parsed.get("output_schema_fields", _DEFAULT_SCHEMA_FIELDS),
            "input_fixture_data": str(parsed.get("input_fixture_data", [(1,)])),
            "null_fixture_data": str(parsed.get("null_fixture_data", [(None,)])),
        }

    def _stub_fixture(self, block: dict) -> dict:
        tid = block.get("transform_id", "unknown")
        return {
            # Keep comments outside the StructType([...]) call to preserve valid Python syntax
            "input_schema_fields": 'StructField("id", IntegerType(), True)',
            "output_schema_fields": 'StructField("id", IntegerType(), True)',
            "input_fixture_data": f"[]  # TODO: add fixture data for {tid}",
            "null_fixture_data": f"[]  # TODO: add null fixture data for {tid}",
        }
