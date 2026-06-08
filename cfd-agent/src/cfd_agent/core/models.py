from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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


class MeshImitationConfig(BaseModel):
    enabled: bool = False
    reference_file: Optional[str] = None
    reference_characteristic_length: Optional[float] = None
    scale_mode: Literal["characteristic_length"] = "characteristic_length"


class DomainImitationConfig(BaseModel):
    enabled: bool = False
    reference_file: Optional[str] = None
    manual_flow_direction: Optional[List[float]] = None

    @field_validator("manual_flow_direction", mode="before")
    @classmethod
    def reject_boolean_flow_direction_components(cls, value: object) -> object:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray, Mapping)):
            return value
        components = list(value)
        if any(isinstance(component, bool) for component in components):
            raise ValueError("manual_flow_direction components must be numeric, not boolean")
        return components

    @field_validator("manual_flow_direction")
    @classmethod
    def validate_manual_flow_direction(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return None
        if len(value) != 3 or not all(math.isfinite(component) for component in value) or not any(component != 0 for component in value):
            raise ValueError("manual_flow_direction must be a finite non-zero three-component vector")
        return [float(component) for component in value]


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
    mesh_imitation: MeshImitationConfig = Field(default_factory=MeshImitationConfig)
    domain_imitation: DomainImitationConfig = Field(default_factory=DomainImitationConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    outputs: OutputConfig = Field(default_factory=OutputConfig)


def load_simulation_task(path: str | Path) -> SimulationTask:
    data = Path(path).read_text(encoding="utf-8")
    return SimulationTask.model_validate_json(data)
