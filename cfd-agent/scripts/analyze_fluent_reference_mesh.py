from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path

import ansys.fluent.core as pyfluent
from ansys.fluent.core.launcher.launcher import LaunchModes
from ansys.fluent.core.services.field_data import SurfaceDataType

from cfd_agent.tools.process_ui import foreground_enabled


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    reference = Path(config["reference_file"]).resolve()
    result_file = Path(config["result_file"]).resolve()
    result: dict = {"success": False, "reference_file": str(reference), "warnings": [], "mesh_settings": {}}
    session = None
    os.environ.setdefault("AWP_ROOT222", os.environ.get("AWP_ROOT221", r"D:\Program Files\ANSYS Inc\v221"))
    try:
        session = pyfluent.launch_fluent(
            product_version="22.2.0",
            mode=LaunchModes.SOLVER,
            version="3d",
            precision="double",
            processor_count=int(config.get("processor_count", 1)),
            cleanup_on_exit=True,
            start_transcript=True,
            show_gui=foreground_enabled(),
            cwd=str(result_file.parent),
        )
        result["fluent_version"] = session.get_fluent_version()
        session.execute_tui(read_reference_command(reference))

        surfaces = session.field_info.get_surfaces_info()
        result["boundary_zone_names"] = sorted(str(name) for name in surfaces)
        object_name = _find_object_wall(result["boundary_zone_names"])
        if object_name:
            bbox = _surface_bbox(session, object_name)
            if bbox:
                result["object_wall_name"] = object_name
                result["object_wall_bbox"] = bbox
                extents = [bbox["max"][i] - bbox["min"][i] for i in range(3)]
                result["reference_characteristic_length"] = max(extents)
                result["detection_method"] = "object_wall_bbox"
            else:
                result["warnings"].append("object_wall vertices could not be read")
        else:
            result["warnings"].append("object_wall boundary was not found")

        if not result.get("reference_characteristic_length"):
            fallback = _h5_reference_profile(reference)
            if fallback:
                result.update(fallback)
                result["warnings"].append("Fluent 2022 R1 field-data service was unavailable; used Fluent HDF5 zone connectivity fallback.")

        report_text = "\n".join(
            str(value)
            for value in [
                session.execute_tui("/report/mesh-size"),
                session.execute_tui("/mesh/check-quality-level 1"),
                session.execute_tui("/mesh/check-quality"),
            ]
            if value is not None
        )
        result["report_text"] = report_text
        result["cell_count"] = _last_int(report_text, r"(\d+)\s+cells") or result.get("cell_count")
        result["min_orthogonal_quality"] = _last_float(report_text, r"Minimum Orthogonal Quality\s*=\s*([0-9.eE+-]+)") or result.get("min_orthogonal_quality")
        result["max_skewness"] = _last_float(report_text, r"maximum skewness(?: of)?\s*:?\s*([0-9.eE+-]+)") or result.get("max_skewness")
        result["success"] = True
    except Exception as exc:
        result["error"] = repr(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        if session is not None:
            try:
                session.exit()
            except Exception as exc:
                result["exit_error"] = repr(exc)
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0 if result["success"] else 1


def _find_object_wall(names: list[str]) -> str | None:
    normalized = {name.lower().replace("-", "_"): name for name in names}
    if "object_wall" in normalized:
        return normalized["object_wall"]
    return next((name for name in names if "object" in name.lower() and "wall" in name.lower()), None)


def read_reference_command(reference: Path) -> str:
    return f'/file/read-case "{reference.resolve().as_posix()}"\n'


def _h5_reference_profile(reference: Path) -> dict | None:
    if not str(reference).lower().endswith((".msh.h5", ".cas.h5")):
        return None
    try:
        import h5py
        import numpy as np

        with h5py.File(reference, "r") as mesh:
            root = mesh["meshes/1"]
            names = root["faces/zoneTopology/name"][0].decode("utf-8").split(";")
            coordinates = np.vstack([root[f"nodes/coords/{name}"][()] for name in sorted(root["nodes/coords"], key=int)])
            candidates = []
            for index, name in enumerate(names, 1):
                if "wall" not in name.lower() or f"faces/nodes/{index}/nodes" not in root:
                    continue
                node_ids = np.unique(root[f"faces/nodes/{index}/nodes"][()])
                points = coordinates[node_ids - 1]
                minimum = points.min(axis=0)
                maximum = points.max(axis=0)
                extents = maximum - minimum
                candidates.append((float(np.linalg.norm(extents)), name, minimum, maximum, extents, len(node_ids)))
            if not candidates:
                return None
            _, name, minimum, maximum, extents, vertex_count = min(candidates, key=lambda item: item[0])
            cell_min = root["cells/zoneTopology/minId"][()]
            cell_max = root["cells/zoneTopology/maxId"][()]
            return {
                "object_wall_name": name,
                "object_wall_bbox": {
                    "min": minimum.tolist(),
                    "max": maximum.tolist(),
                    "vertex_count": vertex_count,
                },
                "reference_characteristic_length": float(max(extents)),
                "detection_method": "smallest_wall_zone_bbox",
                "boundary_zone_names": names,
                "cell_count": int(sum(cell_max - cell_min + 1)),
            }
    except Exception:
        return None


def _surface_bbox(session, surface_name: str) -> dict | None:
    raw = session.field_data.get_surface_data(data_types=[SurfaceDataType.Vertices], surfaces=[surface_name])
    points = _collect_points(raw)
    if not points:
        return None
    return {
        "min": [min(point[index] for point in points) for index in range(3)],
        "max": [max(point[index] for point in points) for index in range(3)],
        "vertex_count": len(points),
    }


def _collect_points(value) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return [(float(value.x), float(value.y), float(value.z))]
    if isinstance(value, dict):
        for child in value.values():
            points.extend(_collect_points(child))
    elif isinstance(value, (list, tuple)):
        if len(value) == 3 and all(isinstance(item, (int, float)) for item in value):
            points.append((float(value[0]), float(value[1]), float(value[2])))
        else:
            for child in value:
                points.extend(_collect_points(child))
    return points


def _last_float(text: str, pattern: str) -> float | None:
    matches = re.findall(pattern, text, re.IGNORECASE)
    return float(matches[-1].rstrip(".")) if matches else None


def _last_int(text: str, pattern: str) -> int | None:
    matches = re.findall(pattern, text, re.IGNORECASE)
    return int(matches[-1]) if matches else None


if __name__ == "__main__":
    raise SystemExit(main())
