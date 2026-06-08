from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, template_dir, write_json
from cfd_agent.tools.process_ui import bring_process_to_foreground


SUPPORTED_DOMAIN_REFERENCE_SUFFIXES = (".scdoc", ".step", ".stp")
STANDARD_BOUNDARIES = {
    "inlet": {"name": "velocity_inlet", "type": "velocity-inlet"},
    "outlet": {"name": "pressure_outlet", "type": "pressure-outlet"},
    "farfield": {"name": "farfield", "type": "wall"},
    "object_wall": {"name": "object_wall", "type": "wall"},
}
SUPPORTED_BOUNDARY_TYPES = {
    "inlet": {"velocity-inlet", "mass-flow-inlet", "pressure-inlet"},
    "outlet": {"pressure-outlet", "outflow"},
    "farfield": {"wall", "pressure-far-field", "symmetry"},
    "object_wall": {"wall"},
}
REQUIRED_CLEARANCE_DIRECTIONS = ("upstream", "downstream", "left", "right", "top", "bottom")
SUPPORTED_ENCLOSURE_SHAPES = {"box", "cylinder"}
DEFAULT_SPACECLAIM_ANALYSIS_TIMEOUT = 600.0


def supported_domain_reference_file(path: str | Path) -> bool:
    return str(path).lower().endswith(SUPPORTED_DOMAIN_REFERENCE_SUFFIXES)


