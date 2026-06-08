from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cfd_agent.core.orchestrator import STAGE_ORDER
from cfd_agent.tools.file_tool import project_root, write_json


EXPECTED_BOUNDARIES = {"velocity_inlet", "pressure_outlet", "farfield", "object_wall"}


def diagnose_output(output_dir: str | Path, root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root) if root is not None else project_root()
    output = Path(output_dir)
    if not output.is_absolute():
        output = base / output
    output = output.resolve()

    pipeline = _read_json(output / "pipeline_state.json")
    quality = _read_json(output / "meshing" / "mesh_quality_report.json")
    smoke = _read_json(base / "outputs" / "deployment_check" / "software_smoke_check.json")
    logs = _read_logs(output)
    issues: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    failed_stage = _failed_stage(pipeline)
    issues.extend(_pipeline_issues(pipeline, output))
    issues.extend(_software_smoke_issues(smoke))
    issues.extend(_mesh_quality_issues(quality))
    issues.extend(_file_pair_issues(output))
    issues.extend(_log_pattern_issues(logs))

    if quality:
        for key in ("cell_count", "max_skewness", "min_orthogonal_quality", "boundary_zone_names"):
            if key in quality:
                metrics[key] = quality[key]

    report = {
        "ok": not issues,
        "output_dir": str(output),
        "failed_stage": failed_stage,
        "issues": _dedupe_issues(issues),
        "metrics": metrics,
        "sources": {
            "pipeline_state": str(output / "pipeline_state.json"),
            "mesh_quality_report": str(output / "meshing" / "mesh_quality_report.json"),
            "software_smoke_check": str(base / "outputs" / "deployment_check" / "software_smoke_check.json"),
            "logs": sorted(str(path) for path in logs),
        },
    }
    target = output / "diagnostics"
    report["report_file"] = write_json(target / "diagnostic_report.json", report)
    markdown_file = target / "diagnostic_report.md"
    markdown_file.write_text(_markdown_report(report), encoding="utf-8")
    report["markdown_file"] = str(markdown_file)
    return report


def _failed_stage(pipeline: dict[str, Any]) -> str | None:
    stage_outputs = pipeline.get("stage_outputs", {})
    if isinstance(stage_outputs, dict):
        for stage in STAGE_ORDER:
            info = stage_outputs.get(stage)
            if isinstance(info, dict) and info.get("success") is False:
                return stage
    stage = pipeline.get("stage")
    return str(stage) if pipeline.get("status") == "failed" and stage else None


