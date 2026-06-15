import pytest
from tool.stage2.layers.l4_idiom import L4IdiomScanner


@pytest.fixture
def scanner():
    return L4IdiomScanner()


def test_r01_collect_loop_detected(scanner):
    code = "for row in df.rdd.collect():\n    process(row)"
    _, violations = scanner.scan(code)
    assert "L4-R01" in [v["rule_id"] for v in violations]


def test_r02_collect_call_detected(scanner):
    code = "data = df.collect()"
    _, violations = scanner.scan(code)
    assert "L4-R02" in [v["rule_id"] for v in violations]


def test_r03_db_in_map_detected(scanner):
    code = "df.rdd.map(lambda row: conn.cursor().execute('SELECT 1'))"
    _, violations = scanner.scan(code)
    assert "L4-R03" in [v["rule_id"] for v in violations]


def test_r04_udf_detected(scanner):
    code = "from pyspark.sql.functions import udf\nmy_udf = udf(lambda x: x + 1)"
    _, violations = scanner.scan(code)
    assert "L4-R04" in [v["rule_id"] for v in violations]


def test_r05_aws_credential_blocks_output(scanner):
    code = 'key = "AKIAIOSFODNN7EXAMPLE"'
    _, violations = scanner.scan(code)
    blocking = [v for v in violations if v["blocks_output"]]
    assert any(v["rule_id"] == "L4-R05" for v in blocking)


def test_r05_aws_credential_sets_blocks_output_true(scanner):
    code = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
    _, violations = scanner.scan(code)
    r05 = [v for v in violations if v["rule_id"] == "L4-R05"]
    assert r05
    assert r05[0]["blocks_output"] is True


def test_r06_hardcoded_s3_autocorrected(scanner):
    code = 'path = "s3://my-bucket/my-prefix/data.parquet"'
    corrected, violations = scanner.scan(code)
    assert "s3://my-bucket" not in corrected
    assert "L4-R06" in [v["rule_id"] for v in violations]


def test_r07_uncached_df_detected(scanner):
    code = (
        "df_orders = spark.read.table('orders')\n"
        "result1 = df_orders.filter('id > 0')\n"
        "result2 = df_orders.select('id')\n"
        "result3 = df_orders.count()\n"
    )
    corrected, violations = scanner.scan(code)
    assert "L4-R07" in [v["rule_id"] for v in violations]


def test_r08_jdbc_no_schema_autocorrected(scanner):
    code = "df = spark.read.jdbc(url='jdbc:postgresql://host/db', table='orders', properties={})"
    corrected, violations = scanner.scan(code)
    assert "schema=" in corrected
    assert "L4-R08" in [v["rule_id"] for v in violations]


def test_r09_autocommit_true_detected(scanner):
    code = "conn.autocommit = True"
    _, violations = scanner.scan(code)
    assert "L4-R09" in [v["rule_id"] for v in violations]


def test_r10_sql_concat_fstring_detected(scanner):
    code = 'table = "orders"\nsql = f"SELECT * FROM {table}"'
    _, violations = scanner.scan(code)
    assert "L4-R10" in [v["rule_id"] for v in violations]


def test_r10_sql_concat_blocks_output_false(scanner):
    code = 'table = "orders"\nsql = f"SELECT * FROM {table}"'
    _, violations = scanner.scan(code)
    r10 = [v for v in violations if v["rule_id"] == "L4-R10"]
    assert r10


def test_r05_no_false_positive_clean_code(scanner):
    code = 'key = args["aws_key_param"]'
    _, violations = scanner.scan(code)
    r05 = [v for v in violations if v["rule_id"] == "L4-R05"]
    assert not r05


def test_r06_no_false_positive_param_ref(scanner):
    code = 'path = args["s3_path"]'
    corrected, violations = scanner.scan(code)
    r06 = [v for v in violations if v["rule_id"] == "L4-R06"]
    assert not r06


def test_r09_autocommit_false_not_flagged(scanner):
    code = "conn.autocommit = False"
    _, violations = scanner.scan(code)
    r09 = [v for v in violations if v["rule_id"] == "L4-R09"]
    assert not r09


def test_clean_code_no_violations(scanner):
    code = "import pyspark\ndf = spark.read.table('orders')\nresult = df.filter('id > 0')\n"
    _, violations = scanner.scan(code)
    security_violations = [v for v in violations if v["rule_id"] in ("L4-R05", "L4-R10")]
    assert not security_violations
