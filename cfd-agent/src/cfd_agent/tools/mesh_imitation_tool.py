from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from cfd_agent.core.models import MeshImitationConfig, SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, project_root, write_json


SUPPORTED_REFERENCE_SUFFIXES = (".msh", ".msh.h5", ".cas", ".cas.h5")
LENGTH_SETTINGS = {
    "global_size",
    "near_body_size",
    "first_layer_height",
    "boundary_layer_total_thickness",
    "curvature_min_size",
    "proximity_min_size",
}


def supported_reference_file(path: str | Path) -> bool:
    lowered = str(path).lower()
    return any(lowered.endswith(suffix) for suffix in SUPPORTED_REFERENCE_SUFFIXES)


def effective_reference_length(profile: dict, config: MeshImitationConfig) -> float:
    value = profile.get("reference_characteristic_length") or config.reference_characteristic_length
    if value is None or float(value) <= 0:
        raise ValueError("reference characteristic length could not be detected; provide a manual value")
    return float(value)


def scale_reference_profile(profile: dict, new_characteristic_length: float, reference_characteristic_length: float | None = None) -> dict:
    reference_length = float(reference_characteristic_length or profile.get("reference_characteristic_length") or 0)
    if reference_length <= 0:
        raise ValueError("reference characteristic length must be greater than 0")
    if new_characteristic_length <= 0:
        raise ValueError("new characteristic length must be greater than 0")
    ratio = new_characteristic_length / reference_length
    settings = {}
    for name, value in profile.get("mesh_settings", {}).items():
        if value is None:
            continue
        settings[name] = float(value) * ratio if name in LENGTH_SETTINGS else value
    return {
        "scale_mode": "characteristic_length",
        "reference_characteristic_length": reference_length,
        "new_characteristic_length": float(new_characteristic_length),
        "scale_ratio": ratio,
        "effective_mesh_settings": settings,
    }


def analyze_reference_mesh(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "mesh_imitation")
    profile_file = root / "mesh_reference_profile.json"
    scaled_file = root / "scaled_mesh_settings.json"
    comparison_file = root / "mesh_imitation_comparison.json"
    log_file = root / "fluent_reference_analysis.log"
    config = task.mesh_imitation

    if not config.enabled:
        return _result(profile_file, scaled_file, comparison_file, log_file, True, True, {}, {}, None)
    reference = Path(config.reference_file or "").expanduser().resolve()
    if not reference.is_file():
        return _result(profile_file, scaled_file, comparison_file, log_file, False, False, {}, {}, f"reference mesh file not found: {reference}")
    if not supported_reference_file(reference):
        return _result(profile_file, scaled_file, comparison_file, log_file, False, False, {}, {}, f"unsupported Fluent reference file: {reference}")

    if dry_run:
        profile = {
            "reference_file": str(reference),
            "reference_characteristic_length": config.reference_characteristic_length,
            "detection_method": "manual_fallback" if config.reference_characteristic_length else "planned_fluent_object_wall_bbox",
            "mesh_settings": {},
            "warnings": ["Dry-run: Fluent reference analysis was not launched."],
        }
    else:
        runner_result_file = root / "fluent_reference_analysis_result.json"
        runner_config_file = root / "fluent_reference_analysis_config.json"
        write_json(
            runner_config_file,
            {
                "reference_file": str(reference),
                "result_file": str(runner_result_file.resolve()),
                "processor_count": int(os.getenv("FLUENT_PROCESSOR_COUNT", "1")),
            },
        )
        runner = project_root() / "scripts" / "analyze_fluent_reference_mesh.py"
        env = runner_environment()
        ansys_root = str(Path(env.get("AWP_ROOT221", r"D:\Program Files\ANSYS Inc\v221")))
        env["AWP_ROOT221"] = ansys_root
        env["AWP_ROOT222"] = ansys_root
        completed = subprocess.run(
            [sys.executable, str(runner), str(runner_config_file.resolve())],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=600,
        )
        log_file.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
        profile = _read_json(runner_result_file)
        if completed.returncode != 0 or not profile.get("success"):
            error = profile.get("error") or f"Fluent reference analysis returned exit code {completed.returncode}"
            return _result(profile_file, scaled_file, comparison_file, log_file, False, False, profile, {}, error)

    try:
        reference_length = effective_reference_length(profile, config)
    except ValueError as exc:
        write_json(profile_file, profile)
        return _result(profile_file, scaled_file, comparison_file, log_file, False, False, profile, {}, str(exc))
    profile["reference_characteristic_length"] = reference_length
    _add_estimated_settings(profile, task)
    scaled = scale_reference_profile(profile, get_characteristic_length(task), reference_length)
    effective = task.mesh.model_dump()
    effective.update(scaled["effective_mesh_settings"])
    scaled["effective_mesh_settings"] = effective
    write_json(profile_file, profile)
    write_json(scaled_file, scaled)
    return _result(profile_file, scaled_file, comparison_file, log_file, True, False, profile, scaled, None)


