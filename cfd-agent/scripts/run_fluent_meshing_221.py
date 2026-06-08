from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import ansys.fluent.core as pyfluent
from ansys.fluent.core.services.datamodel_se import PyMenuGeneric
from cfd_agent.tools.process_ui import foreground_enabled


TASK_IDS = {
    "import": "TaskObject1",
    "surface": "TaskObject3",
    "describe": "TaskObject4",
    "update_regions": "TaskObject9",
    "boundary_layers": "TaskObject10",
    "volume": "TaskObject11",
}


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_file = Path(config["result_file"])
    result: dict = {"success": False, "route": "fluent_meshing_watertight", "tasks": {}, "executed_steps": []}
    session = None
    os.environ.setdefault("AWP_ROOT222", os.environ.get("AWP_ROOT221", r"D:\Program Files\ANSYS Inc\v221"))
    try:
        session = pyfluent.launch_fluent(
            product_version="22.2.0",
            mode="meshing",
            version="3d",
            precision="double",
            processor_count=int(config.get("processor_count", 1)),
            cleanup_on_exit=True,
            start_transcript=True,
            show_gui=foreground_enabled(),
            cwd=str(Path(config["mesh_file"]).parent),
        )
        result["fluent_version"] = session.get_fluent_version()
        session.workflow.InitializeWorkflow(WorkflowType="Watertight Geometry")
        raw = session.workflow._workflow

        def task(task_id: str):
            return PyMenuGeneric(raw.service, raw.rules, [("TaskObject", task_id)])

        import_task = task(TASK_IDS["import"])
        import_task.Arguments.set_state(
            {
                "FileName": str(Path(config["geometry_file"]).resolve()),
                "LengthUnit": config.get("length_unit", "m"),
                "CadImportOptions": {
                    "ImportNamedSelections": True,
                    "OneZonePer": "Body",
                    "SavePMDBIntermediateFile": False,
                },
            }
        )
        _execute(import_task, "import_geometry", result)

        surface = task(TASK_IDS["surface"])
        if config.get("global_size"):
            controls = {"MaxSize": float(config["global_size"])}
            if config.get("near_body_size"):
                controls["MinSize"] = float(config["near_body_size"])
            surface.Arguments.set_state({"CFDSurfaceMeshControls": controls})
            result["applied_surface_mesh_controls"] = controls
        _execute(surface, "surface_mesh", result)

        describe = task(TASK_IDS["describe"])
        describe.Arguments.set_state({"SetupType": "The geometry consists of only fluid regions with no voids"})
        _execute(describe, "describe_geometry", result)

        _execute(task(TASK_IDS["update_regions"]), "update_regions", result)

        boundary_layers = task(TASK_IDS["boundary_layers"])
        if config.get("boundary_layer_enabled", True):
            boundary_layers.Arguments.set_state({"AddChild": "yes"})
            boundary_layers.AddChildToTask()
            boundary_layers.InsertCompoundChildTask()
            child_id = _find_task_id(session.workflow(), "smooth-transition_1")
            if child_id:
                child = task(child_id)
                child_arguments = {
                    "BLControlName": "smooth-transition_1",
                    "NumberOfLayers": int(config.get("layers", 10)),
                    "Rate": float(config.get("growth_rate", 1.2)),
                }
                if config.get("first_layer_height"):
                    child_arguments["FirstLayerHeight"] = float(config["first_layer_height"])
                child.Arguments.set_state(child_arguments)
                result["applied_boundary_layer_controls"] = child_arguments
            _execute(boundary_layers, "boundary_layers", result)
            result["boundary_layer_generated"] = True
        else:
            boundary_layers.Execute()
            result["boundary_layer_generated"] = False

        _execute(task(TASK_IDS["volume"]), "volume_mesh", result)
        result["workflow_state"] = session.workflow()
        result["boundary_zone_names"] = _original_zones(result["workflow_state"])
        session.execute_tui("/mesh/check-quality-level 1\n/mesh/check-quality\n/report/mesh-size")
        session.execute_tui(f'/file/write-mesh "{Path(config["mesh_file"]).resolve().as_posix()}"')
        session.execute_tui(f'/file/write-case "{Path(config["case_file"]).resolve().as_posix()}"')
        result["mesh_exists"] = Path(config["mesh_file"]).is_file()
        result["case_exists"] = Path(config["case_file"]).is_file()
        result["success"] = result["mesh_exists"] and result["case_exists"]
        if not result["success"]:
            result["error"] = "Fluent Meshing completed but mesh/case output is missing"
    except Exception as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
        if session is not None:
            try:
                result["workflow_state_at_failure"] = session.workflow()
                result.setdefault("boundary_zone_names", _original_zones(result["workflow_state_at_failure"]))
            except Exception as state_exc:
                result["workflow_state_error"] = repr(state_exc)
    finally:
        if session is not None:
            try:
                session.exit()
            except Exception as exc:
                result["exit_error"] = repr(exc)
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0 if result["success"] else 1


def _execute(task, name: str, result: dict) -> None:
    result["executed_steps"].append(name)
    task.Execute()
    state = task()
    result["tasks"][name] = state
    if state.get("State") != "Up-to-date" or state.get("Errors"):
        result["failed_task"] = name
        result["failed_task_state"] = state
        raise RuntimeError(f"Fluent Meshing task failed: {name}: {state}")


def _find_task_id(state: dict, name: str) -> str | None:
    for key, value in state.items():
        if key.startswith("TaskObject:") and value.get("_name_") == name:
            return key.split(":", 1)[1]
    return None


def _original_zones(state: dict) -> list[str]:
    for value in state.values():
        if isinstance(value, dict) and value.get("_name_") == "Generate the Surface Mesh":
            zones = value.get("Arguments", {}).get("OriginalZones", [])
            if isinstance(zones, str):
                return [name.strip(" '\"") for name in zones.strip("[]").split(",") if name.strip()]
            return [str(name) for name in zones]
    return []


if __name__ == "__main__":
    raise SystemExit(main())
