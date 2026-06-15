import pytest
from pathlib import Path
from tool.stage1.parsers.adf_parser import AdfParser
from tool.stage1.parsers.ssis_parser import SsisParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
ADF_PIPELINE = FIXTURE_DIR / "sample_adf_pipeline.json"
SSIS_FIXTURE = FIXTURE_DIR / "sample_ssis.dtsx"


@pytest.fixture
def parsed():
    return AdfParser().parse(str(ADF_PIPELINE))


def test_parse_copy_activity_source(parsed):
    sources = parsed["data_sources"]
    assert len(sources) >= 1
    src = next((s for s in sources if s.get("connection_type") == "jdbc"), None)
    assert src is not None
    assert "Orders" in src.get("query_or_path", "")


def test_parse_copy_activity_sink(parsed):
    transforms = parsed["transformations"]
    sink = next((t for t in transforms if t.get("transform_type") == "target_write"), None)
    assert sink is not None
    assert sink.get("write_mode") in ("truncate_insert", "upsert")


def test_parse_sp_activity(parsed):
    transforms = parsed["transformations"]
    sp = next((t for t in transforms if t.get("transform_type") == "sp_call"), None)
    assert sp is not None
    assert "ValidateOrders" in sp.get("sp_name", "")


def test_parse_schedule_trigger(parsed):
    cf = parsed["control_flow"]
    cron = cf.get("cron_expression")
    assert cron is not None
    assert "cron(" in cron


def test_parse_dependency_chain(parsed):
    cf = parsed["control_flow"]
    adj = cf.get("adjacency_list", [])
    assert len(adj) >= 1
    # SP depends on Copy
    sp_dep = next(
        (e for e in adj if "ValidateOrders" in e.get("to_task", "") or "validate" in e.get("to_task", "").lower()),
        None,
    )
    assert sp_dep is not None


def test_azure_linked_service_flagged(tmp_path):
    pipeline = {
        "name": "azure_test",
        "properties": {
            "activities": [
                {
                    "name": "Copy from ADLS",
                    "type": "Copy",
                    "dependsOn": [],
                    "typeProperties": {
                        "source": {"type": "AzureDataLakeStoreSource"},
                        "sink": {"type": "SqlSink", "writeBehavior": "insert"},
                    },
                    "inputs": [
                        {
                            "referenceName": "AdlsLinkedService",
                            "type": "AzureDataLakeStoreLinkedService",
                        }
                    ],
                    "outputs": [],
                }
            ]
        },
    }
    import json

    f = tmp_path / "azure_test.json"
    f.write_text(json.dumps(pipeline))
    result = AdfParser().parse(str(f))
    assert any("VERIFY S3 PATH" in item for item in result["manual_items"])


def test_foreach_flagged_manual(parsed):
    transforms = parsed["transformations"]
    foreach = next(
        (t for t in transforms if "FOREACH" in t.get("flag", "").upper() or "ForEach" in t.get("name", "")),
        None,
    )
    assert foreach is not None
    assert "MANUAL" in foreach.get("flag", "")


def test_dataflow_subparser(parsed):
    transforms = parsed["transformations"]
    df_transforms = [
        t
        for t in transforms
        if t.get("transform_type") in ("source_read", "target_write", "filter", "derive", "aggregate")
    ]
    assert len(df_transforms) >= 3


def test_adf_output_schema_matches_ssis(parsed):
    ssis_parsed = SsisParser().parse(str(SSIS_FIXTURE))
    adf_keys = set(parsed.keys())
    ssis_keys = set(ssis_parsed.keys())
    assert adf_keys == ssis_keys, (
        f"Schema mismatch. ADF extra: {adf_keys - ssis_keys}, SSIS extra: {ssis_keys - adf_keys}"
    )


def test_parameters_extracted(parsed):
    params = parsed["parameters"]
    names = [p["name"] for p in params]
    assert "batchId" in names or "targetEnv" in names


def test_manual_item_count_matches_manual_items(parsed):
    assert parsed["manual_item_count"] == len(parsed["manual_items"])


def test_confidence_score_in_range(parsed):
    score = parsed["confidence_score"]
    assert 0 <= score <= 100


def test_job_name_extracted(parsed):
    assert parsed["job_name"] == "etl_orders_adf"


def test_source_system_is_adf(parsed):
    assert parsed["source_system"] == "ADF"
