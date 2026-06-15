# tasks/sprint-1.md
# Sprint 1: Stage 1 — SSIS Parser

**Duration:** Weeks 2–3  
**Prerequisite:** Sprint 0 merged to main and all acceptance criteria passed  
**Branch:** `feature/sprint-1-ssis-parser`

---

## Read First

1. `CLAUDE.md` — project context
2. `Custom_Tool_Implementation.docx` §3.1 (SSIS Parser), §3.3 (Expression Normaliser), §3.4 (Pattern Classifier), §4 (Requirements Document Schema)

Do NOT read other sections — stay focused on Stage 1 SSIS only.

---

## What to Build

Four modules:
- `tool/stage1/parsers/ssis_parser.py` — SSIS .dtsx XML parser
- `tool/stage1/parsers/expression_normaliser.py` — SSIS expression → natural language
- `tool/stage1/analysers/pattern_classifier.py` — Three-phase pattern detection + SP DAG
- `tool/stage1/writers/mermaid_generator.py` — SP dependency DAG → Mermaid diagram

Also wire into:
- `tool/stage1/writers/requirements_writer.py` — Markdown + etl-spec YAML writer (stub → full)
- `tool/cli.py` — fill in `stage1` subcommand (was a stub in Sprint 0)

---

## Module 1: ssis_parser.py

### Input
Path to a `.dtsx` file (XML)

### Output
Dict matching the requirements document schema (§4 front-matter + all sections §1–§12)

### XML Elements to Extract

Extract all of these (from §3.1 of the spec):

| XPath / Element | Target Field |
|---|---|
| `DTS:Executable[@DTS:ExecutableType="SSIS.Package.3"]/@DTS:ObjectName` | `job_name` |
| `DTS:PackageVariable` | `parameters[]` (type=variable) |
| `DTS:Parameter` | `parameters[]` (type=parameter) |
| `DTS:ConnectionManager` + ConnectionString | `data_sources[].connection_ref` — name only, never credentials |
| `pipeline:component[@componentClassID="DTSAdapter.OleDbSource"]` | `data_sources[]` with sql_query or table_name |
| `pipeline:component[@componentClassID="DTSTransform.DerivedColumn"]` | `transformations[]` type=derive, expression string |
| `pipeline:component[@componentClassID="DTSTransform.Lookup"]` | `transformations[]` type=join, no_match_behaviour |
| `pipeline:component[@componentClassID="DTSTransform.ConditionalSplit"]` | `transformations[]` type=filter, conditions in order |
| `DTS:Executable[@ExecutableType="Microsoft.ExecuteSQLTask"]` | `transformations[]` type=sp_call or source_read |
| `DTS:Executable[@ExecutableType="Microsoft.ExecutePackageTask"]` | `dependencies[]` — child package reference |
| `DTS:EventHandlers/DTS:EventHandler` | `error_handling[]` — OnError, OnWarning, OnSuccess |
| `.//DTS:PrecedenceConstraint` | `control_flow.adjacency_list[]` |

### Key Rules

1. Never store credential values. Store connection manager names only.
2. Extract expression strings verbatim — pass to expression_normaliser.py, not parsed here.
3. Script Component bodies → extract C# body verbatim, flag [MANUAL: SCRIPT COMPONENT C#]
4. ForEach containers → extract structure, flag child tasks as [MANUAL: FOREACH ITERATION]
5. Execute Package Task → record child package path as dependency, do not recurse into child

### Implementation Pattern

```python
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# SSIS XML namespaces
NAMESPACES = {
    "DTS": "www.microsoft.com/SqlServer/Dts",
    "pipeline": "www.microsoft.com/SqlServer/Dts/Pipeline",
    "SQLTask": "www.microsoft.com/sqlserver/dts/tasks/sqltask",
}

class SsisParser:
    def parse(self, dtsx_path: str) -> dict:
        """Parse a .dtsx file and return requirements document data dict."""
        tree = ET.parse(dtsx_path)
        root = tree.getroot()
        return {
            "job_name": self._extract_job_name(root),
            "source_system": "SSIS",
            "source_file": str(dtsx_path),
            "parameters": self._extract_parameters(root),
            "data_sources": self._extract_data_sources(root),
            "transformations": self._extract_transformations(root),
            "control_flow": self._extract_control_flow(root),
            "error_handling": self._extract_error_handling(root),
            "dependencies": self._extract_dependencies(root),
            "manual_item_count": 0,  # updated after flagging
            "confidence_score": 0,   # updated after pattern classification
        }
```

---

## Module 2: expression_normaliser.py

### Input
Raw SSIS expression string (e.g. `ISNULL([CustomerName]) ? "Unknown" : [CustomerName]`)

