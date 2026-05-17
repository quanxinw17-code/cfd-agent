from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.tools.file_tool import ensure_dir


def run_fluent(journal_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    logger = configure_task_logger("cfd_agent.solver", output_dir, "fluent.log")
    output = ensure_dir(Path(output_dir) / "fluent")
    case_file = output / "case.cas.h5"
    data_file = output / "data.dat.h5"
    paired_data_file = output / "case.dat.h5"
    log_file = output / "fluent.log"

    if dry_run:
        logger.info("Dry-run: Fluent execution skipped")
        return {
            "case_file": None,
            "planned_case_file": str(case_file),
            "data_file": None,
            "planned_data_file": str(data_file),
            "planned_paired_data_file": str(paired_data_file),
            "log_file": str(log_file),
            "success": True,
            "skipped": True,
            "error": None,
        }

    if os.getenv("FLUENT_SOLVER_ENABLED", "false").lower() != "true":
        error = "FLUENT_SOLVER_ENABLED is not true; enable it or run with --dry-run"
        logger.error(error)
        return {"case_file": None, "data_file": None, "log_file": str(log_file), "success": False, "error": error}

    fluent_executable = os.getenv("FLUENT_EXECUTABLE", "")
    if not fluent_executable:
        error = "FLUENT_EXECUTABLE is not set"
        logger.error(error)
        return {"case_file": None, "data_file": None, "log_file": str(log_file), "success": False, "error": error}

    resolved = shutil.which(fluent_executable) if not Path(fluent_executable).exists() else fluent_executable
    if not resolved:
        error = f"Fluent executable not found: {fluent_executable}"
        logger.error(error)
        return {"case_file": None, "data_file": None, "log_file": str(log_file), "success": False, "error": error}

    command = [str(resolved), "3ddp", "-g", "-i", str(Path(journal_info["solve_journal"]).resolve())]
    logger.info("Running Fluent command: %s", " ".join(command))
    with open(log_file, "a", encoding="utf-8") as handle:
        completed = subprocess.run(command, cwd=output, text=True, stdout=handle, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        return {"case_file": None, "data_file": None, "log_file": str(log_file), "success": False, "error": "Fluent returned non-zero exit code"}

    _export_solver_csvs(log_file, Path(output_dir) / "postprocess")
    if data_file.exists():
        shutil.copy2(data_file, paired_data_file)
    return {"case_file": str(case_file), "data_file": str(data_file), "paired_data_file": str(paired_data_file), "log_file": str(log_file), "success": True, "error": None}


def _export_solver_csvs(log_file: Path, post_dir: Path) -> None:
    post_dir.mkdir(parents=True, exist_ok=True)
    raw = log_file.read_bytes()
    text = raw.decode("utf-16", errors="ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="ignore")

    residual_rows = []
    residual_pattern = re.compile(
        r"^\s*(\d+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+\d+:\d+:\d+\s+\d+\s*$",
        re.M,
    )
    for match in residual_pattern.finditer(text):
        iteration = int(match.group(1))
        residual_rows.append([iteration, *[match.group(index) for index in range(2, 8)]])
    by_iteration = {row[0]: row for row in residual_rows}
    residual_rows = [by_iteration[index] for index in sorted(by_iteration)]
    with open(post_dir / "residuals.csv", "w", encoding="utf-8", newline="") as handle:
        handle.write("iteration,continuity,x_velocity,y_velocity,z_velocity,k,omega\n")
        for row in residual_rows:
            handle.write(",".join(str(value) for value in row) + "\n")

    force_rows = []
    for direction, label in [((1, 0, 0), "drag_x"), ((0, 1, 0), "lift_y")]:
        pattern = rf"Forces - Direction Vector \({direction[0]} {direction[1]} {direction[2]}\).*?^Net\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)"
        match = re.search(pattern, text, re.S | re.M)
        if match:
            force_rows.append([residual_rows[-1][0] if residual_rows else "", label, *direction, *[match.group(index) for index in range(1, 7)], "wall-6"])
    with open(post_dir / "forces.csv", "w", encoding="utf-8", newline="") as handle:
        handle.write("iteration,quantity,direction_x,direction_y,direction_z,pressure_N,viscous_N,total_N,pressure_coefficient,viscous_coefficient,total_coefficient,zone\n")
        for row in force_rows:
            handle.write(",".join(str(value) for value in row) + "\n")
