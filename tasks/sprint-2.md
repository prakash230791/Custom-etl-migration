# tasks/sprint-2.md
# Sprint 2: Stage 1 — ADF Parser

**Duration:** Weeks 3–4  
**Prerequisite:** Sprint 1 merged to main  
**Branch:** `feature/sprint-2-adf-parser`

---

## Read First

1. `CLAUDE.md` — project context
2. `Custom_Tool_Implementation.docx` §3.2 (ADF Parser)
3. `tool/stage1/parsers/ssis_parser.py` — understand the parser pattern before building adf_parser.py

The ADF parser must produce the **same output schema** as the SSIS parser. Both feed the same requirements_writer.py.

---

## What to Build

- `tool/stage1/parsers/adf_parser.py` — ADF pipeline JSON parser
- Update `tool/cli.py` — fill in ADF path in `stage1` subcommand (currently only handles .dtsx)

Do NOT change:
- ssis_parser.py (already done in Sprint 1)
- requirements_writer.py (already done in Sprint 1)
- pattern_classifier.py (already done in Sprint 1)

---

## Module: adf_parser.py

### Input
Path to an ADF pipeline ARM JSON file

### Output
Same dict schema as SsisParser.parse() output — same keys, same structure

### JSON Paths to Extract (from §3.2)

| JSON Path | Extraction Target |
|---|---|
| `properties.activities[*].name` + `type` | All activity names and types |
| `properties.activities[?type=="Copy"].typeProperties.source` | Copy source: store type, query/table, filter |
| `properties.activities[?type=="Copy"].typeProperties.sink` | Copy sink: store type, writeBehavior |
| `properties.activities[?type=="ExecuteDataFlow"].dataFlow` | Mapping Data Flow reference — parse the referenced Data Flow JSON file too |
| `dataflow.properties.transformations[*]` | Data Flow transform nodes: type, name, config |
| `properties.activities[?type=="SqlServerStoredProcedure"].typeProperties` | SP name and parameters |
| `properties.activities[?type=="ForEach"].activities[*]` | ForEach body — extract structure, flag [MANUAL] |
| `properties.activities[*].dependsOn[*]` | Dependency conditions (Succeeded/Failed/Skipped/Completed) |
| `properties.activities[?type=="WebActivity"].typeProperties.url` | Web Activity URL — flag as Azure Function dependency |
| `triggers[*]` | Trigger definitions: type, recurrence, schedule |
| `properties.parameters[*]` | Pipeline parameters: name, type, defaultValue |

### ADF Activity to Transform Type Mapping

```python
ADF_ACTIVITY_MAP = {
    "Copy":                       "source_read",  # also creates target_write
    "ExecuteDataFlow":            "EXPAND_DATAFLOW",  # recurse into Data Flow file
    "SqlServerStoredProcedure":   "sp_call",
    "ForEach":                    "FOREACH_MANUAL",  # structure captured, body flagged
    "IfCondition":                "IFCOND_MANUAL",   # structure captured, branches flagged
    "WebActivity":                "AZURE_FUNCTION_MANUAL",  # flag Azure Function dep
    "GetMetadata":                "source_read",     # metadata as source
    "Delete":                     "target_write",    # delete as write operation
    "SetVariable":                "VARIABLE_MANUAL", # variable assignment, flag
    "Until":                      "LOOP_MANUAL",     # loop, flag
    "Wait":                       "WAIT",            # wait activity
    "Filter":                     "filter",          # filter activity
    "Lookup":                     "join",            # lookup as join
}
```

### ADF-Specific Rules

1. **Copy Activity → two transforms:** creates both a source_read and a target_write etl-spec block
2. **Data Flow reference:** when activity type is `ExecuteDataFlow`, find the referenced Data Flow JSON file in source-packages/adf/ and parse it recursively
3. **writeBehavior mapping:**
   - `insert` → `write_mode: truncate_insert`
   - `upsert` → `write_mode: upsert`
   - `mergeFiles` → `write_mode: truncate_insert` + WARNING in conversion notes
4. **Linked Service resolution:** resolve dataset references to Linked Services to get connection details. If Linked Service file not found → use Linked Service name as connection_ref + flag [VERIFY CONNECTION]
5. **Azure-specific Linked Services:** ADLS Gen2, Synapse, Azure Blob → flag `[VERIFY S3 PATH: Azure-specific storage dependency]`
6. **Dependency conditions:** Succeeded → normal control flow; Failed → error path; both/Completed → branch logic, flag [MANUAL: DEPENDENCY CONDITION]
7. **Schedule trigger → EventBridge:** recurrence trigger maps to cron_expression in control_flow etl-spec

