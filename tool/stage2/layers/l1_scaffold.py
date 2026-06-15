from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_DEFAULT_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


class L1Scaffold:
    TEMPLATES = [
        ("glue_job_scaffold.j2", "glue-jobs/{job_name}.py"),
        ("step_functions_sfn.j2", "step-functions/{job_name}.asl.json"),
        ("glue_workflow_tf.j2", "glue-workflows/{job_name}.tf"),
        ("eventbridge_tf.j2", "eventbridge/{job_name}.tf"),
        ("aurora_ddl.j2", "db-migrations/V001__{job_name}.sql"),
    ]

    def __init__(self, templates_dir: str | Path | None = None):
        if templates_dir is None:
            templates_dir = _DEFAULT_TEMPLATES_DIR
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            keep_trailing_newline=True,
        )

    def render_all(self, context: dict) -> dict:
        outputs = {}
        for template_file, output_pattern in self.TEMPLATES:
            template = self.env.get_template(template_file)
            output_path = output_pattern.format(**context)
            outputs[output_path] = template.render(**context)
        return outputs
