from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.file_tool import ensure_dir, project_root, template_dir, write_json
from cfd_agent.tools.mesh_imitation_tool import runner_environment


EXPECTED_BOUNDARIES = {"velocity_inlet", "pressure_outlet", "farfield", "object_wall"}
BOUNDARY_ALIASES = {
    "velocity_inlet": "velocity_inlet",
    "velocity-inlet": "velocity_inlet",
    "inlet": "velocity_inlet",
    "air_in": "velocity_inlet",
    "pressure_outlet": "pressure_outlet",
    "pressure-outlet": "pressure_outlet",
    "outlet": "pressure_outlet",
    "air_out": "pressure_outlet",
    "farfield": "farfield",
    "far_field": "farfield",
    "fluid_farfield": "farfield",
    "pressure_far_field": "farfield",
    "pressure-far-field": "farfield",
    "object_wall": "object_wall",
    "body_wall": "object_wall",
    "wall": "object_wall",
}


def generate_mesh_with_fluent_meshing(
    task: SimulationTask,
    domain_info: dict,
    output_dir: str,
    dry_run: bool = False,
    imitation_info: dict | None = None,
) -> dict:
    root = ensure_dir(Path(output_dir) / "meshing")
    logger = configure_task_logger("cfd_agent.fluent_meshing", output_dir, "mesh.log")
    journal_file = root / "fluent_meshing_watertight.jou"
    mesh_file = root / "mesh.msh.h5"
    case_file = root / "mesh_case.cas.h5"
    quality_file = root / "mesh_quality_report.json"
    log_file = root / "fluent_meshing.log"
    result_file = root / "fluent_meshing_result.json"
    config_file = root / "fluent_meshing_config.json"
    geometry_file = _select_geometry_file(domain_info, require_existing=not dry_run)
    quality_report = _empty_quality_report(task)
    quality_report["geometry_file"] = str(Path(geometry_file).resolve()) if geometry_file and Path(geometry_file).exists() else geometry_file
    write_json(quality_file, quality_report)
    _render_review_journal(task, geometry_file, mesh_file, case_file, journal_file)

    if dry_run:
        logger.info("Dry-run Fluent Meshing plan generated: %s", journal_file)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, True, None, planned=True)
    if not geometry_file or not Path(geometry_file).is_file():
        error = "Fluent Meshing requires a real SpaceClaim SCDOC or STEP fluid-domain geometry file"
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, False, error)
    if os.getenv("FLUENT_MESHING_ENABLED", "true").lower() != "true":
        error = "FLUENT_MESHING_ENABLED is not true"
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, False, error)

    for path in (mesh_file, case_file, result_file):
        if path.exists():
            path.unlink()
    settings = _effective_mesh_settings(task, imitation_info)
    config = {
        "geometry_file": str(Path(geometry_file).resolve()),
        "mesh_file": str(mesh_file.resolve()),
        "case_file": str(case_file.resolve()),
        "result_file": str(result_file.resolve()),
        "length_unit": task.geometry.unit,
        "global_size": settings["global_size"],
        "near_body_size": settings["near_body_size"],
        "boundary_layer_enabled": settings["boundary_layer_enabled"],
        "first_layer_height": settings["first_layer_height"],
        "layers": settings["layers"],
        "growth_rate": settings["growth_rate"],
        "processor_count": 1,
    }
    write_json(config_file, config)
    runner = project_root() / "scripts" / "run_fluent_meshing_221.py"
    env = runner_environment()
    ansys_root = str(Path(env.get("AWP_ROOT221", r"D:\Program Files\ANSYS Inc\v221")))
    env["AWP_ROOT221"] = ansys_root
    env["AWP_ROOT222"] = ansys_root
    completed = subprocess.run(
        [sys.executable, str(runner), str(config_file.resolve())],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    log_text = completed.stdout + "\n" + completed.stderr
    log_file.write_text(log_text, encoding="utf-8")
    runner_result = _read_json(result_file)
    runner_result.setdefault("geometry_file", config["geometry_file"])
    runner_result.setdefault("mesh_exists", mesh_file.is_file())
    runner_result.setdefault("case_exists", case_file.is_file())
    quality_report = _quality_report(task, runner_result, log_text)
    write_json(quality_file, quality_report)
    if completed.returncode != 0 or not runner_result.get("success"):
        error = runner_result.get("error") or f"Fluent Meshing runner returned exit code {completed.returncode}"
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, False, error)
    if not quality_report["passed"]:
        reasons = _mesh_failure_reasons(quality_report)
        error = "Fluent Meshing outputs failed validation: " + "; ".join(reasons)
        logger.error(error)
        return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, False, error)
    logger.info("Fluent Meshing completed with %s cells", quality_report["cell_count"])
    return _result(journal_file, mesh_file, case_file, quality_report, quality_file, log_file, True, None)


