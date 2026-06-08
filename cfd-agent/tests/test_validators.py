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


def test_custom_cad_requires_characteristic_length() -> None:
    task = SimulationTask(
        task_id="bad_custom_cad",
        geometry=GeometryConfig(type="custom_cad", parameters={}, cad_file="body.step"),
        motion=MotionConfig(inlet_velocity=10.0),
    )
    assert any("characteristic_length" in error for error in validate_simulation_task(task))


def test_mesh_imitation_requires_reference_file() -> None:
    task = SimulationTask(
        task_id="mesh_imitation",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
        mesh_imitation={"enabled": True},
    )

    assert "mesh imitation requires reference_file" in validate_simulation_task(task)


def test_domain_imitation_requires_reference_file_when_enabled() -> None:
    task = SimulationTask(
        task_id="domain_imitation",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
        domain_imitation={"enabled": True},
    )

    assert "domain imitation requires reference_file" in validate_simulation_task(task)


def test_domain_imitation_rejects_unsupported_reference_file_when_enabled() -> None:
    task = SimulationTask(
        task_id="domain_imitation",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
        domain_imitation={"enabled": True, "reference_file": "fluid_domain.msh.h5"},
    )

    assert "domain imitation reference_file must be .scdoc, .step, or .stp" in validate_simulation_task(task)


def test_domain_imitation_rejects_missing_supported_reference_file_when_enabled(tmp_path) -> None:
    missing_reference = tmp_path / "missing.step"
    task = SimulationTask(
        task_id="domain_imitation",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
        domain_imitation={"enabled": True, "reference_file": str(missing_reference)},
    )

    assert "domain imitation reference_file does not exist" in validate_simulation_task(task)


def test_domain_imitation_accepts_supported_reference_file_when_enabled(tmp_path) -> None:
    reference = tmp_path / "fluid_domain.SCDOC"
    reference.write_text("domain", encoding="utf-8")
    task = SimulationTask(
        task_id="domain_imitation",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
        domain_imitation={"enabled": True, "reference_file": str(reference)},
    )

    assert not any("domain imitation" in error for error in validate_simulation_task(task))
