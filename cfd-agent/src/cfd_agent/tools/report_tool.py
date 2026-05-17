from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.file_tool import ensure_dir, template_dir


def generate_report(task: SimulationTask, workflow_result: dict, output_dir: str) -> dict:
    output = ensure_dir(Path(output_dir) / "report")
    env = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    report_file = output / "report.md"
    report_file.write_text(env.get_template("report.md.j2").render(task=task, result=workflow_result), encoding="utf-8")
    return {"success": True, "report_file": str(report_file), "error": None}
