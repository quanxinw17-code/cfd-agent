from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, write_json


def create_solidworks_model(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "solidworks")
    logger = configure_task_logger("cfd_agent.solidworks", output_dir, "geometry.log")
    script_file = root / "create_model.py"
    native_file = root / "part.sldprt"
    step_file = root / "geometry.step"
    parasolid_file = root / "geometry.x_t"
    metadata_file = root / "geometry_metadata.json"

    length = get_characteristic_length(task)
    metadata = {
        "geometry_type": task.geometry.type,
        "unit": task.geometry.unit,
        "parameters": task.geometry.parameters,
        "characteristic_length": length,
        "reference_area": _reference_area(task),
        "reference_volume": _reference_volume(task),
        "dry_run": dry_run,
        "note": "CAD files are only real when SolidWorks successfully exports them.",
    }
    write_json(metadata_file, metadata)
    _render_template("solidworks_model.py.j2", script_file, {"task": task, "metadata": metadata, "paths": _paths(native_file, step_file, parasolid_file)})

    if dry_run:
        logger.info("Dry-run SolidWorks script generated: %s", script_file)
        return _result(script_file, native_file, step_file, parasolid_file, metadata_file, True, None, planned=True)

    if os.getenv("SOLIDWORKS_ENABLED", "false").lower() != "true":
        error = "SOLIDWORKS_ENABLED is not true; enable it or run with --dry-run"
        logger.error(error)
        return _result(script_file, native_file, step_file, parasolid_file, metadata_file, False, error)

    command = [sys.executable, str(script_file.resolve())]
    logger.info("Running SolidWorks command: %s", " ".join(command))
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    (root / "create_model.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return _result(script_file, native_file, step_file, parasolid_file, metadata_file, False, "SolidWorks Python COM script returned non-zero exit code")
    missing = [str(path) for path in [native_file, step_file, parasolid_file] if not path.exists()]
    if missing:
        return _result(script_file, native_file, step_file, parasolid_file, metadata_file, False, f"SolidWorks script completed but files are missing: {missing}")
    return _result(script_file, native_file, step_file, parasolid_file, metadata_file, True, None)


def _render_template(template_name: str, target: Path, context: dict) -> None:
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    target.write_text(env.get_template(template_name).render(**context), encoding="utf-8")


def _resolve_executable(value: str) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return str(path)
    return shutil.which(value)


def _paths(native_file: Path, step_file: Path, parasolid_file: Path) -> dict[str, str]:
    return {
        "native_file": str(native_file.resolve()),
        "step_file": str(step_file.resolve()),
        "parasolid_file": str(parasolid_file.resolve()),
    }


def _result(script_file: Path, native_file: Path, step_file: Path, parasolid_file: Path, metadata_file: Path, success: bool, error: str | None, planned: bool = False) -> dict:
    return {
        "script_file": str(script_file),
        "native_file": None if planned else str(native_file),
        "step_file": None if planned else str(step_file),
        "parasolid_file": None if planned else str(parasolid_file),
        "planned_native_file": str(native_file) if planned else None,
        "planned_step_file": str(step_file) if planned else None,
        "planned_parasolid_file": str(parasolid_file) if planned else None,
        "metadata_file": str(metadata_file),
        "success": success,
        "error": error,
    }


def _reference_area(task: SimulationTask) -> float | None:
    p = task.geometry.parameters
    if task.geometry.type == "sphere":
        return 3.141592653589793 * (p["diameter"] ** 2) / 4
    if task.geometry.type == "cylinder":
        return p["diameter"] * p["length"]
    return None


def _reference_volume(task: SimulationTask) -> float | None:
    p = task.geometry.parameters
    if task.geometry.type == "sphere":
        return 3.141592653589793 * (p["diameter"] ** 3) / 6
    if task.geometry.type == "cylinder":
        return 3.141592653589793 * (p["diameter"] ** 2) * p["length"] / 4
    return None
