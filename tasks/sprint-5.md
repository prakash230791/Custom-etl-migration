# tasks/sprint-5.md
# Sprint 5: Three-Phase Full Rules + Generators

**Duration:** Week 5 (1 week, parallel with Sprint 4 if team allows)  
**Prerequisite:** Sprint 0 merged to main (Sprint 5 builds on L2, not on L3/L4/L5)  
**Branch:** `feature/sprint-5-three-phase-generators`

---

## Read First

1. `CLAUDE.md`
2. `Custom_Tool_Implementation.docx` §5.2 (L2 rules P1-R1 through P3-R6 in full detail)
3. `tool/stage2/layers/l2_pipeline.py` — Sprint 0 built the L2 scaffolding; Sprint 5 completes it

---

## What to Build

Complete implementations for all generators that Sprint 0 left as stubs:

- `tool/stage2/generators/aurora_ddl.py` — full Flyway DDL generator
- `tool/stage2/generators/lambda_fn.py` — Lambda SP wrapper generator
- `tool/stage2/generators/dqdl.py` — Glue Data Quality DQDL ruleset generator
- `tool/stage2/generators/eventbridge.py` — EventBridge completion event helper
- `tool/templates/aurora_ddl.j2` — complete template (Sprint 0 created a stub)
- `tool/templates/phase2_lambda.j2` — complete Lambda template

---

## Module: aurora_ddl.py

### Purpose
Generate Flyway-compatible SQL migration script for all staging and audit tables.

### Input
```python
{
    "job_name": "etl_orders_daily",
    "staging_tables": [
        {
            "table_name": "staging.tmp_orders",
            "columns": [
                {"name": "order_id", "sql_type": "INTEGER", "nullable": False},
                {"name": "customer_id", "sql_type": "INTEGER", "nullable": True},
                {"name": "amount", "sql_type": "DECIMAL(18,2)", "nullable": True},
                {"name": "order_date", "sql_type": "TIMESTAMP", "nullable": True}
            ]
        }
    ],
    "flyway_version": "V001"
}
```

### Output
SQL file at `db-migrations/V001__{job_name}.sql`

### DDL Rules (from §5.1 aurora_ddl.j2 spec)

1. `CREATE SCHEMA IF NOT EXISTS staging` — always first
2. `CREATE SCHEMA IF NOT EXISTS audit` — always second
3. For each staging table: `CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_{table}` — UNLOGGED is required for performance
4. Standard audit tables (always generate these three):
   - `audit.phase1_load (run_id UUID, source_name TEXT, table_name TEXT, row_count BIGINT, load_duration_ms BIGINT, loaded_at TIMESTAMP DEFAULT now())`
   - `audit.sp_execution_log (run_id UUID, sp_name TEXT, rows_affected BIGINT, execution_duration_ms BIGINT, executed_at TIMESTAMP DEFAULT now())`
   - `audit.phase3_load (run_id UUID, target_table TEXT, rows_inserted BIGINT, rows_updated BIGINT, rows_deleted BIGINT, load_duration_ms BIGINT, loaded_at TIMESTAMP DEFAULT now())`
5. SQL Server → PostgreSQL type mapping applied (from config/type_map.yaml)

### type_map.yaml (create this)

```yaml
# SQL Server → PostgreSQL type mapping
# Used by aurora_ddl.py and stage2 generators

type_mappings:
  NVARCHAR: TEXT
  VARCHAR: TEXT
  CHAR: CHAR
  NCHAR: CHAR
  INT: INTEGER
  BIGINT: BIGINT
  SMALLINT: SMALLINT
  TINYINT: SMALLINT
  BIT: BOOLEAN
  DECIMAL: DECIMAL
  NUMERIC: NUMERIC
  FLOAT: DOUBLE PRECISION
  REAL: REAL
  DATETIME: TIMESTAMP
  DATETIME2: TIMESTAMP
  DATE: DATE
  TIME: TIME
  UNIQUEIDENTIFIER: UUID
  VARBINARY: BYTEA
  IMAGE: BYTEA
  TEXT: TEXT
  NTEXT: TEXT
  XML: XML
  MONEY: DECIMAL(19,4)
  SMALLMONEY: DECIMAL(10,4)

ambiguous_mappings:
  # These need [VERIFY TYPE] flag in DDL
  - NVARCHAR(MAX)   # → TEXT — confirm no length constraint needed
  - VARCHAR(MAX)    # → TEXT — confirm no length constraint needed
  - SQL_VARIANT     # → [MANUAL: determine actual data type]
  - GEOGRAPHY       # → [MANUAL: PostGIS extension required]
  - GEOMETRY        # → [MANUAL: PostGIS extension required]
```

---

## Module: lambda_fn.py

### Purpose
Generate complete Lambda function Python file for a Phase 2 SP call.

