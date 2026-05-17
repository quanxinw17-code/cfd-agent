from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GeometryConfig(BaseModel):
    type: Literal["sphere", "cylinder", "box", "custom_cad"]
    unit: Literal["m", "mm"] = "m"
    parameters: Dict[str, float]
    cad_file: Optional[str] = None


class DomainConfig(BaseModel):
    type: Literal["external", "internal"] = "external"
    upstream_length_ratio: float = 5.0
    downstream_length_ratio: float = 15.0
    side_length_ratio: float = 5.0


class FluidConfig(BaseModel):
    name: str = "air"
    density: float = 1.225
    viscosity: float = 1.789e-5
    temperature: float = 288.15
    pressure: float = 101325.0


class MotionConfig(BaseModel):
    type: Literal["stationary", "uniform_translation", "rotation"] = "stationary"
    inlet_velocity: float
    attack_angle_deg: float = 0.0
    angular_velocity_rad_s: Optional[float] = None


class MeshConfig(BaseModel):
    global_size: Optional[float] = None
    near_body_size: Optional[float] = None
    boundary_layer_enabled: bool = True
    target_y_plus: float = 1.0
    first_layer_height: Optional[float] = None
    layers: int = 15
    growth_rate: float = 1.2
    max_skewness: float = 0.85
    min_orthogonal_quality: float = 0.15


class SolverConfig(BaseModel):
    steady: bool = True
    solver_type: Literal["pressure_based", "density_based"] = "pressure_based"
    turbulence_model: Literal["laminar", "k_epsilon", "k_omega_sst"] = "k_omega_sst"
    residual_target: float = 1e-5
    max_iterations: int = 1000


class OutputConfig(BaseModel):
    requested: List[str] = Field(
        default_factory=lambda: [
            "drag_coefficient",
            "lift_coefficient",
            "pressure_contour",
            "velocity_contour",
            "residuals",
            "report",
        ]
    )


class SimulationTask(BaseModel):
    task_id: str
    geometry: GeometryConfig
    domain: DomainConfig = Field(default_factory=DomainConfig)
    fluid: FluidConfig = Field(default_factory=FluidConfig)
    motion: MotionConfig
    mesh: MeshConfig = Field(default_factory=MeshConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    outputs: OutputConfig = Field(default_factory=OutputConfig)


def load_simulation_task(path: str | Path) -> SimulationTask:
    data = Path(path).read_text(encoding="utf-8")
    return SimulationTask.model_validate_json(data)

