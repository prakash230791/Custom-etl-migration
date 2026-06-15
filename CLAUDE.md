# Custom ETL Migration Tool — Project Context

## What This Tool Does

Two-stage pipeline converting SSIS `.dtsx` and ADF pipeline JSON into AWS Glue PySpark jobs.

**Stage 1** → Parse source files → generate human-readable requirements document (Markdown + etl-spec YAML blocks)  
**Stage 2** → Read signed-off requirements doc → generate Glue jobs, IaC, Lambda functions, tests

The requirements document is the authoritative intermediate artefact. Stage 2 cannot run until a human signs off Stage 1. This gate is non-negotiable.

---

## Repository Layout

```
Custom-etl-migration/
├── CLAUDE.md                         # This file
├── pyproject.toml
├── .github/workflows/
│   ├── test.yml                      # CI: lint + pytest on every PR
│   └── intake.yml                    # Auto-trigger Stage 1+2 on commit to source-packages/
├── source-packages/
│   ├── ssis/                         # Input: .dtsx, .conmgr, .params files
│   └── adf/                          # Input: ADF pipeline ARM JSON files
├── requirements-docs/
│   └── {job_name}/REQUIREMENTS.md   # Stage 1 output (version-controlled)
├── generated/
│   ├── glue-jobs/{job_name}.py
│   ├── glue-workflows/{job_name}.tf
│   ├── step-functions/{job_name}.asl.json
│   ├── eventbridge/{job_name}.tf
│   ├── lambda/{job_name}/{sp_name}.py
│   ├── db-migrations/V{n}__{job_name}.sql
│   ├── dqdl/{job_name}.json
│   └── tests/test_{job_name}.py
├── docs/
│   └── {job_name}_conversion_notes.md
├── tool/
│   ├── cli.py                        # CLI: pre-screen | stage1 | stage2 | pipeline
│   ├── prescreen/
│   │   ├── classifier.py
│   │   └── reporter.py
│   ├── stage1/
│   │   ├── parsers/
│   │   │   ├── ssis_parser.py
│   │   │   ├── adf_parser.py
│   │   │   └── expression_normaliser.py
│   │   ├── analysers/
│   │   │   ├── dependency_graph.py
│   │   │   ├── pattern_classifier.py
│   │   │   └── manual_flagger.py
│   │   └── writers/
│   │       ├── requirements_writer.py
│   │       └── mermaid_generator.py
│   ├── stage2/
│   │   ├── spec_parser.py
│   │   ├── layers/
│   │   │   ├── l1_scaffold.py
│   │   │   ├── l2_pipeline.py
│   │   │   ├── l3_expressions.py
│   │   │   ├── l4_idiom.py
│   │   │   └── l5_tests.py
│   │   ├── generators/
│   │   │   ├── glue_job.py
│   │   │   ├── glue_workflow.py
│   │   │   ├── step_functions.py
│   │   │   ├── eventbridge.py
│   │   │   ├── lambda_fn.py
│   │   │   ├── aurora_ddl.py
│   │   │   ├── dqdl.py
│   │   │   └── conversion_notes.py
│   │   └── qa/
│   │       ├── qa_pipeline.py        # QA-1 through QA-6 orchestrator
│   │       ├── idiom_rules.py        # L4 rule definitions
│   │       └── validators.py
│   ├── templates/
│   │   ├── glue_job_scaffold.j2
│   │   ├── phase1_download.j2
│   │   ├── phase2_lambda.j2
│   │   ├── phase3_load.j2
│   │   ├── step_functions_sfn.j2
│   │   ├── glue_workflow_tf.j2
│   │   ├── eventbridge_tf.j2
│   │   ├── aurora_ddl.j2
│   │   └── unit_test_skeleton.j2
│   └── config/
│       ├── ssis_task_map.yaml
│       ├── adf_activity_map.yaml
│       ├── type_map.yaml
│       └── llm_prompts.yaml
└── tests/
    ├── test_ssis_parser.py
    ├── test_adf_parser.py
    ├── test_spec_parser.py
    ├── test_l1_scaffold.py
    ├── test_l2_pipeline.py
    ├── test_l4_idiom.py
    └── fixtures/
        ├── sample_ssis.dtsx
        ├── sample_adf.json
        └── expected_requirements.md
```

---

## Five-Layer Code Generation Engine (Stage 2)

| Layer | Module | Deterministic? | Sprint |
|-------|--------|----------------|--------|
| L1 — Structural Scaffold | l1_scaffold.py + Jinja2 templates | Yes | Sprint 0 |
| L2 — Data Pipeline Scaffold | l2_pipeline.py + Jinja2 templates | Yes | Sprint 0 |
| L3 — Expression Translation | l3_expressions.py + Claude API | No (LLM) | Sprint 3 |
| L4 — Idiom Enforcement | l4_idiom.py + idiom_rules.py | Yes (AST) | Sprint 0 |
| L5 — Test Generation | l5_tests.py + Claude API + Jinja2 | No (LLM) | Sprint 4 |

---

## Three-Phase Pattern (Critical Concept)

Most ETL jobs follow this pattern. Detection drives ASL template selection.

