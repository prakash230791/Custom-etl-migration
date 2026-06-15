import pytest
from tool.stage2.generators.lambda_fn import LambdaFnGenerator


@pytest.fixture
def gen():
    return LambdaFnGenerator()


def _sp_block(duration=5, params=None):
    return {
        "sp_name": "dbo.usp_ValidateOrders",
        "sp_rewrite_strategy": "keep_plpgsql",
        "sp_estimated_duration_minutes": duration,
        "sp_parameters": params or [],
        "transaction_scope": "individual",
    }


def test_uses_rds_proxy(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "RDS_PROXY_ENDPOINT" in code


def test_autocommit_false(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "conn.autocommit = False" in code


def test_rollback_on_exception(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "conn.rollback()" in code


def test_audit_insert_present(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "audit.sp_execution_log" in code


def test_commit_present(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "conn.commit()" in code


def test_long_sp_generates_glue_job(gen):
    result, warnings = gen.generate("etl_orders", _sp_block(duration=15))
    filename = list(result.keys())[0]
    code = list(result.values())[0]
    assert "glue_shell" in filename
    assert "Glue Python Shell" in code or "waitForTaskToken" in code or "WARNING" in code
    assert any("P2-R5" in w for w in warnings)


def test_short_sp_generates_lambda(gen):
    result, warnings = gen.generate("etl_orders", _sp_block(duration=5))
    filename = list(result.keys())[0]
    assert "glue_shell" not in filename
    assert "lambda_handler" in list(result.values())[0]
    assert warnings == []


def test_sp_parameters_extracted(gen):
    params = [{"name": "run_id", "type": "UUID"}, {"name": "batch_date", "type": "DATE"}]
    result, _ = gen.generate("etl_orders", _sp_block(params=params))
    code = list(result.values())[0]
    assert 'run_id = event["run_id"]' in code
    assert 'batch_date = event["batch_date"]' in code


def test_sp_name_in_call(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    assert "dbo.usp_ValidateOrders" in code


def test_rds_proxy_not_direct_aurora(gen):
    result, _ = gen.generate("etl_orders", _sp_block())
    code = list(result.values())[0]
    # Must use env var, not a hardcoded host
    assert "RDS_PROXY_ENDPOINT" in code
    assert "aurora.cluster" not in code
