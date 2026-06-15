_LAMBDA_TEMPLATE = """\
# Generated Lambda function: {sp_name}
# Pattern: keep_plpgsql (P2-R1)

import os
import time
import json

import boto3
import psycopg2
import psycopg2.errors


def lambda_handler(event, context):
    run_id = event["run_id"]
{parameter_extraction}
    # P2-R3: RDS Proxy connection, autocommit=False
    conn = psycopg2.connect(
        host=os.environ["RDS_PROXY_ENDPOINT"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=30,
    )
    conn.autocommit = False

    start_time = time.time()
    try:
        cur = conn.cursor()

        # P2-R1: Call SP directly (keep_plpgsql strategy)
        cur.execute("CALL {sp_name}({param_placeholders})", [{param_values}])
        rows_affected = cur.rowcount

        # P2-R6: Audit INSERT
        duration_ms = int((time.time() - start_time) * 1000)
        cur.execute(
            "INSERT INTO audit.sp_execution_log "
            "(run_id, sp_name, rows_affected, execution_duration_ms, executed_at) "
            "VALUES (%s, %s, %s, %s, now())",
            [run_id, "{sp_name}", rows_affected, duration_ms],
        )

        conn.commit()  # P2-R3: COMMIT after audit INSERT

        return {{
            "statusCode": 200,
            "run_id": run_id,
            "sp_name": "{sp_name}",
            "rows_affected": rows_affected,
        }}

    except psycopg2.errors.RaiseException as exc:
        # P2-R4: Catch business logic errors (pgcode P0001) — no retry
        conn.rollback()
        raise RuntimeError(f"SP business logic error: {{exc}}") from exc

    except psycopg2.Error:
        # P2-R3: ROLLBACK on any psycopg2 error
        conn.rollback()
        raise

    finally:
        conn.close()
"""

_GLUE_SHELL_TEMPLATE = """\
# Generated Glue Python Shell job: {sp_name}
# WARNING (P2-R5): sp_estimated_duration_minutes={duration}min > 12 — using Glue Python Shell
# with waitForTaskToken pattern instead of Lambda.

import os
import sys
import time
import json

import boto3
import psycopg2
import psycopg2.errors

args = {{k: v for k, v in (a.split("=", 1) for a in sys.argv[1:] if "=" in a)}}
run_id = args.get("run_id", "")
task_token = args.get("task_token", "")

conn = psycopg2.connect(
    host=os.environ["RDS_PROXY_ENDPOINT"],
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    connect_timeout=30,
)
conn.autocommit = False

sfn = boto3.client("stepfunctions")
start_time = time.time()
try:
    cur = conn.cursor()
    cur.execute("CALL {sp_name}({param_placeholders})", [{param_values}])
    rows_affected = cur.rowcount
    duration_ms = int((time.time() - start_time) * 1000)
    cur.execute(
        "INSERT INTO audit.sp_execution_log "
        "(run_id, sp_name, rows_affected, execution_duration_ms, executed_at) "
        "VALUES (%s, %s, %s, %s, now())",
        [run_id, "{sp_name}", rows_affected, duration_ms],
    )
    conn.commit()
    if task_token:
        sfn.send_task_success(taskToken=task_token, output=json.dumps({{"rows_affected": rows_affected}}))
except psycopg2.Error:
    conn.rollback()
    if task_token:
        sfn.send_task_failure(taskToken=task_token, error="SPError", cause=str(sys.exc_info()[1]))
    raise
finally:
    conn.close()
"""


class LambdaFnGenerator:
    def generate(self, job_name: str, sp_block: dict) -> dict:
        """Generate Lambda or Glue Python Shell for an SP call. Returns {filename: content}."""
        sp_name = sp_block.get("sp_name", "unknown_sp")
        duration = int(sp_block.get("sp_estimated_duration_minutes", 0) or 0)
        params = sp_block.get("sp_parameters", [])

        param_extraction = self._build_param_extraction(params)
        param_placeholders = ", ".join(["%s"] * len(params))
        param_values = ", ".join(p["name"] for p in params) if params else ""

        safe_sp = sp_name.replace(".", "_").replace("[", "").replace("]", "")

        if duration > 12:
            content = _GLUE_SHELL_TEMPLATE.format(
                sp_name=sp_name,
                duration=duration,
                param_placeholders=param_placeholders,
                param_values=param_values,
            )
            filename = f"generated/lambda/{job_name}/{safe_sp}_glue_shell.py"
            warnings = [f"P2-R5 WARNING: {sp_name} duration {duration}min > 12 — Glue Python Shell generated"]
        else:
            content = _LAMBDA_TEMPLATE.format(
                sp_name=sp_name,
                parameter_extraction=param_extraction,
                param_placeholders=param_placeholders,
                param_values=param_values,
            )
            filename = f"generated/lambda/{job_name}/{safe_sp}.py"
            warnings = []

        return {filename: content}, warnings

    def _build_param_extraction(self, params: list) -> str:
        if not params:
            return ""
        lines = []
        for p in params:
            name = p["name"]
            lines.append(f'    {name} = event["{name}"]')
        return "\n".join(lines) + "\n"
