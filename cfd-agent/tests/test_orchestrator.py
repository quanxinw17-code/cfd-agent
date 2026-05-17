from pathlib import Path

from cfd_agent.core.models import GeometryConfig, MotionConfig, SimulationTask
from cfd_agent.core.orchestrator import run_simulation


def _valid_task() -> SimulationTask:
    return SimulationTask(
        task_id="dry_run_test",
        geometry=GeometryConfig(type="sphere", parameters={"diameter": 0.1}),
        motion=MotionConfig(inlet_velocity=30.0),
    )


def test_dry_run_executes_end_to_end(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True)
    assert result["status"] == "success"
    assert result["stage"] == "completed"
    assert (tmp_path / "report" / "report.md").exists()
    assert (tmp_path / "solidworks" / "create_model.py").exists()
    assert (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "meshing" / "fluent_meshing_watertight.jou").exists()
    assert (tmp_path / "fluent" / "fluent_setup.jou").exists()
    assert (tmp_path / "fluent" / "fluent_solve.jou").exists()


def test_invalid_input_fails(tmp_path: Path) -> None:
    task = SimulationTask(task_id="invalid", geometry=GeometryConfig(type="sphere", parameters={}), motion=MotionConfig(inlet_velocity=30.0))
    result = run_simulation(task, str(tmp_path), dry_run=True)
    assert result["status"] == "failed"
    assert result["errors"]


def test_output_directory_is_created(tmp_path: Path) -> None:
    output = tmp_path / "new_output"
    result = run_simulation(_valid_task(), str(output), dry_run=True)
    assert result["status"] == "success"
    assert output.exists()


def test_result_shape(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True)
    for key in ["status", "stage", "files", "errors"]:
        assert key in result


def test_segmented_run_stops_at_solidworks(tmp_path: Path) -> None:
    result = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="solidworks")
    assert result["status"] == "success"
    assert result["stage"] == "SOLIDWORKS_MODEL_CREATED"
    assert (tmp_path / "solidworks" / "create_model.py").exists()
    assert not (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "pipeline_state.json").exists()


def test_segmented_run_can_resume_from_spaceclaim(tmp_path: Path) -> None:
    first = run_simulation(_valid_task(), str(tmp_path), dry_run=True, to_stage="solidworks")
    assert first["status"] == "success"

    second = run_simulation(_valid_task(), str(tmp_path), dry_run=True, from_stage="spaceclaim", to_stage="meshing")
    assert second["status"] == "success"
    assert second["stage"] == "FLUENT_MESH_CREATED"
    assert (tmp_path / "spaceclaim" / "create_external_domain.py").exists()
    assert (tmp_path / "meshing" / "fluent_meshing_watertight.jou").exists()
