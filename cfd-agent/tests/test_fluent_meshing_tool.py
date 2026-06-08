import json
from pathlib import Path

from cfd_agent.core.models import GeometryConfig, MotionConfig, SimulationTask
from cfd_agent.tools.fluent_meshing_tool import (
    _effective_mesh_settings,
    _mesh_failure_reasons,
    _quality_report,
    generate_mesh_with_fluent_meshing,
)


def test_quality_report_accepts_valid_fluent_meshing_output() -> None:
    task = SimulationTask(
        task_id="mesh_quality",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )
    runner = {
        "boundary_zone_names": ["velocity_inlet", "pressure_outlet", "farfield", "object_wall"],
        "boundary_layer_generated": True,
        "tasks": {
            "surface_mesh": {"State": "Up-to-date"},
            "volume_mesh": {"State": "Up-to-date"},
        },
    }
    log = """
    Surface Meshing complete, with a maximum skewness of: 0.38
    19188 cells were created
    Minimum Orthogonal Quality = 6.85930e-01
    Maximum Cell Squish = 3.14070e-01
    """

    report = _quality_report(task, runner, log)

    assert report["passed"] is True
    assert report["cell_count"] == 19188
    assert report["min_orthogonal_quality"] == 0.68593


def test_quality_report_rejects_missing_boundary_zone() -> None:
    task = SimulationTask(
        task_id="mesh_quality",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )
    runner = {"boundary_zone_names": ["object_wall"], "boundary_layer_generated": True, "tasks": {}}
    report = _quality_report(task, runner, "maximum skewness of: 0.2\n10 cells were created\nMinimum Orthogonal Quality = 0.9")

    assert report["passed"] is False
    assert report["missing_boundary_zones"] == ["farfield", "pressure_outlet", "velocity_inlet"]


def test_effective_mesh_settings_prefers_imitation_values() -> None:
    task = SimulationTask(
        task_id="mesh_settings",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )

    settings = _effective_mesh_settings(task, {"effective_mesh_settings": {"global_size": 0.004, "layers": 8}})

    assert settings["global_size"] == 0.004
    assert settings["layers"] == 8
    assert settings["growth_rate"] == task.mesh.growth_rate


def test_quality_report_normalizes_boundary_aliases_and_records_failed_tasks() -> None:
    task = SimulationTask(
        task_id="mesh_quality_aliases",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )
    runner = {
        "boundary_zone_names": ["inlet", "outlet", "fluid_farfield", "wall"],
        "boundary_layer_generated": True,
        "mesh_exists": True,
        "case_exists": True,
        "tasks": {
            "surface_mesh": {"State": "Up-to-date"},
            "volume_mesh": {"State": "Failed", "Errors": ["volume failed"]},
        },
    }
    log = "maximum skewness of: 0.2\n10 cells were created\nMinimum Orthogonal Quality = 0.9"

    report = _quality_report(task, runner, log)

    assert report["boundary_zone_names"] == ["velocity_inlet", "pressure_outlet", "farfield", "object_wall"]
    assert report["raw_boundary_zone_names"] == ["inlet", "outlet", "fluid_farfield", "wall"]
    assert report["missing_boundary_zones"] == []
    assert report["failed_workflow_tasks"] == {"volume_mesh": {"State": "Failed", "Errors": ["volume failed"]}}
    assert report["output_files_ok"] is True
    assert report["passed"] is False


def test_quality_report_rejects_missing_mesh_or_case_outputs() -> None:
    task = SimulationTask(
        task_id="mesh_quality_outputs",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )
    runner = {
        "boundary_zone_names": ["velocity_inlet", "pressure_outlet", "farfield", "object_wall"],
        "boundary_layer_generated": True,
        "mesh_exists": True,
        "case_exists": False,
        "tasks": {"surface_mesh": {"State": "Up-to-date"}, "volume_mesh": {"State": "Up-to-date"}},
    }

    report = _quality_report(task, runner, "maximum skewness of: 0.2\n10 cells were created\nMinimum Orthogonal Quality = 0.9")

    assert report["output_files_ok"] is False
    assert report["passed"] is False


def test_mesh_failure_reasons_are_specific() -> None:
    report = {
        "missing_boundary_zones": ["farfield"],
        "failed_workflow_tasks": {"volume_mesh": {"State": "Failed"}},
        "output_files_ok": False,
        "max_skewness": 0.92,
        "min_orthogonal_quality": 0.03,
        "limits": {"max_skewness": 0.85, "min_orthogonal_quality": 0.1},
        "boundary_layer_generated": False,
    }

    reasons = _mesh_failure_reasons(report)

    assert "missing boundary zones: farfield" in reasons
    assert "failed workflow tasks: volume_mesh" in reasons
    assert "mesh/case output files are missing" in reasons
    assert "max skewness 0.92 exceeds limit 0.85" in reasons
    assert "min orthogonal quality 0.03 below limit 0.1" in reasons
    assert "boundary layer was not generated" in reasons


def test_generate_mesh_with_fluent_meshing_uses_step_when_scdoc_path_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    task = SimulationTask(
        task_id="mesh_geometry_fallback",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )
    missing_scdoc = tmp_path / "spaceclaim" / "fluid_domain.scdoc"
    step = tmp_path / "spaceclaim" / "fluid_domain.step"
    step.parent.mkdir()
    step.write_text("step", encoding="utf-8")
    captured = {}

    def fake_run(command, cwd, env, text, capture_output, check, timeout):
        config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        captured["geometry_file"] = config["geometry_file"]
        Path(config["mesh_file"]).write_text("mesh", encoding="utf-8")
        Path(config["case_file"]).write_text("case", encoding="utf-8")
        Path(config["result_file"]).write_text(
            json.dumps(
                {
                    "success": True,
                    "boundary_zone_names": ["velocity_inlet", "pressure_outlet", "farfield", "object_wall"],
                    "boundary_layer_generated": True,
                    "mesh_exists": True,
                    "case_exists": True,
                    "tasks": {
                        "surface_mesh": {"State": "Up-to-date"},
                        "volume_mesh": {"State": "Up-to-date"},
                    },
                }
            ),
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "maximum skewness of: 0.2\n10 cells were created\nMinimum Orthogonal Quality = 0.9"
            stderr = ""

        return Completed()

    monkeypatch.setenv("FLUENT_MESHING_ENABLED", "true")
    monkeypatch.setattr("cfd_agent.tools.fluent_meshing_tool.subprocess.run", fake_run)

    result = generate_mesh_with_fluent_meshing(
        task,
        {"scdoc_file": str(missing_scdoc), "step_file": str(step)},
        str(tmp_path),
    )

    assert result["success"] is True
    assert captured["geometry_file"] == str(step.resolve())
    assert result["quality_report"]["geometry_file"] == str(step.resolve())
