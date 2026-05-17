from __future__ import annotations

from .errors import CFDAgentError
from .models import SimulationTask


def get_characteristic_length(task: SimulationTask) -> float:
    params = task.geometry.parameters
    geometry_type = task.geometry.type

    if geometry_type in {"sphere", "cylinder"}:
        if "diameter" not in params:
            raise CFDAgentError(f"{geometry_type} requires parameter 'diameter'")
        return params["diameter"]
    if geometry_type == "box":
        required = ["length", "width", "height"]
        missing = [name for name in required if name not in params]
        if missing:
            raise CFDAgentError(f"box requires parameters: {', '.join(missing)}")
        return max(params["length"], params["width"], params["height"])
    if geometry_type == "custom_cad":
        if "characteristic_length" not in params:
            raise CFDAgentError("custom_cad requires parameter 'characteristic_length'")
        return params["characteristic_length"]

    raise CFDAgentError(f"unsupported geometry type: {geometry_type}")


def calculate_reynolds_number(rho: float, velocity: float, length: float, mu: float) -> float:
    return rho * velocity * length / mu


def calculate_mach_number(velocity: float, speed_of_sound: float = 340.0) -> float:
    return velocity / speed_of_sound


def classify_flow(reynolds_number: float, mach_number: float) -> dict:
    compressibility = "incompressible" if mach_number < 0.3 else "compressible"
    regime = "laminar" if reynolds_number < 2300 else "turbulent"
    return {
        "compressibility": compressibility,
        "regime": regime,
        "recommended_solver": "pressure_based" if compressibility == "incompressible" else "density_based",
        "recommended_turbulence_model": "laminar" if regime == "laminar" else "k_omega_sst",
    }

