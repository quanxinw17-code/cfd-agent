import json
from pathlib import Path

from cfd_agent.tools.case_manager_tool import create_case, list_cases, update_case_meta


def test_list_cases_reads_outputs_and_pipeline_status(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    case_dir = outputs / "sphere_001"
    case_dir.mkdir(parents=True)
    (case_dir / "pipeline_state.json").write_text(
        json.dumps({"status": "success", "stage": "completed", "errors": [], "stage_outputs": {"report": {"success": True}}}),
        encoding="utf-8",
    )
    (case_dir / "report").mkdir()
    (case_dir / "report" / "report.md").write_text("report", encoding="utf-8")

    cases = list_cases(tmp_path)

    assert cases["ok"] is True
    assert cases["cases"][0]["name"] == "sphere_001"
    assert cases["cases"][0]["status"] == "success"
    assert cases["cases"][0]["stage"] == "completed"
    assert cases["cases"][0]["has_report"] is True
    assert cases["cases"][0]["output"] == str(case_dir.resolve())


def test_create_case_writes_meta_and_unique_output_path(tmp_path: Path) -> None:
    result = create_case(tmp_path, {"name": "Sphere 001", "description": "simple sphere", "tags": "sphere, validation"})

    output = Path(result["case"]["output"])
    meta = json.loads((output / "case_meta.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert output.name == "sphere_001"
    assert meta["name"] == "Sphere 001"
    assert meta["description"] == "simple sphere"
    assert meta["tags"] == ["sphere", "validation"]

    second = create_case(tmp_path, {"name": "Sphere 001"})
    assert Path(second["case"]["output"]).name == "sphere_001_002"


def test_update_case_meta_merges_existing_metadata(tmp_path: Path) -> None:
    output = tmp_path / "outputs" / "case_a"
    output.mkdir(parents=True)
    (output / "case_meta.json").write_text(json.dumps({"name": "Case A", "tags": ["old"], "created_at": "keep"}), encoding="utf-8")

    result = update_case_meta(output, {"description": "updated", "tags": ["new"]})

    assert result["ok"] is True
    assert result["case"]["name"] == "Case A"
    assert result["case"]["description"] == "updated"
    assert result["case"]["tags"] == ["new"]
    assert result["case"]["created_at"] == "keep"
