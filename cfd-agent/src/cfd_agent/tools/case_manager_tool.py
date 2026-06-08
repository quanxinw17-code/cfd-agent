from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cfd_agent.tools.file_tool import project_root, write_json


def list_cases(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root) if root is not None else project_root()
    outputs = base / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    cases = [_case_summary(path, base) for path in outputs.iterdir() if path.is_dir()]
    cases.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    return {"ok": True, "outputs_dir": str(outputs.resolve()), "cases": cases}


def create_case(root: str | Path | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = Path(root) if root is not None else project_root()
    payload = payload or {}
    outputs = base / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    display_name = str(payload.get("name") or "").strip() or _timestamp_name()
    case_id = _unique_case_id(outputs, _slug(display_name))
    output = outputs / case_id
    output.mkdir(parents=True, exist_ok=False)
    meta = {
        "case_id": case_id,
        "name": display_name,
        "description": str(payload.get("description") or "").strip(),
        "tags": _parse_tags(payload.get("tags")),
        "created_at": _now(),
        "updated_at": _now(),
        "input_source": str(payload.get("input_source") or "").strip(),
        "notes": str(payload.get("notes") or "").strip(),
    }
    write_json(output / "case_meta.json", meta)
    return {"ok": True, "case": _case_summary(output, base)}


def update_case_meta(output_dir: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    meta_file = output / "case_meta.json"
    meta = _read_json(meta_file)
    meta.setdefault("case_id", output.name)
    meta.setdefault("name", output.name)
    meta.setdefault("created_at", _now())
    for key in ("name", "description", "input_source", "notes"):
        if key in payload:
            meta[key] = str(payload.get(key) or "").strip()
    if "tags" in payload:
        meta["tags"] = _parse_tags(payload.get("tags"))
    meta["updated_at"] = _now()
    write_json(meta_file, meta)
    return {"ok": True, "case": {**_case_summary(output, output.parents[1] if output.parent.name == "outputs" else project_root()), **meta}}


def _case_summary(path: Path, base: Path) -> dict[str, Any]:
    meta = _read_json(path / "case_meta.json")
    pipeline = _read_json(path / "pipeline_state.json")
    diagnostics = path / "diagnostics" / "diagnostic_report.md"
    report = path / "report" / "report.md"
    updated_at = _latest_mtime(path)
    status = pipeline.get("status") or "not_started"
    stage = pipeline.get("stage")
    try:
        relative_output = path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        relative_output = str(path.resolve())
    return {
        "case_id": meta.get("case_id") or path.name,
        "name": meta.get("name") or path.name,
        "description": meta.get("description", ""),
        "tags": _parse_tags(meta.get("tags")),
        "output": str(path.resolve()),
        "relative_output": relative_output,
        "status": status,
        "stage": stage,
        "has_report": report.is_file(),
        "has_diagnostics": diagnostics.is_file(),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at") or updated_at,
        "last_modified": updated_at,
        "errors": pipeline.get("errors") or [],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_mtime(path: Path) -> str | None:
    newest = path.stat().st_mtime if path.exists() else None
    for child in path.rglob("*"):
        try:
            newest = max(newest or 0, child.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(newest).isoformat(timespec="seconds") if newest else None


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or _timestamp_name()


def _unique_case_id(outputs: Path, base: str) -> str:
    if not (outputs / base).exists():
        return base
    index = 2
    while True:
        candidate = f"{base}_{index:03d}"
        if not (outputs / candidate).exists():
            return candidate
        index += 1


def _parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,，\s]+", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    return [part.strip() for part in parts if part and part.strip()]


def _timestamp_name() -> str:
    return "case_" + datetime.now().strftime("%Y%m%d_%H%M")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
