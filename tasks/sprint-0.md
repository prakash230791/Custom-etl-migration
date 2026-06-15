# tasks/sprint-0.md
# Sprint 0: Minimum Viable Tool — L1 + L2 + L4

**Duration:** Weeks 1–2  
**Status:** Ready to implement  
**Blocks:** SSIS rewrite stream cannot use the custom tool until Sprint 0 passes all acceptance criteria

---

## Read First

Before writing a single line of code, read:
1. `CLAUDE.md` — full project context, layout, rules
2. `Custom_Tool_Implementation.docx` — complete spec (§1 overview, §2 repo layout, §4 etl-spec schema, §5 generation engine, §6 QA gates, §8 sprint plan)

---

## What to Build in Sprint 0

Sprint 0 delivers three independent layers only:
- **L1** — Jinja2 structural scaffold (job skeleton, ASL, IaC, DDL)
- **L2** — Data pipeline scaffold (18 rules: P1-R1 through P3-R6)
- **L4** — AST anti-pattern scanner (10 rules: L4-R01 through L4-R10)

Do NOT build in Sprint 0:
- Stage 1 parsers (Sprint 1 and 2)
- L3 LLM expression translation (Sprint 3)
- L5 test generation (Sprint 4)
- Full CI/CD intake workflow (Sprint 6)

---

## Step 1: Create Directory Structure

Create every directory and empty file exactly as specified in CLAUDE.md repository layout.

Key directories to create:
```
tool/__init__.py
tool/cli.py
tool/stage2/__init__.py
tool/stage2/layers/__init__.py
tool/stage2/layers/l1_scaffold.py
tool/stage2/layers/l2_pipeline.py
tool/stage2/layers/l4_idiom.py
tool/stage2/qa/__init__.py
tool/stage2/qa/idiom_rules.py
tool/stage2/qa/qa_pipeline.py
tool/stage2/qa/validators.py
tool/templates/glue_job_scaffold.j2
tool/templates/phase1_download.j2
tool/templates/phase2_lambda.j2
tool/templates/phase3_load.j2
tool/templates/step_functions_sfn.j2
tool/templates/glue_workflow_tf.j2
tool/templates/eventbridge_tf.j2
tool/templates/aurora_ddl.j2
tool/config/llm_prompts.yaml
tests/__init__.py
tests/test_l1_scaffold.py
tests/test_l2_pipeline.py
tests/test_l4_idiom.py
tests/fixtures/sample_etl_spec.yaml
source-packages/ssis/.gitkeep
source-packages/adf/.gitkeep
requirements-docs/.gitkeep
generated/glue-jobs/.gitkeep
generated/glue-workflows/.gitkeep
generated/step-functions/.gitkeep
generated/eventbridge/.gitkeep
generated/lambda/.gitkeep
generated/db-migrations/.gitkeep
generated/dqdl/.gitkeep
generated/tests/.gitkeep
```

---

## Step 2: pyproject.toml

Create `pyproject.toml` with:
- Python 3.11+
- Dependencies: jinja2, pyyaml, ruff, pytest, click
- Entry point: `tool.cli:main`

```toml
[tool.poetry]
name = "etl-migration-tool"
version = "0.1.0"
description = "Custom SSIS/ADF to AWS Glue migration tool"
python = "^3.11"

[tool.poetry.dependencies]
python = "^3.11"
jinja2 = "^3.1"
pyyaml = "^6.0"
click = "^8.1"
boto3 = "^1.34"

[tool.poetry.dev-dependencies]
pytest = "^8.0"
ruff = "^0.4"

[tool.poetry.scripts]
etl-tool = "tool.cli:main"

[tool.ruff]
line-length = 120
target-version = "py311"
```

---

## Step 3: Implement L1 — Structural Scaffold (l1_scaffold.py)

**Input:** dict containing job metadata from requirements doc front-matter + §6 control flow etl-spec block  
**Output:** dict of {filename: rendered_content} for all 5 templates

