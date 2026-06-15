from dataclasses import dataclass, field
from tool.stage2.layers.l4_idiom import L4IdiomScanner


@dataclass
class QAResult:
    blocked: bool = False
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    findings: dict = field(default_factory=dict)


class QAPipeline:
    def __init__(self):
        self.scanner = L4IdiomScanner()

    def run(self, generated_artifacts: dict, spec_blocks: list, etl_spec_context: dict) -> QAResult:
        result = QAResult()

        # QA-1: L4 Idiom Scan — runs first, security violations block output
        for artifact_path, code in generated_artifacts.items():
            if not artifact_path.endswith(".py"):
                continue
            _, violations = self.scanner.scan(code)
            for v in violations:
                result.violations.append({"artifact": artifact_path, **v})
                if v.get("blocks_output"):
                    result.blocked = True

        if result.blocked:
            return result

        # QA-2: Spec Block Completeness
        missing = []
        required_fields = ["transform_type", "transform_id"]
        for block in spec_blocks:
            for field_name in required_fields:
                if field_name not in block:
                    missing.append(f"Block missing '{field_name}': {block}")
        if missing:
            result.findings["QA-2"] = missing

        # QA-3: L3 Expression Confidence
        l3_results = etl_spec_context.get("l3_results", [])
        qa3_findings = self._run_qa3_expression_confidence(l3_results)
        if qa3_findings:
            result.findings["QA-3"] = qa3_findings

        # QA-4: Transaction Pattern
        phase3_blocks = [b for b in spec_blocks if b.get("transform_type") == "target_write"]
        transaction_groups = etl_spec_context.get("transaction_groups", [])
        if phase3_blocks and not transaction_groups:
            result.findings["QA-4"] = "REQUIRES_REVIEW: No transaction_groups defined for Phase 3 writes"

        # QA-5: IaC Completeness
        iac_paths = [k for k in generated_artifacts if k.endswith(".tf") or k.endswith(".asl.json")]
        if not iac_paths:
            result.findings["QA-5"] = "WARNING: No IaC artifacts generated"

        # QA-6: Test Coverage
        generated_tests = etl_spec_context.get("generated_tests", {})
        qa6_findings = self._run_qa6_test_coverage(spec_blocks, generated_tests)
        if qa6_findings:
            result.findings["QA-6"] = qa6_findings

        return result

    def _run_qa6_test_coverage(self, spec_blocks: list, generated_tests: dict) -> list:
        findings = []
        all_test_content = " ".join(generated_tests.values())
        for block in spec_blocks:
            transform_id = block.get("transform_id")
            if not transform_id:
                continue
            test_key = f"test_{transform_id}_standard"
            if test_key not in all_test_content:
                findings.append({
                    "gate": "QA-6",
                    "severity": "WARNING",
                    "message": f"No test generated for transform {transform_id}",
                })
        return findings

    def _run_qa3_expression_confidence(self, l3_results: list) -> list:
        findings = []
        for result in l3_results:
            if result.get("manual_review_required") and result.get("confidence", 0) >= 70:
                findings.append({
                    "gate": "QA-3",
                    "severity": "WARNING",
                    "message": (
                        f"Expression marked manual_review_required despite confidence "
                        f"{result['confidence']}"
                    ),
                })
        return findings
