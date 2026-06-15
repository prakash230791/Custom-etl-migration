import json
import re
from pathlib import Path

AZURE_LINKED_SERVICE_TYPES = {
    "AzureDataLakeStoreLinkedService",
    "AzureDataLakeStorageLinkedService",
    "AzureBlobStorageLinkedService",
    "AzureBlobFSLinkedService",
    "AzureSynapseArtifactsLinkedService",
}

WRITE_BEHAVIOR_MAP = {
    "insert": "truncate_insert",
    "upsert": "upsert",
    "mergeFiles": "truncate_insert",  # + WARNING
}

ADF_ACTIVITY_MAP = {
    "Copy": "source_read",
    "ExecuteDataFlow": "EXPAND_DATAFLOW",
    "SqlServerStoredProcedure": "sp_call",
    "ForEach": "FOREACH_MANUAL",
    "IfCondition": "IFCOND_MANUAL",
    "WebActivity": "AZURE_FUNCTION_MANUAL",
    "GetMetadata": "source_read",
    "Delete": "target_write",
    "SetVariable": "VARIABLE_MANUAL",
    "Until": "LOOP_MANUAL",
    "Wait": "WAIT",
    "Filter": "filter",
    "Lookup": "join",
}

DATAFLOW_TYPE_MAP = {
    "source": "source_read",
    "sink": "target_write",
    "filter": "filter",
    "project": "derive",
    "derived": "derive",
    "join": "join",
    "aggregate": "aggregate",
    "sort": "sort",
    "union": "union",
    "conditionalSplit": "filter",
    "lookup": "join",
    "select": "derive",
    "window": "window",
}


