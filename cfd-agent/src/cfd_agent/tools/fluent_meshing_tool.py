from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.file_tool import ensure_dir, write_json


def generate_mesh_with_fluent_meshing(task: SimulationTask, domain_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "meshing")
    logger = configure_task_logger("cfd_agent.fluent_meshing", output_dir, "mesh.log")
    journal_file = root / "fluent_meshing_watertight.jou"
    mesh_file = root / "mesh.msh.h5"
    case_file = root / "mesh_case.cas.h5"
    quality_file = root / "mesh_quality_report.json"
    geometry_file = domain_info.get("step_file") or domain_info.get("planned_step_file")
    quality_report = {"cell_count": None, "max_skewness": None, "min_orthogonal_quality": None, "passed": None}
    write_json(quality_file, quality_report)
    _render_template(
        "fluent_meshing_watertight.jou.j2",
        journal_file,
        {
            "task": task,
            "geometry_file": str(geometry_file).replace("\\", "/"),
            "mesh_file": str(mesh_file).replace("\\", "/"),
            "case_file": str(case_file).replace("\\", "/"),
            "quality_file": str(quality_file).replace("\\", "/"),
        },
    )

    if dry_run:
        logger.info("Dry-run Fluent Meshing journal generated: %s", journal_file)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, True, None, planned=True)

    if mesh_file.exists() and case_file.exists():
        quality_report = _load_quality_report(quality_file, quality_report)
        logger.info("Using existing validated mesh/case files: %s %s", mesh_file, case_file)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, True, None)

    fallback_mesh = root / "gmsh_volume_fluent_faces_flipped.msh"
    if os.getenv("CFD_AGENT_GMSH_FALLBACK", "true").lower() == "true" and fallback_mesh.exists():
        return _convert_fluent_mesh(fallback_mesh, mesh_file, case_file, quality_file, quality_report, root, logger)

    if os.getenv("FLUENT_MESHING_ENABLED", "false").lower() != "true":
        error = "FLUENT_MESHING_ENABLED is not true; enable it or run with --dry-run"
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, error)
    if not domain_info.get("step_file"):
        error = "Fluent Meshing requires a real SpaceClaim fluid domain STEP file; none was produced"
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, error)

    executable = os.getenv("FLUENT_EXECUTABLE", "")
    resolved = _resolve_executable(executable)
    if not resolved:
        error = f"Fluent executable not found: {executable}"
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, error)

    command = [resolved, "3ddp", "-g", "-meshing", "-i", str(journal_file)]
    logger.info("Running Fluent Meshing command: %s", " ".join(command))
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    (root / "fluent_meshing.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, "Fluent Meshing returned non-zero exit code")
    return _result(journal_file, mesh_file, case_file, quality_report, quality_file, True, None)


def _convert_fluent_mesh(fallback_mesh: Path, mesh_file: Path, case_file: Path, quality_file: Path, quality_report: dict, root: Path, logger) -> dict:
    executable = os.getenv("FLUENT_EXECUTABLE", r"D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe")
    resolved = _resolve_executable(executable)
    journal_file = root / "fluent_convert_existing_volume_mesh.jou"
    if not resolved:
        error = f"Fluent executable not found: {executable}"
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, error)

    journal = f"""/file/read-mesh "{str(fallback_mesh.resolve()).replace("\\", "/")}"
/file/write-mesh "{str(mesh_file.resolve()).replace("\\", "/")}"
ok
/file/write-case "{str(case_file.resolve()).replace("\\", "/")}"
yes
/exit
yes
"""
    journal_file.write_text(journal, encoding="utf-8")
    command = [str(resolved), "3ddp", "-g", "-i", str(journal_file.resolve())]
    logger.info("Converting existing Gmsh volume mesh with Fluent: %s", " ".join(command))
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    (root / "fluent_meshing.log").write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, "Fluent mesh conversion returned non-zero exit code")
    if not mesh_file.exists() or not case_file.exists():
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, False, "Fluent mesh conversion completed but mesh/case files are missing")
    quality_report = _load_quality_report(quality_file, quality_report)
    return _result(journal_file, mesh_file, case_file, quality_report, quality_file, True, None)


def _load_quality_report(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    import json

    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _render_template(template_name: str, target: Path, context: dict) -> None:
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    target.write_text(env.get_template(template_name).render(**context), encoding="utf-8")


def _resolve_executable(value: str) -> str | None:
    if not value:
        return None
    if Path(value).exists():
        return value
    return shutil.which(value)


def _result(journal_file: Path, mesh_file: Path, case_file: Path, quality_report: dict, quality_file: Path, success: bool, error: str | None, planned: bool = False) -> dict:
    return {
        "meshing_journal": str(journal_file),
        "mesh_file": None if planned else str(mesh_file),
        "case_file": None if planned else str(case_file),
        "planned_mesh_file": str(mesh_file) if planned else None,
        "planned_case_file": str(case_file) if planned else None,
        "quality_report": quality_report,
        "quality_report_file": str(quality_file),
        "success": success,
        "error": error,
    }
