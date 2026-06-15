import pytest
from tool.stage2.layers.l2_pipeline import L2Pipeline


@pytest.fixture
def pipeline():
    return L2Pipeline(job_name="etl_orders_daily")


def test_source_read_generates_truncate(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "orders", "row_count_estimate": 500000, "connection_type": "jdbc", "query_or_path": "dbo.Orders"}]
    snippets = pipeline.process_blocks(blocks)
    phase1 = "\n".join(snippets["phase1"])
    assert "TRUNCATE staging.tmp_orders" in phase1


def test_source_read_large_dpu_g1x(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "orders", "row_count_estimate": 500000, "connection_type": "jdbc", "query_or_path": "dbo.Orders"}]
    snippets = pipeline.process_blocks(blocks)
    phase1 = "\n".join(snippets["phase1"])
    assert "G.1X" in phase1


def test_source_read_small_dpu_g025x(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "customers", "row_count_estimate": 45000, "connection_type": "jdbc", "query_or_path": "dbo.Customers"}]
    snippets = pipeline.process_blocks(blocks)
    phase1 = "\n".join(snippets["phase1"])
    assert "G.025X" in phase1


def test_source_read_very_large_dpu_g2x(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "bigdata", "row_count_estimate": 20_000_000, "connection_type": "jdbc", "query_or_path": "dbo.BigTable"}]
    snippets = pipeline.process_blocks(blocks)
    phase1 = "\n".join(snippets["phase1"])
    assert "G.2X" in phase1


def test_target_write_truncate_insert_generates_begin_truncate_insert_commit(pipeline):
    blocks = [{"transform_type": "target_write", "target_schema": "public", "target_table": "orders", "write_mode": "truncate_insert"}]
    snippets = pipeline.process_blocks(blocks)
    phase3 = "\n".join(snippets["phase3"])
    assert "BEGIN" in phase3
    assert "TRUNCATE public.orders" in phase3
    assert "INSERT INTO public.orders" in phase3
    assert "conn.commit()" in phase3


def test_target_write_generates_eventbridge_put_events(pipeline):
    blocks = [{"transform_type": "target_write", "target_schema": "public", "target_table": "orders", "write_mode": "truncate_insert"}]
    snippets = pipeline.process_blocks(blocks)
    phase3 = "\n".join(snippets["phase3"])
    assert "put_events" in phase3


def test_sp_call_generates_lambda_body_with_rds_proxy(pipeline):
    blocks = [{"transform_type": "sp_call", "sp_name": "dbo.usp_Validate", "sp_rewrite_strategy": "keep_plpgsql", "sp_estimated_duration_minutes": 5}]
    snippets = pipeline.process_blocks(blocks)
    lambda_code = "\n".join(snippets["lambda"])
    assert "rds_proxy_endpoint" in lambda_code
    assert "autocommit = False" in lambda_code


def test_sp_call_generates_audit_insert(pipeline):
    blocks = [{"transform_type": "sp_call", "sp_name": "dbo.usp_Validate", "sp_rewrite_strategy": "keep_plpgsql", "sp_estimated_duration_minutes": 5}]
    snippets = pipeline.process_blocks(blocks)
    lambda_code = "\n".join(snippets["lambda"])
    assert "audit.sp_execution_log" in lambda_code


def test_join_generates_df_join(pipeline):
    blocks = [{"transform_type": "join", "transform_id": "df_joined", "left": "df_orders", "right": "df_customers", "join_key": "customer_id", "join_type": "left"}]
    snippets = pipeline.process_blocks(blocks)
    phase2 = "\n".join(snippets["phase2"])
    assert "df_orders.join(df_customers" in phase2
    assert "how='left'" in phase2


def test_source_read_generates_audit_insert(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "orders", "row_count_estimate": 100, "connection_type": "jdbc", "query_or_path": "dbo.Orders"}]
    snippets = pipeline.process_blocks(blocks)
    phase1 = "\n".join(snippets["phase1"])
    assert "audit.phase1_load" in phase1


def test_target_write_rollback_on_exception(pipeline):
    blocks = [{"transform_type": "target_write", "target_schema": "public", "target_table": "orders", "write_mode": "truncate_insert"}]
    snippets = pipeline.process_blocks(blocks)
    phase3 = "\n".join(snippets["phase3"])
    assert "conn.rollback()" in phase3


def test_target_write_autocommit_false(pipeline):
    blocks = [{"transform_type": "target_write", "target_schema": "public", "target_table": "orders", "write_mode": "truncate_insert"}]
    snippets = pipeline.process_blocks(blocks)
    phase3 = "\n".join(snippets["phase3"])
    assert "autocommit = False" in phase3


def test_source_read_unknown_rowcount_warns(pipeline):
    blocks = [{"transform_type": "source_read", "source_id": "x", "connection_type": "jdbc", "query_or_path": "dbo.X"}]
    snippets = pipeline.process_blocks(blocks)
    assert any("row_count_estimate unknown" in w for w in snippets["warnings"])


def test_filter_generates_df_filter(pipeline):
    blocks = [{"transform_type": "filter", "transform_id": "df_filtered", "source": "df_in", "condition": "col > 0"}]
    snippets = pipeline.process_blocks(blocks)
    assert "df_in.filter" in "\n".join(snippets["phase2"])


def test_aggregate_generates_groupby_agg(pipeline):
    blocks = [{"transform_type": "aggregate", "transform_id": "df_agg", "source": "df_in", "group_by": ["region"], "aggregations": ["sum"]}]
    snippets = pipeline.process_blocks(blocks)
    assert "groupBy" in "\n".join(snippets["phase2"])


def test_union_generates_unionbyname(pipeline):
    blocks = [{"transform_type": "union", "transform_id": "df_union", "inputs": ["df_a", "df_b"]}]
    snippets = pipeline.process_blocks(blocks)
    assert "unionByName" in "\n".join(snippets["phase2"])


def test_derive_generates_withcolumn(pipeline):
    blocks = [{"transform_type": "derive", "transform_id": "df_derived", "source": "df_in", "output_column": "new_col", "expression": "col_a + col_b"}]
    snippets = pipeline.process_blocks(blocks)
    assert "withColumn" in "\n".join(snippets["phase2"])


def test_sp_call_long_sp_warns(pipeline):
    blocks = [{"transform_type": "sp_call", "sp_name": "dbo.usp_LongOp", "sp_rewrite_strategy": "keep_plpgsql", "sp_estimated_duration_minutes": 15}]
    snippets = pipeline.process_blocks(blocks)
    assert any("P2-R5 WARNING" in w for w in snippets["warnings"])