### L1 Input Schema

```python
context = {
    "job_name": "etl_orders_daily",
    "glue_version": "4.0",
    "iam_role_arn": "${var.glue_iam_role_arn}",  # Always a parameter reference
    "scripts_location": "s3://${var.glue_scripts_bucket}/jobs/",
    "pattern": "THREE_PHASE_STATIC_LOAD",  # or GENERAL_ETL
    "phases": [
        {
            "phase": 1,
            "name": "Static Data Download",
            "execution": "parallel",
            "tasks": ["download_products", "download_rates"]
        },
        {
            "phase": 2,
            "name": "SP Execution",
            "execution": "mixed",
            "sp_dependency_graph": {
                "sp_init":    {"depends_on": []},
                "sp_enrich":  {"depends_on": ["sp_init"]},
                "sp_validate":{"depends_on": ["sp_enrich"]}
            }
        },
        {
            "phase": 3,
            "name": "Main Table Load",
            "execution": "parallel",
            "tasks": ["load_orders", "load_items"],
            "transaction_groups": [["load_orders", "load_items"]]
        }
    ],
    "cron_expression": "cron(0 2 * * ? *)",
    "staging_tables": ["staging.tmp_orders", "staging.tmp_customers"],
    "audit_tables": [
        "audit.phase1_load",
        "audit.sp_execution_log",
        "audit.phase3_load"
    ]
}
```

### L1 Templates to Create (all 5 are required)

**glue_job_scaffold.j2** — Glue PySpark job skeleton
- Imports (GlueContext, SparkContext, getResolvedOptions, Job)
- GlueContext and SparkSession initialisation
- getResolvedOptions for job parameters
- try/except wrapper
- job.commit() at end
- Phase 1, 2, 3 placeholder comments

**step_functions_sfn.j2** — Step Functions ASL JSON
- Initialize state
- Phase1_Parallel state: one branch per Phase 1 task
- Phase2 states: built from sp_dependency_graph adjacency list (Parallel for independent, sequential for dependent)
- DataQualityGate state
- Phase3_Parallel state: one branch per Phase 3 task
- HandleFailure and DataQualityFailed error states

**glue_workflow_tf.j2** — Terraform for Glue Workflow
- `aws_glue_workflow` resource
- Conditional triggers (SUCCEEDED/FAILED)
- Glue job resources with DPU placeholders

**eventbridge_tf.j2** — Terraform for EventBridge
- `aws_cloudwatch_event_rule` with cron_expression
- Target: Step Functions StartExecution
- IAM role for EventBridge → Step Functions

**aurora_ddl.j2** — Flyway DDL migration script
- `CREATE SCHEMA IF NOT EXISTS staging`
- `CREATE SCHEMA IF NOT EXISTS audit`
- `CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_*` for each staging table
- `CREATE TABLE IF NOT EXISTS audit.phase1_load (...)`
- `CREATE TABLE IF NOT EXISTS audit.sp_execution_log (...)`
- `CREATE TABLE IF NOT EXISTS audit.phase3_load (...)`

### L1 Implementation Pattern

```python
# tool/stage2/layers/l1_scaffold.py
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

class L1Scaffold:
    TEMPLATES = [
        ("glue_job_scaffold.j2",  "glue-jobs/{job_name}.py"),
        ("step_functions_sfn.j2", "step-functions/{job_name}.asl.json"),
        ("glue_workflow_tf.j2",   "glue-workflows/{job_name}.tf"),
        ("eventbridge_tf.j2",     "eventbridge/{job_name}.tf"),
        ("aurora_ddl.j2",         "db-migrations/V001__{job_name}.sql"),
    ]

    def __init__(self, templates_dir: str = "tool/templates"):
        self.env = Environment(loader=FileSystemLoader(templates_dir), keep_trailing_newline=True)

    def render_all(self, context: dict) -> dict[str, str]:
        """Render all 5 L1 templates. Returns {output_path: rendered_content}."""
        outputs = {}
        for template_file, output_pattern in self.TEMPLATES:
            template = self.env.get_template(template_file)
            output_path = output_pattern.format(**context)
            outputs[output_path] = template.render(context)
        return outputs
```

