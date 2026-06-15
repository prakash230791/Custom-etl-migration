import yaml
from pathlib import Path


class SpecParser:
    def parse(self, requirements_doc: str | Path) -> dict:
        path = Path(requirements_doc)
        content = path.read_text(encoding="utf-8") if path.exists() else str(requirements_doc)
        return self._parse_yaml_content(content)

    def parse_yaml(self, yaml_content: str) -> dict:
        return self._parse_yaml_content(yaml_content)

    def _parse_yaml_content(self, content: str) -> dict:
        if content.strip().startswith("job_name:") or content.strip().startswith("---"):
            return yaml.safe_load(content) or {}
        blocks = []
        in_block = False
        current = []
        for line in content.splitlines():
            if line.strip() == "```yaml" or line.strip() == "``` yaml":
                in_block = True
                current = []
            elif line.strip() == "```" and in_block:
                in_block = False
                text = "\n".join(current)
                try:
                    parsed = yaml.safe_load(text)
                    if isinstance(parsed, dict):
                        blocks.append(parsed)
                except yaml.YAMLError:
                    pass
            elif in_block:
                current.append(line)
        if not blocks:
            try:
                return yaml.safe_load(content) or {}
            except yaml.YAMLError:
                return {}
        merged = {}
        for block in blocks:
            merged.update(block)
        return merged
