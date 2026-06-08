from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import math
from collections.abc import Mapping
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, template_dir, write_json
from cfd_agent.tools.process_ui import bring_process_to_foreground


def create_external_flow_domain(
    task: SimulationTask,
    solidworks_info: dict,
    output_dir: str,
    dry_run: bool = False,
    imitation_info: dict | None = None,
) -> dict:
    root = ensure_dir(Path(output_dir) / "spaceclaim")
    logger = configure_task_logger("cfd_agent.spaceclaim", output_dir, "geometry.log")
    script_file = root / "create_external_domain.py"
    log_file = root / "spaceclaim.log"
    scdoc_file = root / "fluid_domain.scdoc"
    pmdb_file = root / "fluid_domain.pmdb"
    step_file = root / "fluid_domain.step"
    named_file = root / "named_selections.json"
    length = get_characteristic_length(task)
    source_geometry = (
        solidworks_info.get("source_file")
        or solidworks_info.get("step_file")
        or solidworks_info.get("parasolid_file")
        or solidworks_info.get("native_file")
        or solidworks_info.get("planned_step_file")
        or solidworks_info.get("planned_parasolid_file")
    )
    if source_geometry:
        source_geometry = str(Path(source_geometry).resolve())

    domain_settings = _domain_settings(task, length, imitation_info)
    named = {
        domain_settings["boundary_names"]["inlet"]: {"type": domain_settings["boundary_types"]["inlet"]},
        domain_settings["boundary_names"]["outlet"]: {"type": domain_settings["boundary_types"]["outlet"]},
        domain_settings["boundary_names"]["farfield"]: {"type": domain_settings["boundary_types"]["farfield"]},
        domain_settings["boundary_names"]["object_wall"]: {"type": domain_settings["boundary_types"]["object_wall"]},
        "symmetry": {"type": "symmetry", "optional": True},
    }
    write_json(named_file, named)
    _render_template(
        "spaceclaim_external_domain.py.j2",
        script_file,
        {
            "task": task,
            "length": length,
            "source_geometry": source_geometry,
            "paths": _paths(scdoc_file, pmdb_file, step_file, named_file, log_file),
            "domain_settings": domain_settings,
        },
    )

    if dry_run:
        logger.info("Dry-run SpaceClaim script generated: %s", script_file)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, True, None, planned=True)

    if os.getenv("SPACECLAIM_ENABLED", "false").lower() != "true":
        error = "SPACECLAIM_ENABLED is not true; enable it or run with --dry-run"
        logger.error(error)
        return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, False, error)
    if not source_geometry or not Path(source_geometry).is_file():
        error = "SpaceClaim requires a real STEP, Parasolid, or SLDPRT source file; none was produced"
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
    process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bring_process_to_foreground(process.pid)
    stdout, stderr = process.communicate()
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(stdout + "\n" + stderr)
    checks = _spaceclaim_checks(scdoc_file, step_file, named_file, stdout + "\n" + stderr, domain_settings)
    if process.returncode != 0:
        return _result(
            script_file,
            scdoc_file,
            pmdb_file,
            step_file,
            named_file,
            False,
            "SpaceClaim returned non-zero exit code",
            checks=checks,
        )
    check_errors = _spaceclaim_check_errors(checks)
    if check_errors:
        return _result(
            script_file,
            scdoc_file,
            pmdb_file,
            step_file,
            named_file,
            False,
            "SpaceClaim completed but validation failed: " + "; ".join(check_errors),
            checks=checks,
        )
    return _result(script_file, scdoc_file, pmdb_file, step_file, named_file, True, None, checks=checks)


def _render_template(template_name: str, target: Path, context: dict) -> None:
    env = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    env.filters["repr"] = repr
    target.write_text(env.get_template(template_name).render(**context), encoding="utf-8")


def _resolve_executable(value: str) -> str | None:
    if not value:
        return None
    if Path(value).exists():
        return value
    return shutil.which(value)


def _domain_settings(task: SimulationTask, length: float, imitation_info: dict | None) -> dict:
    settings = {
        "enclosure_shape": "box",
        "flow_direction": [1.0, 0.0, 0.0],
        "clearances": {
            "upstream": float(task.domain.upstream_length_ratio) * length,
            "downstream": float(task.domain.downstream_length_ratio) * length,
            "left": float(task.domain.side_length_ratio) * length,
            "right": float(task.domain.side_length_ratio) * length,
            "top": float(task.domain.side_length_ratio) * length,
            "bottom": float(task.domain.side_length_ratio) * length,
        },
        "boundary_names": {
            "inlet": "velocity_inlet",
            "outlet": "pressure_outlet",
            "farfield": "farfield",
            "object_wall": "object_wall",
        },
        "boundary_types": {
            "inlet": "velocity-inlet",
            "outlet": "pressure-outlet",
            "farfield": "wall",
            "object_wall": "wall",
        },
    }
    effective = (imitation_info or {}).get("effective_domain_settings")
    if not isinstance(effective, dict):
        return settings

    shape = effective.get("enclosure_shape")
    if shape in {"box", "cylinder"}:
        settings["enclosure_shape"] = shape
    elif shape is not None:
        settings["enclosure_shape"] = "box"

    if "flow_direction" in effective and effective["flow_direction"] is not None:
        settings["flow_direction"] = _axis_aligned_flow_direction(effective["flow_direction"])

    _merge_numeric_mapping(settings["clearances"], effective.get("clearances"), "clearances")
    _merge_string_mapping(settings["boundary_names"], effective.get("boundary_names"))
    _merge_string_mapping(settings["boundary_types"], effective.get("boundary_types"))
    return settings


