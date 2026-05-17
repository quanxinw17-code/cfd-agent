from __future__ import annotations

import csv
from pathlib import Path

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.file_tool import ensure_dir


def postprocess_results(task: SimulationTask, solver_info: dict, output_dir: str, dry_run: bool = False) -> dict:
    logger = configure_task_logger("cfd_agent.postprocess", output_dir, "postprocess.log")
    output = ensure_dir(Path(output_dir) / "postprocess")
    residuals = output / "residuals.csv"
    forces = output / "forces.csv"

    metrics = {"drag_coefficient": None, "lift_coefficient": None}
    if forces.exists():
        with open(forces, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            last = rows[-1]
            metrics["drag_coefficient"] = _optional_float(last.get("drag_coefficient"))
            metrics["lift_coefficient"] = _optional_float(last.get("lift_coefficient"))

    logger.info("Postprocess completed; dry_run=%s, residuals_exists=%s, forces_exists=%s", dry_run, residuals.exists(), forces.exists())
    return {
        "success": True,
        "residuals_csv": str(residuals) if residuals.exists() else None,
        "forces_csv": str(forces) if forces.exists() else None,
        "figures": {
            "pressure_contour": str(output / "pressure_contour.png") if (output / "pressure_contour.png").exists() else None,
            "velocity_contour": str(output / "velocity_contour.png") if (output / "velocity_contour.png").exists() else None,
        },
        "metrics": metrics,
        "error": None,
    }


def _optional_float(value: str | None) -> float | None:
    try:
        return None if value in {None, ""} else float(value)
    except ValueError:
        return None
