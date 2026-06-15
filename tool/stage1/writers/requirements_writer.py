"""Requirements writer — Sprint 1 implementation."""

from datetime import datetime, timezone
from pathlib import Path

import yaml


class RequirementsWriter:
    def write(self, parsed: dict, output_path: str) -> str:
        content = self._generate(parsed)
        Path(output_path).write_text(content, encoding="utf-8")
        return content

    def _generate(self, parsed: dict) -> str:
        sections = []
        sections.append(self._front_matter(parsed))
        sections.append(self._section_overview(parsed))
        sections.append(self._section_data_sources(parsed))
        sections.append(self._section_data_targets(parsed))
        sections.append(self._section_transformations(parsed))
        sections.append(self._section_business_rules(parsed))
        sections.append(self._section_control_flow(parsed))
        sections.append(self._section_error_handling(parsed))
        sections.append(self._section_schedule(parsed))
        sections.append(self._section_parameters(parsed))
        sections.append(self._section_dq_rules(parsed))
        sections.append(self._section_dependencies(parsed))
        sections.append(self._section_assumptions(parsed))
        return "\n\n".join(sections)

    def _front_matter(self, p: dict) -> str:
        fm = {
            "job_name": p.get("job_name", "unknown"),
            "source_system": p.get("source_system", "SSIS"),
            "source_file": p.get("source_file", ""),
            "target_system": "AWS_GLUE",
            "pattern": p.get("pattern", "GENERAL_ETL"),
            "stage1_generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stage1_version": "0.1.0",
            "manual_item_count": p.get("manual_item_count", 0),
            "confidence_score": p.get("confidence_score", 100),
            "stage1_approved_by": "",
            "stage1_approved_date": "",
            "business_sme_approved_by": "",
            "business_sme_approved_date": "",
            "stage2_permitted": False,
        }
        return "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---"

    def _section_overview(self, p: dict) -> str:
        return (
            f"# {p.get('job_name', 'Unknown Job')} — Requirements Document\n\n"
            f"## §1 Overview\n\n"
            f"**Source System:** {p.get('source_system', 'SSIS')}  \n"
            f"**Source File:** `{p.get('source_file', '')}`  \n"
            f"**Detected Pattern:** `{p.get('pattern', 'GENERAL_ETL')}`  \n"
            f"**Confidence Score:** {p.get('confidence_score', 0)}%  \n"
            f"**Manual Items:** {p.get('manual_item_count', 0)}\n\n"
            f"[REVIEWER: Verify the above overview is accurate before approving Stage 2.]"
        )

    def _section_data_sources(self, p: dict) -> str:
        lines = ["## §2 Data Sources"]
        sources = p.get("data_sources", [])
        if not sources:
            lines.append("No data sources detected.")
        for src in sources:
            sid = src.get("source_id", "unknown")
            lines.append(f"\n### Source: {sid}")
            lines.append(f"Connection: `{src.get('connection_ref', '')}`  ")
            lines.append(f"Query/Path: `{src.get('query_or_path', '')}`\n")
            block = {
                "transform_id": sid,
                "transform_type": "source_read",
                "source_id": sid,
                "connection_type": src.get("connection_type", "jdbc"),
                "connection_ref": src.get("connection_ref", ""),
                "source_type": src.get("source_type", "table"),
                "query_or_path": src.get("query_or_path", ""),
                "row_count_estimate": "[MANUAL INPUT REQUIRED]",
            }
            lines.append("```yaml\n" + yaml.dump(block, default_flow_style=False, sort_keys=False).strip() + "\n```")
        return "\n".join(lines)

    def _section_data_targets(self, p: dict) -> str:
        lines = ["## §3 Data Targets"]
        targets = [t for t in p.get("transformations", []) if t.get("transform_type") == "target_write"]
        if not targets:
            lines.append("No data targets detected.")
        for tgt in targets:
            tid = tgt.get("transform_id", "unknown")
            lines.append(f"\n### Target: {tid}")
            block = {
                "transform_id": tid,
                "transform_type": "target_write",
                "target_schema": tgt.get("target_schema", "[MANUAL INPUT REQUIRED]"),
                "target_table": tgt.get("target_table", "[MANUAL INPUT REQUIRED]"),
                "write_mode": tgt.get("write_mode", "truncate_insert"),
            }
            lines.append("```yaml\n" + yaml.dump(block, default_flow_style=False, sort_keys=False).strip() + "\n```")
        return "\n".join(lines)

    def _section_transformations(self, p: dict) -> str:
        lines = ["## §4 Transformations"]
        transforms = [t for t in p.get("transformations", []) if t.get("transform_type") not in ("target_write",)]
        if not transforms:
            lines.append("No transformations detected.")
        for t in transforms:
            tid = t.get("transform_id", "unknown")
            ttype = t.get("transform_type", "unknown")
            lines.append(f"\n### Transform: {tid} ({ttype})")
            if "flag" in t:
                lines.append(f"> **{t['flag']}**")
            block = {k: v for k, v in t.items() if k not in ("name",)}
            lines.append("```yaml\n" + yaml.dump(block, default_flow_style=False, sort_keys=False).strip() + "\n```")
        return "\n".join(lines)

    def _section_business_rules(self, p: dict) -> str:
        return "## §5 Business Rules\n\n[MANUAL INPUT REQUIRED: Describe business rules and validation logic here.]"

    def _section_control_flow(self, p: dict) -> str:
        lines = ["## §6 Control Flow"]
        mermaid = p.get("sp_dag_mermaid", "")
        if mermaid:
            lines.append("\n### SP Dependency DAG")
            lines.append(mermaid)
        cf = p.get("control_flow", {})
        adj = cf.get("adjacency_list", [])
        if adj:
            lines.append("\n### Adjacency List")
            block = {"adjacency_list": adj}
            lines.append("```yaml\n" + yaml.dump(block, default_flow_style=False, sort_keys=False).strip() + "\n```")
        return "\n".join(lines)

    def _section_error_handling(self, p: dict) -> str:
        lines = ["## §7 Error Handling"]
        handlers = p.get("error_handling", [])
        if not handlers:
            lines.append("No event handlers detected. Default Step Functions error handling applies.")
        for h in handlers:
            lines.append(f"\n**{h.get('handler_type', 'Unknown')}**: {', '.join(h.get('actions', []))}")
        return "\n".join(lines)

    def _section_schedule(self, p: dict) -> str:
        return "## §8 Schedule & Triggers\n\n[MANUAL INPUT REQUIRED: Specify schedule/trigger for this job.]"

    def _section_parameters(self, p: dict) -> str:
        lines = ["## §9 Parameters"]
        params = p.get("parameters", [])
        if not params:
            lines.append("No parameters detected.")
        for param in params:
            lines.append(
                f"- **{param.get('name', '')}** ({param.get('type', '')}): "
                f"{param.get('value', param.get('default_value', ''))}"
            )
        return "\n".join(lines)

    def _section_dq_rules(self, p: dict) -> str:
        return "## §10 Data Quality Rules\n\n[MANUAL INPUT REQUIRED: Define data quality checks for this job.]"

    def _section_dependencies(self, p: dict) -> str:
        lines = ["## §11 Dependencies"]
        deps = p.get("dependencies", [])
        if not deps:
            lines.append("No child package dependencies detected.")
        for dep in deps:
            lines.append(f"- **{dep.get('name', '')}** ({dep.get('type', '')}): `{dep.get('path', '')}`")
        return "\n".join(lines)

    def _section_assumptions(self, p: dict) -> str:
        lines = ["## §12 Assumptions & Gaps"]
        manual_items = p.get("manual_items", [])
        if not manual_items:
            lines.append("No manual items flagged.")
        for item in manual_items:
            lines.append(f"- {item}")
        lines.append("\n[REVIEWER: Address all items above before signing off Stage 1.]")
        return "\n".join(lines)