### Output
Dict: `{natural_language: str, pyspark_hint: str, requires_manual: bool, original: str}`

### Patterns to Handle (from §3.3)

Implement all patterns from the spec §3.3 expression table:

| SSIS Expression | Natural Language | PySpark Hint |
|---|---|---|
| `ISNULL([col])` | Is the value of {col} null? | `coalesce(col, default)` or `col.isNull()` |
| `(DT_WSTR, 50)[col]` | Cast {col} to string max length 50 | `col.cast(StringType()).substr(0,50)` |
| `DATEPART("year", [col])` | Extract year from {col} | `year(col("col"))` |
| `GETDATE()` | Current timestamp at execution time | `current_timestamp()` |
| `TRIM([col])` | Remove leading/trailing whitespace | `trim(col("col"))` |
| `REPLACE([col], "a", "b")` | Replace "a" with "b" in {col} | `regexp_replace(col("col"), "a", "b")` |
| `LEFT([col], 3)` | First 3 characters of {col} | `col("col").substr(1, 3)` |
| `[col1] + [col2]` | Concatenate {col1} and {col2} | `concat(col("col1"), col("col2"))` |
| `iif([cond], [v1], [v2])` | If {cond} then {v1} else {v2} | `when(condition, v1).otherwise(v2)` |
| Nested >3 levels | [MANUAL: COMPLEX EXPRESSION — original: {raw}] | Route to L3 in Stage 2 |
| C# Script Component | [MANUAL: SCRIPT COMPONENT C# — see §12] | Route to L3 if enabled |

---

## Module 3: pattern_classifier.py

### Input
The parsed output dict from ssis_parser.py (specifically control_flow.adjacency_list and transformations)

### Output
```python
{
    "pattern": "THREE_PHASE_STATIC_LOAD",  # or "GENERAL_ETL"
    "phase_boundaries": {
        "phase1_tasks": ["download_products", "download_rates"],
        "phase2_tasks": ["sp_init", "sp_enrich", "sp_validate"],
        "phase3_tasks": ["transfer_orders", "transfer_items"]
    },
    "sp_dependency_graph": {
        "sp_init":     {"depends_on": []},
        "sp_enrich":   {"depends_on": ["sp_init"]},
        "sp_validate": {"depends_on": ["sp_enrich"]}
    },
    "parallel_groups": [
        ["sp_enrich", "sp_calc"]  # These can run in parallel (same depends_on set)
    ]
}
```

### Detection Rules (from §3.4)

**Phase 1 signals:**
- TRUNCATE TABLE in Execute SQL Tasks at package start
- OLEDB Destination or sink with `staging_` or `tmp_` prefix
- Multiple parallel source reads

**Phase 2 signals:**
- Execute SQL Tasks calling stored procedures
- Data Flow Tasks operating on staging tables
- Complex DML in Execute SQL Tasks

**Phase 3 signals:**
- INSERT INTO main SELECT * FROM staging patterns
- Copy Activity sink with non-staging table prefix
- Task name contains "transfer" or "load"

**All three detected → THREE_PHASE_STATIC_LOAD**  
**Any phase missing → GENERAL_ETL**

### SP Dependency DAG Builder

From the adjacency list in `control_flow`, build the SP dependency graph:
1. Group SP tasks only (not data flow tasks)
2. Read PrecedenceConstraint elements to determine ordering
3. For each SP: collect its `depends_on` set
4. Identify independent SPs at each level (same depends_on set → Parallel candidates)

---

## Module 4: mermaid_generator.py

### Input
`sp_dependency_graph` dict from pattern_classifier.py

### Output
Mermaid diagram string to embed in requirements document §6

```python
def generate_sp_dag_mermaid(sp_dependency_graph: dict) -> str:
    """
    Generate Mermaid flowchart from SP dependency graph.
    
    Example output:
    ```mermaid
    flowchart TD
        sp_init["sp_init"]
        sp_enrich["sp_enrich"]
        sp_validate["sp_validate"]
        sp_init --> sp_enrich
        sp_enrich --> sp_validate
    ```
    """
```

---

## Update requirements_writer.py

Generate the full requirements document Markdown from the parsed dict.

Sections to generate:
- §1 Overview (job_name, source_system, pattern)
- §2 Data Sources (one subsection per source with etl-spec block)
- §3 Data Targets (stubs — populated from etl-spec blocks in §4)
- §4 Transformations (one subsection + etl-spec block per transform)
- §5 Business Rules (stub with [MANUAL INPUT REQUIRED])
- §6 Control Flow (Mermaid DAG + control_flow etl-spec block)
- §7 Error Handling (from error_handling list)
- §8 Schedule & Triggers (from parameters/schedule)
- §9 Parameters (from parameters list)
- §10 Data Quality Rules (stub with [MANUAL INPUT REQUIRED])
- §11 Dependencies (child packages)
- §12 Assumptions & Gaps ([MANUAL] items collected here)