---

## Step 4: Implement L2 — Data Pipeline Scaffold (l2_pipeline.py)

**Input:** List of etl-spec YAML blocks from requirements document §4  
**Output:** Phase-organised Python code snippets assembled into the L1 scaffold

### L2 Must Implement All 18 Rules

Implement all rules exactly as specified. No partial implementation.

**Phase 1 Rules:**
- P1-R1: One Glue Python Shell job per distinct source_id
- P1-R2: TRUNCATE staging.tmp_{table} before ANY read
- P1-R3: If query_or_path contains SELECT with JOIN → JDBC pushdown (not PySpark join)
- P1-R4: conn.autocommit = False; COMMIT after audit INSERT only; except: ROLLBACK
- P1-R5: INSERT INTO audit.phase1_load after successful staging write
- P1-R6: DPU sizing: <100K → G.025X/2; <10M → G.1X/2; >10M → G.2X/4; unknown → G.1X/2 + WARNING

**Phase 2 Rules:**
- P2-R1: Absent or [MANUAL] sp_rewrite_strategy → always default to keep_plpgsql (Lambda wrapper)
- P2-R2: sp_dependency_graph adjacency list → Step Functions ASL Parallel/sequential states
- P2-R3: Lambda uses RDS Proxy endpoint; autocommit=False; try/CALL/COMMIT; except/ROLLBACK; finally/close
- P2-R4: Step Functions Retry: MaxAttempts=2, IntervalSeconds=30, BackoffRate=2.0; Catch P0001 → HandleFailure
- P2-R5: sp_estimated_duration_minutes > 12 → Glue Python Shell + waitForTaskToken; emit WARNING
- P2-R6: INSERT INTO audit.sp_execution_log after each CALL

**Phase 3 Rules:**
- P3-R1: transaction_groups from control flow etl-spec → tables in same group share ONE psycopg2 transaction
- P3-R2: except psycopg2.Error: conn.rollback(); do NOT truncate staging on failure; log to CloudWatch
- P3-R3: truncate_insert → BEGIN; TRUNCATE; INSERT INTO main SELECT * FROM staging; COMMIT. upsert → INSERT ON CONFLICT in batches of 1000. [MANUAL] → truncate_insert skeleton + TODO
- P3-R4: Upsert batching: executemany in batches of 1000; entire loop in single transaction
- P3-R5: INSERT INTO audit.phase3_load after COMMIT
- P3-R6: boto3 put_events EventBridge completion event after final Phase 3 COMMIT

### L2 etl-spec Block Types to Handle

Handle all of these transform_type values:
- `source_read` → Phase 1 code
- `target_write` → Phase 3 code
- `join` → Phase 2 PySpark df.join()
- `filter` → Phase 2 df.filter()
- `aggregate` → Phase 2 df.groupBy().agg()
- `sort` → Phase 2 df.orderBy() (only if required=true; else WARNING)
- `union` → Phase 2 df.unionByName()
- `window` → Phase 2 df.withColumn(Window...)
- `sp_call` → Phase 2 Lambda function body
- `derive` → Phase 2 df.withColumn()

### L2 Templates to Create

**phase1_download.j2** — Glue Python Shell job for a single source download  
**phase2_lambda.j2** — Lambda function body for SP call (keep_plpgsql pattern)  
**phase3_load.j2** — Phase 3 main table transfer with transaction management  

---

## Step 5: Implement L4 — Idiom Enforcement (l4_idiom.py + idiom_rules.py)

**Input:** Python code string (any generated .py file)  
**Output:** Tuple of (corrected_code: str, violations: list[dict])