def _merge_numeric_mapping(target: dict, source: object, label: str) -> None:
    if source is None:
        return
    if not isinstance(source, Mapping):
        return
    for key in target:
        if key not in source or source[key] is None:
            continue
        value = _finite_float(source[key], f"{label}.{key}")
        if value <= 0:
            raise ValueError(f"{label}.{key} must be finite and positive")
        target[key] = value


def _merge_string_mapping(target: dict, source: object) -> None:
    if source is None:
        return
    if not isinstance(source, Mapping):
        return
    for key in target:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            target[key] = value


def _axis_aligned_flow_direction(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector")
    components = [_finite_float(component, "flow_direction") for component in value]
    magnitudes = [abs(component) for component in components]
    if max(magnitudes) <= 0:
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector")
    axis = max(range(3), key=lambda index: magnitudes[index])
    direction = [0.0, 0.0, 0.0]
    direction[axis] = 1.0 if components[axis] > 0 else -1.0
    return direction


def _finite_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be finite") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _paths(scdoc_file: Path, pmdb_file: Path, step_file: Path, named_file: Path, log_file: Path) -> dict[str, str]:
    return {
        "scdoc_file": str(scdoc_file.resolve()),
        "pmdb_file": str(pmdb_file.resolve()),
        "step_file": str(step_file.resolve()),
        "named_selections_file": str(named_file.resolve()),
        "log_file": str(log_file.resolve()),
    }


def _spaceclaim_checks(scdoc_file: Path, step_file: Path, named_file: Path, log_text: str, domain_settings: dict) -> dict:
    expected_names = domain_settings["boundary_names"]
    log_counts_by_name = {
        name: int(count)
        for name, count in re.findall(r"named_selection:([^\s]+)\s+count=(\d+)", log_text, re.IGNORECASE)
    }
    role_counts = {
        role: log_counts_by_name.get(name)
        for role, name in expected_names.items()
    }
    files = {
        "fluid_domain.scdoc": scdoc_file.is_file(),
        "fluid_domain.step": step_file.is_file(),
        "named_selections.json": named_file.is_file(),
    }
    named_payload = _read_json(named_file)
    return {
        "output_files": files,
        "output_files_ok": all(files.values()),
        "imported_bodies": _last_int(log_text, r"imported_bodies=(\d+)"),
        "boolean_subtract_ok": "boolean_subtract=ok" in log_text or "boolean_subtract=skipped" in log_text,
        "named_selection_counts": role_counts,
        "raw_named_selection_counts": log_counts_by_name,
        "expected_boundary_names": expected_names,
        "named_selections_json_ok": bool(named_payload) and all(name in named_payload for name in expected_names.values()),
    }


def _spaceclaim_check_errors(checks: dict) -> list[str]:
    errors = []
    missing_files = [name for name, exists in checks.get("output_files", {}).items() if not exists]
    if missing_files:
        errors.append("missing output files: " + ", ".join(missing_files))
    if checks.get("imported_bodies") == 0:
        errors.append("source CAD imported zero bodies")
    if checks.get("boolean_subtract_ok") is False:
        errors.append("boolean subtract was not confirmed in spaceclaim.log")
    missing_groups = [
        role
        for role, count in checks.get("named_selection_counts", {}).items()
        if count is not None and count <= 0
    ]
    if missing_groups:
        errors.append("empty named selections: " + ", ".join(missing_groups))
    if checks.get("named_selections_json_ok") is False:
        errors.append("named_selections.json does not contain all expected boundary names")
    return errors


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _last_int(text: str, pattern: str) -> int | None:
    matches = re.findall(pattern, text, re.IGNORECASE)
    return int(matches[-1]) if matches else None


def _result(
    script_file: Path,
    scdoc_file: Path,
    pmdb_file: Path,
    step_file: Path,
    named_file: Path,
    success: bool,
    error: str | None,
    planned: bool = False,
    checks: dict | None = None,
) -> dict:
    return {
        "spaceclaim_script": str(script_file),
        "scdoc_file": None if planned or not scdoc_file.exists() else str(scdoc_file),
        "pmdb_file": None if planned or not pmdb_file.exists() else str(pmdb_file),
        "step_file": None if planned or not step_file.exists() else str(step_file),
        "planned_scdoc_file": str(scdoc_file) if planned else None,
        "planned_pmdb_file": str(pmdb_file) if planned else None,
        "planned_step_file": str(step_file) if planned else None,
        "named_selections_file": str(named_file),
        "spaceclaim_checks": checks or {},
        "success": success,
        "error": error,
    }
