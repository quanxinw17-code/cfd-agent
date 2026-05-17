from pathlib import Path

from cfd_agent.core.models import SimulationTask, load_simulation_task


def test_load_example_task() -> None:
    path = Path("examples/sphere_external_flow.json")
    task = load_simulation_task(path)
    assert isinstance(task, SimulationTask)
    assert task.geometry.type == "sphere"
    assert task.motion.inlet_velocity == 30.0