- **Phase 1** — TRUNCATE staging tables → download sources in parallel
- **Phase 2** — Execute SPs or transforms operating on staged data
- **Phase 3** — Transfer from staging to main tables (single transaction per FK group)

Pattern detected → `THREE_PHASE_STATIC_LOAD` → use three-phase ASL template  
Pattern not detected → `GENERAL_ETL` → use general template

---

## L2 Rules Summary (18 Rules)

**Phase 1 (P1-R1 to P1-R6):** One job per source; TRUNCATE before read; JDBC pushdown for JOINs; autocommit=False; audit INSERT; DPU sizing from row_count_estimate  
**Phase 2 (P2-R1 to P2-R6):** Default keep_plpgsql; Step Functions from dependency DAG; Lambda via RDS Proxy; retry config; long SP → Glue Python Shell; audit INSERT  
**Phase 3 (P3-R1 to P3-R6):** Single transaction per FK group; ROLLBACK on exception; write_mode drives transfer pattern; upsert in batches of 1000; audit INSERT; EventBridge completion event

---

## L4 Anti-Pattern Rules (10 Rules)

| Rule | Severity |
|------|----------|
| L4-R01: Loop over df.rdd.collect() | FLAG_MANUAL |
| L4-R02: .collect() on large data | FLAG_MANUAL |
| L4-R03: psycopg2 inside df.map() | AUTO_CORRECT or FLAG_MANUAL |
| L4-R04: udf() where not custom_logic | FLAG_MANUAL |
| L4-R05: AWS credential in string | FLAG_SECURITY — BLOCKS OUTPUT |
| L4-R06: Hard-coded S3 path | AUTO_CORRECT |
| L4-R07: DataFrame not cached when used >2x | AUTO_CORRECT |
| L4-R08: spark.read.jdbc() without schema= | AUTO_CORRECT |
| L4-R09: autocommit=True in Phase 3 | FLAG_CORRECTNESS_RISK |
| L4-R10: SQL string concatenation | FLAG_SECURITY |

---

## QA Gates (Stage 2)

| Gate | Trigger | Blocks Output? |
|------|---------|----------------|
| QA-1: L4 Idiom Scan | Before any file written | Security violations only |
| QA-2: Spec Block Completeness | After spec parser loads | No — placeholder written |
| QA-3: L3 Expression Confidence | After each L3 API call | No — [MANUAL] fallback |
| QA-4: Transaction Pattern | After L2 generates code | No — flag + REQUIRES_REVIEW |
| QA-5: IaC Completeness | After L1 generates IaC | No — placeholder written |
| QA-6: Test Coverage | After L5 generates tests | No — warning only |

---

## CLI Commands

```bash
# Pre-screen single file
python -m tool.cli pre-screen source-packages/ssis/job.dtsx

# Pre-screen directory → CSV
python -m tool.cli pre-screen source-packages/ --output-csv census.csv

# Stage 1 only
python -m tool.cli stage1 source-packages/ssis/job.dtsx

# Stage 2 only (requirements doc must be signed off)
python -m tool.cli stage2 requirements-docs/job/REQUIREMENTS.md

# Full pipeline (testing only — skips approval gate)
python -m tool.cli pipeline source-packages/ssis/job.dtsx --skip-approval-gate
```

---

## Testing Standards

```bash
pytest tests/ -v          # All tests must pass
ruff check tool/          # Zero lint errors
```

- L3 and L5 API calls must be mocked in tests — no live API calls in CI
- All L4 rules must have a test that deliberately introduces the anti-pattern and confirms detection
- L1 templates must have a test that confirms rendered output matches a stored fixture

---

## Stack

- Python 3.11+
- Jinja2 (template rendering)
- PyYAML (etl-spec block parsing)
- pytest + ruff (test and lint)
- ast module (L4 AST scanning)
- anthropic SDK (L3 + L5 — Sprint 3+)
- boto3 (EventBridge emission, S3)
- psycopg2 (Aurora PostgreSQL)

---

## Sprint Scope

| Sprint | What Gets Built | Status |
|--------|----------------|--------|
| Sprint 0 | L1 + L2 + L4 + CLI stubs + CI skeleton | **Current sprint** |
| Sprint 1 | Stage 1 SSIS parser (ssis_parser.py, pattern_classifier.py, mermaid_generator.py) | Pending |
| Sprint 2 | Stage 1 ADF parser (adf_parser.py) | Pending |
| Sprint 3 | L3 LLM expression translation | Pending |
| Sprint 4 | L5 test generation | Pending |
| Sprint 5 | Three-phase full rules + generators (aurora_ddl, lambda_fn, dqdl) | Pending |
| Sprint 6 | CI/CD GitHub Actions (intake.yml + test.yml) | Pending |

---

## Key Rules for Code Generation

1. Never generate `autocommit = True` in Phase 3 code
2. Always TRUNCATE staging table before Phase 1 read
3. Always use RDS Proxy endpoint in Lambda — never direct Aurora connection
4. Never hardcode S3 paths — always use parameter references
5. Never use `.collect()` on a DataFrame with row_count_estimate > 10K without a guard
6. Always wrap Phase 3 in a single transaction per FK-linked table group
7. Always emit audit INSERTs in all three phases
8. Always emit EventBridge completion event after Phase 3 COMMIT
