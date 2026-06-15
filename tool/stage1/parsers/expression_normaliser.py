"""Expression normaliser — Sprint 1 implementation."""

import re
from dataclasses import dataclass


@dataclass
class NormalisedExpression:
    natural_language: str
    pyspark_hint: str
    requires_manual: bool
    original: str


class ExpressionNormaliser:
    def normalise(self, expression: str) -> NormalisedExpression:
        expr = expression.strip()
        result = self._try_patterns(expr)
        if result:
            return result
        # Check nesting depth
        depth = self._nesting_depth(expr)
        if depth > 3:
            return NormalisedExpression(
                natural_language=f"[MANUAL: COMPLEX EXPRESSION — original: {expr}]",
                pyspark_hint="# Route to L3 LLM in Stage 2",
                requires_manual=True,
                original=expr,
            )
        return NormalisedExpression(
            natural_language=f"Expression: {expr}",
            pyspark_hint=f"# TODO: translate: {expr}",
            requires_manual=False,
            original=expr,
        )

    def _nesting_depth(self, expr: str) -> int:
        depth = max_depth = 0
        for ch in expr:
            if ch == "(":
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == ")":
                depth -= 1
        return max_depth

    def _try_patterns(self, expr: str):
        # ISNULL([col])
        m = re.match(r"^ISNULL\(\[(\w+)\]\)$", expr, re.IGNORECASE)
        if m:
            col = m.group(1)
            return NormalisedExpression(
                natural_language=f"Is the value of {col} null?",
                pyspark_hint=f'coalesce(col("{col}"), default) or col("{col}").isNull()',
                requires_manual=False,
                original=expr,
            )

        # (DT_WSTR, N)[col]
        m = re.match(r"^\(DT_WSTR,\s*(\d+)\)\[(\w+)\]$", expr, re.IGNORECASE)
        if m:
            length, col = m.group(1), m.group(2)
            return NormalisedExpression(
                natural_language=f"Cast {col} to string with max length {length}",
                pyspark_hint=f'col("{col}").cast(StringType()).substr(0, {length})',
                requires_manual=False,
                original=expr,
            )

        # DATEPART("year", [col])
        m = re.match(r'^DATEPART\("(\w+)",\s*\[(\w+)\]\)$', expr, re.IGNORECASE)
        if m:
            part, col = m.group(1), m.group(2)
            return NormalisedExpression(
                natural_language=f"Extract the {part} from {col}",
                pyspark_hint=f'{part}(col("{col}"))',
                requires_manual=False,
                original=expr,
            )

        # GETDATE()
        if re.match(r"^GETDATE\(\)$", expr, re.IGNORECASE):
            return NormalisedExpression(
                natural_language="Current timestamp at execution time",
                pyspark_hint="current_timestamp()",
                requires_manual=False,
                original=expr,
            )

        # TRIM([col])
        m = re.match(r"^TRIM\(\[(\w+)\]\)$", expr, re.IGNORECASE)
        if m:
            col = m.group(1)
            return NormalisedExpression(
                natural_language=f"Remove leading and trailing whitespace from {col}",
                pyspark_hint=f'trim(col("{col}"))',
                requires_manual=False,
                original=expr,
            )

        # REPLACE([col], "a", "b")
        m = re.match(r'^REPLACE\(\[(\w+)\],\s*"([^"]*)",\s*"([^"]*)"\)$', expr, re.IGNORECASE)
        if m:
            col, old, new = m.group(1), m.group(2), m.group(3)
            return NormalisedExpression(
                natural_language=f'In {col}, replace all occurrences of "{old}" with "{new}"',
                pyspark_hint=f'regexp_replace(col("{col}"), "{old}", "{new}")',
                requires_manual=False,
                original=expr,
            )

        # LEFT([col], N)
        m = re.match(r"^LEFT\(\[(\w+)\],\s*(\d+)\)$", expr, re.IGNORECASE)
        if m:
            col, length = m.group(1), m.group(2)
            return NormalisedExpression(
                natural_language=f"First {length} characters of {col}",
                pyspark_hint=f'col("{col}").substr(1, {length})',
                requires_manual=False,
                original=expr,
            )

        # [col1] + [col2]
        m = re.match(r"^\[(\w+)\]\s*\+\s*\[(\w+)\]$", expr)
        if m:
            col1, col2 = m.group(1), m.group(2)
            return NormalisedExpression(
                natural_language=f"Concatenate {col1} and {col2}",
                pyspark_hint=f'concat(col("{col1}"), col("{col2}"))',
                requires_manual=False,
                original=expr,
            )

        # iif([cond], [val1], [val2])
        m = re.match(r"^iif\((.+),\s*(.+),\s*(.+)\)$", expr, re.IGNORECASE)
        if m:
            cond, val1, val2 = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            return NormalisedExpression(
                natural_language=f"If {cond} then {val1} else {val2}",
                pyspark_hint=f"when({cond}, {val1}).otherwise({val2})",
                requires_manual=False,
                original=expr,
            )

        return None