Include YAML front-matter with stage2_permitted: false until human signs off.

---

## Update CLI stage1 subcommand

```python
@main.command()
@click.argument("source_file")
@click.option("--output", default="requirements-docs/")
def stage1(source_file, output):
    """Parse SSIS/ADF file and generate requirements document."""
    from tool.stage1.parsers.ssis_parser import SsisParser
    from tool.stage1.parsers.expression_normaliser import ExpressionNormaliser
    from tool.stage1.analysers.pattern_classifier import PatternClassifier
    from tool.stage1.writers.mermaid_generator import MermaidGenerator
    from tool.stage1.writers.requirements_writer import RequirementsWriter

    path = Path(source_file)
    if path.suffix == ".dtsx":
        parser = SsisParser()
    else:
        click.echo(f"ADF parser not yet implemented (Sprint 2). Source: {source_file}")
        return

    parsed = parser.parse(str(path))
    classified = PatternClassifier().classify(parsed)
    parsed["pattern"] = classified["pattern"]
    parsed["sp_dependency_graph"] = classified["sp_dependency_graph"]
    mermaid = MermaidGenerator().generate_sp_dag_mermaid(classified["sp_dependency_graph"])
    parsed["sp_dag_mermaid"] = mermaid

    output_dir = Path(output) / parsed["job_name"]
    output_dir.mkdir(parents=True, exist_ok=True)
    requirements_path = output_dir / "REQUIREMENTS.md"
    RequirementsWriter().write(parsed, str(requirements_path))
    click.echo(f"Stage 1 complete: {requirements_path}")
    click.echo(f"Manual items: {parsed['manual_item_count']}")
    click.echo("Next: review and sign off REQUIREMENTS.md, then run stage2")
```

---

## Fixtures

Create in `tests/fixtures/`:
- `sample_ssis.dtsx` — minimal but realistic SSIS package XML with:
  - One OleDb Source (dbo.Orders table)
  - One Derived Column transform
  - One Lookup transform
  - One Execute SQL Task (SP call)
  - One OleDb Destination (staging.tmp_orders)
  - PrecedenceConstraints linking them in order
- `expected_requirements.md` — what the requirements doc should look like for the sample fixture

---

## Tests

### tests/test_ssis_parser.py

1. `test_parse_returns_job_name` — assert job_name extracted correctly
2. `test_parse_extracts_oledb_source` — assert data_sources has connection_ref and query_or_path
3. `test_parse_never_stores_credentials` — assert no connection string values in output
4. `test_parse_extracts_derived_column_expression` — raw expression string in transformations
5. `test_parse_extracts_sp_call` — Execute SQL Task → transform type sp_call
6. `test_parse_extracts_precedence_constraints` — adjacency list built correctly
7. `test_parse_flags_script_component_manual` — Script Component → [MANUAL] flag

### tests/test_pattern_classifier.py

1. `test_detects_three_phase_pattern` — given staging tables + SP tasks + INSERT main → THREE_PHASE_STATIC_LOAD
2. `test_detects_general_etl` — given no staging tables → GENERAL_ETL
3. `test_builds_sp_dependency_graph` — SP precedence constraints → correct adjacency list
4. `test_identifies_parallel_groups` — two SPs with same depends_on → same parallel group

---

## Acceptance Criteria — Sprint 1 Complete When ALL Pass

- [ ] `ssis_parser.py` extracts all elements from the §3.1 XPath table
- [ ] Parser never stores credential values in output
- [ ] Script Component body → [MANUAL: SCRIPT COMPONENT C#] flag
- [ ] `expression_normaliser.py` handles all patterns in §3.3 table
- [ ] Complex expressions (>3 nesting levels) → [MANUAL] with original expression
- [ ] `pattern_classifier.py` correctly detects THREE_PHASE_STATIC_LOAD from sample fixture
- [ ] SP dependency graph built correctly from PrecedenceConstraints
- [ ] `mermaid_generator.py` produces valid Mermaid flowchart string
- [ ] `requirements_writer.py` generates Markdown with all 12 sections
- [ ] Requirements doc includes YAML front-matter with `stage2_permitted: false`
- [ ] CLI `stage1 sample_ssis.dtsx` runs end-to-end and writes REQUIREMENTS.md
- [ ] Manual item count correctly reported in CLI output
- [ ] `pytest tests/ -v` → 100% pass
- [ ] `ruff check tool/` → zero errors
- [ ] PR opened against main
