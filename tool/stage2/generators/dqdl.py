import json


class DqdlGenerator:
    def generate(self, job_name: str, spec_blocks: list, dq_rules: list = None) -> dict:
        """Generate Glue DQDL ruleset JSON. Returns {filename: json_content}."""
        rules = []

        # Baseline: RowCount > 0 for every source/staging table
        source_tables = set()
        primary_keys = set()
        for block in spec_blocks:
            ttype = block.get("transform_type", "")
            if ttype == "source_read":
                table = block.get("query_or_path", "") or block.get("source_id", "")
                if table:
                    source_tables.add(table)
            if ttype in ("source_read", "target_write"):
                pk = block.get("primary_key") or block.get("upsert_key")
                if pk:
                    primary_keys.add((block.get("target_table", block.get("source_id", "")), pk))

        for table in sorted(source_tables):
            rules.append({
                "rule_type": "RowCount",
                "expression": "> 0",
                "applies_to": table,
            })

        for table, pk in sorted(primary_keys):
            rules.append({
                "rule_type": "IsComplete",
                "expression": "= 1",
                "applies_to": pk,
            })
            rules.append({
                "rule_type": "IsUnique",
                "expression": "= 1",
                "applies_to": pk,
            })

        # If no sources found, add a generic RowCount rule
        if not rules:
            rules.append({
                "rule_type": "RowCount",
                "expression": "> 0",
                "applies_to": f"{job_name}_output",
            })

        # Additional rules from §10 dq_rules
        for rule in (dq_rules or []):
            rule_type = rule.get("check_type", "")
            column = rule.get("column", "")
            if rule_type == "null_check":
                rules.append({"rule_type": "IsComplete", "expression": "= 1", "applies_to": column})
            elif rule_type == "range_check":
                low = rule.get("min", 0)
                high = rule.get("max", 9999999)
                rules.append({
                    "rule_type": "ColumnValues",
                    "expression": f"between {low} and {high}",
                    "applies_to": column,
                })
            elif rule_type == "referential_integrity":
                ref_table = rule.get("reference_table", "")
                rules.append({
                    "rule_type": "ReferentialIntegrity",
                    "expression": f"references {ref_table}",
                    "applies_to": column,
                })

        ruleset = {"ruleset_name": f"{job_name}_dq", "rules": rules}
        content = json.dumps(ruleset, indent=2)
        filename = f"generated/dqdl/{job_name}.json"
        return {filename: content}