### idiom_rules.py

Define all 10 rules as structured data:

```python
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    AUTO_CORRECT = "AUTO_CORRECT"
    FLAG_MANUAL = "FLAG_MANUAL"
    FLAG_INFO = "FLAG_INFO"
    FLAG_CORRECTNESS_RISK = "FLAG_CORRECTNESS_RISK"
    FLAG_SECURITY = "FLAG_SECURITY"

@dataclass
class IdiomRule:
    rule_id: str
    description: str
    severity: Severity
    blocks_output: bool  # True only for FLAG_SECURITY

L4_RULES = [
    IdiomRule("L4-R01", "Loop over df.rdd.collect() or df.toLocalIterator()", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R02", ".collect() on large DataFrame", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R03", "psycopg2 call inside df.rdd.map() or df.foreach()", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R04", "udf() where expression_type != custom_logic", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R05", "AWS credential string (AKIA...)", Severity.FLAG_SECURITY, True),
    IdiomRule("L4-R06", "Hard-coded s3:// path literal", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R07", "DataFrame used >2x without .cache()", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R08", "spark.read.jdbc() without schema= param", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R09", "conn.autocommit = True in Phase 3", Severity.FLAG_CORRECTNESS_RISK, False),
    IdiomRule("L4-R10", "SQL string concatenation f-string or +", Severity.FLAG_SECURITY, False),
]
```

### l4_idiom.py

Implement the scanner using Python's `ast` module:

```python
import ast
from typing import Tuple

class L4IdiomScanner:
    def scan(self, python_code: str) -> Tuple[str, list[dict]]:
        """
        Scan generated Python code for all 10 L4 anti-patterns.
        Returns (corrected_code, violations_list).
        violations_list items: {rule_id, description, severity, line_no, blocks_output}
        """
        ...

    def _check_r01_collect_loop(self, tree): ...
    def _check_r02_collect_call(self, tree): ...
    def _check_r03_db_in_map(self, tree): ...
    def _check_r04_udf_call(self, tree): ...
    def _check_r05_aws_credential(self, tree): ...   # Must set blocks_output=True
    def _check_r06_hardcoded_s3(self, tree): ...     # Auto-correct
    def _check_r07_uncached_df(self, tree): ...      # Auto-correct
    def _check_r08_jdbc_no_schema(self, tree): ...   # Auto-correct
    def _check_r09_autocommit_true(self, tree): ...
    def _check_r10_sql_concat(self, tree): ...       # Must set blocks_output=True
```

---

## Step 6: Implement CLI (cli.py)

Use `click` library. Four subcommands:

```python
@click.group()
def main(): pass

@main.command()
@click.argument("source_path")
@click.option("--output-csv", default=None)
def pre_screen(source_path, output_csv):
    """Pre-screen SSIS/ADF files for eligibility."""
    # Sprint 1 implementation — Sprint 0: stub that prints "Pre-screen not yet implemented"
    click.echo(f"Pre-screen: {source_path} (not implemented until Sprint 1)")

@main.command()
@click.argument("source_file")
@click.option("--output", default="requirements-docs/")
def stage1(source_file, output):
    """Parse SSIS/ADF file and generate requirements document."""
    # Sprint 1 implementation — Sprint 0: stub
    click.echo(f"Stage 1: {source_file} (not implemented until Sprint 1)")

@main.command()
@click.argument("requirements_doc")
@click.option("--output", default="generated/")
def stage2(requirements_doc, output):
    """Generate Glue code from signed-off requirements document."""
    from tool.stage2.spec_parser import SpecParser
    from tool.stage2.layers.l1_scaffold import L1Scaffold
    from tool.stage2.layers.l2_pipeline import L2Pipeline
    from tool.stage2.layers.l4_idiom import L4IdiomScanner
    from tool.stage2.qa.qa_pipeline import QAPipeline
    # Full Sprint 0 implementation here

@main.command()
@click.argument("source_file")
@click.option("--skip-approval-gate", is_flag=True, default=False)
def pipeline(source_file, skip_approval_gate):
    """Run Stage 1 + Stage 2 end-to-end (testing only)."""
    # Sprint 1+ implementation — Sprint 0: stub
    click.echo(f"Pipeline: {source_file} (Stage 1 not yet implemented)")
```

