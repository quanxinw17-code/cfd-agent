from __future__ import annotations

import shutil
from pathlib import Path

from cfd_agent.core.logging_config import configure_task_logger
from cfd_agent.core.models import SimulationTask
from cfd_agent.core.physics import get_characteristic_length
from cfd_agent.tools.file_tool import ensure_dir, write_json


SUPPORTED_CAD_EXTENSIONS = {".step", ".stp", ".x_t", ".x_b", ".sldprt"}


def import_custom_cad(task: SimulationTask, output_dir: str, dry_run: bool = False) -> dict:
    root = ensure_dir(Path(output_dir) / "custom_cad")
    logger = configure_task_logger("cfd_agent.custom_cad", output_dir, "geometry.log")
    metadata_file = root / "geometry_metadata.json"
    source = Path(task.geometry.cad_file or "").expanduser()

    if not source.is_absolute():
        source = source.resolve()
    extension = source.suffix.lower()
    error = None
    if not source.is_file():
        error = f"Custom CAD file not found: {source}"
    elif extension not in SUPPORTED_CAD_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_CAD_EXTENSIONS))
        error = f"Unsupported custom CAD extension {extension!r}; expected one of: {supported}"

    imported_file = root / f"imported_geometry{extension}" if extension else root / "imported_geometry"
    metadata = {
        "geometry_type": "custom_cad",
        "source_file": str(source),
        "imported_file": str(imported_file),
        "characteristic_length": get_characteristic_length(task),
        "supported_extensions": sorted(SUPPORTED_CAD_EXTENSIONS),
        "dry_run": dry_run,
    }
    write_json(metadata_file, metadata)

    if error:
        logger.error(error)
        return _result(imported_file, metadata_file, False, error)

    if source.resolve() != imported_file.resolve():
        shutil.copy2(source, imported_file)
    logger.info("Imported custom CAD file: %s -> %s", source, imported_file)
    return _result(imported_file, metadata_file, True, None)


def _result(imported_file: Path, metadata_file: Path, success: bool, error: str | None) -> dict:
    extension = imported_file.suffix.lower()
    return {
        "script_file": None,
        "native_file": str(imported_file) if success and extension == ".sldprt" else None,
        "step_file": str(imported_file) if success and extension in {".step", ".stp"} else None,
        "parasolid_file": str(imported_file) if success and extension in {".x_t", ".x_b"} else None,
        "source_file": str(imported_file) if success else None,
        "metadata_file": str(metadata_file),
        "success": success,
        "error": error,
        "imported": success,
    }
