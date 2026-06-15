"""SSIS parser — Sprint 1 implementation."""

import re
import xml.etree.ElementTree as ET

NAMESPACES = {
    "DTS": "www.microsoft.com/SqlServer/Dts",
    "pipeline": "www.microsoft.com/SqlServer/Dts/Pipeline",
    "SQLTask": "www.microsoft.com/sqlserver/dts/tasks/sqltask",
}

# NOTE: XML namespace URIs used in ElementTree findall/find require {uri} format.
# DTS namespace in actual dtsx files: "www.microsoft.com/SqlServer/Dts" - note no "http://"
DTS_NS = "www.microsoft.com/SqlServer/Dts"
PIPELINE_NS = "www.microsoft.com/SqlServer/Dts/Pipeline"
SQLTASK_NS = "www.microsoft.com/sqlserver/dts/tasks/sqltask"


class SsisParser:
    def parse(self, dtsx_path: str) -> dict:
        tree = ET.parse(dtsx_path)
        root = tree.getroot()
        manual_items = []
        result = {
            "job_name": self._extract_job_name(root),
            "source_system": "SSIS",
            "source_file": str(dtsx_path),
            "parameters": self._extract_parameters(root),
            "data_sources": self._extract_data_sources(root, manual_items),
            "transformations": self._extract_transformations(root, manual_items),
            "control_flow": self._extract_control_flow(root),
            "error_handling": self._extract_error_handling(root),
            "dependencies": self._extract_dependencies(root),
        }
        result["manual_item_count"] = len(manual_items)
        result["manual_items"] = manual_items
        result["confidence_score"] = max(0, 100 - len(manual_items) * 10)
        return result

    def _dts(self, tag):
        return f"{{{DTS_NS}}}{tag}"

    def _pipeline(self, tag):
        return f"{{{PIPELINE_NS}}}{tag}"

    def _sqltask(self, tag):
        return f"{{{SQLTASK_NS}}}{tag}"

    def _extract_job_name(self, root) -> str:
        return root.get(self._dts("ObjectName"), "unknown_job")

    def _extract_parameters(self, root) -> list:
        params = []
        for var in root.iter(self._dts("Variable")):
            name = var.get(self._dts("ObjectName"), "")
            dtype = var.get(self._dts("DataType"), "")
            value_el = var.find(self._dts("VariableValue"))
            value = value_el.text if value_el is not None else ""
            params.append(
                {
                    "name": name,
                    "type": "variable",
                    "data_type": dtype,
                    "value": value,
                }
            )
        for param in root.iter(self._dts("PackageParameter")):
            name = param.get(self._dts("ObjectName"), "")
            dtype = param.get(self._dts("DataType"), "")
            default = param.get(self._dts("DefaultValue"), "")
            params.append(
                {
                    "name": name,
                    "type": "parameter",
                    "data_type": dtype,
                    "default_value": default,
                }
            )
        return params

    def _extract_data_sources(self, root, manual_items) -> list:
        sources = []
        # OleDb Sources from pipeline components
        for comp in root.iter(self._pipeline("component")):
            class_id = comp.get(self._pipeline("componentClassID"), "")
            if "OleDbSource" in class_id or "DTSAdapter.OleDbSource" in class_id:
                name = comp.get(self._pipeline("name"), "")
                conn_ref = ""
                query_or_path = ""
                for prop in comp.iter(self._pipeline("property")):
                    prop_name = prop.get(self._pipeline("name"), "")
                    if prop_name == "SqlCommand" and prop.text:
                        query_or_path = prop.text.strip()
                    elif prop_name == "OpenRowset" and prop.text and not query_or_path:
                        query_or_path = prop.text.strip()
                # Connection manager ref — only store the name, NOT the connection string
                for conn_mgr in comp.iter(self._pipeline("connection")):
                    conn_ref = conn_mgr.get(self._pipeline("description"), conn_mgr.get(self._pipeline("name"), ""))
                    break
                sources.append(
                    {
                        "source_id": name.lower().replace(" ", "_"),
                        "connection_ref": conn_ref,
                        "source_type": "query" if "SELECT" in query_or_path.upper() else "table",
                        "query_or_path": query_or_path,
                        "connection_type": "jdbc",
                    }
                )
        # Execute SQL Tasks that are SELECTs
        for exe in root.iter(self._dts("Executable")):
            exe_type = exe.get(self._dts("ExecutableType"), "")
            if "ExecuteSQLTask" in exe_type:
                obj_data = exe.find(self._dts("ObjectData"))
                if obj_data is not None:
                    sql_task = obj_data.find(self._sqltask("SqlTaskData"))
                    if sql_task is not None:
                        sql_stmt = sql_task.get(self._sqltask("SqlStatementSource"), "")
                        if sql_stmt and "SELECT" in sql_stmt.upper() and "INSERT" not in sql_stmt.upper():
                            name = exe.get(self._dts("ObjectName"), "sql_source")
                            sources.append(
                                {
                                    "source_id": name.lower().replace(" ", "_"),
                                    "connection_ref": sql_task.get(self._sqltask("Connection"), ""),
                                    "source_type": "query",
                                    "query_or_path": sql_stmt,
                                    "connection_type": "jdbc",
                                }
                            )
        return sources

    def _extract_transformations(self, root, manual_items) -> list:
        transforms = []
        # Pipeline components
        for comp in root.iter(self._pipeline("component")):
            class_id = comp.get(self._pipeline("componentClassID"), "")
            name = comp.get(self._pipeline("name"), "")
            tid = name.lower().replace(" ", "_")
            if "DerivedColumn" in class_id:
                expressions = []
                for output in comp.iter(self._pipeline("output")):
                    for col in output.iter(self._pipeline("outputColumn")):
                        col_name = col.get(self._pipeline("name"), "")
                        expressions.append({"output_column": col_name, "expression": ""})
                transforms.append(
                    {
                        "transform_id": tid,
                        "transform_type": "derive",
                        "name": name,
                        "expressions": expressions,
                    }
                )
            elif "Lookup" in class_id:
                no_match = "redirect"
                for prop in comp.iter(self._pipeline("property")):
                    if prop.get(self._pipeline("name"), "") == "NoMatchBehavior":
                        no_match = prop.text or "redirect"
                transforms.append(
                    {
                        "transform_id": tid,
                        "transform_type": "join",
                        "name": name,
                        "join_type": "left",
                        "no_match_behaviour": no_match,
                    }
                )
            elif "ConditionalSplit" in class_id:
                conditions = []
                for output in comp.iter(self._pipeline("output")):
                    cond_name = output.get(self._pipeline("name"), "")
                    for prop in output.iter(self._pipeline("property")):
                        if prop.get(self._pipeline("name"), "") == "Expression":
                            conditions.append({"name": cond_name, "expression": prop.text or ""})
                transforms.append(
                    {
                        "transform_id": tid,
                        "transform_type": "filter",
                        "name": name,
                        "conditions": conditions,
                    }
                )
            elif "ScriptComponent" in class_id or ("Script" in class_id and "Component" in class_id):
                flag = "[MANUAL: SCRIPT COMPONENT C#]"
                manual_items.append(flag)
                transforms.append(
                    {
                        "transform_id": tid,
                        "transform_type": "manual",
                        "name": name,
                        "flag": flag,
                    }
                )
            elif "OleDbDestination" in class_id or "DTSAdapter.OleDbDestination" in class_id:
                table_name = ""
                conn_ref = ""
                for prop in comp.iter(self._pipeline("property")):
                    if prop.get(self._pipeline("name"), "") == "OpenRowset":
                        table_name = prop.text or ""
                for conn_mgr in comp.iter(self._pipeline("connection")):
                    conn_ref = conn_mgr.get(self._pipeline("description"), "")
                    break
                transforms.append(
                    {
                        "transform_id": tid,
                        "transform_type": "target_write",
                        "name": name,
                        "target_table": table_name,
                        "connection_ref": conn_ref,
                        "write_mode": "truncate_insert",
                    }
                )
        # Execute SQL Tasks — SP calls and DML
        for exe in root.iter(self._dts("Executable")):
            exe_type = exe.get(self._dts("ExecutableType"), "")
            if "ExecuteSQLTask" in exe_type:
                obj_data = exe.find(self._dts("ObjectData"))
                if obj_data is not None:
                    sql_task = obj_data.find(self._sqltask("SqlTaskData"))
                    if sql_task is not None:
                        sql_stmt = sql_task.get(self._sqltask("SqlStatementSource"), "")
                        conn = sql_task.get(self._sqltask("Connection"), "")
                        name = exe.get(self._dts("ObjectName"), "sql_task")
                        tid = name.lower().replace(" ", "_")
                        if sql_stmt and "SELECT" not in sql_stmt.upper():
                            sp_name = ""
                            if re.search(r"\b(?:EXEC(?:UTE)?|CALL)\b", sql_stmt, re.IGNORECASE):
                                m = re.search(r"(?:EXEC(?:UTE)?|CALL)\s+([\w.]+)", sql_stmt, re.IGNORECASE)
                                if m:
                                    sp_name = m.group(1)
                            transforms.append(
                                {
                                    "transform_id": tid,
                                    "transform_type": "sp_call" if sp_name else "sql_task",
                                    "name": name,
                                    "sp_name": sp_name,
                                    "sql_statement": sql_stmt,
                                    "connection_ref": conn,
                                    "sp_rewrite_strategy": "keep_plpgsql",
                                    "sp_estimated_duration_minutes": 5,
                                }
                            )
            elif "ForEachEnumerator" in exe_type or "ForEach" in exe_type:
                name = exe.get(self._dts("ObjectName"), "foreach")
                flag = "[MANUAL: FOREACH ITERATION]"
                manual_items.append(flag)
                transforms.append(
                    {
                        "transform_id": name.lower().replace(" ", "_"),
                        "transform_type": "manual",
                        "name": name,
                        "flag": flag,
                    }
                )
        return transforms

    def _extract_control_flow(self, root) -> dict:
        adjacency = []
        for constraint in root.iter(self._dts("PrecedenceConstraint")):
            from_id = constraint.get(self._dts("From"), "")
            to_id = constraint.get(self._dts("To"), "")
            if from_id and to_id:
                adjacency.append({"from_task": from_id, "to_task": to_id})
        return {"adjacency_list": adjacency}

    def _extract_error_handling(self, root) -> list:
        handlers = []
        event_handlers_el = root.find(self._dts("EventHandlers"))
        if event_handlers_el is not None:
            for handler in event_handlers_el.iter(self._dts("EventHandler")):
                htype = handler.get(self._dts("EventName"), handler.get(self._dts("ObjectName"), ""))
                actions = []
                for child in handler:
                    child_name = child.get(self._dts("ObjectName"), "")
                    if child_name:
                        actions.append(child_name)
                handlers.append({"handler_type": htype, "actions": actions})
        return handlers

    def _extract_dependencies(self, root) -> list:
        deps = []
        for exe in root.iter(self._dts("Executable")):
            exe_type = exe.get(self._dts("ExecutableType"), "")
            if "ExecutePackageTask" in exe_type:
                name = exe.get(self._dts("ObjectName"), "")
                deps.append(
                    {
                        "name": name,
                        "type": "child_package",
                        "path": "[MANUAL: resolve child package path]",
                    }
                )
        return deps
