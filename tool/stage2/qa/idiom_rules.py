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
    blocks_output: bool


L4_RULES = [
    IdiomRule("L4-R01", "Loop over df.rdd.collect() or df.toLocalIterator()", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R02", ".collect() on large DataFrame", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R03", "psycopg2 call inside df.rdd.map() or df.foreach()", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R04", "udf() where expression_type != custom_logic", Severity.FLAG_MANUAL, False),
    IdiomRule("L4-R05", "AWS credential string (AKIA...)", Severity.FLAG_SECURITY, True),
    IdiomRule("L4-R06", "Hard-coded s3:// path literal", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R07", "DataFrame not cached when used >2x", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R08", "spark.read.jdbc() without schema= param", Severity.AUTO_CORRECT, False),
    IdiomRule("L4-R09", "conn.autocommit = True in Phase 3", Severity.FLAG_CORRECTNESS_RISK, False),
    IdiomRule("L4-R10", "SQL string concatenation f-string or +", Severity.FLAG_SECURITY, False),
]

RULES_BY_ID = {r.rule_id: r for r in L4_RULES}
