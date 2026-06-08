from __future__ import annotations

from pathlib import Path
from typing import Any

from cfd_agent.core.models import SimulationTask
from cfd_agent.core.validators import validate_simulation_task
from cfd_agent.tools.file_tool import write_json


def preview_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        task = _task_from_form(payload)
    except Exception as exc:
        return {"ok": False, "task": None, "errors": [str(exc)]}
    errors = validate_simulation_task(task)
    return {"ok": not errors, "task": task.model_dump(), "errors": errors}


def save_task_payload(payload: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    preview = preview_task_payload(payload)
    if not preview["ok"]:
        return {**preview, "input_file": None}
    output = Path(output_dir)
    input_file = output / "input" / "task.json"
    write_json(input_file, preview["task"])
    return {**preview, "input_file": str(input_file.resolve())}


def load_task_payload(path: str | Path) -> dict[str, Any]:
    task = SimulationTask.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return {"ok": True, "task": task.model_dump(), "form": _form_from_task(task), "errors": []}


def _task_from_form(payload: dict[str, Any]) -> SimulationTask:
    geometry_type = str(payload.get("geometry_type") or "sphere")
    parameters = _geometry_parameters(geometry_type, payload)
    cad_file = str(payload.get("cad_file") or "").strip() or None
    task = {
        "task_id": str(payload.get("task_id") or "parametric_task").strip() or "parametric_task",
        "geometry": {
            "type": geometry_type,
            "unit": str(payload.get("unit") or "m"),
            "parameters": parameters,
            "cad_file": cad_file,
        },
        "domain": {
            "type": "external",
            "upstream_length_ratio": _float(payload, "upstream_length_ratio", 5.0),
            "downstream_length_ratio": _float(payload, "downstream_length_ratio", 15.0),
            "side_length_ratio": _float(payload, "side_length_ratio", 5.0),
        },
        "fluid": {
            "name": str(payload.get("fluid_name") or "air"),
            "density": _float(payload, "fluid_density", 1.225),
            "viscosity": _float(payload, "fluid_viscosity", 1.789e-5),
            "temperature": _float(payload, "fluid_temperature", 288.15),
            "pressure": _float(payload, "fluid_pressure", 101325.0),
        },
        "motion": {
            "type": str(payload.get("motion_type") or "stationary"),
            "inlet_velocity": _float(payload, "inlet_velocity"),
            "attack_angle_deg": _float(payload, "attack_angle_deg", 0.0),
        },
        "mesh": {
            "global_size": _optional_float(payload, "global_size"),
            "near_body_size": _optional_float(payload, "near_body_size"),
            "boundary_layer_enabled": _bool(payload.get("boundary_layer_enabled"), True),
            "target_y_plus": _float(payload, "target_y_plus", 1.0),
            "first_layer_height": _optional_float(payload, "first_layer_height"),
            "layers": _int(payload, "mesh_layers", 15),
            "growth_rate": _float(payload, "mesh_growth_rate", 1.2),
            "max_skewness": _float(payload, "max_skewness", 0.85),
            "min_orthogonal_quality": _float(payload, "min_orthogonal_quality", 0.15),
        },
        "solver": {
            "steady": _bool(payload.get("solver_steady"), True),
            "solver_type": str(payload.get("solver_type") or "pressure_based"),
            "turbulence_model": str(payload.get("turbulence_model") or "k_omega_sst"),
            "residual_target": _float(payload, "residual_target", 1e-5),
            "max_iterations": _int(payload, "max_iterations", 1000),
        },
    }
    return SimulationTask.model_validate(task)


def _geometry_parameters(geometry_type: str, payload: dict[str, Any]) -> dict[str, float]:
    if geometry_type == "sphere":
        return {"diameter": _float(payload, "diameter")}
    if geometry_type == "cylinder":
        return {"diameter": _float(payload, "diameter"), "length": _float(payload, "length")}
    if geometry_type == "box":
        return {
            "length": _float(payload, "length"),
            "width": _float(payload, "width"),
            "height": _float(payload, "height"),
        }
    if geometry_type == "custom_cad":
        return {"characteristic_length": _float(payload, "characteristic_length")}
    raise ValueError(f"unsupported geometry_type: {geometry_type}")


def _form_from_task(task: SimulationTask) -> dict[str, Any]:
    params = task.geometry.parameters
    return {
        "task_id": task.task_id,
        "geometry_type": task.geometry.type,
        "unit": task.geometry.unit,
        "diameter": params.get("diameter"),
        "length": params.get("length"),
        "width": params.get("width"),
        "height": params.get("height"),
        "characteristic_length": params.get("characteristic_length"),
        "cad_file": task.geometry.cad_file,
        "inlet_velocity": task.motion.inlet_velocity,
        "attack_angle_deg": task.motion.attack_angle_deg,
        "fluid_name": task.fluid.name,
        "fluid_density": task.fluid.density,
        "fluid_viscosity": task.fluid.viscosity,
        "fluid_temperature": task.fluid.temperature,
        "fluid_pressure": task.fluid.pressure,
        "upstream_length_ratio": task.domain.upstream_length_ratio,
        "downstream_length_ratio": task.domain.downstream_length_ratio,
        "side_length_ratio": task.domain.side_length_ratio,
        "global_size": task.mesh.global_size,
        "near_body_size": task.mesh.near_body_size,
        "boundary_layer_enabled": task.mesh.boundary_layer_enabled,
        "target_y_plus": task.mesh.target_y_plus,
        "first_layer_height": task.mesh.first_layer_height,
        "mesh_layers": task.mesh.layers,
        "mesh_growth_rate": task.mesh.growth_rate,
        "max_skewness": task.mesh.max_skewness,
        "min_orthogonal_quality": task.mesh.min_orthogonal_quality,
        "solver_steady": task.solver.steady,
        "solver_type": task.solver.solver_type,
        "turbulence_model": task.solver.turbulence_model,
        "residual_target": task.solver.residual_target,
        "max_iterations": task.solver.max_iterations,
    }


def _float(payload: dict[str, Any], key: str, default: float | None = None) -> float:
    value = payload.get(key)
    if value in (None, ""):
        if default is None:
            raise ValueError(f"{key} is required")
        return float(default)
    return float(value)


def _optional_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return None if value in (None, "") else float(value)


def _int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key)
    return int(default) if value in (None, "") else int(value)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