def _pipeline_issues(pipeline: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    issues = []
    for error in _as_list(pipeline.get("errors")):
        issues.append(
            _issue(
                "pipeline_error",
                "error",
                "Pipeline reported an error",
                str(error),
                "Open the failed stage log and rerun from that stage after correcting the upstream input or software setting.",
                output / "pipeline_state.json",
            )
        )
    stage_outputs = pipeline.get("stage_outputs", {})
    if isinstance(stage_outputs, dict):
        for stage, info in stage_outputs.items():
            if isinstance(info, dict) and info.get("success") is False:
                evidence = info.get("error") or f"{stage} returned success=false"
                issues.append(
                    _issue(
                        f"{stage}_failed",
                        "error",
                        f"{stage} failed",
                        str(evidence),
                        f"Review the {stage} output and rerun with from_stage='{stage}' after fixing the cause.",
                        output / "pipeline_state.json",
                    )
                )
    return issues


def _software_smoke_issues(smoke: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []
    checks = smoke.get("checks", {})
    if not isinstance(checks, dict):
        return issues
    for name, check in checks.items():
        if isinstance(check, dict) and check.get("ok") is False:
            issues.append(
                _issue(
                    "software_smoke_failed",
                    "error",
                    f"{name} smoke check failed",
                    str(check.get("message") or check.get("error") or "Smoke check failed."),
                    "Fix the executable path or license/startup issue in one-click deployment, then run the software smoke check again.",
                    check.get("log_file"),
                )
            )
    return issues


def _mesh_quality_issues(quality: dict[str, Any]) -> list[dict[str, Any]]:
    if not quality:
        return []
    issues = []
    passed = quality.get("passed")
    if passed is None:
        passed = quality.get("quality_ok")
    if passed is False:
        evidence = _quality_evidence(quality)
        issues.append(
            _issue(
                "mesh_quality_failed",
                "error",
                "Mesh quality failed",
                evidence,
                "Reduce global/near-body mesh size, improve enclosure scale, or rerun mesh imitation from a validated reference.",
                quality.get("quality_report_file") or "meshing/mesh_quality_report.json",
            )
        )
    boundary_names = set(_as_list(quality.get("boundary_zone_names")))
    missing = set(_as_list(quality.get("missing_boundary_zones"))) or (EXPECTED_BOUNDARIES - boundary_names if boundary_names else set())
    if missing:
        issues.append(
            _issue(
                "missing_boundary_zone",
                "error",
                "Boundary zone names are incomplete",
                "Missing: " + ", ".join(sorted(str(name) for name in missing)),
                "Regenerate the SpaceClaim named selections and verify inlet, outlet, farfield, and object_wall before meshing.",
                quality.get("quality_report_file") or "meshing/mesh_quality_report.json",
            )
        )
    if quality.get("boundary_layer_generated") is False:
        issues.append(
            _issue(
                "boundary_layer_missing",
                "warning",
                "Boundary layer was not generated",
                "boundary_layer_generated=false",
                "Check object_wall naming and boundary-layer controls in Fluent Meshing.",
                quality.get("quality_report_file") or "meshing/mesh_quality_report.json",
            )
        )
    return issues


def _file_pair_issues(output: Path) -> list[dict[str, Any]]:
    issues = []
    case = output / "fluent" / "case.cas.h5"
    paired_data = output / "fluent" / "case.dat.h5"
    solver_data = output / "fluent" / "data.dat.h5"
    if case.exists() and not paired_data.exists():
        issues.append(
            _issue(
                "missing_fluent_case_data_pair",
                "error",
                "Fluent GUI case/data pair is incomplete",
                f"{case.name} exists but {paired_data.name} is missing.",
                "Rerun Fluent Solver or copy/save the paired data as case.dat.h5 before opening the case interactively.",
                case,
            )
        )
    if case.exists() and not solver_data.exists():
        issues.append(
            _issue(
                "missing_solver_data",
                "warning",
                "Solver data file is missing",
                f"{case.name} exists but {solver_data.name} is missing.",
                "Run the solver stage until data.dat.h5 is written.",
                case,
            )
        )
    return issues


def _log_pattern_issues(logs: dict[Path, str]) -> list[dict[str, Any]]:
    rules = [
        (
            re.compile(r"executable not found|is not set|launch failed", re.IGNORECASE),
            "software_launch_error",
            "error",
            "Software launch or path error",
            "Set the correct executable path in one-click deployment and rerun the smoke check.",
        ),
        (
            re.compile(r"case\.dat\.h5.*not found|not found.*case\.dat\.h5", re.IGNORECASE),
            "missing_fluent_case_data_pair",
            "error",
            "Fluent GUI case/data pair is incomplete",
            "Rerun Fluent Solver or save the paired case.dat.h5 file.",
        ),
        (
            re.compile(r"fluid_domain\.(step|scdoc).*not found|requires a real SpaceClaim", re.IGNORECASE),
            "missing_spaceclaim_domain",
            "error",
            "SpaceClaim fluid-domain output is missing",
            "Rerun SpaceClaim and verify fluid_domain.scdoc, fluid_domain.step, and named_selections.json.",
        ),
        (
            re.compile(r"maximum skewness|min(?:imum)? orthogonal quality|mesh quality", re.IGNORECASE),
            "mesh_quality_log_signal",
            "warning",
            "Mesh quality signal found in logs",
            "Open mesh_quality_report.json and adjust mesh controls if limits are exceeded.",
        ),
    ]
    issues = []
    for path, text in logs.items():
        for pattern, code, severity, title, recommendation in rules:
            match = pattern.search(text)
            if match:
                issues.append(_issue(code, severity, title, _excerpt(text, match.start()), recommendation, path))
    return issues


def _read_logs(output: Path) -> dict[Path, str]:
    candidates = [
        output / "workflow.log",
        output / "geometry.log",
        output / "mesh.log",
        output / "fluent.log",
        output / "solidworks" / "create_model.log",
        output / "spaceclaim" / "spaceclaim.log",
        output / "meshing" / "fluent_meshing.log",
        output / "mesh_imitation" / "fluent_reference_analysis.log",
        output / "domain_imitation" / "spaceclaim_reference_analysis.log",
        output / "fluent" / "fluent.log",
    ]
    logs = {}
    for path in candidates:
        if path.is_file():
            logs[path.resolve()] = _read_text(path)
    return logs


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _quality_evidence(quality: dict[str, Any]) -> str:
    parts = []
    for key in ("cell_count", "max_skewness", "min_orthogonal_quality", "boundary_layer_generated"):
        if key in quality:
            parts.append(f"{key}={quality[key]}")
    limits = quality.get("limits")
    if limits:
        parts.append(f"limits={limits}")
    return "; ".join(parts) or "mesh_quality_report indicates failure"


def _excerpt(text: str, index: int, radius: int = 120) -> str:
    start = max(index - radius, 0)
    end = min(index + radius, len(text))
    return " ".join(text[start:end].split())


def _issue(code: str, severity: str, title: str, evidence: str, recommendation: str, source: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "recommendation": recommendation,
        "source": str(source) if source is not None else None,
    }


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for issue in issues:
        key = (issue["code"], issue["evidence"], issue["source"])
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# CFD Agent Diagnostic Report",
        "",
        f"- Output: `{report['output_dir']}`",
        f"- Status: {'OK' if report['ok'] else 'Issues found'}",
        f"- Failed stage: `{report.get('failed_stage') or 'unknown'}`",
        "",
        "## Issues",
    ]
    if not report["issues"]:
        lines.append("")
        lines.append("No issues detected from the available logs and state files.")
    for issue in report["issues"]:
        lines.extend(
            [
                "",
                f"### {issue['title']}",
                "",
                f"- Severity: `{issue['severity']}`",
                f"- Code: `{issue['code']}`",
                f"- Evidence: {issue['evidence']}",
                f"- Recommendation: {issue['recommendation']}",
                f"- Source: `{issue['source']}`",
            ]
        )
    if report["metrics"]:
        lines.extend(["", "## Mesh Metrics", ""])
        for key, value in report["metrics"].items():
            lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)
