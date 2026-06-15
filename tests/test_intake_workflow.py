import csv
import subprocess
import sys
from pathlib import Path

import yaml

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SSIS_FIXTURE = FIXTURE_DIR / "sample_ssis.dtsx"
ADF_FIXTURE = FIXTURE_DIR / "sample_adf_pipeline.json"


# ── pre-screen ────────────────────────────────────────────────────────────────


def test_prescreen_writes_csv(tmp_path):
    from tool.prescreen.classifier import classify_file

    row = classify_file(str(SSIS_FIXTURE))
    csv_path = tmp_path / "result.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert "eligible" in rows[0]
    assert "source_file" in rows[0]
    assert "recommended_tool" in rows[0]


def test_prescreen_ssis_fixture_eligible():
    from tool.prescreen.classifier import classify_file

    row = classify_file(str(SSIS_FIXTURE))
    assert row["eligible"] == "TRUE"
    assert row["source_type"] == "SSIS"


def test_prescreen_adf_fixture_eligible():
    from tool.prescreen.classifier import classify_file

    row = classify_file(str(ADF_FIXTURE))
    assert row["eligible"] == "TRUE"
    assert row["source_type"] == "ADF_PIPELINE"


def test_prescreen_unsupported_file_not_eligible(tmp_path):
    from tool.prescreen.classifier import classify_file

    bad = tmp_path / "file.csv"
    bad.write_text("a,b,c")
    row = classify_file(str(bad))
    assert row["eligible"] == "FALSE"
    assert "UNSUPPORTED" in row["blocking_reason"]


def test_prescreen_script_component_reduces_confidence(tmp_path):
    from tool.prescreen.classifier import classify_file

    dtsx = tmp_path / "script.dtsx"
    dtsx.write_text(
        """<?xml version="1.0"?>
<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts"
    DTS:ExecutableType="SSIS.Package.3" DTS:ObjectName="script_pkg">
  <DTS:Executables>
    <DTS:Executable DTS:ExecutableType="Microsoft.Pipeline" DTS:ObjectName="DFT">
      <DTS:ObjectData>
        <pipeline:components xmlns:pipeline="www.microsoft.com/SqlServer/Dts/Pipeline">
          <pipeline:component pipeline:componentClassID="DTSTransform.ScriptComponent"
              pipeline:name="Script" />
        </pipeline:components>
      </DTS:ObjectData>
    </DTS:Executable>
  </DTS:Executables>
</DTS:Executable>""",
        encoding="utf-8",
    )
    row = classify_file(str(dtsx))
    assert int(row["estimated_confidence"]) < 100


# ── stage1 ────────────────────────────────────────────────────────────────────


def test_stage1_writes_requirements_doc(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "tool.cli", "stage1", str(SSIS_FIXTURE), "--output", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    reqs = tmp_path / "etl_orders_daily" / "REQUIREMENTS.md"
    assert reqs.exists()
    content = reqs.read_text()
    assert "stage2_permitted" in content
    assert "job_name" in content


def test_stage1_sets_stage2_permitted_false(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "tool.cli", "stage1", str(SSIS_FIXTURE), "--output", str(tmp_path)],
        capture_output=True,
    )
    reqs = tmp_path / "etl_orders_daily" / "REQUIREMENTS.md"
    import re

    content = reqs.read_text()
    fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert fm_match, "No YAML front-matter found"
    fm = yaml.safe_load(fm_match.group(1))
    assert fm.get("stage2_permitted") is False


# ── stage2 approval gate ──────────────────────────────────────────────────────


def test_stage2_requires_stage2_permitted_true(tmp_path):
    reqs = tmp_path / "REQUIREMENTS.md"
    reqs.write_text(
        "---\njob_name: test_job\nstage2_permitted: false\n---\n\n# Test\n",
        encoding="utf-8",
    )
    from tool.stage2.spec_parser import SpecParser

    spec = SpecParser().parse(str(reqs))
    assert spec.get("stage2_permitted") is False

    # Importing cli and calling stage2 with stage2_permitted=false should raise ValueError
    from click.testing import CliRunner
    from tool.cli import stage2

    runner = CliRunner()
    result = runner.invoke(stage2, [str(reqs)])
    assert result.exit_code != 0 or (result.exception and isinstance(result.exception, ValueError))


def test_stage2_runs_when_permitted(tmp_path):
    reqs = tmp_path / "REQUIREMENTS.md"
    # Write a minimal valid spec with stage2_permitted: true
    reqs.write_text(
        (
            "---\n"
            "job_name: test_job\n"
            "stage2_permitted: true\n"
            "glue_version: '4.0'\n"
            "iam_role_arn: '${var.role}'\n"
            "scripts_location: 's3://${var.bucket}/'\n"
            "cron_expression: 'cron(0 2 * * ? *)'\n"
            "staging_tables: []\n"
            "phases: []\n"
            "---\n\n# Test\n"
        ),
        encoding="utf-8",
    )
    from click.testing import CliRunner
    from tool.cli import stage2

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(stage2, [str(reqs), "--output", str(out_dir)])
    assert result.exit_code == 0, result.output


# ── full pipeline ──────────────────────────────────────────────────────────────


def test_full_pipeline_skip_gate(tmp_path):
    from click.testing import CliRunner
    from tool.cli import pipeline

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            pipeline,
            [str(SSIS_FIXTURE), "--skip-approval-gate", "--output", str(tmp_path / "generated")],
        )
    assert result.exit_code == 0, result.output + (result.exception and str(result.exception) or "")
    assert "Stage 2 complete" in result.output


def test_full_pipeline_without_skip_gate_stops_at_stage1(tmp_path):
    from click.testing import CliRunner
    from tool.cli import pipeline

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(pipeline, [str(SSIS_FIXTURE)])
    assert result.exit_code == 0
    assert "Stage 1 complete" in result.output
    assert "Stage 2 complete" not in result.output