class AdfParser:
    def parse(self, json_path: str) -> dict:
        path = Path(json_path)
        with open(path, encoding="utf-8") as f:
            pipeline = json.load(f)

        manual_items = []
        props = pipeline.get("properties", {})
        activities = props.get("activities", [])
        triggers = pipeline.get("triggers", [])
        parameters = props.get("parameters", {})

        job_name = pipeline.get("name", path.stem)
        data_sources = []
        transformations = []
        adjacency = []
        cron_expression = None
        dependencies = []

        # Build adjacency list from dependsOn
        for act in activities:
            act_name = act.get("name", "")
            for dep in act.get("dependsOn", []):
                dep_name = dep.get("activity", "")
                conditions = dep.get("dependencyConditions", ["Succeeded"])
                if any(c in ("Failed", "Completed", "Skipped") for c in conditions):
                    manual_items.append(
                        f"[MANUAL: DEPENDENCY CONDITION] {act_name} depends on {dep_name} with condition {conditions}"
                    )
                adjacency.append({"from_task": dep_name, "to_task": act_name})

        # Parse triggers
        for trigger in triggers:
            ttype = trigger.get("properties", {}).get("type", trigger.get("type", ""))
            if "Schedule" in ttype or "Tumbling" in ttype:
                recurrence = trigger.get("properties", {}).get("recurrence", {}) or trigger.get("recurrence", {})
                cron_expression = self._recurrence_to_cron(recurrence)

        # Parse activities
        for act in activities:
            act_type = act.get("type", "")
            act_name = act.get("name", "")
            act_id = act_name.lower().replace(" ", "_")
            type_props = act.get("typeProperties", {})

            if act_type == "Copy":
                src = type_props.get("source", {})
                sink = type_props.get("sink", {})

                # Source
                query = src.get("sqlReaderQuery") or src.get("query", "")
                table = src.get("tableOption", "") or ""
                conn_ref = self._resolve_linked_service(act, path.parent, manual_items)
                src_id = f"{act_id}_source"
                data_sources.append(
                    {
                        "source_id": src_id,
                        "connection_ref": conn_ref,
                        "source_type": "query" if query else "table",
                        "query_or_path": query or table,
                        "connection_type": "jdbc",
                    }
                )

                # Sink / target_write
                write_behavior = sink.get("writeBehavior", "insert")
                write_mode = WRITE_BEHAVIOR_MAP.get(write_behavior, "truncate_insert")
                if write_behavior == "mergeFiles":
                    manual_items.append(
                        f"[WARNING: mergeFiles writeBehavior on {act_name} mapped to truncate_insert — verify]"
                    )
                sink_table = sink.get("tableOption") or sink.get("table", "")
                sink_schema = sink.get("schema", "public")
                transformations.append(
                    {
                        "transform_id": f"{act_id}_sink",
                        "transform_type": "target_write",
                        "name": f"{act_name} Sink",
                        "target_schema": sink_schema,
                        "target_table": sink_table,
                        "write_mode": write_mode,
                    }
                )

            elif act_type == "SqlServerStoredProcedure":
                sp_name = type_props.get("storedProcedureName", "")
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "sp_call",
                        "name": act_name,
                        "sp_name": sp_name,
                        "sp_rewrite_strategy": "keep_plpgsql",
                        "sp_estimated_duration_minutes": 5,
                        "sql_statement": f"EXECUTE {sp_name}",
                    }
                )

            elif act_type == "ExecuteDataFlow":
                df_ref = type_props.get("dataFlow", {}) or {}
                df_name = df_ref.get("referenceName", "")
                # Try to find the dataflow JSON in same dir
                df_path = path.parent / f"{df_name}.json"
                if df_path.exists():
                    df_transforms = self._parse_data_flow(str(df_path), manual_items)
                    transformations.extend(df_transforms)
                else:
                    manual_items.append(f"[MANUAL: DATA FLOW FILE NOT FOUND] {df_name}.json — resolve manually")
                    transformations.append(
                        {
                            "transform_id": act_id,
                            "transform_type": "manual",
                            "name": act_name,
                            "flag": f"[MANUAL: DATA FLOW FILE NOT FOUND] {df_name}",
                        }
                    )

            elif act_type == "ForEach":
                flag = f"[MANUAL: FOREACH ITERATION] {act_name}"
                manual_items.append(flag)
                # Capture child activities structurally
                child_acts = type_props.get("activities", [])
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "manual",
                        "name": act_name,
                        "flag": flag,
                        "child_count": len(child_acts),
                    }
                )

            elif act_type == "IfCondition":
                flag = f"[MANUAL: IF CONDITION] {act_name}"
                manual_items.append(flag)
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "manual",
                        "name": act_name,
                        "flag": flag,
                    }
                )

            elif act_type == "WebActivity":
                url = type_props.get("url", "")
                flag = f"[MANUAL: AZURE FUNCTION DEPENDENCY] {act_name} — URL: {url}"
                manual_items.append(flag)
                dependencies.append({"name": act_name, "type": "azure_function", "url": url})
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "manual",
                        "name": act_name,
                        "flag": flag,
                    }
                )

            elif act_type in ("SetVariable", "Until", "Wait"):
                flag = f"[MANUAL: {ADF_ACTIVITY_MAP.get(act_type, act_type).upper()}] {act_name}"
                manual_items.append(flag)
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "manual",
                        "name": act_name,
                        "flag": flag,
                    }
                )

            elif act_type == "Filter":
                condition = type_props.get("condition", {}).get("value", "")
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "filter",
                        "name": act_name,
                        "condition": condition,
                    }
                )

            elif act_type == "Lookup":
                source = type_props.get("source", {})
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "join",
                        "name": act_name,
                        "join_type": "left",
                        "query_or_path": source.get("sqlReaderQuery", ""),
                    }
                )

            elif act_type == "GetMetadata":
                conn_ref = self._resolve_linked_service(act, path.parent, manual_items)
                data_sources.append(
                    {
                        "source_id": act_id,
                        "connection_ref": conn_ref,
                        "source_type": "metadata",
                        "query_or_path": "",
                        "connection_type": "api",
                    }
                )

            elif act_type == "Delete":
                transformations.append(
                    {
                        "transform_id": act_id,
                        "transform_type": "target_write",
                        "name": act_name,
                        "target_table": type_props.get("dataset", {}).get("referenceName", ""),
                        "write_mode": "truncate_insert",
                    }
                )

        # Parse parameters
        params = []
        for pname, pval in parameters.items():
            params.append(
                {
                    "name": pname,
                    "type": "parameter",
                    "data_type": pval.get("type", "string"),
                    "default_value": pval.get("defaultValue", ""),
                }
            )

        result = {
            "job_name": job_name,
            "source_system": "ADF",
            "source_file": str(json_path),
            "parameters": params,
            "data_sources": data_sources,
            "transformations": transformations,
            "control_flow": {"adjacency_list": adjacency, "cron_expression": cron_expression},
            "error_handling": [],
            "dependencies": dependencies,
            "manual_item_count": len(manual_items),
            "manual_items": manual_items,
            "confidence_score": max(0, 100 - len(manual_items) * 10),
        }
        return result

    def _resolve_linked_service(self, activity: dict, base_dir: Path, manual_items: list) -> str:
        """Extract connection ref from activity dataset reference. Flag Azure-specific services."""
        # Try to get linked service name from inputs/outputs
        for io in activity.get("inputs", []) + activity.get("outputs", []):
            ref_name = io.get("referenceName", "")
            if any(azure_type in str(io) for azure_type in AZURE_LINKED_SERVICE_TYPES):
                flag = f"[VERIFY S3 PATH: Azure-specific storage dependency] {ref_name}"
                if flag not in manual_items:
                    manual_items.append(flag)
            return ref_name
        # Fallback: try typeProperties.source.storeSettings or linkedServiceName
        type_props = activity.get("typeProperties", {})
        ls = (
            type_props.get("source", {}).get("storeSettings", {}).get("type", "")
            or type_props.get("linkedServiceName", {}).get("referenceName", "")
            or "unknown_connection"
        )
        return ls

    def _parse_data_flow(self, dataflow_path: str, manual_items: list) -> list:
        with open(dataflow_path, encoding="utf-8") as f:
            df = json.load(f)
        transforms = []
        for t in df.get("properties", {}).get("transformations", []):
            t_type = t.get("type", "")
            t_name = t.get("name", "")
            mapped = DATAFLOW_TYPE_MAP.get(t_type, "manual")
            if mapped == "manual":
                flag = f"[MANUAL: UNKNOWN DATAFLOW TRANSFORM TYPE] {t_type} — {t_name}"
                manual_items.append(flag)
            transforms.append(
                {
                    "transform_id": t_name.lower().replace(" ", "_"),
                    "transform_type": mapped,
                    "name": t_name,
                    "source": t.get("dataset", {}).get("referenceName", ""),
                }
            )
        return transforms

    def _recurrence_to_cron(self, recurrence: dict) -> str:
        """Convert ADF schedule recurrence to cron expression (best-effort)."""
        if not recurrence:
            return "cron(0 0 * * ? *)"
        freq = recurrence.get("frequency", "Day").lower()
        interval = recurrence.get("interval", 1)
        start_time = recurrence.get("startTime", "")
        hour = 0
        minute = 0
        if start_time:
            m = re.search(r"T(\d{2}):(\d{2})", start_time)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
        if freq == "minute":
            return f"cron(*/{interval} * * * ? *)"
        if freq == "hour":
            return f"cron(0 */{interval} * * ? *)"
        if freq == "day":
            return f"cron({minute} {hour} */{interval} * ? *)"
        if freq == "week":
            return f"cron({minute} {hour} ? * MON *)"
        if freq == "month":
            return f"cron({minute} {hour} 1 */{interval} ? *)"
        return f"cron({minute} {hour} * * ? *)"