---

## Step 7: Implement QA Pipeline (qa_pipeline.py)

Implement the QA-1 through QA-6 orchestrator:

```python
class QAPipeline:
    def run(self, generated_artifacts: dict, spec_blocks: list, etl_spec_context: dict) -> QAResult:
        """
        Run all 6 QA gates in sequence.
        QA-1 security violation → immediately return QAResult(blocked=True)
        All other gates → collect findings, continue, return full QAResult
        """
        result = QAResult()
        
        # QA-1: L4 Idiom Scan (runs first, can block)
        # QA-2: Spec Block Completeness
        # QA-3: L3 Expression Confidence (skipped in Sprint 0 — no L3)
        # QA-4: Transaction Pattern
        # QA-5: IaC Completeness
        # QA-6: Test Coverage (skipped in Sprint 0 — no L5)
        
        return result
```

---

## Step 8: Create Fixtures and Tests

### tests/fixtures/sample_etl_spec.yaml

```yaml
job_name: etl_orders_daily
source_system: SSIS
pattern: THREE_PHASE_STATIC_LOAD
stage2_permitted: true

phases:
  - phase: 1
    name: Static Data Download
    execution: parallel
    tasks:
      - transform_id: source_orders
        transform_type: source_read
        source_id: orders_source
        connection_type: jdbc
        connection_ref: AzureSqlServer
        source_type: table
        query_or_path: dbo.Orders
        row_count_estimate: 500000
      - transform_id: source_customers
        transform_type: source_read
        source_id: customers_source
        connection_type: jdbc
        connection_ref: AzureSqlServer
        query_or_path: dbo.Customers
        row_count_estimate: 45000

  - phase: 2
    name: SP Execution
    execution: mixed
    sp_dependency_graph:
      sp_init:     {depends_on: []}
      sp_enrich:   {depends_on: [sp_init]}
      sp_validate: {depends_on: [sp_enrich]}
    tasks:
      - transform_id: join_orders_customers
        transform_type: join
        left: df_orders
        right: df_customers
        join_key: customer_id
        join_type: left
        null_handling: include_nulls_from_right

      - transform_id: call_sp_validate
        transform_type: sp_call
        sp_name: dbo.usp_ValidateOrders
        sp_rewrite_strategy: keep_plpgsql
        sp_estimated_duration_minutes: 5
        transaction_scope: individual

  - phase: 3
    name: Main Table Load
    execution: parallel
    tasks:
      - transform_id: load_orders_main
        transform_type: target_write
        target_schema: public
        target_table: orders
        write_mode: truncate_insert
      - transform_id: load_customers_main
        transform_type: target_write
        target_schema: public
        target_table: customers
        write_mode: truncate_insert
    transaction_groups:
      - [orders, customers]

schedule:
  trigger_type: schedule
  cron_expression: "cron(0 2 * * ? *)"

staging_tables:
  - staging.tmp_orders
  - staging.tmp_customers
```

### tests/test_l1_scaffold.py

Write tests that verify:
1. `render_all()` returns exactly 5 keys
2. Glue job .py output contains `GlueContext`, `job.commit()`, `getResolvedOptions`
3. Step Functions ASL is valid JSON with Phase1_Parallel, Phase2, Phase3_Parallel states
4. Terraform .tf output contains `aws_glue_workflow` and `aws_cloudwatch_event_rule` resources
5. Aurora DDL contains `CREATE UNLOGGED TABLE IF NOT EXISTS staging.tmp_orders`
6. All 5 templates render without Jinja2 exceptions

