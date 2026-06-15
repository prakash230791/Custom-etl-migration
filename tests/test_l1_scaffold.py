import json
import pytest
from pathlib import Path
from tool.stage2.layers.l1_scaffold import L1Scaffold
import yaml


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_etl_spec.yaml"


@pytest.fixture
def context():
    return yaml.safe_load(FIXTURE_PATH.read_text())


@pytest.fixture
def scaffold():
    return L1Scaffold(templates_dir=str(Path(__file__).parent.parent / "tool" / "templates"))


def test_render_all_returns_five_keys(scaffold, context):
    outputs = scaffold.render_all(context)
    assert len(outputs) == 5


def test_glue_job_contains_required_elements(scaffold, context):
    outputs = scaffold.render_all(context)
    glue_job = next(v for k, v in outputs.items() if k.endswith(".py"))
    assert "GlueContext" in glue_job
    assert "job.commit()" in glue_job
    assert "getResolvedOptions" in glue_job


def test_step_functions_is_valid_json(scaffold, context):
    outputs = scaffold.render_all(context)
    asl = next(v for k, v in outputs.items() if k.endswith(".asl.json"))
    parsed = json.loads(asl)
    assert "States" in parsed


def test_step_functions_has_phase_states(scaffold, context):
    outputs = scaffold.render_all(context)
    asl = next(v for k, v in outputs.items() if k.endswith(".asl.json"))
    parsed = json.loads(asl)
    states = parsed["States"]
    assert "Phase1_Parallel" in states
    assert "Phase3_Parallel" in states
    assert "DataQualityGate" in states


def test_terraform_contains_glue_workflow(scaffold, context):
    outputs = scaffold.render_all(context)
    tf_files = [v for k, v in outputs.items() if k.endswith(".tf") and "glue-workflow" in k]
    assert tf_files
    assert "aws_glue_workflow" in tf_files[0]


def test_terraform_contains_eventbridge_rule(scaffold, context):
    outputs = scaffold.render_all(context)
    tf_files = [v for k, v in outputs.items() if k.endswith(".tf") and "eventbridge" in k]
    assert tf_files
    assert "aws_cloudwatch_event_rule" in tf_files[0]


def test_aurora_ddl_contains_unlogged_table(scaffold, context):
    outputs = scaffold.render_all(context)
    ddl = next(v for k, v in outputs.items() if k.endswith(".sql"))
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_orders" in ddl


def test_all_templates_render_without_error(scaffold, context):
    outputs = scaffold.render_all(context)
    for path, content in outputs.items():
        assert content is not None
        assert len(content) > 0
