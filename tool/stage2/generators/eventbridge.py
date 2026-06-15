import json


class EventBridgeHelper:
    """Emit ETL completion events to EventBridge (used in Phase 3 generated code)."""

    @staticmethod
    def build_put_events_call(job_name: str, target_table: str, extra: dict = None) -> str:
        """Return Python code snippet that calls boto3 put_events for Phase 3 completion."""
        detail = {"job_name": job_name, "target_table": target_table}
        if extra:
            detail.update(extra)
        detail_json = json.dumps(detail)
        return (
            f"boto3.client('events').put_events(Entries=[{{\n"
            f"    'Source': 'etl.{job_name}',\n"
            f"    'DetailType': 'Phase3Complete',\n"
            f"    'Detail': '{detail_json}',\n"
            f"    'EventBusName': 'default',\n"
            f"}}])"
        )

    @staticmethod
    def build_terraform(job_name: str, cron_expression: str, state_machine_arn_ref: str = None) -> str:
        """Return Terraform HCL for EventBridge rule targeting a Step Functions state machine."""
        sfn_ref = state_machine_arn_ref or f"aws_sfn_state_machine.{job_name}.arn"
        return f"""\
resource "aws_cloudwatch_event_rule" "{job_name}_trigger" {{
  name                = "{job_name}_trigger"
  description         = "EventBridge trigger for {job_name}"
  schedule_expression = "{cron_expression}"
}}

resource "aws_cloudwatch_event_target" "{job_name}_sfn" {{
  rule      = aws_cloudwatch_event_rule.{job_name}_trigger.name
  target_id = "{job_name}_sfn"
  arn       = {sfn_ref}
  role_arn  = aws_iam_role.{job_name}_eventbridge.arn
}}

resource "aws_iam_role" "{job_name}_eventbridge" {{
  name = "{job_name}_eventbridge_role"
  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {{ Service = "events.amazonaws.com" }}
    }}]
  }})
}}

resource "aws_iam_role_policy" "{job_name}_eventbridge_policy" {{
  name = "{job_name}_eventbridge_policy"
  role = aws_iam_role.{job_name}_eventbridge.id
  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = [{sfn_ref}]
    }}]
  }})
}}
"""