def _effective_mesh_settings(task: SimulationTask, imitation_info: dict | None) -> dict:
    settings = task.mesh.model_dump()
    if imitation_info and imitation_info.get("success") is not False and not imitation_info.get("skipped"):
        settings.update({name: value for name, value in imitation_info.get("effective_mesh_settings", {}).items() if value is not None})
    return settings


def _empty_quality_report(task: SimulationTask) -> dict:
    return {
        "route": "fluent_meshing_watertight",
        "geometry_file": None,
        "cell_count": None,
        "max_skewness": None,
        "max_skewness_scope": "surface",
        "max_cell_squish": None,
        "min_orthogonal_quality": None,
        "raw_boundary_zone_names": [],
        "boundary_zone_names": [],
        "missing_boundary_zones": [],
        "boundary_layer_generated": None,
        "failed_workflow_tasks": {},
        "output_files_ok": None,
        "limits": {"max_skewness": task.mesh.max_skewness, "min_orthogonal_quality": task.mesh.min_orthogonal_quality},
        "passed": None,
    }


def _quality_report(task: SimulationTask, runner_result: dict, log_text: str) -> dict:
    report = _empty_quality_report(task)
    report["cell_count"] = _last_int(log_text, r"(\d+)\s+cells were created")
    report["max_skewness"] = _last_float(log_text, r"maximum skewness of\s*:?\s*([0-9.eE+-]+)")
    report["max_cell_squish"] = _last_float(log_text, r"Maximum Cell Squish\s*=\s*([0-9.eE+-]+)")
    report["min_orthogonal_quality"] = _last_float(log_text, r"Minimum Orthogonal Quality\s*=\s*([0-9.eE+-]+)")
    report["geometry_file"] = runner_result.get("geometry_file")
    raw_boundaries = [str(name) for name in runner_result.get("boundary_zone_names", [])]
    report["raw_boundary_zone_names"] = raw_boundaries
    report["boundary_zone_names"] = _normalize_boundary_zones(raw_boundaries)
    report["missing_boundary_zones"] = sorted(EXPECTED_BOUNDARIES - set(report["boundary_zone_names"]))
    report["boundary_layer_generated"] = bool(runner_result.get("boundary_layer_generated"))
    task_states = runner_result.get("tasks", {})
    report["workflow_tasks"] = {name: value.get("State") for name, value in task_states.items()}
    report["failed_workflow_tasks"] = {
        name: value
        for name, value in task_states.items()
        if value.get("State") != "Up-to-date" or value.get("Errors")
    }
    if "mesh_exists" in runner_result or "case_exists" in runner_result:
        report["output_files_ok"] = bool(runner_result.get("mesh_exists") and runner_result.get("case_exists"))
    else:
        report["output_files_ok"] = True
    boundaries_ok = not report["missing_boundary_zones"]
    quality_ok = (
        bool(report["cell_count"])
        and report["max_skewness"] is not None
        and report["max_skewness"] <= task.mesh.max_skewness
        and report["min_orthogonal_quality"] is not None
        and report["min_orthogonal_quality"] >= task.mesh.min_orthogonal_quality
    )
    layers_ok = not task.mesh.boundary_layer_enabled or report["boundary_layer_generated"]
    tasks_ok = not report["failed_workflow_tasks"]
    report["passed"] = bool(boundaries_ok and quality_ok and layers_ok and tasks_ok and report["output_files_ok"])
    return report


