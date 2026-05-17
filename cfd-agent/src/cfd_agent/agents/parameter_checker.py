from __future__ import annotations

from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import calculate_mach_number, calculate_reynolds_number, classify_flow, get_characteristic_length
from cfd_agent.core.validators import validate_simulation_task


def check_parameters(task: SimulationTask) -> dict:
    errors = validate_simulation_task(task)
    if errors:
        return {"valid": False, "errors": errors, "physics": None, "warnings": []}
    length = get_characteristic_length(task)
    reynolds = calculate_reynolds_number(task.fluid.density, task.motion.inlet_velocity, length, task.fluid.viscosity)
    mach = calculate_mach_number(task.motion.inlet_velocity)
    flow = classify_flow(reynolds, mach)
    warnings = []
    if flow["compressibility"] == "compressible":
        warnings.append("Mach number is >= 0.3; MVP incompressible defaults should be reviewed.")
    return {"valid": True, "errors": [], "physics": {"reynolds_number": reynolds, "mach_number": mach, **flow}, "warnings": warnings}

