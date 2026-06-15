from jinja2 import Environment, FileSystemLoader


_DPU_MAP = [
    (100_000, "G.025X", 2),
    (10_000_000, "G.1X", 2),
]


def _dpu_for_row_count(row_count_estimate) -> tuple:
    if row_count_estimate is None:
        return "G.1X", 2, True
    count = int(row_count_estimate)
    if count < 100_000:
        return "G.025X", 2, False
    if count < 10_000_000:
        return "G.1X", 2, False
    return "G.2X", 4, False


class L2Pipeline:
    def __init__(self, templates_dir: str = "tool/templates", job_name: str = "etl_job"):
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            keep_trailing_newline=True,
        )
        self.job_name = job_name

    def process_blocks(self, blocks: list) -> dict:
        snippets = {"phase1": [], "phase2": [], "phase3": [], "lambda": [], "warnings": []}
        for block in blocks:
            transform_type = block.get("transform_type", "")
            if transform_type == "source_read":
                snippets["phase1"].append(self._handle_source_read(block, snippets["warnings"]))
            elif transform_type == "target_write":
                snippets["phase3"].append(self._handle_target_write(block))
            elif transform_type == "sp_call":
                sp_snippet, warning = self._handle_sp_call(block)
                snippets["lambda"].append(sp_snippet)
                if warning:
                    snippets["warnings"].append(warning)
            elif transform_type == "join":
                snippets["phase2"].append(self._handle_join(block))
            elif transform_type == "filter":
                snippets["phase2"].append(self._handle_filter(block))
            elif transform_type == "aggregate":
                snippets["phase2"].append(self._handle_aggregate(block))
            elif transform_type == "sort":
                snippets["phase2"].append(self._handle_sort(block, snippets["warnings"]))
            elif transform_type == "union":
                snippets["phase2"].append(self._handle_union(block))
            elif transform_type == "window":
                snippets["phase2"].append(self._handle_window(block))
            elif transform_type == "derive":
                snippets["phase2"].append(self._handle_derive(block))
        return snippets

    def _handle_source_read(self, block: dict, warnings: list) -> str:
        source_id = block.get("source_id", "unknown")
        staging_table = f"staging.tmp_{source_id}"
        row_count = block.get("row_count_estimate")
        dpu_type, num_workers, unknown = _dpu_for_row_count(row_count)
        query = block.get("query_or_path", "")
        connection_type = block.get("connection_type", "jdbc")
        has_join = "SELECT" in str(query).upper() and "JOIN" in str(query).upper()

        if unknown:
            warnings.append(f"P1-R6 WARNING: row_count_estimate unknown for {source_id}, defaulting to G.1X/2")

        lines = [
            f"# P1-R2: TRUNCATE {staging_table} before read",
            f"# P1-R6: DPU sizing: {dpu_type}/{num_workers} (row_count_estimate={row_count})",
            "with conn.cursor() as cur:",
            f"    cur.execute('TRUNCATE {staging_table}')",
            "conn.commit()",
        ]
        if has_join and connection_type == "jdbc":
            lines.append("# P1-R3: JDBC pushdown for JOIN query")
            lines.append(
                f"df_{source_id} = spark.read.jdbc(url=connection_url, table='({query}) AS t', properties=jdbc_props)"
            )
        elif connection_type == "jdbc":
            lines.append(
                f"df_{source_id} = spark.read.jdbc(url=connection_url, table='{query}', properties=jdbc_props)"
            )
        else:
            lines.append(f"df_{source_id} = spark.read.format('{connection_type}').load('{query}')")

        audit_insert = (
            f'    cur.execute("INSERT INTO audit.phase1_load'
            f' (job_name, source_id, rows_loaded, batch_id) VALUES (%s, %s, %s, %s)",'
            f" (job_name, '{source_id}', df_{source_id}.count(), batch_id))"
        )
        lines += [
            "# P1-R4: autocommit=False, audit INSERT",
            "with conn.cursor() as cur:",
            audit_insert,
            "conn.commit()",
        ]
        return "\n".join(lines)

    def _handle_target_write(self, block: dict) -> str:
        target_table = block.get("target_table", "unknown")
        target_schema = block.get("target_schema", "public")
        write_mode = block.get("write_mode", "truncate_insert")

        lines = []
        if write_mode == "truncate_insert":
            audit_line = (
                f'        cur.execute("INSERT INTO audit.phase3_load'
                f' (job_name, target_table, batch_id) VALUES (%s, %s, %s)",'
                f" (job_name, '{target_table}', batch_id))"
            )
            lines += [
                f"# P3-R3: truncate_insert for {target_schema}.{target_table}",
                "conn.autocommit = False",
                "try:",
                "    with conn.cursor() as cur:",
                "        cur.execute('BEGIN')",
                f"        cur.execute('TRUNCATE {target_schema}.{target_table}')",
                f"        cur.execute('INSERT INTO {target_schema}.{target_table}"
                f" SELECT * FROM staging.tmp_{target_table}')",
                "        # P3-R5: Audit INSERT",
                audit_line,
                "    conn.commit()  # P3-R1: single transaction per FK group",
                "except psycopg2.Error:",
                "    conn.rollback()  # P3-R2: ROLLBACK on exception",
                "    raise",
            ]
        elif write_mode == "upsert":
            audit_line = (
                f'        cur.execute("INSERT INTO audit.phase3_load'
                f' (job_name, target_table, batch_id) VALUES (%s, %s, %s)",'
                f" (job_name, '{target_table}', batch_id))"
            )
            lines += [
                "# P3-R3 + P3-R4: upsert in batches of 1000",
                "conn.autocommit = False",
                "try:",
                "    with conn.cursor() as cur:",
                "        for i in range(0, len(rows), 1000):",
                "            batch = rows[i:i+1000]",
                f"            cur.executemany('INSERT INTO {target_schema}.{target_table}"
                f" VALUES %s ON CONFLICT DO UPDATE SET ...', batch)",
                audit_line,
                "    conn.commit()",
                "except psycopg2.Error:",
                "    conn.rollback()",
                "    raise",
            ]
        else:
            audit_line = (
                f'        cur.execute("INSERT INTO audit.phase3_load'
                f' (job_name, target_table, batch_id) VALUES (%s, %s, %s)",'
                f" (job_name, '{target_table}', batch_id))"
            )
            lines += [
                f"# P3-R3: [MANUAL] write_mode={write_mode} — truncate_insert skeleton + TODO",
                "conn.autocommit = False",
                "try:",
                "    with conn.cursor() as cur:",
                "        cur.execute('BEGIN')",
                f"        cur.execute('TRUNCATE {target_schema}.{target_table}')",
                f"        # TODO: implement write logic for write_mode={write_mode}",
                f"        cur.execute('INSERT INTO {target_schema}.{target_table}"
                f" SELECT * FROM staging.tmp_{target_table}')",
                audit_line,
                "    conn.commit()",
                "except psycopg2.Error:",
                "    conn.rollback()",
                "    raise",
            ]

        put_events_line = (
            f"events_client.put_events(Entries=[{{"
            f"'Source': 'etl.{self.job_name}', "
            f"'DetailType': 'Phase3Complete', "
            f"'Detail': '{{\"target_table\": \"{target_table}\"}}', "
            f"'EventBusName': 'default'}}])"
        )
        lines += [
            "# P3-R6: EventBridge completion event",
            "import boto3",
            "events_client = boto3.client('events')",
            put_events_line,
        ]
        return "\n".join(lines)

    def _handle_sp_call(self, block: dict) -> tuple:
        sp_name = block.get("sp_name", "unknown_sp")
        duration = block.get("sp_estimated_duration_minutes", 0)
        warning = None
        if duration and int(duration) > 12:
            warning = (
                f"P2-R5 WARNING: {sp_name} estimated {duration}min > 12 — consider Glue Python Shell + waitForTaskToken"
            )

        audit_line = (
            f'        cur.execute("INSERT INTO audit.sp_execution_log'
            f' (job_name, sp_name, status) VALUES (%s, %s, %s)",'
            f" (job_name, '{sp_name}', 'SUCCESS'))"
        )
        lines = [
            "# P2-R1: keep_plpgsql strategy — Lambda wrapper",
            "# P2-R3: Lambda uses RDS Proxy; autocommit=False",
            "conn = psycopg2.connect(host=rds_proxy_endpoint, dbname=db_name, ...)",
            "conn.autocommit = False",
            "try:",
            "    with conn.cursor() as cur:",
            f"        cur.execute('CALL {sp_name}()')",
            "        # P2-R6: Audit INSERT",
            audit_line,
            "    conn.commit()",
            "except psycopg2.errors.RaiseException:",
            "    conn.rollback()",
            "    raise",
            "finally:",
            "    conn.close()",
        ]
        return "\n".join(lines), warning

    def _handle_join(self, block: dict) -> str:
        left = block.get("left", "df_left")
        right = block.get("right", "df_right")
        key = block.get("join_key", "id")
        join_type = block.get("join_type", "inner")
        result_name = block.get("transform_id", "df_joined")
        return f"{result_name} = {left}.join({right}, on='{key}', how='{join_type}')"

    def _handle_filter(self, block: dict) -> str:
        source = block.get("source", "df")
        condition = block.get("condition", "True")
        result_name = block.get("transform_id", "df_filtered")
        return f"{result_name} = {source}.filter({condition!r})"

    def _handle_aggregate(self, block: dict) -> str:
        source = block.get("source", "df")
        group_by = block.get("group_by", [])
        aggs = block.get("aggregations", [])
        result_name = block.get("transform_id", "df_agg")
        group_str = ", ".join(f"'{c}'" for c in group_by)
        agg_str = ", ".join(f"F.{a}()" for a in aggs) if aggs else "F.count('*')"
        return f"{result_name} = {source}.groupBy({group_str}).agg({agg_str})"

    def _handle_sort(self, block: dict, warnings: list) -> str:
        source = block.get("source", "df")
        columns = block.get("sort_columns", [])
        result_name = block.get("transform_id", "df_sorted")
        required = block.get("required", False)
        if not required:
            warnings.append(f"Sort {result_name} is not marked required=true — may be unnecessary")
        cols_str = ", ".join(f"'{c}'" for c in columns)
        return f"{result_name} = {source}.orderBy({cols_str})"

    def _handle_union(self, block: dict) -> str:
        inputs = block.get("inputs", ["df_a", "df_b"])
        result_name = block.get("transform_id", "df_union")
        first = inputs[0]
        rest = inputs[1:]
        union_chain = first
        for inp in rest:
            union_chain = f"{union_chain}.unionByName({inp})"
        return f"{result_name} = {union_chain}"

    def _handle_window(self, block: dict) -> str:
        source = block.get("source", "df")
        col_name = block.get("output_column", "window_col")
        result_name = block.get("transform_id", "df_windowed")
        return (
            "from pyspark.sql import Window\n"
            "import pyspark.sql.functions as F\n"
            "w = Window.partitionBy('partition_col').orderBy('order_col')\n"
            f"{result_name} = {source}.withColumn('{col_name}', F.row_number().over(w))"
        )

    def _handle_derive(self, block: dict) -> str:
        source = block.get("source", "df")
        col_name = block.get("output_column", "derived_col")
        expression = block.get("expression", "None")
        result_name = block.get("transform_id", "df_derived")
        return f"{result_name} = {source}.withColumn('{col_name}', F.expr({expression!r}))"
