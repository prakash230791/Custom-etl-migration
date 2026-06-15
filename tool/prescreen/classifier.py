import xml.etree.ElementTree as ET
from pathlib import Path


_INELIGIBLE_CLASS_IDS = {
    "DTSTransform.ScriptComponent",
    "Microsoft.SqlServer.Dts.Tasks.ScriptTask.ScriptTask",
}

_INELIGIBLE_KEYWORDS = [
    "Microsoft.MSDTC",
    "Microsoft.SqlServer.Dts.Tasks.TransferDatabaseTask",
]


def classify_file(source_file: str) -> dict:
    """Return a pre-screen classification row for one source file."""
    path = Path(source_file)
    row = {
        "source_file": str(source_file),
        "object_name": path.stem,
        "source_type": _detect_source_type(path),
        "eligible": "TRUE",
        "blocking_reason": "",
        "manual_item_count": 0,
        "estimated_confidence": 80,
        "recommended_tool": "CUSTOM_TOOL",
        "estimated_iac_outputs": "",
    }

    if path.suffix == ".dtsx":
        _classify_dtsx(path, row)
    elif path.suffix == ".json":
        _classify_adf_json(path, row)
    else:
        row["eligible"] = "FALSE"
        row["blocking_reason"] = f"UNSUPPORTED_FILE_TYPE:{path.suffix}"
        row["recommended_tool"] = "GHCP_DEVELOPER"

    return row


def _detect_source_type(path: Path) -> str:
    if path.suffix == ".dtsx":
        return "SSIS"
    if path.suffix == ".json":
        return "ADF_PIPELINE"
    return "UNKNOWN"


def _classify_dtsx(path: Path, row: dict) -> None:
    DTS_NS = "www.microsoft.com/SqlServer/Dts"
    PIPELINE_NS = "www.microsoft.com/SqlServer/Dts/Pipeline"

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        row["object_name"] = root.get(f"{{{DTS_NS}}}ObjectName", path.stem)
    except ET.ParseError as exc:
        row["eligible"] = "FALSE"
        row["blocking_reason"] = f"PARSE_ERROR:{exc}"
        row["recommended_tool"] = "GHCP_DEVELOPER"
        return

    manual_count = 0
    blocking = []

    for comp in root.iter(f"{{{PIPELINE_NS}}}component"):
        class_id = comp.get(f"{{{PIPELINE_NS}}}componentClassID", "")
        if any(bad in class_id for bad in _INELIGIBLE_CLASS_IDS):
            manual_count += 1
        if "Script" in class_id:
            manual_count += 1

    for exe in root.iter(f"{{{DTS_NS}}}Executable"):
        exe_type = exe.get(f"{{{DTS_NS}}}ExecutableType", "")
        if any(kw in exe_type for kw in _INELIGIBLE_KEYWORDS):
            blocking.append(f"UNSUPPORTED_TASK:{exe_type}")
        if "ForEach" in exe_type:
            manual_count += 1

    if blocking:
        row["eligible"] = "FALSE"
        row["blocking_reason"] = ";".join(blocking)
        row["recommended_tool"] = "GHCP_DEVELOPER"
    else:
        row["eligible"] = "TRUE"
        row["estimated_confidence"] = max(20, 100 - manual_count * 10)

    row["manual_item_count"] = manual_count
    row["estimated_iac_outputs"] = "glue_job:1,step_functions:1,eventbridge:1"


def _classify_adf_json(path: Path, row: dict) -> None:
    import json

    try:
        with open(path, encoding="utf-8") as f:
            pipeline = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        row["eligible"] = "FALSE"
        row["blocking_reason"] = f"PARSE_ERROR:{exc}"
        row["recommended_tool"] = "GHCP_DEVELOPER"
        return

    manual_count = 0
    blocking = []
    activities = pipeline.get("properties", {}).get("activities", [])

    _MANUAL_TYPES = {"ForEach", "IfCondition", "WebActivity", "SetVariable", "Until"}
    _INELIGIBLE_TYPES: set = set()

    for act in activities:
        act_type = act.get("type", "")
        if act_type in _MANUAL_TYPES:
            manual_count += 1
        if act_type in _INELIGIBLE_TYPES:
            blocking.append(f"UNSUPPORTED_ACTIVITY:{act_type}")

    if blocking:
        row["eligible"] = "FALSE"
        row["blocking_reason"] = ";".join(blocking)
        row["recommended_tool"] = "GHCP_DEVELOPER"

    row["manual_item_count"] = manual_count
    row["estimated_confidence"] = max(20, 100 - manual_count * 10)
    row["estimated_iac_outputs"] = f"glue_job:1,lambda:{max(0, len(activities) - 2)},step_functions:1"