def _select_geometry_file(domain_info: dict, require_existing: bool) -> str | None:
    keys = ("scdoc_file", "step_file", "pmdb_file", "planned_scdoc_file", "planned_step_file")
    candidates = [domain_info.get(key) for key in keys if domain_info.get(key)]
    if not require_existing:
        return str(candidates[0]) if candidates else None
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return str(candidates[0]) if candidates else None


def _normalize_boundary_zones(names: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for name in names:
        key = _boundary_key(name)
        value = BOUNDARY_ALIASES.get(key, name)
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _boundary_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _mesh_failure_reasons(report: dict) -> list[str]:
    reasons = []
    missing = report.get("missing_boundary_zones") or []
    if missing:
        reasons.append("missing boundary zones: " + ", ".join(missing))
    failed_tasks = report.get("failed_workflow_tasks") or {}
    if failed_tasks:
        reasons.append("failed workflow tasks: " + ", ".join(sorted(failed_tasks)))
    if report.get("output_files_ok") is False:
        reasons.append("mesh/case output files are missing")
    limits = report.get("limits") or {}
    max_skewness = report.get("max_skewness")
    max_skewness_limit = limits.get("max_skewness")
    if max_skewness is not None and max_skewness_limit is not None and max_skewness > max_skewness_limit:
        reasons.append(f"max skewness {max_skewness:g} exceeds limit {max_skewness_limit:g}")
    min_orthogonal = report.get("min_orthogonal_quality")
    min_orthogonal_limit = limits.get("min_orthogonal_quality")
    if min_orthogonal is not None and min_orthogonal_limit is not None and min_orthogonal < min_orthogonal_limit:
        reasons.append(f"min orthogonal quality {min_orthogonal:g} below limit {min_orthogonal_limit:g}")
    if report.get("boundary_layer_generated") is False:
        reasons.append("boundary layer was not generated")
    if not reasons:
        reasons.append("mesh quality report did not meet acceptance criteria")
    return reasons


def _last_float(text: str, pattern: str) -> float | None:
    matches = re.findall(pattern, text, re.IGNORECASE)
    return float(matches[-1].rstrip(".")) if matches else None


def _last_int(text: str, pattern: str) -> int | None:
    matches = re.findall(pattern, text, re.IGNORECASE)
    return int(matches[-1]) if matches else None


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _render_review_journal(task: SimulationTask, geometry_file: str | None, mesh_file: Path, case_file: Path, target: Path) -> None:
    env = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    target.write_text(
        env.get_template("fluent_meshing_watertight.jou.j2").render(
            task=task,
            geometry_file=str(geometry_file or "").replace("\\", "/"),
            mesh_file=str(mesh_file.resolve()).replace("\\", "/"),
            case_file=str(case_file.resolve()).replace("\\", "/"),
        ),
        encoding="utf-8",
    )


def _result(journal_file: Path, mesh_file: Path, case_file: Path, quality_report: dict, quality_file: Path, log_file: Path, success: bool, error: str | None, planned: bool = False) -> dict:
    return {
        "route": "fluent_meshing_watertight",
        "meshing_journal": str(journal_file),
        "mesh_file": None if planned or not mesh_file.exists() else str(mesh_file),
        "case_file": None if planned or not case_file.exists() else str(case_file),
        "planned_mesh_file": str(mesh_file) if planned else None,
        "planned_case_file": str(case_file) if planned else None,
        "quality_report": quality_report,
        "quality_report_file": str(quality_file),
        "log_file": str(log_file),
        "success": success,
        "error": error,
    }
