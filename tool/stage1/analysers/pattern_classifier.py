"""Pattern classifier — Sprint 1 implementation."""


class PatternClassifier:
    def classify(self, parsed: dict) -> dict:
        transforms = parsed.get("transformations", [])
        control_flow = parsed.get("control_flow", {})

        phase1_detected = self._detect_phase1(transforms)
        phase2_detected = self._detect_phase2(transforms)
        phase3_detected = self._detect_phase3(transforms)

        pattern = (
            "THREE_PHASE_STATIC_LOAD" if (phase1_detected and phase2_detected and phase3_detected) else "GENERAL_ETL"
        )

        phase1_tasks = [t["transform_id"] for t in transforms if self._is_phase1_task(t)]
        phase2_tasks = [t["transform_id"] for t in transforms if self._is_phase2_task(t)]
        phase3_tasks = [t["transform_id"] for t in transforms if self._is_phase3_task(t)]

        sp_tasks = [t for t in transforms if t.get("transform_type") == "sp_call"]
        sp_dag = self._build_sp_dag(sp_tasks, control_flow.get("adjacency_list", []))
        parallel_groups = self._find_parallel_groups(sp_dag)

        return {
            "pattern": pattern,
            "phase_boundaries": {
                "phase1_tasks": phase1_tasks,
                "phase2_tasks": phase2_tasks,
                "phase3_tasks": phase3_tasks,
            },
            "sp_dependency_graph": sp_dag,
            "parallel_groups": parallel_groups,
        }

    def _is_phase1_task(self, t: dict) -> bool:
        table = t.get("target_table", "") or t.get("query_or_path", "")
        return (
            t.get("transform_type") == "source_read"
            or ("staging" in table.lower() or "tmp_" in table.lower())
            or "truncate" in t.get("sql_statement", "").lower()
        )

    def _is_phase2_task(self, t: dict) -> bool:
        return t.get("transform_type") in (
            "sp_call",
            "join",
            "filter",
            "aggregate",
            "derive",
            "window",
        )

    def _is_phase3_task(self, t: dict) -> bool:
        sql = t.get("sql_statement", "")
        name = t.get("name", "")
        return (
            t.get("transform_type") == "target_write"
            or ("transfer" in name.lower() or "load" in name.lower())
            or ("INSERT" in sql.upper() and "staging" not in sql.lower() and "FROM staging" in sql.upper())
        )

    def _detect_phase1(self, transforms) -> bool:
        for t in transforms:
            sql = t.get("sql_statement", "").upper()
            table = t.get("target_table", "").lower()
            if "TRUNCATE" in sql:
                return True
            if "staging_" in table or "tmp_" in table:
                return True
            if t.get("transform_type") == "source_read":
                return True
        return False

    def _detect_phase2(self, transforms) -> bool:
        return any(t.get("transform_type") in ("sp_call", "sql_task") for t in transforms)

    def _detect_phase3(self, transforms) -> bool:
        for t in transforms:
            sql = t.get("sql_statement", "").upper()
            name = t.get("name", "").lower()
            if t.get("transform_type") == "target_write":
                table = t.get("target_table", "").lower()
                if "staging" not in table and "tmp_" not in table:
                    return True
            if "transfer" in name or "load" in name:
                return True
            if "INSERT INTO" in sql and "FROM STAGING" in sql:
                return True
        return False

    def _build_sp_dag(self, sp_tasks: list, adjacency: list) -> dict:
        sp_ids = {t["transform_id"] for t in sp_tasks}
        dag = {sp_id: {"depends_on": []} for sp_id in sp_ids}
        for edge in adjacency:
            from_t = edge.get("from_task", "").lower().replace(" ", "_")
            to_t = edge.get("to_task", "").lower().replace(" ", "_")
            if from_t in dag and to_t in dag:
                if from_t not in dag[to_t]["depends_on"]:
                    dag[to_t]["depends_on"].append(from_t)
        return dag

    def _find_parallel_groups(self, sp_dag: dict) -> list:
        depends_map: dict = {}
        for sp_id, info in sp_dag.items():
            key = tuple(sorted(info["depends_on"]))
            depends_map.setdefault(key, []).append(sp_id)
        return [group for group in depends_map.values() if len(group) > 1]