### ADF Mapping Data Flow Sub-Parser

When an activity is `ExecuteDataFlow`, parse the Data Flow JSON separately:

```python
def _parse_data_flow(self, dataflow_path: str) -> list[dict]:
    """
    Parse an ADF Mapping Data Flow JSON file.
    Returns list of transform dicts, one per transformation node.
    """
    with open(dataflow_path) as f:
        df = json.load(f)
    
    transforms = []
    for t in df.get("properties", {}).get("transformations", []):
        transform_type = self._map_dataflow_type(t.get("type"))
        transforms.append({
            "transform_id": t.get("name"),
            "transform_type": transform_type,
            # ... extract type-specific config
        })
    return transforms

def _map_dataflow_type(self, adf_type: str) -> str:
    return {
        "source":           "source_read",
        "sink":             "target_write",
        "filter":           "filter",
        "project":          "derive",
        "derived":          "derive",
        "join":             "join",
        "aggregate":        "aggregate",
        "sort":             "sort",
        "union":            "union",
        "conditionalSplit": "filter",
        "lookup":           "join",
        "select":           "derive",  # column rename/select
        "window":           "window",
    }.get(adf_type, "MANUAL")
```

---

## Update CLI (stage1 subcommand)

```python
@main.command()
@click.argument("source_file")
@click.option("--output", default="requirements-docs/")
def stage1(source_file, output):
    from pathlib import Path
    from tool.stage1.parsers.ssis_parser import SsisParser
    from tool.stage1.parsers.adf_parser import AdfParser
    # ...

    path = Path(source_file)
    if path.suffix == ".dtsx":
        parsed = SsisParser().parse(str(path))
    elif path.suffix == ".json":
        parsed = AdfParser().parse(str(path))
    else:
        click.echo(f"Unsupported file type: {path.suffix}")
        return
    # ... rest of stage1 unchanged from Sprint 1
```

---

## Fixtures

Create in `tests/fixtures/`:

**`sample_adf_pipeline.json`** — minimal but realistic ADF pipeline JSON with:
- One Copy Activity (SQL Server source → staging sink)
- One SqlServerStoredProcedure Activity
- One ExecuteDataFlow Activity (reference to sample_adf_dataflow.json)
- DependsOn linking them in sequence
- A Schedule Trigger

**`sample_adf_dataflow.json`** — minimal ADF Mapping Data Flow with:
- One source transformation
- One filter transformation
- One derived column transformation
- One aggregate transformation
- One sink transformation

---

## Tests

### tests/test_adf_parser.py

1. `test_parse_copy_activity_source` — Copy source → source_read etl-spec block with correct query_or_path
2. `test_parse_copy_activity_sink` — Copy sink → target_write etl-spec block with correct write_mode
3. `test_parse_sp_activity` — SqlServerStoredProcedure → sp_call with sp_name
4. `test_parse_schedule_trigger` — trigger → cron_expression in control_flow
5. `test_parse_dependency_chain` — dependsOn array → correct adjacency list
6. `test_azure_linked_service_flagged` — ADLS Gen2 Linked Service → [VERIFY S3 PATH] flag
7. `test_foreach_flagged_manual` — ForEach → [MANUAL] with structure captured
8. `test_dataflow_subparser` — ExecuteDataFlow → recurses into dataflow file, returns transform list
9. `test_adf_output_schema_matches_ssis` — AdfParser.parse() output has same top-level keys as SsisParser.parse()

---

## Acceptance Criteria — Sprint 2 Complete When ALL Pass

- [ ] `adf_parser.py` extracts all elements from the §3.2 JSON path table
- [ ] Copy Activity creates BOTH source_read AND target_write etl-spec blocks
- [ ] Data Flow activities recursively parse the referenced Data Flow JSON file
- [ ] Azure-specific Linked Services flagged `[VERIFY S3 PATH]`
- [ ] ForEach and IfCondition activities captured structurally, body flagged [MANUAL]
- [ ] Schedule trigger extracted as cron_expression in control_flow
- [ ] `AdfParser.parse()` output schema is identical to `SsisParser.parse()` output schema
- [ ] CLI `stage1 sample_adf_pipeline.json` runs end-to-end and writes REQUIREMENTS.md
- [ ] `pytest tests/ -v` → 100% pass including new test_adf_parser.py
- [ ] `ruff check tool/` → zero errors
- [ ] PR opened against main
