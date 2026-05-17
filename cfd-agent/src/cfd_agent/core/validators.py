from __future__ import annotations

from .models import SimulationTask


def validate_simulation_task(task: SimulationTask) -> list[str]:
    errors: list[str] = []
    params = task.geometry.parameters
    geometry_type = task.geometry.type

    required_by_geometry = {
        "sphere": ["diameter"],
        "cylinder": ["diameter", "length"],
        "box": ["length", "width", "height"],
    }
    for name in required_by_geometry.get(geometry_type, []):
        if name not in params:
            errors.append(f"{geometry_type} requires parameter '{name}'")

    if geometry_type == "custom_cad" and not task.geometry.cad_file:
        errors.append("custom_cad requires cad_file")

    for name, value in params.items():
        if value <= 0:
            errors.append(f"geometry parameter '{name}' must be greater than 0")

    if task.motion.inlet_velocity <= 0:
        errors.append("inlet_velocity must be greater than 0")
    if task.fluid.density <= 0:
        errors.append("fluid density must be greater than 0")
    if task.fluid.viscosity <= 0:
        errors.append("fluid viscosity must be greater than 0")
    if task.mesh.layers < 0 or task.mesh.layers > 100:
        errors.append("mesh layers must be between 0 and 100")
    if not (1.0 <= task.mesh.growth_rate <= 1.5):
        errors.append("mesh growth_rate must be between 1.0 and 1.5")
    if task.solver.max_iterations <= 0:
        errors.append("solver max_iterations must be greater than 0")
    if task.solver.residual_target <= 0:
        errors.append("solver residual_target must be greater than 0")

    return errors

