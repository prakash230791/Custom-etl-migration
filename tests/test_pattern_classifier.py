import pytest
from tool.stage1.analysers.pattern_classifier import PatternClassifier


@pytest.fixture
def classifier():
    return PatternClassifier()


def _make_parsed(transforms, adjacency=None):
    return {
        "transformations": transforms,
        "control_flow": {"adjacency_list": adjacency or []},
    }


def test_detects_three_phase_pattern(classifier):
    parsed = _make_parsed(
        [
            {
                "transform_id": "src1",
                "transform_type": "source_read",
                "target_table": "staging.tmp_orders",
                "sql_statement": "",
                "name": "source1",
            },
            {
                "transform_id": "sp1",
                "transform_type": "sp_call",
                "sp_name": "dbo.usp_Process",
                "sql_statement": "",
                "name": "sp1",
            },
            {
                "transform_id": "load1",
                "transform_type": "target_write",
                "target_table": "public.orders",
                "sql_statement": "",
                "name": "load orders",
            },
        ]
    )
    result = classifier.classify(parsed)
    assert result["pattern"] == "THREE_PHASE_STATIC_LOAD"


def test_detects_general_etl(classifier):
    parsed = _make_parsed(
        [
            {
                "transform_id": "t1",
                "transform_type": "join",
                "sql_statement": "",
                "name": "join",
                "target_table": "",
            },
        ]
    )
    result = classifier.classify(parsed)
    assert result["pattern"] == "GENERAL_ETL"


def test_builds_sp_dependency_graph(classifier):
    parsed = _make_parsed(
        transforms=[
            {
                "transform_id": "sp_init",
                "transform_type": "sp_call",
                "sp_name": "sp_init",
                "sql_statement": "",
                "name": "sp_init",
            },
            {
                "transform_id": "sp_enrich",
                "transform_type": "sp_call",
                "sp_name": "sp_enrich",
                "sql_statement": "",
                "name": "sp_enrich",
            },
        ],
        adjacency=[
            {"from_task": "sp_init", "to_task": "sp_enrich"},
        ],
    )
    result = classifier.classify(parsed)
    dag = result["sp_dependency_graph"]
    assert "sp_init" in dag
    assert "sp_enrich" in dag
    assert "sp_init" in dag["sp_enrich"]["depends_on"]


def test_identifies_parallel_groups(classifier):
    parsed = _make_parsed(
        transforms=[
            {
                "transform_id": "sp_init",
                "transform_type": "sp_call",
                "sp_name": "sp_init",
                "sql_statement": "",
                "name": "sp_init",
            },
            {
                "transform_id": "sp_a",
                "transform_type": "sp_call",
                "sp_name": "sp_a",
                "sql_statement": "",
                "name": "sp_a",
            },
            {
                "transform_id": "sp_b",
                "transform_type": "sp_call",
                "sp_name": "sp_b",
                "sql_statement": "",
                "name": "sp_b",
            },
        ],
        adjacency=[
            {"from_task": "sp_init", "to_task": "sp_a"},
            {"from_task": "sp_init", "to_task": "sp_b"},
        ],
    )
    result = classifier.classify(parsed)
    groups = result["parallel_groups"]
    assert any(len(g) >= 2 for g in groups)


def test_empty_transforms_gives_general_etl(classifier):
    parsed = _make_parsed([])
    result = classifier.classify(parsed)
    assert result["pattern"] == "GENERAL_ETL"


def test_phase_boundaries_populated(classifier):
    parsed = _make_parsed(
        [
            {
                "transform_id": "src1",
                "transform_type": "source_read",
                "target_table": "",
                "sql_statement": "",
                "name": "src1",
            },
            {
                "transform_id": "sp1",
                "transform_type": "sp_call",
                "sp_name": "sp1",
                "sql_statement": "",
                "name": "sp1",
            },
        ]
    )
    result = classifier.classify(parsed)
    assert "phase_boundaries" in result
    pb = result["phase_boundaries"]
    assert "phase1_tasks" in pb
    assert "phase2_tasks" in pb
    assert "phase3_tasks" in pb
