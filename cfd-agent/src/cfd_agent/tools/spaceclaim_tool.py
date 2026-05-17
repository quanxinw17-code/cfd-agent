from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, template_dir, write_json


def create_external_flow_domain(task: SimulationTask, solidworks_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "spaceclaim")
    logger = configure_task_logger("cfd_agent.spaceclaim", output_dir, "geometry.log")
    script_file = root / "create_external_domain.py"
    log_file = root / "spaceclaim.log"
    scdoc_file = root / "fluid_domain.scdoc"
    pmdb_file = root / "fluid_domain.pmdb"
    step_file = root / "fluid_domain.step"
    named_file = root / "named_selections.json"
    length = get_characteristic_length(task)
    source_geometry = solidworks_info.get("step_file") or solidworks_info.get("planned_step_file")
    if source_geometry:
        source_geometry = str(Path(source_geometry).resolve())

    named = {
        "velocity_inlet": {"type": "velocity-inlet"},
        "pressure_outlet": {"type": "pressure-outlet"},
        "farfield": {"type": "wall"},
        "object_wall": {"type": "wall"},
        "symmetry": {"type": "symmetry", "optional": True},
    }
    write_json(named_file, named)
    _render_template(
        "spaceclaim_external_domain.py.j2",
        script_file,
        {"task": task, "length": length, "source_geometry": source_geometry, "paths": _paths(scdoc_file, pmdb_file, step_file, named_file, log_file)},
    )

    if dry_run:
        logger.info("Dry-run SpaceClaim script generated: %s", script_file)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, True, None, planned=True)

    if os.getenv("SPACECLAIM_ENABLED", "false").lower() != "true":
        error = "SPACECLAIM_ENABLED is not true; enable it or run with --dry-run"
        logger.error(error)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, error)
    if not solidworks_info.get("step_file") and not solidworks_info.get("parasolid_file"):
        error = "SpaceClaim requires a real SolidWorks STEP or Parasolid file; none was produced"
        logger.error(error)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, error)

    executable = os.getenv("SPACECLAIM_EXECUTABLE", "")
    resolved = _resolve_executable(executable)
    if not resolved:
        error = f"SpaceClaim executable not found: {executable}"
        logger.error(error)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, error)

    command = [
        str(resolved),
        "/Splash=False",
        "/Welcome=False",
        f"/RunScript={script_file.resolve()}",
        "/ScriptAPI=22",
        "/ExitAfterScript=True",
    ]
    logger.info("Running SpaceClaim command: %s", " ".join(command))
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(completed.stdout + "\n" + completed.stderr)
    if completed.returncode != 0:
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, "SpaceClaim returned non-zero exit code")
    missing = [str(path) for path in [step_file] if not path.exists()]
    if missing:
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, f"SpaceClaim completed but files are missing: {missing}")
    return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, True, None)


def _render_template(template_name: str, target: Path, context: dict) -> None:
    env = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    target.write_text(env.get_template(template_name).render(**context), encoding="utf-8")


def _resolve_executable(value: str) -> str | None:
    if not value:
        return None
    if Path(value).exists():
        return value
    return shutil.which(value)


def _paths(scdoc_file: Path, pmdb_file: Path, step_file: Path, named_file: Path, log_file: Path) -> dict[str, str]:
    return {
        "scdoc_file": str(scdoc_file.resolve()),
        "pmdb_file": str(pmdb_file.resolve()),
        "step_file": str(step_file.resolve()),
        "named_selections_file": str(named_file.resolve()),
        "log_file": str(log_file.resolve()),
    }


def _result(script_file: Path, scdoc_file: Path, pmdb_file: Path, step_file: Path, named_file: Path, success: bool, error: str | None, planned: bool = False) -> dict:
    return {
        "spaceclaim_script": str(script_file),
        "scdoc_file": None if planned or not scdoc_file.exists() else str(scdoc_file),
        "pmdb_file": None if planned or not pmdb_file.exists() else str(pmdb_file),
        "step_file": None if planned or not step_file.exists() else str(step_file),
        "planned_scdoc_file": str(scdoc_file) if planned else None,
        "planned_pmdb_file": str(pmdb_file) if planned else None,
        "planned_step_file": str(step_file) if planned else None,
        "named_selections_file": str(named_file),
        "success": success,
        "error": error,
    }
