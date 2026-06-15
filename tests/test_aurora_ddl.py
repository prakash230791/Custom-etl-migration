import pytest
from tool.stage2.generators.aurora_ddl import AuroraDDLGenerator


@pytest.fixture
def gen():
    return AuroraDDLGenerator()


def _ctx(columns=None):
    return {
        "job_name": "etl_orders_daily",
        "flyway_version": "V001",
        "staging_tables": [
            {
                "table_name": "staging.tmp_orders",
                "columns": columns
                or [
                    {"name": "order_id", "sql_type": "INT", "nullable": False},
                    {"name": "customer_id", "sql_type": "INT", "nullable": True},
                    {"name": "amount", "sql_type": "DECIMAL(18,2)", "nullable": True},
                    {"name": "order_date", "sql_type": "DATETIME", "nullable": True},
                ],
            }
        ],
    }


def test_always_generates_unlogged_table(gen):
    result = gen.generate(_ctx())
    sql = list(result.values())[0]
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_orders" in sql


def test_type_mapping_applied(gen):
    result = gen.generate(_ctx([{"name": "name_col", "sql_type": "NVARCHAR", "nullable": True}]))
    sql = list(result.values())[0]
    assert "TEXT" in sql
    assert "NVARCHAR" not in sql.split("--")[0]  # not in code part


def test_int_type_mapping(gen):
    result = gen.generate(_ctx([{"name": "id", "sql_type": "INT", "nullable": False}]))
    sql = list(result.values())[0]
    assert "INTEGER" in sql


def test_datetime_type_mapping(gen):
    result = gen.generate(_ctx([{"name": "ts", "sql_type": "DATETIME", "nullable": True}]))
    sql = list(result.values())[0]
    assert "TIMESTAMP" in sql


def test_ambiguous_type_flagged(gen):
    result = gen.generate(_ctx([{"name": "desc", "sql_type": "NVARCHAR(MAX)", "nullable": True}]))
    sql = list(result.values())[0]
    assert "VERIFY TYPE" in sql


def test_audit_tables_always_generated(gen):
    result = gen.generate(_ctx())
    sql = list(result.values())[0]
    assert "audit.phase1_load" in sql
    assert "audit.sp_execution_log" in sql
    assert "audit.phase3_load" in sql


def test_flyway_version_in_filename(gen):
    result = gen.generate(_ctx())
    filename = list(result.keys())[0]
    assert filename.startswith("db-migrations/V001")


def test_schema_creation_first(gen):
    result = gen.generate(_ctx())
    sql = list(result.values())[0]
    staging_pos = sql.index("CREATE SCHEMA IF NOT EXISTS staging")
    audit_pos = sql.index("CREATE SCHEMA IF NOT EXISTS audit")
    assert staging_pos < audit_pos


def test_string_staging_table_fallback(gen):
    ctx = {
        "job_name": "simple_job",
        "flyway_version": "V001",
        "staging_tables": ["staging.tmp_simple"],
    }
    result = gen.generate(ctx)
    sql = list(result.values())[0]
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_simple" in sql


def test_not_null_constraint(gen):
    result = gen.generate(_ctx([{"name": "id", "sql_type": "INT", "nullable": False}]))
    sql = list(result.values())[0]
    assert "NOT NULL" in sql
