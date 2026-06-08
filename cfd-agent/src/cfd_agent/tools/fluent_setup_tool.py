from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cfd_agent.core.models import SimulationTask
from cfd_agent.tools.file_tool import ensure_dir, template_dir


def create_fluent_journal(task: SimulationTask, mesh_info: dict, output_dir: str) -> dict:
    output = ensure_dir(Path(output_dir) / "fluent")
    mesh_case = _absolute(mesh_info.get("case_file") or mesh_info.get("planned_case_file"))
    mesh_file = _absolute(mesh_info.get("mesh_file") or mesh_info.get("planned_mesh_file")) or mesh_case or str((output / "mesh.msh.h5").resolve())
    context = {
        "mesh_file": mesh_file.replace("\\", "/"),
        "mesh_case": str(mesh_case or mesh_file).replace("\\", "/"),
        "case_file": str((output / "case.cas.h5").resolve()).replace("\\", "/"),
        "data_file": str((output / "data.dat.h5").resolve()).replace("\\", "/"),
        "velocity": task.motion.inlet_velocity,
        "density": task.fluid.density,
        "viscosity": task.fluid.viscosity,
        "turbulence_model": task.solver.turbulence_model,
        "residual_target": task.solver.residual_target,
        "max_iterations": task.solver.max_iterations,
    }
    setup_path = output / "fluent_setup.jou"
    solve_path = output / "fluent_solve.jou"
    env = Environment(loader=FileSystemLoader(template_dir()), autoescape=False)
    setup_path.write_text(env.get_template("fluent_setup.jou.j2").render(**context), encoding="utf-8")
    solve_path.write_text(_solver_journal(context), encoding="utf-8")
    return {"success": True, "setup_journal": str(setup_path), "solve_journal": str(solve_path), "error": None}


def _absolute(value: str | None) -> str | None:
    if not value:
        return None
    return str(Path(value).resolve())


def _solver_journal(context: dict) -> str:
    iterations = min(int(context["max_iterations"]), 20)
    return f"""/file/read-case "{context["mesh_case"]}"
/define/models/viscous/kw-sst yes
/define/boundary-conditions/zone-type farfield symmetry
/define/boundary-conditions/velocity-inlet velocity_inlet
yes
yes
no
{context["velocity"]}
no
0
yes
no
1
no
0
no
0
no
no
yes
5
10
/define/boundary-conditions/modify-zones/list-zones
/solve/initialize/hyb-initialization
/solve/iterate {iterations}
/report/forces/wall-forces
yes
1
0
0
no
/report/forces/wall-forces
yes
0
1
0
no
/file/write-case "{context["case_file"]}"
ok
/file/write-data "{context["data_file"]}"
ok
/exit
yes
"""
