from pathlib import Path

import pytest

from cfd_agent.core.models import GeometryConfig, MeshImitationConfig, MotionConfig, SimulationTask
from cfd_agent.tools.mesh_imitation_tool import (
    analyze_reference_mesh,
    effective_reference_length,
    runner_environment,
    scale_reference_profile,
    supported_reference_file,
    write_mesh_comparison,
)
from scripts.analyze_fluent_reference_mesh import read_reference_command


def test_supported_reference_file_accepts_native_fluent_formats(tmp_path: Path) -> None:
    for name in ["reference.msh", "reference.msh.h5", "reference.cas", "reference.cas.h5"]:
        assert supported_reference_file(tmp_path / name)
    assert not supported_reference_file(tmp_path / "reference.step")


def test_runner_environment_uses_absolute_source_path(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "src")

    env = runner_environment()

    assert Path(env["PYTHONPATH"].split(__import__("os").pathsep)[0]).is_absolute()


def test_reference_runner_uses_tui_read_commands_for_fluent_221(tmp_path: Path) -> None:
    assert read_reference_command(tmp_path / "reference.msh.h5").startswith('/file/read-case "')
    assert read_reference_command(tmp_path / "reference.cas.h5").startswith('/file/read-case "')


def test_effective_reference_length_prefers_detected_length() -> None:
    config = MeshImitationConfig(enabled=True, reference_file="reference.msh.h5", reference_characteristic_length=0.4)
    assert effective_reference_length({"reference_characteristic_length": 0.25}, config) == 0.25


def test_effective_reference_length_uses_manual_fallback() -> None:
    config = MeshImitationConfig(enabled=True, reference_file="reference.msh.h5", reference_characteristic_length=0.4)
    assert effective_reference_length({}, config) == 0.4


def test_effective_reference_length_requires_detected_or_manual_value() -> None:
    config = MeshImitationConfig(enabled=True, reference_file="reference.msh.h5")
    with pytest.raises(ValueError, match="reference characteristic length"):
        effective_reference_length({}, config)


def test_scale_reference_profile_scales_lengths_and_copies_dimensionless_values() -> None:
    profile = {
        "reference_characteristic_length": 0.1,
        "mesh_settings": {
            "global_size": 0.01,
            "near_body_size": 0.002,
            "first_layer_height": 0.0001,
            "boundary_layer_total_thickness": 0.005,
            "layers": 12,
            "growth_rate": 1.18,
            "boundary_layer_enabled": True,
        },
    }
    scaled = scale_reference_profile(profile, new_characteristic_length=0.2)
    assert scaled["scale_ratio"] == 2.0
    assert scaled["effective_mesh_settings"]["global_size"] == 0.02
    assert scaled["effective_mesh_settings"]["near_body_size"] == 0.004
    assert scaled["effective_mesh_settings"]["first_layer_height"] == 0.0002
    assert scaled["effective_mesh_settings"]["boundary_layer_total_thickness"] == 0.01
    assert scaled["effective_mesh_settings"]["layers"] == 12
    assert scaled["effective_mesh_settings"]["growth_rate"] == 1.18
    assert scaled["effective_mesh_settings"]["boundary_layer_enabled"] is True


def test_dry_run_reference_analysis_writes_planned_outputs(tmp_path: Path) -> None:
    reference = tmp_path / "reference.msh.h5"
    reference.write_text("mesh", encoding="utf-8")
    task = SimulationTask(
        task_id="imitate",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.2}),
        motion=MotionConfig(inlet_velocity=30.0),
        mesh_imitation={"enabled": True, "reference_file": str(reference), "reference_characteristic_length": 0.1},
    )

    result = analyze_reference_mesh(task, str(tmp_path / "output"), dry_run=True)

    assert result["success"] is True
    assert result["skipped"] is False
    assert Path(result["profile_file"]).exists()
    assert Path(result["scaled_settings_file"]).exists()
    assert result["effective_mesh_settings"]["global_size"] == 0.01


def test_disabled_reference_analysis_is_successfully_skipped(tmp_path: Path) -> None:
    task = SimulationTask(
        task_id="plain",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.2}),
        motion=MotionConfig(inlet_velocity=30.0),
    )

    result = analyze_reference_mesh(task, str(tmp_path), dry_run=False)

    assert result["success"] is True
    assert result["skipped"] is True


def test_write_mesh_comparison_compares_reference_and_generated_mesh(tmp_path: Path) -> None:
    imitation = {
        "enabled": True,
        "profile": {"cell_count": 1000, "min_orthogonal_quality": 0.4, "boundary_zone_names": ["object_wall"]},
        "scaled_settings": {"scale_ratio": 2.0, "effective_mesh_settings": {"global_size": 0.02}},
    }
    mesh = {"quality_report": {"cell_count": 1200, "min_orthogonal_quality": 0.5, "boundary_zone_names": ["object_wall"]}}

    path = write_mesh_comparison(imitation, mesh, tmp_path)

    assert path is not None
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert payload["cell_count_ratio"] == 1.2
    assert payload["scale_ratio"] == 2.0