def write_mesh_comparison(imitation_info: dict, mesh_info: dict, output_dir: str | Path) -> Path | None:
    if imitation_info.get("skipped") or imitation_info.get("success") is False:
        return None
    reference = imitation_info.get("profile", {})
    generated = mesh_info.get("quality_report", {})
    reference_cells = reference.get("cell_count")
    generated_cells = generated.get("cell_count")
    payload = {
        "reference_file": reference.get("reference_file"),
        "scale_ratio": imitation_info.get("scaled_settings", {}).get("scale_ratio"),
        "requested_effective_mesh_settings": imitation_info.get("effective_mesh_settings", {}),
        "reference": {
            "cell_count": reference_cells,
            "min_orthogonal_quality": reference.get("min_orthogonal_quality"),
            "max_skewness": reference.get("max_skewness"),
            "boundary_zone_names": reference.get("boundary_zone_names", []),
        },
        "generated": {
            "cell_count": generated_cells,
            "min_orthogonal_quality": generated.get("min_orthogonal_quality"),
            "max_skewness": generated.get("max_skewness"),
            "boundary_zone_names": generated.get("boundary_zone_names", []),
            "boundary_layer_generated": generated.get("boundary_layer_generated"),
        },
        "cell_count_ratio": generated_cells / reference_cells if reference_cells and generated_cells else None,
    }
    path = ensure_dir(Path(output_dir) / "mesh_imitation") / "mesh_imitation_comparison.json"
    write_json(path, payload)
    return path


def _add_estimated_settings(profile: dict, task: SimulationTask) -> None:
    settings = profile.setdefault("mesh_settings", {})
    length = float(profile["reference_characteristic_length"])
    cell_count = int(profile.get("cell_count") or 0)
    divisions = max(cell_count ** (1 / 3), 20) if cell_count else 20
    settings.setdefault("global_size", length / divisions)
    settings.setdefault("near_body_size", settings["global_size"] / 2)
    for name in ("first_layer_height", "layers", "growth_rate", "boundary_layer_enabled"):
        settings.setdefault(name, getattr(task.mesh, name))
    profile.setdefault("estimated_fields", []).extend(["global_size", "near_body_size"])


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def runner_environment() -> dict[str, str]:
    env = os.environ.copy()
    source = str((project_root() / "src").resolve())
    existing = [
        str((project_root() / value).resolve()) if not Path(value).is_absolute() else value
        for value in env.get("PYTHONPATH", "").split(os.pathsep)
        if value
    ]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys([source, *existing]))
    return env


def _result(
    profile_file: Path,
    scaled_file: Path,
    comparison_file: Path,
    log_file: Path,
    success: bool,
    skipped: bool,
    profile: dict,
    scaled: dict,
    error: str | None,
) -> dict:
    return {
        "enabled": not skipped,
        "success": success,
        "skipped": skipped,
        "profile": profile,
        "scaled_settings": scaled,
        "effective_mesh_settings": scaled.get("effective_mesh_settings", {}),
        "profile_file": str(profile_file),
        "scaled_settings_file": str(scaled_file),
        "comparison_file": str(comparison_file),
        "log_file": str(log_file),
        "error": error,
    }
