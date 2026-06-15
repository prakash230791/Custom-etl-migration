import ast
import re

from tool.stage2.qa.idiom_rules import RULES_BY_ID


def _make_violation(rule_id: str, line_no: int) -> dict:
    rule = RULES_BY_ID[rule_id]
    return {
        "rule_id": rule_id,
        "description": rule.description,
        "severity": rule.severity.value,
        "line_no": line_no,
        "blocks_output": rule.blocks_output,
    }


class L4IdiomScanner:
    def scan(self, python_code: str) -> tuple[str, list]:
        violations = []
        try:
            tree = ast.parse(python_code)
        except SyntaxError:
            return python_code, violations

        violations.extend(self._check_r01_collect_loop(tree))
        violations.extend(self._check_r02_collect_call(tree, python_code))
        violations.extend(self._check_r03_db_in_map(tree, python_code))
        violations.extend(self._check_r04_udf_call(tree))
        violations.extend(self._check_r05_aws_credential(tree, python_code))
        corrected_code, r06_viols = self._check_r06_hardcoded_s3(python_code)
        violations.extend(r06_viols)
        corrected_code, r07_viols = self._check_r07_uncached_df(corrected_code)
        violations.extend(r07_viols)
        corrected_code, r08_viols = self._check_r08_jdbc_no_schema(corrected_code)
        violations.extend(r08_viols)
        violations.extend(self._check_r09_autocommit_true(tree))
        violations.extend(self._check_r10_sql_concat(tree))

        return corrected_code, violations

    def _check_r01_collect_loop(self, tree: ast.AST) -> list:
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                iter_node = node.iter
                if isinstance(iter_node, ast.Call):
                    func = iter_node.func
                    if isinstance(func, ast.Attribute):
                        if func.attr in ("collect", "toLocalIterator"):
                            violations.append(_make_violation("L4-R01", getattr(node, "lineno", 0)))
        return violations

    def _check_r02_collect_call(self, tree: ast.AST, code: str) -> list:
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "collect":
                    line_no = getattr(node, "lineno", 0)
                    violations.append(_make_violation("L4-R02", line_no))
        return violations

    def _check_r03_db_in_map(self, tree: ast.AST, code: str) -> list:
        violations = []

        # AST-based: check for map/foreach/flatMap calls containing db operations in lambda body
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                is_map = isinstance(func, ast.Attribute) and func.attr in ("map", "foreach", "flatMap")
                if is_map and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Lambda):
                        for subnode in ast.walk(arg.body):
                            if isinstance(subnode, ast.Attribute) and subnode.attr in (
                                "cursor", "connect", "execute", "callproc"
                            ):
                                violations.append(_make_violation("L4-R03", getattr(node, "lineno", 0)))
                                break

        # Regex fallback: check for map/foreach containing db keywords on same or adjacent lines
        map_pattern = re.compile(r'\.(map|foreach|flatMap)\s*\(')
        db_pattern = re.compile(r'\.(cursor|execute|callproc|connect)\(')
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if map_pattern.search(line):
                # Check current line and next few lines for db operations
                window = "\n".join(lines[i : i + 5])
                if db_pattern.search(window):
                    # Check if this line was already caught by AST
                    already = any(v["rule_id"] == "L4-R03" and v["line_no"] == i + 1 for v in violations)
                    if not already:
                        violations.append(_make_violation("L4-R03", i + 1))

        return violations

    def _check_r04_udf_call(self, tree: ast.AST) -> list:
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name == "udf":
                    violations.append(_make_violation("L4-R04", getattr(node, "lineno", 0)))
        return violations

    def _check_r05_aws_credential(self, tree: ast.AST, code: str) -> list:
        violations = []
        pattern = re.compile(r"AKIA[0-9A-Z]{16}")
        for i, line in enumerate(code.splitlines(), 1):
            if pattern.search(line):
                violations.append(_make_violation("L4-R05", i))
        return violations

    def _check_r06_hardcoded_s3(self, code: str) -> tuple[str, list]:
        violations = []
        pattern = re.compile(r'(["\'])s3://[^\'"]+\1')
        for i, line in enumerate(code.splitlines(), 1):
            if pattern.search(line):
                violations.append(_make_violation("L4-R06", i))
        corrected = pattern.sub('"${s3_path}"', code)
        return corrected, violations

    def _check_r07_uncached_df(self, code: str) -> tuple[str, list]:
        violations = []
        df_counts: dict = {}
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            matches = re.findall(r"\b(df_\w+)\b", line)
            for name in matches:
                if name not in df_counts:
                    df_counts[name] = []
                df_counts[name].append(i)
        corrected_lines = list(lines)
        offset = 0
        for name, occurrences in df_counts.items():
            if len(occurrences) > 2 and f"{name}.cache()" not in code:
                first_line = occurrences[0]
                violations.append(_make_violation("L4-R07", first_line))
                insert_idx = first_line + offset
                if insert_idx <= len(corrected_lines):
                    corrected_lines.insert(insert_idx, f"{name} = {name}.cache()")
                    offset += 1
        return "\n".join(corrected_lines), violations

    def _check_r08_jdbc_no_schema(self, code: str) -> tuple[str, list]:
        violations = []
        pattern = re.compile(r"spark\.read\.jdbc\(([^)]*)\)")
        lines = code.splitlines()
        corrected_lines = []
        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m and "schema=" not in m.group(1):
                violations.append(_make_violation("L4-R08", i))
                line = pattern.sub(
                    lambda mo: mo.group(0).rstrip(")") + ", schema=StructType([]))",
                    line,
                )
            corrected_lines.append(line)
        return "\n".join(corrected_lines), violations

    def _check_r09_autocommit_true(self, tree: ast.AST) -> list:
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "autocommit":
                        if isinstance(node.value, ast.Constant) and node.value.value is True:
                            violations.append(_make_violation("L4-R09", getattr(node, "lineno", 0)))
        return violations

    def _check_r10_sql_concat(self, tree: ast.AST) -> list:
        violations = []
        sql_keywords = {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "CALL"}
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                violations.append(_make_violation("L4-R10", getattr(node, "lineno", 0)))
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        if any(kw in sub.value.upper() for kw in sql_keywords):
                            violations.append(_make_violation("L4-R10", getattr(node, "lineno", 0)))
                            break
        return violations