### Input
sp_call etl-spec block:
```python
{
    "sp_name": "dbo.usp_ValidateOrders",
    "sp_rewrite_strategy": "keep_plpgsql",
    "sp_parameters": [
        {"name": "run_id", "type": "UUID", "source": "execution_input"},
        {"name": "batch_date", "type": "DATE", "source": "execution_input"}
    ],
    "sp_estimated_duration_minutes": 5,
    "transaction_scope": "individual"
}
```

### Output
Lambda function file at `generated/lambda/{job_name}/{sp_name}.py`

### Lambda Rules (P2-R1 through P2-R6)

The Lambda must implement exactly this pattern — no variations:

```python
# Generated Lambda function: {sp_name}
# Pattern: keep_plpgsql (P2-R1)

import os
import time
import psycopg2
import boto3
import json

def lambda_handler(event, context):
    run_id = event["run_id"]
    # Extract SP parameters from event
    {parameter_extraction}
    
    # P2-R3: RDS Proxy connection, autocommit=False
    conn = psycopg2.connect(
        host=os.environ["RDS_PROXY_ENDPOINT"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=30
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
            "INSERT INTO audit.sp_execution_log (run_id, sp_name, rows_affected, execution_duration_ms, executed_at) VALUES (%s, %s, %s, %s, now())",
            [run_id, "{sp_name}", rows_affected, duration_ms]
        )
        
        conn.commit()  # P2-R3: COMMIT after audit INSERT
        
        return {
            "statusCode": 200,
            "run_id": run_id,
            "sp_name": "{sp_name}",
            "rows_affected": rows_affected
        }
    
    except psycopg2.errors.RaiseException as e:
        # P2-R4: Catch business logic errors (pgcode P0001) — no retry
        conn.rollback()
        raise RuntimeError(f"SP business logic error: {{e}}") from e
    
    except psycopg2.Error as e:
        # P2-R3: ROLLBACK on any psycopg2 error
        conn.rollback()
        raise
    
    finally:
        conn.close()
```

If `sp_estimated_duration_minutes > 12` (P2-R5):
- Generate Glue Python Shell job instead of Lambda
- Add WARNING to conversion_notes.md
- Use `waitForTaskToken` pattern in Step Functions Task state

---

## Module: dqdl.py

### Purpose
Generate Glue Data Quality DQDL ruleset for each job.

### Input
etl-spec blocks from §4 + any §10 (Data Quality Rules) entries from requirements doc

### Output
JSON file at `generated/dqdl/{job_name}.json`

### Baseline Rules (always generated even when §10 is sparse)

```json
{
  "ruleset_name": "{job_name}_dq",
  "rules": [
    {"rule_type": "RowCount", "expression": "> 0", "applies_to": "{staging_table}"},
    {"rule_type": "IsComplete", "expression": "= 1", "applies_to": "{primary_key_column}"},
    {"rule_type": "IsUnique", "expression": "= 1", "applies_to": "{primary_key_column}"}
  ]
}
```

Additional rules generated from §10 entries in requirements doc:
- Null check → `IsComplete` rule
- Range check → `ColumnValues` rule with between expression
- Referential integrity → `ReferentialIntegrity` rule

---

## Tests

### tests/test_aurora_ddl.py
1. `test_always_generates_unlogged_table` — output contains `UNLOGGED TABLE`
2. `test_type_mapping_applied` — NVARCHAR → TEXT in output
3. `test_ambiguous_type_flagged` — NVARCHAR(MAX) → `[VERIFY TYPE]` comment
4. `test_audit_tables_always_generated` — output contains all 3 audit tables
5. `test_flyway_version_in_filename` — output filename starts with V001

### tests/test_lambda_fn.py
1. `test_uses_rds_proxy` — `RDS_PROXY_ENDPOINT` env var in generated code
2. `test_autocommit_false` — `conn.autocommit = False` present
3. `test_rollback_on_exception` — `conn.rollback()` in except block
4. `test_audit_insert_present` — `audit.sp_execution_log` INSERT present
5. `test_long_sp_generates_glue_job` — sp_estimated_duration_minutes=15 → Glue job, not Lambda

---

## Acceptance Criteria — Sprint 5 Complete When ALL Pass

- [ ] `aurora_ddl.py` always generates UNLOGGED staging tables
- [ ] All SQL Server → PostgreSQL type mappings from type_map.yaml applied
- [ ] Ambiguous types generate [VERIFY TYPE] comment
- [ ] All 3 audit tables always generated
- [ ] `lambda_fn.py` uses RDS Proxy endpoint (never direct Aurora)
- [ ] Lambda always has `autocommit = False` and ROLLBACK in except block
- [ ] SP duration > 12 min → Glue Python Shell generated, WARNING in conversion notes
- [ ] `dqdl.py` generates at least RowCount > 0 and IsComplete for primary key
- [ ] All new tests pass
- [ ] `ruff check tool/` → zero errors
- [ ] PR opened against main
