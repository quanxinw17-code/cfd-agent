from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import calculate_mach_number, calculate_reynolds_number, classify_flow, get_characteristic_length
from cfd_agent.core.state import WorkflowState
from cfd_agent.core.validators import validate_simulation_task
from cfd_agent.tools.file_tool import ensure_dir
from cfd_agent.tools.fluent_setup_tool import create_fluent_journal
from cfd_agent.tools.fluent_meshing_tool import generate_mesh_with_fluent_meshing
from cfd_agent.tools.postprocess_tool import postprocess_results
from cfd_agent.tools.report_tool import generate_report
from cfd_agent.tools.solver_tool import run_fluent
from cfd_agent.tools.solidworks_tool import create_solidworks_model
from cfd_agent.tools.spaceclaim_tool import create_external_flow_domain


STAGE_ORDER = ("validate", "solidworks", "spaceclaim", "meshing", "fluent_setup", "solver", "postprocess", "report")


def run_simulation(task: SimulationTask, output_dir: str, dry_run: bool = False, from_stage: str | None = None, to_stage: str | None = None) -> dict:
    started = perf_counter()
    output = ensure_dir(output_dir)
    logger = configure_task_logger("cfd_agent.workflow", output, "workflow.log")
    from_stage = _normalize_stage(from_stage, "validate")
    to_stage = _normalize_stage(to_stage, "report")
    if STAGE_ORDER.index(from_stage) > STAGE_ORDER.index(to_stage):
        raise ValueError(f"from_stage must not be after to_stage: {from_stage} > {to_stage}")

    state = WorkflowState.CREATED
    errors: list[str] = []
    files: dict[str, str | None] = {}
    physics_summary: dict | None = None
    results = {"drag_coefficient": None, "lift_coefficient": None}
    stage_state = _load_pipeline_state(output)
    stage_outputs: dict[str, dict] = dict(stage_state.get("stage_outputs", {}))

    workflow_result = {
        "task_id": task.task_id,
        "status": "running",
        "stage": state.value,
        "dry_run": dry_run,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "physics_summary": physics_summary,
        "files": files,
        "results": results,
        "errors": errors,
        "stage_outputs": stage_outputs,
    }

    try:
        logger.info("Starting workflow task_id=%s dry_run=%s from_stage=%s to_stage=%s", task.task_id, dry_run, from_stage, to_stage)
        if _should_run("validate", from_stage, to_stage):
            validation_errors = validate_simulation_task(task)
            if validation_errors:
                errors.extend(validation_errors)
                state = WorkflowState.FAILED
                return _finish(workflow_result, "failed", state, output, task, logger, started)

            length = get_characteristic_length(task)
            reynolds = calculate_reynolds_number(task.fluid.density, task.motion.inlet_velocity, length, task.fluid.viscosity)
            mach = calculate_mach_number(task.motion.inlet_velocity)
            flow = classify_flow(reynolds, mach)
            physics_summary = {
                "reynolds_number": reynolds,
                "mach_number": mach,
                "flow_regime": flow["regime"],
                "compressibility": flow["compressibility"],
                "recommended_solver": flow["recommended_solver"],
                "recommended_turbulence_model": flow["recommended_turbulence_model"],
            }
            workflow_result["physics_summary"] = physics_summary
            stage_outputs["validate"] = {"success": True, "physics_summary": physics_summary}
            state = WorkflowState.VALIDATED
            _checkpoint(output, workflow_result, state)
            logger.info("Physics summary: %s", physics_summary)
            if _stop_at("validate", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            physics_summary = stage_outputs.get("validate", {}).get("physics_summary")
            workflow_result["physics_summary"] = physics_summary

        if _should_run("solidworks", from_stage, to_stage):
            solidworks_info = create_solidworks_model(task, str(output), dry_run=dry_run)
            stage_outputs["solidworks"] = solidworks_info
            _apply_solidworks_files(files, solidworks_info)
            if not solidworks_info.get("success"):
                errors.append(solidworks_info.get("error") or "SolidWorks model generation failed")
                state = WorkflowState.FAILED
                return _finish(workflow_result, "failed", state, output, task, logger, started)
            state = WorkflowState.SOLIDWORKS_MODEL_CREATED
            _checkpoint(output, workflow_result, state)
            if _stop_at("solidworks", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            solidworks_info = _require_stage_output(stage_outputs, "solidworks", from_stage)
            _apply_solidworks_files(files, solidworks_info)

        if _should_run("spaceclaim", from_stage, to_stage):
            domain_info = create_external_flow_domain(task, solidworks_info, str(output), dry_run=dry_run)
            stage_outputs["spaceclaim"] = domain_info
            _apply_spaceclaim_files(files, domain_info)
            if not domain_info.get("success"):
                errors.append(domain_info.get("error") or "SpaceClaim domain generation failed")
                state = WorkflowState.FAILED
                return _finish(workflow_result, "failed", state, output, task, logger, started)
            state = WorkflowState.SPACECLAIM_DOMAIN_CREATED
            _checkpoint(output, workflow_result, state)
            if _stop_at("spaceclaim", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            domain_info = _require_stage_output(stage_outputs, "spaceclaim", from_stage)
            _apply_spaceclaim_files(files, domain_info)

        if _should_run("meshing", from_stage, to_stage):
            mesh_info = generate_mesh_with_fluent_meshing(task, domain_info, str(output), dry_run=dry_run)
            stage_outputs["meshing"] = mesh_info
            _apply_mesh_files(files, mesh_info)
            if not mesh_info.get("success"):
                errors.append(mesh_info.get("error") or "Fluent Meshing failed")
                state = WorkflowState.FAILED
                return _finish(workflow_result, "failed", state, output, task, logger, started)
            state = WorkflowState.FLUENT_MESH_CREATED
            _checkpoint(output, workflow_result, state)
            if _stop_at("meshing", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            mesh_info = _require_stage_output(stage_outputs, "meshing", from_stage)
            _apply_mesh_files(files, mesh_info)

        if _should_run("fluent_setup", from_stage, to_stage):
            journal_info = create_fluent_journal(task, mesh_info, str(output))
            stage_outputs["fluent_setup"] = journal_info
            files["fluent_setup_journal"] = journal_info.get("setup_journal")
            files["fluent_solve_journal"] = journal_info.get("solve_journal")
            state = WorkflowState.CASE_CREATED
            _checkpoint(output, workflow_result, state)
            if _stop_at("fluent_setup", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            journal_info = _require_stage_output(stage_outputs, "fluent_setup", from_stage)
            files["fluent_setup_journal"] = journal_info.get("setup_journal")
            files["fluent_solve_journal"] = journal_info.get("solve_journal")

        if _should_run("solver", from_stage, to_stage):
            solver_info = run_fluent(journal_info, str(output), dry_run=dry_run)
            stage_outputs["solver"] = solver_info
            _apply_solver_files(files, solver_info)
            if not solver_info.get("success"):
                errors.append(solver_info.get("error") or "solver failed")
                state = WorkflowState.FAILED
                return _finish(workflow_result, "failed", state, output, task, logger, started)
            state = WorkflowState.SOLVER_COMPLETED
            _checkpoint(output, workflow_result, state)
            if _stop_at("solver", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            solver_info = _require_stage_output(stage_outputs, "solver", from_stage)
            _apply_solver_files(files, solver_info)

        if _should_run("postprocess", from_stage, to_stage):
            post_info = postprocess_results(task, solver_info, str(output), dry_run=dry_run)
            stage_outputs["postprocess"] = post_info
            _apply_postprocess_files(files, results, post_info)
            state = WorkflowState.POSTPROCESSED
            _checkpoint(output, workflow_result, state)
            if _stop_at("postprocess", to_stage):
                return _finish(workflow_result, "success", state, output, task, logger, started)
        else:
            post_info = _require_stage_output(stage_outputs, "postprocess", from_stage)
            _apply_postprocess_files(files, results, post_info)

        workflow_result["status"] = "success"
        workflow_result["stage"] = state.value
        if _should_run("report", from_stage, to_stage):
            report_info = generate_report(task, workflow_result, str(output))
            stage_outputs["report"] = report_info
            files["report"] = report_info.get("report_file")
            state = WorkflowState.REPORT_CREATED
            _checkpoint(output, workflow_result, state)
        return _finish(workflow_result, "success", state, output, task, logger, started)
    except Exception as exc:
        logger.exception("Workflow failed unexpectedly")
        errors.append(str(exc))
        return _finish(workflow_result, "failed", WorkflowState.FAILED, output, task, logger, started)


def _finish(workflow_result: dict, status: str, state: WorkflowState, output: Path, task: SimulationTask, logger, started: float) -> dict:
    workflow_result["status"] = status
    workflow_result["stage"] = "completed" if state == WorkflowState.REPORT_CREATED else state.value
    workflow_result["elapsed_seconds"] = round(perf_counter() - started, 3)
    if "report" not in workflow_result["files"] and workflow_result.get("to_stage") == "report":
        try:
            report_info = generate_report(task, workflow_result, str(output))
            workflow_result["files"]["report"] = report_info.get("report_file")
            workflow_result["stage_outputs"]["report"] = report_info
        except Exception as exc:  # pragma: no cover
            workflow_result["errors"].append(f"report generation failed: {exc}")
    _checkpoint(output, workflow_result, state)
    logger.info("Workflow finished status=%s stage=%s elapsed=%s", workflow_result["status"], workflow_result["stage"], workflow_result["elapsed_seconds"])
    return workflow_result


def _normalize_stage(stage: str | None, default: str) -> str:
    value = (stage or default).lower().replace("-", "_")
    aliases = {"fluent": "solver", "solve": "solver", "mesh": "meshing", "geometry": "solidworks"}
    value = aliases.get(value, value)
    if value not in STAGE_ORDER:
        raise ValueError(f"Unknown stage {stage!r}; expected one of: {', '.join(STAGE_ORDER)}")
    return value


def _should_run(stage: str, from_stage: str, to_stage: str) -> bool:
    return STAGE_ORDER.index(from_stage) <= STAGE_ORDER.index(stage) <= STAGE_ORDER.index(to_stage)


def _stop_at(stage: str, to_stage: str) -> bool:
    return STAGE_ORDER.index(stage) == STAGE_ORDER.index(to_stage)


def _load_pipeline_state(output: Path) -> dict:
    state_file = output / "pipeline_state.json"
    if not state_file.exists():
        return {}
    with open(state_file, encoding="utf-8") as handle:
        return json.load(handle)


def _checkpoint(output: Path, workflow_result: dict, state: WorkflowState) -> None:
    payload = {
        "task_id": workflow_result["task_id"],
        "status": workflow_result["status"],
        "stage": "completed" if state == WorkflowState.REPORT_CREATED else state.value,
        "dry_run": workflow_result["dry_run"],
        "from_stage": workflow_result["from_stage"],
        "to_stage": workflow_result["to_stage"],
        "physics_summary": workflow_result.get("physics_summary"),
        "files": workflow_result["files"],
        "results": workflow_result["results"],
        "errors": workflow_result["errors"],
        "stage_outputs": workflow_result["stage_outputs"],
    }
    with open(output / "pipeline_state.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _require_stage_output(stage_outputs: dict[str, dict], stage: str, from_stage: str) -> dict:
    info = stage_outputs.get(stage)
    if not info:
        raise ValueError(f"Cannot start from {from_stage!r}: missing prior stage output {stage!r} in pipeline_state.json")
    return info


def _apply_solidworks_files(files: dict, solidworks_info: dict) -> None:
    files["solidworks_script"] = solidworks_info.get("script_file")
    files["solidworks_native"] = solidworks_info.get("native_file") or solidworks_info.get("planned_native_file")
    files["geometry"] = solidworks_info.get("step_file") or solidworks_info.get("planned_step_file")
    files["parasolid"] = solidworks_info.get("parasolid_file") or solidworks_info.get("planned_parasolid_file")
    files["geometry_metadata"] = solidworks_info.get("metadata_file")


def _apply_spaceclaim_files(files: dict, domain_info: dict) -> None:
    files["spaceclaim_script"] = domain_info.get("spaceclaim_script")
    files["fluid_domain"] = domain_info.get("step_file") or domain_info.get("planned_step_file")
    files["named_selections"] = domain_info.get("named_selections_file")


def _apply_mesh_files(files: dict, mesh_info: dict) -> None:
    files["mesh"] = mesh_info.get("mesh_file") or mesh_info.get("planned_mesh_file")
    files["mesh_case"] = mesh_info.get("case_file") or mesh_info.get("planned_case_file")
    files["fluent_meshing_journal"] = mesh_info.get("meshing_journal")
    files["mesh_quality_report"] = mesh_info.get("quality_report_file")


def _apply_solver_files(files: dict, solver_info: dict) -> None:
    files["case"] = solver_info.get("case_file") or solver_info.get("planned_case_file")
    files["data"] = solver_info.get("data_file") or solver_info.get("planned_data_file")
    files["paired_data"] = solver_info.get("paired_data_file") or solver_info.get("planned_paired_data_file")
    files["fluent_log"] = solver_info.get("log_file")


def _apply_postprocess_files(files: dict, results: dict, post_info: dict) -> None:
    files["residuals"] = post_info.get("residuals_csv")
    files["forces"] = post_info.get("forces_csv")
    files["pressure_contour"] = post_info.get("figures", {}).get("pressure_contour")
    files["velocity_contour"] = post_info.get("figures", {}).get("velocity_contour")
    results.update(post_info.get("metrics", {}))
