import json
from pathlib import Path

from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.task_editor_tool import load_task_payload, preview_task_payload, save_task_payload


def _sphere_payload() -> dict:
    return {
        "task_id": "sphere_parametric",
        "geometry_type": "sphere",
        "unit": "m",
        "diameter": "0.1",
        "inlet_velocity": "30",
        "attack_angle_deg": "0",
        "fluid_density": "1.225",
        "fluid_viscosity": "1.789e-5",
        "fluid_temperature": "288.15",
        "fluid_pressure": "101325",
        "upstream_length_ratio": "5",
        "downstream_length_ratio": "15",
        "side_length_ratio": "5",
        "boundary_layer_enabled": True,
        "mesh_layers": "15",
        "mesh_growth_rate": "1.2",
        "max_skewness": "0.85",
        "min_orthogonal_quality": "0.15",
        "solver_steady": True,
        "solver_type": "pressure_based",
        "turbulence_model": "k_omega_sst",
        "residual_target": "1e-5",
        "max_iterations": "1000",
    }


def test_preview_task_payload_builds_valid_simulation_task() -> None:
    result = preview_task_payload(_sphere_payload())

    assert result["ok"] is True
    assert result["errors"] == []
    task = SimulationTask.model_validate(result["task"])
    assert task.geometry.type == "sphere"
    assert task.geometry.parameters["diameter"] == 0.1
    assert task.motion.inlet_velocity == 30.0
    assert task.mesh.layers == 15


def test_preview_task_payload_supports_box_geometry() -> None:
    payload = {
        **_sphere_payload(),
        "geometry_type": "box",
        "length": "2",
        "width": "1",
        "height": "0.5",
    }

    result = preview_task_payload(payload)

    assert result["ok"] is True
    assert result["task"]["geometry"]["parameters"] == {"length": 2.0, "width": 1.0, "height": 0.5}


def test_save_task_payload_writes_current_case_input_file(tmp_path: Path) -> None:
    output = tmp_path / "outputs" / "sphere_001"

    result = save_task_payload(_sphere_payload(), output)

    saved = output / "input" / "task.json"
    assert result["ok"] is True
    assert result["input_file"] == str(saved.resolve())
    assert json.loads(saved.read_text(encoding="utf-8"))["task_id"] == "sphere_parametric"


def test_load_task_payload_reads_existing_json(tmp_path: Path) -> None:
    path = tmp_path / "task.json"
    task = preview_task_payload(_sphere_payload())["task"]
    path.write_text(json.dumps(task), encoding="utf-8")

    result = load_task_payload(path)

    assert result["ok"] is True
    assert result["form"]["geometry_type"] == "sphere"
    assert result["form"]["diameter"] == 0.1
    assert result["form"]["inlet_velocity"] == 30.0
