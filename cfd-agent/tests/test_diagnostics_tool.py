import json
from pathlib import Path

from cfd_agent.tools.diagnostics_tool import diagnose_output


def test_diagnose_output_reports_missing_case_data_pair(tmp_path: Path) -> None:
    output = tmp_path / "case"
    fluent = output / "fluent"
    fluent.mkdir(parents=True)
    (fluent / "case.cas.h5").write_text("case", encoding="utf-8")
    (output / "pipeline_state.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stage": "failed",
                "errors": ["File case.dat.h5 not found"],
                "stage_outputs": {"solver": {"success": False, "error": "File case.dat.h5 not found"}},
            }
        ),
        encoding="utf-8",
    )

    report = diagnose_output(output)

    assert report["ok"] is False
    assert report["failed_stage"] == "solver"
    assert any(issue["code"] == "missing_fluent_case_data_pair" for issue in report["issues"])
    assert (output / "diagnostics" / "diagnostic_report.json").exists()
    assert (output / "diagnostics" / "diagnostic_report.md").exists()


def test_diagnose_output_detects_fluent_meshing_quality_and_boundary_errors(tmp_path: Path) -> None:
    output = tmp_path / "case"
    meshing = output / "meshing"
    meshing.mkdir(parents=True)
    (meshing / "mesh_quality_report.json").write_text(
        json.dumps(
            {
                "quality_ok": False,
                "max_skewness": 0.97,
                "min_orthogonal_quality": 0.04,
                "boundary_zone_names": ["velocity_inlet", "pressure_outlet", "object_wall"],
                "missing_boundary_zones": ["farfield"],
            }
        ),
        encoding="utf-8",
    )
    (meshing / "fluent_meshing.log").write_text("Maximum skewness of : 0.97\nMinimum Orthogonal Quality = 0.04", encoding="utf-8")
    (output / "pipeline_state.json").write_text(
        json.dumps({"status": "failed", "errors": ["mesh validation failed"], "stage_outputs": {"meshing": {"success": False}}}),
        encoding="utf-8",
    )

    report = diagnose_output(output)
    codes = {issue["code"] for issue in report["issues"]}

    assert "mesh_quality_failed" in codes
    assert "missing_boundary_zone" in codes
    assert report["metrics"]["max_skewness"] == 0.97
    assert report["metrics"]["min_orthogonal_quality"] == 0.04


def test_diagnose_output_includes_deployment_smoke_failures(tmp_path: Path) -> None:
    root = tmp_path
    output = root / "outputs" / "sphere_001"
    output.mkdir(parents=True)
    deployment = root / "outputs" / "deployment_check"
    deployment.mkdir(parents=True)
    (deployment / "software_smoke_check.json").write_text(
        json.dumps(
            {
                "ok": False,
                "checks": {
                    "spaceclaim": {"ok": False, "message": "SpaceClaim executable not found: Z:/missing/SpaceClaim.exe"},
                    "fluent_meshing": {"ok": False, "message": "Fluent executable not found: Z:/missing/fluent.exe"},
                },
            }
        ),
        encoding="utf-8",
    )

    report = diagnose_output(output, root=root)

    codes = {issue["code"] for issue in report["issues"]}
    assert "software_smoke_failed" in codes
    assert any("SpaceClaim executable not found" in issue["evidence"] for issue in report["issues"])