### tests/test_l2_pipeline.py

Write tests that verify:
1. source_read block → generates TRUNCATE before read (P1-R2)
2. source_read with row_count_estimate=500000 → G.1X DPU comment (P1-R6)
3. source_read with row_count_estimate=50000 → G.025X DPU comment (P1-R6)
4. target_write with write_mode=truncate_insert → generates BEGIN/TRUNCATE/INSERT/COMMIT (P3-R3)
5. target_write → generates EventBridge put_events call (P3-R6)
6. sp_call → generates Lambda function body with RDS Proxy + autocommit=False (P2-R3)
7. join block → generates df.join() with correct join_type (left)
8. All 18 rules have at least one test

### tests/test_l4_idiom.py

Write one test per rule that **deliberately introduces** the anti-pattern and verifies detection:

```python
def test_r01_collect_loop_detected():
    code = "for row in df.rdd.collect():\n    process(row)"
    scanner = L4IdiomScanner()
    _, violations = scanner.scan(code)
    rule_ids = [v["rule_id"] for v in violations]
    assert "L4-R01" in rule_ids

def test_r05_aws_credential_blocks_output():
    code = 'key = "AKIAIOSFODNN7EXAMPLE"'
    scanner = L4IdiomScanner()
    _, violations = scanner.scan(code)
    blocking = [v for v in violations if v["blocks_output"]]
    assert any(v["rule_id"] == "L4-R05" for v in blocking)

def test_r06_hardcoded_s3_autocorrected():
    code = 'path = "s3://my-bucket/my-prefix/data.parquet"'
    scanner = L4IdiomScanner()
    corrected, violations = scanner.scan(code)
    assert "s3://my-bucket" not in corrected
    assert "L4-R06" in [v["rule_id"] for v in violations]

# ... one test per rule for all 10
```

---

## Step 9: CI Skeleton (.github/workflows/test.yml)

```yaml
name: CI — Lint and Test

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["main"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check tool/
      - name: Test
        run: pytest tests/ -v
```

---

## Acceptance Criteria — Sprint 0 Complete When ALL Pass

- [ ] All directories and files created as per CLAUDE.md layout
- [ ] L1 renders all 5 templates with no Jinja2 errors given sample_etl_spec.yaml context
- [ ] L1 Step Functions ASL output is valid JSON with Phase1_Parallel, Phase2, Phase3_Parallel
- [ ] L1 Aurora DDL output contains UNLOGGED TABLE for each staging table
- [ ] L2 generates TRUNCATE before read for every source_read block (P1-R2)
- [ ] L2 generates correct DPU sizing comment for all three row count ranges (P1-R6)
- [ ] L2 generates RDS Proxy + autocommit=False in Lambda SP wrapper (P2-R3)
- [ ] L2 generates single transaction for FK-grouped tables in Phase 3 (P3-R1)
- [ ] L2 generates EventBridge put_events after Phase 3 COMMIT (P3-R6)
- [ ] L4 detects all 10 anti-patterns when deliberately introduced in test code
- [ ] L4-R05 and L4-R10 set blocks_output=True
- [ ] L4-R06, L4-R07, L4-R08 auto-correct the code
- [ ] QA-1 runs L4 scan before any file is written to disk
- [ ] QA-1 returns blocked=True when L4-R05 (security) is detected
- [ ] CLI `stage2` command runs end-to-end on sample_etl_spec.yaml and writes to generated/
- [ ] `pytest tests/ -v` → 100% pass, zero failures
- [ ] `ruff check tool/` → zero errors
- [ ] Code committed and pushed to sprint-0 branch
- [ ] PR opened against main

---

## After Sprint 0 — Do Not Start Sprint 1 Until

1. PR merged to main
2. All acceptance criteria above ticked
3. (Ideally) verified on at least one real .dtsx file from the estate using `--skip-approval-gate` flag
