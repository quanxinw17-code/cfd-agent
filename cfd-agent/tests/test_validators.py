from cfd_agent.core.models import FluidConfig, GeometryConfig, MotionConfig, SimulationTask
from cfd_agent.core.validators import validate_simulation_task


def test_sphere_missing_diameter_reports_error() -> None:
    task = SimulationTask(task_id="bad_sphere", geometry=GeometryConfig(type="sphere", parameters={}), motion=MotionConfig(inlet_velocity=10.0))
    assert any("diameter" in error for error in validate_simulation_task(task))


def test_cylinder_missing_length_reports_error() -> None:
    task = SimulationTask(
        task_id="bad_cylinder",
        geometry=GeometryConfig(type="cylinder", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=10.0),
    )
    assert any("length" in error for error in validate_simulation_task(task))


def test_negative_velocity_reports_error() -> None:
    task = SimulationTask(
        task_id="bad_velocity",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=-1.0),
    )
    assert any("inlet_velocity" in error for error in validate_simulation_task(task))


def test_zero_viscosity_reports_error() -> None:
    task = SimulationTask(
        task_id="bad_viscosity",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=1.0),
        fluid=FluidConfig(viscosity=0.0),
    )
    assert any("viscosity" in error for error in validate_simulation_task(task))

