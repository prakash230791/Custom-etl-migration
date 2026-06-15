import pytest
from pathlib import Path
from tool.stage1.parsers.ssis_parser import SsisParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ssis.dtsx"


@pytest.fixture
def parsed():
    return SsisParser().parse(str(FIXTURE))


def test_parse_returns_job_name(parsed):
    assert parsed["job_name"] == "etl_orders_daily"


def test_parse_extracts_oledb_source(parsed):
    sources = parsed["data_sources"]
    assert len(sources) >= 1
    src = sources[0]
    assert src.get("connection_ref") or src.get("query_or_path")
    assert "Orders" in src.get("query_or_path", "") or src.get("connection_type") == "jdbc"


def test_parse_never_stores_credentials(parsed):
    import json

    text = json.dumps(parsed)
    # The connection string value "[REDACTED — never store credentials]" should NOT be
    # present in the parsed result — the parser must only store the connection name/ref
    assert "[REDACTED" not in text


def test_parse_extracts_derived_column_expression(parsed):
    transforms = parsed["transformations"]
    derive = next((t for t in transforms if t.get("transform_type") == "derive"), None)
    assert derive is not None


def test_parse_extracts_sp_call(parsed):
    transforms = parsed["transformations"]
    sp = next((t for t in transforms if t.get("transform_type") == "sp_call"), None)
    assert sp is not None
    assert "ValidateOrders" in sp.get("sp_name", "") or "ValidateOrders" in sp.get("sql_statement", "")


def test_parse_extracts_precedence_constraints(parsed):
    cf = parsed["control_flow"]
    adj = cf.get("adjacency_list", [])
    assert len(adj) >= 1
    assert any("Data Flow Task" in e.get("from_task", "") for e in adj)


def test_parse_extracts_variable_parameters(parsed):
    params = parsed["parameters"]
    assert len(params) >= 1
    names = [p["name"] for p in params]
    assert "BatchId" in names


def test_parse_extracts_target_write(parsed):
    transforms = parsed["transformations"]
    target = next((t for t in transforms if t.get("transform_type") == "target_write"), None)
    assert target is not None
    assert "staging" in target.get("target_table", "").lower() or target.get("target_table")


def test_parse_extracts_error_handlers(parsed):
    handlers = parsed["error_handling"]
    assert len(handlers) >= 1
    assert any(h.get("handler_type") == "OnError" for h in handlers)


def test_parse_confidence_score_max_100(parsed):
    assert 0 <= parsed["confidence_score"] <= 100


def test_parse_manual_item_count_non_negative(parsed):
    assert parsed["manual_item_count"] >= 0


def test_parse_flags_script_component_manual(tmp_path):
    dtsx = tmp_path / "test_script.dtsx"
    dtsx.write_text(
        '<?xml version="1.0"?>\n'
        '<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts"\n'
        '    DTS:ExecutableType="SSIS.Package.3" DTS:ObjectName="test_pkg">\n'
        "  <DTS:Executables>\n"
        '    <DTS:Executable DTS:ExecutableType="Microsoft.Pipeline" DTS:ObjectName="DFT">\n'
        "      <DTS:ObjectData>\n"
        '        <pipeline:components xmlns:pipeline="www.microsoft.com/SqlServer/Dts/Pipeline">\n'
        '          <pipeline:component pipeline:componentClassID="DTSTransform.ScriptComponent"\n'
        '              pipeline:name="Script Transform" />\n'
        "        </pipeline:components>\n"
        "      </DTS:ObjectData>\n"
        "    </DTS:Executable>\n"
        "  </DTS:Executables>\n"
        "</DTS:Executable>",
        encoding="utf-8",
    )
    result = SsisParser().parse(str(dtsx))
    transforms = result["transformations"]
    manual = next((t for t in transforms if t.get("transform_type") == "manual"), None)
    assert manual is not None
    assert "MANUAL" in manual.get("flag", "")
    assert result["manual_item_count"] >= 1


def test_parse_script_component_reduces_confidence(tmp_path):
    dtsx = tmp_path / "test_script2.dtsx"
    dtsx.write_text(
        '<?xml version="1.0"?>\n'
        '<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts"\n'
        '    DTS:ExecutableType="SSIS.Package.3" DTS:ObjectName="test_pkg2">\n'
        "  <DTS:Executables>\n"
        '    <DTS:Executable DTS:ExecutableType="Microsoft.Pipeline" DTS:ObjectName="DFT">\n'
        "      <DTS:ObjectData>\n"
        '        <pipeline:components xmlns:pipeline="www.microsoft.com/SqlServer/Dts/Pipeline">\n'
        '          <pipeline:component pipeline:componentClassID="DTSTransform.ScriptComponent"\n'
        '              pipeline:name="Script1" />\n'
        '          <pipeline:component pipeline:componentClassID="DTSTransform.ScriptComponent"\n'
        '              pipeline:name="Script2" />\n'
        "        </pipeline:components>\n"
        "      </DTS:ObjectData>\n"
        "    </DTS:Executable>\n"
        "  </DTS:Executables>\n"
        "</DTS:Executable>",
        encoding="utf-8",
    )
    result = SsisParser().parse(str(dtsx))
    assert result["manual_item_count"] == 2
    assert result["confidence_score"] == 80