def analyze_reference_domain(task: SimulationTask, output_dir: str | Path, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "domain_imitation")
    profile_file = root / "domain_reference_profile.json"
    scaled_file = root / "scaled_domain_settings.json"
    comparison_file = root / "domain_imitation_comparison.json"
    log_file = root / "spaceclaim_reference_analysis.log"
    script_file = root / "analyze_reference_domain.py"
    result_file = root / "spaceclaim_reference_analysis_result.json"
    config = task.domain_imitation

    if not config.enabled:
        return _analysis_result(profile_file, scaled_file, comparison_file, log_file, True, True, {}, {}, None)

    reference = Path(config.reference_file or "").expanduser().resolve()
    if not reference.is_file():
        return _analysis_result(
            profile_file,
            scaled_file,
            comparison_file,
            log_file,
            False,
            False,
            {},
            {},
            f"reference domain file not found: {reference}",
        )
    if not supported_domain_reference_file(reference):
        return _analysis_result(
            profile_file,
            scaled_file,
            comparison_file,
            log_file,
            False,
            False,
            {},
            {},
            f"unsupported SpaceClaim reference domain file: {reference}; use .scdoc, .step, or .stp",
        )

    new_length = get_characteristic_length(task)
    if dry_run:
        profile = _planned_domain_profile(task, reference, new_length)
        log_file.write_text(
            "Dry-run: SpaceClaim reference analysis was not launched; planned domain imitation settings were generated.\n",
            encoding="utf-8",
        )
    else:
        _render_analysis_script(reference, result_file, script_file, config.manual_flow_direction)
        result_file.unlink(missing_ok=True)
        executable = _resolve_spaceclaim_executable(os.getenv("SPACECLAIM_EXECUTABLE", ""))
        if not executable:
            return _analysis_result(
                profile_file,
                scaled_file,
                comparison_file,
                log_file,
                False,
                False,
                {},
                {},
                "SpaceClaim executable not found; set SPACECLAIM_EXECUTABLE to a valid SpaceClaim.exe path",
            )
        command = [
            str(executable),
            "/Splash=False",
            "/Welcome=False",
            f"/RunScript={script_file.resolve()}",
            "/ScriptAPI=22",
            "/ExitAfterScript=True",
        ]
        try:
            timeout = _analysis_timeout()
            process = subprocess.Popen(
                command,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            bring_process_to_foreground(process.pid)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        stdout, stderr = "", "SpaceClaim process did not exit after terminate and kill."
                _write_process_log(log_file, stdout, stderr)
                return _analysis_result(
                    profile_file,
                    scaled_file,
                    comparison_file,
                    log_file,
                    False,
                    False,
                    {},
                    {},
                    f"SpaceClaim reference analysis timed out after {timeout:g} seconds; inspect {log_file}",
                )
        except (OSError, ValueError) as exc:
            return _analysis_result(
                profile_file,
                scaled_file,
                comparison_file,
                log_file,
                False,
                False,
                {},
                {},
                f"could not launch SpaceClaim reference analysis: {exc}",
            )
        _write_process_log(log_file, stdout, stderr)
        if process.returncode != 0:
            return _analysis_result(
                profile_file,
                scaled_file,
                comparison_file,
                log_file,
                False,
                False,
                {},
                {},
                f"SpaceClaim reference analysis returned exit code {process.returncode}; inspect {log_file}",
            )
        if not result_file.is_file():
            return _analysis_result(
                profile_file,
                scaled_file,
                comparison_file,
                log_file,
                False,
                False,
                {},
                {},
                f"SpaceClaim completed but did not produce result JSON: {result_file}; inspect {log_file}",
            )
        try:
            profile = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _analysis_result(
                profile_file,
                scaled_file,
                comparison_file,
                log_file,
                False,
                False,
                {},
                {},
                f"SpaceClaim result JSON could not be read: {exc}; inspect {result_file}",
            )
        schema_error = _validate_analysis_profile(profile)
        if schema_error:
            return _analysis_result(profile_file, scaled_file, comparison_file, log_file, False, False, {}, {}, schema_error)
        if not profile["success"]:
            detail = profile.get("error")
            error = detail if isinstance(detail, str) and detail.strip() else "SpaceClaim could not confidently analyze the reference domain"
            return _analysis_result(profile_file, scaled_file, comparison_file, log_file, False, False, profile, {}, error)
        profile["reference_file"] = str(reference)
        if not profile.get("flow_direction"):
            if config.manual_flow_direction:
                profile["flow_direction"] = _dominant_axis_direction(config.manual_flow_direction)
                profile.setdefault("warnings", []).append(
                    "Detected flow direction was missing; used domain_imitation.manual_flow_direction."
                )
                if profile["flow_direction"] != list(config.manual_flow_direction):
                    profile["warnings"].append(
                        f"Flow direction was not axis-aligned; using dominant axis direction {profile['flow_direction']}."
                    )
            else:
                write_json(profile_file, profile)
                return _analysis_result(
                    profile_file,
                    scaled_file,
                    comparison_file,
                    log_file,
                    False,
                    False,
                    profile,
                    {},
                    "flow direction could not be detected; provide domain_imitation.manual_flow_direction",
                )
        else:
            _coerce_profile_flow_direction_to_axis(profile)

    try:
        _coerce_profile_flow_direction_to_axis(profile)
        scaled = scale_domain_profile(profile, new_length)
    except ValueError as exc:
        write_json(profile_file, profile)
        return _analysis_result(profile_file, scaled_file, comparison_file, log_file, False, False, profile, {}, str(exc))
    write_json(profile_file, profile)
    write_json(scaled_file, scaled)
    return _analysis_result(profile_file, scaled_file, comparison_file, log_file, True, False, profile, scaled, None)


def map_boundary_roles(roles: dict) -> dict:
    roles = roles if isinstance(roles, dict) else {}
    mapped = {}
    used_names = set()
    standard_name_roles = {value["name"]: role for role, value in STANDARD_BOUNDARIES.items()}
    for role, fallback in STANDARD_BOUNDARIES.items():
        reference = roles.get(role)
        reference = reference if isinstance(reference, dict) else {}
        reference_name = _valid_text(reference.get("name"))
        if (
            not reference_name
            or reference_name in used_names
            or standard_name_roles.get(reference_name, role) != role
        ):
            reference_name = fallback["name"]
        used_names.add(reference_name)
        reference_type = reference.get("type")
        mapped[role] = {
            "name": reference_name,
            "type": reference_type
            if isinstance(reference_type, str) and reference_type in SUPPORTED_BOUNDARY_TYPES[role]
            else fallback["type"],
        }
    return mapped


def scale_domain_profile(profile: dict, new_characteristic_length: float) -> dict:
    reference_length = _finite_positive(
        profile.get("reference_characteristic_length"),
        "reference and new characteristic lengths must be finite positive numbers",
    )
    new_length = _finite_positive(
        new_characteristic_length,
        "reference and new characteristic lengths must be finite positive numbers",
    )
    ratios = profile.get("clearance_ratios")
    if not isinstance(ratios, dict) or set(ratios) != set(REQUIRED_CLEARANCE_DIRECTIONS):
        raise ValueError("six finite positive directional clearance ratios are required")
    normalized_ratios = {
        direction: _finite_positive(ratios[direction], "six finite positive directional clearance ratios are required")
        for direction in REQUIRED_CLEARANCE_DIRECTIONS
    }
    flow_direction = _normalized_flow_direction(profile.get("flow_direction"))
    mapped_boundaries = map_boundary_roles(profile.get("boundary_roles", {}))
    enclosure_shape = profile.get("enclosure_shape", "box")
    warnings = list(profile.get("warnings") or [])
    if not isinstance(enclosure_shape, str) or enclosure_shape not in SUPPORTED_ENCLOSURE_SHAPES:
        warnings.append(f"Unknown enclosure shape {enclosure_shape!r}; using 'box'.")
        enclosure_shape = "box"
    axis_direction = _dominant_axis_direction(flow_direction)
    if axis_direction != flow_direction:
        warnings.append(f"Flow direction was not axis-aligned; using dominant axis direction {axis_direction}.")
        flow_direction = axis_direction
    scale_ratio = new_length / reference_length
    if not math.isfinite(scale_ratio):
        raise ValueError("scale_ratio must be finite")
    clearances = {direction: value * new_length for direction, value in normalized_ratios.items()}
    if not all(math.isfinite(value) for value in clearances.values()):
        raise ValueError("absolute clearances must be finite")

    return {
        "scale_ratio": scale_ratio,
        "reference_characteristic_length": reference_length,
        "new_characteristic_length": new_length,
        "effective_domain_settings": {
            "enclosure_shape": enclosure_shape,
            "flow_direction": flow_direction,
            "clearances": clearances,
            "clearance_ratios": normalized_ratios,
            "boundary_names": {role: value["name"] for role, value in mapped_boundaries.items()},
            "boundary_types": {role: value["type"] for role, value in mapped_boundaries.items()},
        },
        "warnings": warnings,
    }


def write_domain_comparison(imitation_info: dict, domain_info: dict, output_dir: str | Path) -> Path | None:
    if imitation_info.get("skipped") or imitation_info.get("success") is False:
        return None
    profile = imitation_info.get("profile", {})
    scaled = imitation_info.get("scaled_settings", {})
    warnings = list(dict.fromkeys([*(profile.get("warnings") or []), *(scaled.get("warnings") or [])]))
    payload = {
        "reference": {
            "reference_file": profile.get("reference_file"),
            "enclosure_shape": profile.get("enclosure_shape"),
        },
        "scale_ratio": scaled.get("scale_ratio"),
        "requested_effective_settings": imitation_info.get("effective_domain_settings", {}),
        "generated": {
            "scdoc_file": domain_info.get("scdoc_file") or domain_info.get("planned_scdoc_file"),
            "step_file": domain_info.get("step_file") or domain_info.get("planned_step_file"),
            "named_selections_file": domain_info.get("named_selections_file"),
        },
        "warnings": warnings,
    }
    path = ensure_dir(Path(output_dir) / "domain_imitation") / "domain_imitation_comparison.json"
    write_json(path, payload)
    return path


def _valid_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _finite_positive(value: object, message: str) -> float:
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(message)
    return number


def _normalized_flow_direction(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(isinstance(component, bool) for component in value):
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector")
    try:
        components = [float(component) for component in value]
    except (TypeError, ValueError):
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector") from None
    if not all(math.isfinite(component) for component in components):
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector")
    scale = max(abs(component) for component in components)
    if scale == 0:
        raise ValueError("flow_direction must be a three-dimensional finite non-zero vector")
    scaled_components = [component / scale for component in components]
    scaled_norm = math.sqrt(sum(component * component for component in scaled_components))
    return [component / scaled_norm for component in scaled_components]


def _dominant_axis_direction(value: object) -> list[float]:
    direction = _normalized_flow_direction(value)
    axis = max(range(3), key=lambda index: abs(direction[index]))
    sign = 1.0 if direction[axis] > 0 else -1.0
    result = [0.0, 0.0, 0.0]
    result[axis] = sign
    return result


def _validate_analysis_profile(profile: object) -> str | None:
    if not isinstance(profile, dict):
        return "SpaceClaim result JSON must be an object"
    if not isinstance(profile.get("success"), bool):
        return "SpaceClaim result success must be a boolean"
    warnings = profile.get("warnings", [])
    if not isinstance(warnings, list):
        return "SpaceClaim result warnings must be a list"
    return None


def _planned_domain_profile(task: SimulationTask, reference: Path, characteristic_length: float) -> dict:
    side_ratio = float(task.domain.side_length_ratio)
    requested_direction = list(task.domain_imitation.manual_flow_direction or [1.0, 0.0, 0.0])
    flow_direction = _dominant_axis_direction(requested_direction)
    warnings = ["Dry-run: SpaceClaim reference domain analysis was not launched."]
    if flow_direction != requested_direction:
        warnings.append(f"Flow direction was not axis-aligned; using dominant axis direction {flow_direction}.")
    return {
        "success": True,
        "reference_file": str(reference),
        "reference_characteristic_length": float(characteristic_length),
        "detection_method": "dry_run_planned_box_profile",
        "enclosure_shape": "box",
        "clearance_ratios": {
            "upstream": float(task.domain.upstream_length_ratio),
            "downstream": float(task.domain.downstream_length_ratio),
            "left": side_ratio,
            "right": side_ratio,
            "top": side_ratio,
            "bottom": side_ratio,
        },
        "flow_direction": flow_direction,
        "boundary_roles": STANDARD_BOUNDARIES,
        "warnings": warnings,
    }


def _coerce_profile_flow_direction_to_axis(profile: dict) -> None:
    original = profile.get("flow_direction")
    axis_direction = _dominant_axis_direction(original)
    if axis_direction != original:
        profile["flow_direction"] = axis_direction
        warnings = profile.setdefault("warnings", [])
        warning = f"Flow direction was not axis-aligned; using dominant axis direction {axis_direction}."
        if warning not in warnings:
            warnings.append(warning)


def _render_analysis_script(
    reference: Path,
    result_file: Path,
    script_file: Path,
    manual_flow_direction: list[float] | None = None,
) -> None:
    environment = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    rendered = environment.get_template("spaceclaim_analyze_reference_domain.py.j2").render(
        reference_file=str(reference),
        result_file=str(result_file.resolve()),
        manual_flow_direction=repr(manual_flow_direction),
    )
    script_file.write_text(rendered, encoding="utf-8")


def _resolve_spaceclaim_executable(value: str) -> str | None:
    if not value:
        return None
    expanded = Path(value).expanduser()
    if expanded.is_file():
        return str(expanded)
    return shutil.which(value)


def _analysis_timeout() -> float:
    value = float(os.getenv("SPACECLAIM_ANALYSIS_TIMEOUT", str(DEFAULT_SPACECLAIM_ANALYSIS_TIMEOUT)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("SPACECLAIM_ANALYSIS_TIMEOUT must be a finite positive number")
    return value


def _write_process_log(path: Path, stdout: str | None, stderr: str | None) -> None:
    path.write_text((stdout or "") + "\n" + (stderr or ""), encoding="utf-8")


def _analysis_result(
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
        "effective_domain_settings": scaled.get("effective_domain_settings", {}),
        "profile_file": str(profile_file),
        "scaled_settings_file": str(scaled_file),
        "comparison_file": str(comparison_file),
        "log_file": str(log_file),
        "error": error,
    }
