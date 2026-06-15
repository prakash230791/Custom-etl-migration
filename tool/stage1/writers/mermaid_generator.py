"""Mermaid generator — Sprint 1 implementation."""


class MermaidGenerator:
    def generate_sp_dag_mermaid(self, sp_dependency_graph: dict) -> str:
        if not sp_dependency_graph:
            return '```mermaid\nflowchart TD\n    no_sps["No SP dependencies"]\n```'
        lines = ["```mermaid", "flowchart TD"]
        for sp_id in sp_dependency_graph:
            lines.append(f'    {sp_id}["{sp_id}"]')
        for sp_id, info in sp_dependency_graph.items():
            for dep in info.get("depends_on", []):
                lines.append(f"    {dep} --> {sp_id}")
        lines.append("```")
        return "\n".join(lines)
