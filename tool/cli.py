import sys
from pathlib import Path

import click


@click.group()
def main():
    pass


@main.command("pre-screen")
@click.argument("source_path")
@click.option("--output-csv", default=None)
def pre_screen(source_path, output_csv):
    """Pre-screen SSIS/ADF files for eligibility."""
    click.echo(f"Pre-screen: {source_path} (not implemented until Sprint 1)")


@main.command("stage1")
@click.argument("source_file")
@click.option("--output", default="requirements-docs/")
def stage1(source_file, output):
    """Parse SSIS/ADF file and generate requirements document."""
    from pathlib import Path
    from tool.stage1.parsers.ssis_parser import SsisParser
    from tool.stage1.analysers.pattern_classifier import PatternClassifier
    from tool.stage1.writers.mermaid_generator import MermaidGenerator
    from tool.stage1.writers.requirements_writer import RequirementsWriter

    path = Path(source_file)
    if path.suffix == ".dtsx":
        parsed = SsisParser().parse(str(path))
    elif path.suffix == ".json":
        from tool.stage1.parsers.adf_parser import AdfParser
        parsed = AdfParser().parse(str(path))
    else:
        click.echo(f"Unsupported file type: {path.suffix}. Expected .dtsx or .json")
        return
    classified = PatternClassifier().classify(parsed)
    parsed["pattern"] = classified["pattern"]
    parsed["sp_dependency_graph"] = classified["sp_dependency_graph"]
    mermaid = MermaidGenerator().generate_sp_dag_mermaid(classified["sp_dependency_graph"])
    parsed["sp_dag_mermaid"] = mermaid

    output_dir = Path(output) / parsed["job_name"]
    output_dir.mkdir(parents=True, exist_ok=True)
    requirements_path = output_dir / "REQUIREMENTS.md"
    RequirementsWriter().write(parsed, str(requirements_path))
    click.echo(f"Stage 1 complete: {requirements_path}")
    click.echo(f"Manual items: {parsed['manual_item_count']}")
    click.echo("Next: review and sign off REQUIREMENTS.md, then run stage2")


@main.command("stage2")
@click.argument("requirements_doc")
@click.option("--output", default="generated/")
def stage2(requirements_doc, output):
    """Generate Glue code from signed-off requirements document."""
    from tool.stage2.spec_parser import SpecParser
    from tool.stage2.layers.l1_scaffold import L1Scaffold
    from tool.stage2.layers.l2_pipeline import L2Pipeline
    from tool.stage2.qa.qa_pipeline import QAPipeline

    spec = SpecParser().parse(requirements_doc)
    if not spec:
        click.echo("ERROR: Could not parse requirements document.", err=True)
        sys.exit(1)

    job_name = spec.get("job_name", "unknown_job")
    output_dir = Path(output)

    l1 = L1Scaffold()
    artifacts = l1.render_all(spec)

    all_blocks = []
    for phase in spec.get("phases", []):
        all_blocks.extend(phase.get("tasks", []))

    l2 = L2Pipeline(job_name=job_name)
    snippets = l2.process_blocks(all_blocks)

    qa = QAPipeline()
    qa_result = qa.run(artifacts, all_blocks, spec)

    if qa_result.blocked:
        click.echo("ERROR: QA-1 security violation detected. Output blocked.", err=True)
        for v in qa_result.violations:
            if v.get("blocks_output"):
                click.echo(f"  {v['rule_id']}: {v['description']} (line {v['line_no']})", err=True)
        sys.exit(1)

    for rel_path, content in artifacts.items():
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        click.echo(f"  Written: {out_path}")

    if snippets.get("warnings"):
        for w in snippets["warnings"]:
            click.echo(f"WARNING: {w}")

    click.echo(f"Stage 2 complete. {len(artifacts)} artifacts written to {output_dir}")


@main.command("pipeline")
@click.argument("source_file")
@click.option("--skip-approval-gate", is_flag=True, default=False)
def pipeline(source_file, skip_approval_gate):
    """Run Stage 1 + Stage 2 end-to-end (testing only)."""
    click.echo(f"Pipeline: {source_file} (Stage 1 not yet implemented)")
