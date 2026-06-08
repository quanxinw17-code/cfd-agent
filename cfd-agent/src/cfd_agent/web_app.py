from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from cfd_agent.agents.requirement_parser import parse_requirement
from cfd_agent.core.models import DomainImitationConfig, MeshImitationConfig, SimulationTask, load_simulation_task
from cfd_agent.core.orchestrator import run_simulation
from cfd_agent.tools.case_manager_tool import create_case, list_cases
from cfd_agent.tools.diagnostics_tool import diagnose_output
from cfd_agent.tools.deployment_tool import deployment_check, load_project_env, software_smoke_check, write_project_env
from cfd_agent.tools.task_editor_tool import load_task_payload, preview_task_payload, save_task_payload


ROOT = Path.cwd().resolve()
DEFAULT_INPUT = "examples/sphere_external_flow.json"
DEFAULT_OUTPUT = "outputs/sphere_001"
DEFAULT_DESCRIPTION = "分析一个直径 0.1 米的球体外流场，入口速度 30 m/s，攻角 0 度"
STAGES = ["validate", "solidworks", "domain_imitation", "spaceclaim", "mesh_imitation", "meshing", "fluent_setup", "solver", "postprocess", "report"]
STAGE_LABELS = {
    "validate": "1. 参数与物理检查",
    "solidworks": "2. 几何生成 / CAD 导入",
    "spaceclaim": "3. SpaceClaim 流体域",
    "meshing": "4. 体网格生成",
    "fluent_setup": "5. Fluent 求解设置",
    "solver": "6. Fluent 求解",
    "postprocess": "7. 后处理",
    "report": "8. 生成报告",
}
STAGE_LABELS["mesh_imitation"] = "4. Reference mesh imitation"
STAGE_LABELS["domain_imitation"] = "3. External domain imitation"
STAGE_BUTTONS = "".join(
    f'<div class="stage-item" data-stage="{stage}"><span class="stage-state">待运行</span><strong>{STAGE_LABELS[stage]}</strong>'
    f'<button class="stage-run run-action" onclick="runStage(\'{stage}\')">运行此步</button></div>'
    for stage in STAGES
)


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.request: dict = {}
        self.result: dict | None = None
        self.error: str | None = None

    def snapshot(self) -> dict:
        with self.lock:
            output_dir = self.request.get("output", DEFAULT_OUTPUT)
            pipeline = _read_json(Path(output_dir) / "pipeline_state.json")
            return {
                "running": self.running,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "request": self.request,
                "result": self.result,
                "error": self.error,
                "pipeline": pipeline,
                "artifacts": _collect_artifacts(Path(output_dir)),
            }


JOB = JobState()


class CFDHandler(BaseHTTPRequestHandler):
    server_version = "CFDAgentWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
        elif parsed.path == "/api/state":
            self._send_json(JOB.snapshot())
        elif parsed.path == "/api/cases":
            self._send_json(list_cases(ROOT))
        elif parsed.path == "/api/browse":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            try:
                self._send_json({"path": _browse_path(kind)})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"error": f"无法打开选择窗口：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        elif parsed.path == "/files":
            self._send_file(parse_qs(parsed.query).get("path", [""])[0])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/run",
            "/api/parse",
            "/api/deploy/check",
            "/api/deploy/save",
            "/api/deploy/smoke",
            "/api/diagnose",
            "/api/cases/create",
            "/api/task/preview",
            "/api/task/save",
            "/api/task/load",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if parsed.path == "/api/parse":
            self._send_json(parse_requirement(payload.get("description", "")))
            return
        if parsed.path == "/api/deploy/check":
            self._send_json(deployment_check(ROOT, _deployment_payload_from_form(payload)))
            return
        if parsed.path == "/api/deploy/save":
            env_file = write_project_env(_deployment_payload_from_form(payload), ROOT)
            self._send_json({"ok": True, "env_file": str(env_file.resolve()), "check": deployment_check(ROOT)})
            return
        if parsed.path == "/api/deploy/smoke":
            self._send_json(software_smoke_check(ROOT, _deployment_payload_from_form(payload)))
            return
        if parsed.path == "/api/diagnose":
            output_dir = _safe_path(payload.get("output", DEFAULT_OUTPUT))
            self._send_json(diagnose_output(output_dir, ROOT))
            return
        if parsed.path == "/api/cases/create":
            self._send_json(create_case(ROOT, payload))
            return
        if parsed.path == "/api/task/preview":
            self._send_json(preview_task_payload(payload))
            return
        if parsed.path == "/api/task/save":
            output_dir = _safe_path(payload.get("output", DEFAULT_OUTPUT))
            self._send_json(save_task_payload(payload, output_dir))
            return
        if parsed.path == "/api/task/load":
            self._send_json(load_task_payload(_safe_path(payload.get("input", DEFAULT_INPUT))))
            return
        with JOB.lock:
            if JOB.running:
                self._send_json({"ok": False, "error": "A workflow is already running."}, HTTPStatus.CONFLICT)
                return
            JOB.running = True
            JOB.started_at = time.time()
            JOB.finished_at = None
            JOB.request = payload
            JOB.result = None
            JOB.error = None
        thread = threading.Thread(target=_run_job, args=(payload,), daemon=True)
        thread.start()
        self._send_json({"ok": True})

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, value: str) -> None:
        try:
            path = _safe_path(value)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _content_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)


def _run_job(payload: dict) -> None:
    old_env = os.environ.copy()
    try:
        load_project_env(ROOT)
        if payload.get("full_auto_env", True):
            os.environ.setdefault("CFD_AGENT_FOREGROUND", "true")
            os.environ.setdefault("SOLIDWORKS_ENABLED", "true")
            os.environ.setdefault("SPACECLAIM_ENABLED", "true")
            os.environ.setdefault("SPACECLAIM_EXECUTABLE", r"D:\Program Files\ANSYS Inc\v221\scdm\SpaceClaim.exe")
            os.environ.setdefault("FLUENT_EXECUTABLE", r"D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe")
            os.environ.setdefault("FLUENT_MESHING_ENABLED", "true")
            os.environ.setdefault("FLUENT_SOLVER_ENABLED", "true")

        task = _task_from_payload(payload)
        if payload.get("cad_file"):
            cad_file = _safe_path(payload["cad_file"])
            characteristic_length = float(payload.get("characteristic_length") or 0)
            task = task.model_copy(
                update={
                    "geometry": task.geometry.model_copy(
                        update={
                            "type": "custom_cad",
                            "cad_file": str(cad_file),
                            "parameters": {"characteristic_length": characteristic_length},
                        }
                    )
                }
            )
        result = run_simulation(
            task,
            str(_safe_path(payload.get("output", DEFAULT_OUTPUT))),
            dry_run=bool(payload.get("dry_run", False)),
            from_stage=payload.get("from_stage") or None,
            to_stage=payload.get("to_stage") or None,
        )
        with JOB.lock:
            JOB.result = result
            JOB.error = None if result.get("status") == "success" else "; ".join(result.get("errors", []))
    except Exception:
        with JOB.lock:
            JOB.error = traceback.format_exc()
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        with JOB.lock:
            JOB.running = False
            JOB.finished_at = time.time()


def _task_from_payload(payload: dict) -> SimulationTask:
    description = str(payload.get("description") or "").strip()
    if description:
        parsed = parse_requirement(description)
        if payload.get("cad_file") and float(payload.get("characteristic_length") or 0) > 0:
            values = parsed["parsed_values"]
            if values["inlet_velocity"] is None:
                raise ValueError("自然语言任务缺少：入口速度")
            return SimulationTask.model_validate(
                {
                    "task_id": "natural_language_custom_cad_task",
                    "geometry": {
                        "type": "custom_cad",
                        "unit": "m",
                        "parameters": {"characteristic_length": float(payload["characteristic_length"])},
                        "cad_file": str(_safe_path(payload["cad_file"])),
                    },
                    "motion": {
                        "type": "stationary",
                        "inlet_velocity": values["inlet_velocity"],
                        "attack_angle_deg": values["attack_angle_deg"],
                    },
                    "solver": {"max_iterations": values["max_iterations"]},
                }
            )
        if parsed["missing_fields"]:
            raise ValueError("自然语言任务缺少：" + "、".join(parsed["missing_fields"]))
        task = SimulationTask.model_validate(parsed["task"])
    else:
        task = load_simulation_task(_safe_path(payload.get("input", DEFAULT_INPUT)))
    if payload.get("mesh_imitation_enabled"):
        reference_file = _safe_path(payload.get("reference_mesh_file", ""))
        manual_length = float(payload.get("reference_characteristic_length") or 0) or None
        task = task.model_copy(
            update={
                "mesh_imitation": MeshImitationConfig(
                    enabled=True,
                    reference_file=str(reference_file),
                    reference_characteristic_length=manual_length,
                )
            }
        )
    if payload.get("domain_imitation_enabled"):
        reference_file = _safe_path(payload.get("reference_domain_file", ""))
        task = task.model_copy(
            update={
                "domain_imitation": DomainImitationConfig(
                    enabled=True,
                    reference_file=str(reference_file),
                    manual_flow_direction=_parse_manual_flow_direction(payload.get("manual_flow_direction", "")),
                )
            }
        )
    return task


def _parse_manual_flow_direction(value: str | None) -> list[float] | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ValueError("manual_flow_direction must contain three comma-separated numbers, for example: 1,0,0")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("manual_flow_direction must contain three comma-separated numbers, for example: 1,0,0") from exc


def _deployment_payload_from_form(payload: dict) -> dict:
    return {
        "spaceclaim_executable": payload.get("deploy_spaceclaim_executable", ""),
        "fluent_executable": payload.get("deploy_fluent_executable", ""),
        "foreground": bool(payload.get("deploy_foreground", True)),
        "solidworks_enabled": bool(payload.get("deploy_solidworks_enabled", True)),
        "spaceclaim_enabled": bool(payload.get("deploy_spaceclaim_enabled", True)),
        "fluent_meshing_enabled": bool(payload.get("deploy_fluent_meshing_enabled", True)),
        "fluent_solver_enabled": bool(payload.get("deploy_fluent_solver_enabled", True)),
    }


def _safe_path(value: str | os.PathLike[str]) -> Path:
    path = Path(unquote(str(value))).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        if not resolved.exists():
            raise
    return resolved


def _browse_path(kind: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "directory":
            selected = filedialog.askdirectory(title="选择 CFD 输出目录", mustexist=True, parent=root)
        elif kind == "cad":
            selected = filedialog.askopenfilename(
                title="选择自定义 CAD 文件",
                filetypes=[
                    ("支持的 CAD 文件", "*.step *.stp *.x_t *.x_b *.sldprt"),
                    ("STEP", "*.step *.stp"),
                    ("Parasolid", "*.x_t *.x_b"),
                    ("SolidWorks Part", "*.sldprt"),
                    ("所有文件", "*.*"),
                ],
                parent=root,
            )
        elif kind == "mesh":
            selected = filedialog.askopenfilename(
                title="Select Fluent reference mesh or case",
                filetypes=[
                    ("Fluent mesh or case", "*.msh *.msh.h5 *.cas *.cas.h5"),
                    ("All files", "*.*"),
                ],
                parent=root,
            )
        elif kind == "domain":
            selected = filedialog.askopenfilename(
                title="Select SpaceClaim reference fluid domain",
                filetypes=[
                    ("SpaceClaim or STEP domain", "*.scdoc *.step *.stp"),
                    ("SpaceClaim", "*.scdoc"),
                    ("STEP", "*.step *.stp"),
                    ("All files", "*.*"),
                ],
                parent=root,
            )
        else:
            raise ValueError("未知选择类型")
        return str(Path(selected).resolve()) if selected else ""
    finally:
        root.destroy()


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _collect_artifacts(output_dir: Path) -> list[dict]:
    files = [
        output_dir / "pipeline_state.json",
        output_dir / "solidworks" / "geometry.step",
        output_dir / "solidworks" / "geometry.x_t",
        output_dir / "spaceclaim" / "fluid_domain.scdoc",
        output_dir / "spaceclaim" / "fluid_domain.step",
        output_dir / "domain_imitation" / "domain_reference_profile.json",
        output_dir / "domain_imitation" / "scaled_domain_settings.json",
        output_dir / "domain_imitation" / "domain_imitation_comparison.json",
        output_dir / "domain_imitation" / "spaceclaim_reference_analysis.log",
        output_dir / "mesh_imitation" / "mesh_reference_profile.json",
        output_dir / "mesh_imitation" / "scaled_mesh_settings.json",
        output_dir / "mesh_imitation" / "mesh_imitation_comparison.json",
        output_dir / "mesh_imitation" / "fluent_reference_analysis.log",
        output_dir / "meshing" / "mesh.msh.h5",
        output_dir / "meshing" / "mesh_case.cas.h5",
        output_dir / "fluent" / "case.cas.h5",
        output_dir / "fluent" / "case.dat.h5",
        output_dir / "fluent" / "data.dat.h5",
        output_dir / "postprocess" / "residuals.csv",
        output_dir / "postprocess" / "forces.csv",
        output_dir / "report" / "report.md",
        output_dir / "diagnostics" / "diagnostic_report.json",
        output_dir / "diagnostics" / "diagnostic_report.md",
    ]
    files.extend(sorted((output_dir / "custom_cad").glob("imported_geometry.*")))
    files.append(output_dir / "custom_cad" / "geometry_metadata.json")
    artifacts = []
    for file in files:
        path = file if file.is_absolute() else ROOT / file
        if path.exists():
            resolved = path.resolve()
            try:
                display_path = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                display_path = str(resolved)
            artifacts.append(
                {
                    "name": path.name,
                    "path": display_path,
                    "size": path.stat().st_size,
                    "url": f"/files?path={quote(str(resolved))}",
                }
            )
    return artifacts


def _content_type(path: Path) -> str:
    if path.suffix in {".md", ".log", ".jou", ".json", ".csv", ".txt"}:
        return "text/plain; charset=utf-8"
    if path.suffix == ".html":
        return "text/html; charset=utf-8"
    return "application/octet-stream"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CFD Agent local web entry")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), CFDHandler)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(f"CFD Agent web entry: {url}")
    server.serve_forever()
    return 0


INDEX_HTML = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CFD Agent</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, "Segoe UI", Arial, sans-serif; }}
    body {{ margin: 0; background: #f4f6f8; color: #17202a; }}
    header {{ background: #1e293b; color: #fff; padding: 18px 28px; }}
    h1 {{ margin: 0; font-size: 22px; font-weight: 650; letter-spacing: 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px; display: grid; grid-template-columns: 390px 1fr; gap: 18px; }}
    section {{ background: #fff; border: 1px solid #d8dee6; border-radius: 8px; padding: 16px; }}
    h2 {{ font-size: 15px; margin: 0 0 14px; }}
    label {{ display: block; font-size: 12px; font-weight: 650; color: #4b5563; margin: 12px 0 6px; }}
    input, select, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 9px 10px; font-size: 13px; background: #fff; font-family: inherit; }}
    textarea {{ min-height: 108px; resize: vertical; line-height: 1.5; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .path-row {{ display: grid; grid-template-columns: minmax(0, 1fr) 42px; gap: 7px; }}
    .browse-btn {{ width: 42px; margin: 0; padding: 0; background: #475569; font-size: 18px; }}
    .check {{ display: flex; align-items: center; gap: 8px; margin-top: 12px; color: #334155; font-size: 13px; }}
    .check input {{ width: auto; }}
    button {{ width: 100%; border: 0; border-radius: 6px; background: #2563eb; color: white; padding: 11px 12px; font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 16px; }}
    button:disabled {{ background: #94a3b8; cursor: default; }}
    .secondary {{ background: #475569; }}
    .stage-list {{ display: grid; gap: 7px; margin-top: 12px; }}
    .stage-item {{ display: grid; grid-template-columns: 58px 1fr 82px; gap: 9px; align-items: center; border-top: 1px solid #e5e7eb; padding-top: 7px; }}
    .stage-item strong {{ font-size: 12px; }}
    .stage-state {{ color: #64748b; font-size: 11px; }}
    .stage-item.done .stage-state {{ color: #15803d; font-weight: 700; }}
    .stage-run {{ width: auto; margin: 0; padding: 7px 9px; font-size: 12px; background: #475569; }}
    .case-list {{ display: grid; gap: 8px; margin-top: 10px; max-height: 240px; overflow: auto; }}
    .case-item {{ border-top: 1px solid #e5e7eb; padding-top: 8px; display: grid; gap: 6px; }}
    .case-item strong {{ font-size: 13px; }}
    .case-meta {{ color: #64748b; font-size: 11px; }}
    .case-actions {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
    .case-actions button {{ margin: 0; padding: 7px 8px; font-size: 12px; }}
    .status {{ display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #94a3b8; }}
    .dot.run {{ background: #f59e0b; }}
    .dot.ok {{ background: #16a34a; }}
    .dot.fail {{ background: #dc2626; }}
    pre {{ background: #0f172a; color: #e5e7eb; border-radius: 7px; padding: 12px; overflow: auto; max-height: 360px; font-size: 12px; line-height: 1.5; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e5e7eb; padding: 8px 6px; }}
    a {{ color: #1d4ed8; text-decoration: none; }}
    .muted {{ color: #64748b; font-size: 12px; }}
    @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header><h1>CFD Agent 本地入口</h1></header>
  <main>
    <section>
      <h2>运行设置</h2>
      <label>自然语言任务描述</label>
      <div>
        <h2>项目 / 案例管理</h2>
        <label>新案例名称</label>
        <input id="caseName" placeholder="例如 sphere_002 或 A350_10km">
        <label>案例描述</label>
        <input id="caseDescription" placeholder="可选备注">
        <label>标签</label>
        <input id="caseTags" placeholder="sphere, validation">
        <div class="row">
          <button class="secondary" onclick="refreshCases()">刷新案例</button>
          <button class="secondary" onclick="createCase()">创建案例</button>
        </div>
        <div id="caseList" class="case-list"></div>
      </div>
      <textarea id="description">{DEFAULT_DESCRIPTION}</textarea>
      <button class="secondary" style="margin-top:8px" onclick="previewTask()">解析任务</button>
      <pre id="parsePreview" style="max-height:210px;margin:8px 0 0">{{}}</pre>
      <details open>
        <summary class="muted" style="cursor:pointer;margin-top:12px">参数化任务编辑器</summary>
        <label>Task ID</label>
        <input id="paramTaskId" value="sphere_parametric_001">
        <label>几何类型</label>
        <select id="paramGeometryType"><option value="sphere">sphere</option><option value="cylinder">cylinder</option><option value="box">box</option><option value="custom_cad">custom_cad</option></select>
        <div class="row"><div><label>直径 / 特征长度</label><input id="paramDiameter" type="number" step="any" value="0.1"></div><div><label>长度</label><input id="paramLength" type="number" step="any" value="1.0"></div></div>
        <div class="row"><div><label>宽度</label><input id="paramWidth" type="number" step="any" value="1.0"></div><div><label>高度</label><input id="paramHeight" type="number" step="any" value="1.0"></div></div>
        <div class="row"><div><label>入口速度</label><input id="paramInletVelocity" type="number" step="any" value="30"></div><div><label>攻角</label><input id="paramAttackAngle" type="number" step="any" value="0"></div></div>
        <div class="row"><div><label>密度</label><input id="paramDensity" type="number" step="any" value="1.225"></div><div><label>粘度</label><input id="paramViscosity" type="number" step="any" value="1.789e-5"></div></div>
        <div class="row"><div><label>上游倍数</label><input id="paramUpstream" type="number" step="any" value="5"></div><div><label>下游倍数</label><input id="paramDownstream" type="number" step="any" value="15"></div></div>
        <label>侧向倍数</label><input id="paramSide" type="number" step="any" value="5">
        <div class="row"><div><label>全局尺寸</label><input id="paramGlobalSize" type="number" step="any" placeholder="auto"></div><div><label>近壁尺寸</label><input id="paramNearBodySize" type="number" step="any" placeholder="auto"></div></div>
        <label class="check"><input id="paramBoundaryLayer" type="checkbox" checked> 启用边界层</label>
        <div class="row"><div><label>边界层层数</label><input id="paramLayers" type="number" step="1" value="15"></div><div><label>增长率</label><input id="paramGrowthRate" type="number" step="any" value="1.2"></div></div>
        <div class="row"><div><label>最大 skewness</label><input id="paramMaxSkewness" type="number" step="any" value="0.85"></div><div><label>最小正交质量</label><input id="paramMinOrthogonal" type="number" step="any" value="0.15"></div></div>
        <div class="row"><div><label>湍流模型</label><select id="paramTurbulence"><option value="k_omega_sst">k_omega_sst</option><option value="k_epsilon">k_epsilon</option><option value="laminar">laminar</option></select></div><div><label>最大迭代</label><input id="paramMaxIterations" type="number" step="1" value="1000"></div></div>
        <label>残差目标</label><input id="paramResidualTarget" type="number" step="any" value="1e-5">
        <div class="row"><button class="secondary" onclick="loadParameterTask()">加载当前任务</button><button class="secondary" onclick="previewParameterTask()">生成预览</button></div>
        <button class="secondary" onclick="saveParameterTask()">保存到当前案例</button>
        <pre id="parameterTaskPreview" style="max-height:230px;margin:8px 0 0">{{}}</pre>
      </details>
      <details>
        <summary class="muted" style="cursor:pointer;margin-top:12px">高级：使用任务 JSON 文件</summary>
        <label>任务 JSON 路径（自然语言为空时使用）</label>
        <input id="input" value="{DEFAULT_INPUT}">
      </details>
      <label>输出目录</label>
      <div class="path-row">
        <input id="output" value="{DEFAULT_OUTPUT}">
        <button class="browse-btn" title="选择输出文件夹" onclick="browsePath('directory', 'output', this)">&#128193;</button>
      </div>
      <label class="check"><input id="oneClickDeployEnabled" type="checkbox"> One-click deployment mode</label>
      <div id="deployPanel">
        <label>SpaceClaim executable</label>
        <input id="deploySpaceClaimExecutable" placeholder="D:/Program Files/ANSYS Inc/v221/scdm/SpaceClaim.exe">
        <label>Fluent executable</label>
        <input id="deployFluentExecutable" placeholder="D:/Program Files/ANSYS Inc/v221/fluent/ntbin/win64/fluent.exe">
        <label class="check"><input id="deployForeground" type="checkbox" checked> Run commercial software in foreground</label>
        <label class="check"><input id="deploySolidWorksEnabled" type="checkbox" checked> Enable SolidWorks</label>
        <label class="check"><input id="deploySpaceClaimEnabled" type="checkbox" checked> Enable SpaceClaim</label>
        <label class="check"><input id="deployFluentMeshingEnabled" type="checkbox" checked> Enable Fluent Meshing</label>
        <label class="check"><input id="deployFluentSolverEnabled" type="checkbox" checked> Enable Fluent Solver</label>
        <div class="row">
          <button class="secondary" onclick="runDeploymentCheck()">检测环境</button>
          <button class="secondary" onclick="saveDeploymentConfig()">保存配置</button>
        </div>
        <button class="secondary" onclick="runSoftwareSmokeCheck()">运行软件自检</button>
        <pre id="deploymentStatus" style="max-height:180px;margin:8px 0 0">{{}}</pre>
      </div>
      <label>自定义 CAD 文件（可选）</label>
      <div class="path-row">
      <input id="cadFile" placeholder="D:/models/body.step / body.x_t / body.sldprt">
        <button class="browse-btn" title="选择 CAD 文件" onclick="browsePath('cad', 'cadFile', this)">&#128194;</button>
      </div>
      <label>CAD 特征长度（米）</label>
      <input id="characteristicLength" type="number" min="0" step="any" placeholder="例如 0.1">
      <label class="check"><input id="domainImitationEnabled" type="checkbox"> External domain imitation</label>
      <label>SpaceClaim reference fluid domain</label>
      <div class="path-row">
        <input id="referenceDomainFile" placeholder="D:/reference/fluid_domain.scdoc">
        <button class="browse-btn" title="Select SpaceClaim reference fluid domain" onclick="browsePath('domain', 'referenceDomainFile', this)">&#128194;</button>
      </div>
      <label>Manual flow direction (optional)</label>
      <input id="manualFlowDirection" placeholder="Auto-detect, or enter 1,0,0">
      <label class="check"><input id="meshImitationEnabled" type="checkbox"> Reference mesh imitation</label>
      <label>Fluent reference mesh / case</label>
      <div class="path-row">
        <input id="referenceMeshFile" placeholder="D:/reference/reference.msh.h5">
        <button class="browse-btn" title="Select Fluent reference mesh" onclick="browsePath('mesh', 'referenceMeshFile', this)">&#128194;</button>
      </div>
      <label>Reference characteristic length (m, optional fallback)</label>
      <input id="referenceCharacteristicLength" type="number" min="0" step="any" placeholder="Auto-detect from object_wall">
      <div class="row">
        <div><label>从阶段</label><select id="fromStage"><option value="">从头开始</option>{''.join(f'<option value="{s}">{s}</option>' for s in STAGES)}</select></div>
        <div><label>到阶段</label><select id="toStage"><option value="">跑到最后</option>{''.join(f'<option value="{s}">{s}</option>' for s in STAGES)}</select></div>
      </div>
      <label class="check"><input id="dryRun" type="checkbox"> dry-run，只生成脚本/计划</label>
      <label class="check"><input id="fullAutoEnv" type="checkbox" checked> 自动设置本机 SolidWorks / SpaceClaim / Fluent 路径</label>
      <button id="fullRunBtn" class="run-action" onclick="runFullWorkflow()">全流程自动运行</button>
      <button id="rangeRunBtn" class="secondary run-action" onclick="runRangeWorkflow()">运行所选阶段范围</button>
      <p class="muted">真实运行会调用商业软件，窗口可能会打开或短暂无响应。当前入口一次只运行一个任务。</p>
      <h2 style="margin-top:22px">分阶段运行</h2>
      <div class="stage-list">{STAGE_BUTTONS}</div>
      <p class="muted">逐步运行时请按顺序执行。每一步会读取同一输出目录中上一步保存的结果。</p>
    </section>
    <div>
      <section>
        <div class="status"><span id="dot" class="dot"></span><strong id="status">等待运行</strong></div>
        <div id="summary" class="muted"></div>
      </section>
      <section style="margin-top:18px">
        <h2>错误诊断中心</h2>
        <button class="secondary" onclick="runDiagnostics()">运行诊断</button>
        <pre id="diagnosticsStatus" style="max-height:260px;margin:8px 0 0">{{}}</pre>
      </section>
      <section style="margin-top:18px">
        <h2>关键输出</h2>
        <table><thead><tr><th>文件</th><th>大小</th><th>打开</th></tr></thead><tbody id="artifacts"></tbody></table>
      </section>
      <section style="margin-top:18px">
        <h2>状态详情</h2>
        <pre id="details">{{}}</pre>
      </section>
    </div>
  </main>
  <script>
    function basePayload() {{
      return {{
        description: document.getElementById('description').value,
        input: document.getElementById('input').value,
        output: document.getElementById('output').value,
        cad_file: document.getElementById('cadFile').value,
        characteristic_length: document.getElementById('characteristicLength').value,
        domain_imitation_enabled: document.getElementById('domainImitationEnabled').checked,
        reference_domain_file: document.getElementById('referenceDomainFile').value,
        manual_flow_direction: document.getElementById('manualFlowDirection').value,
        mesh_imitation_enabled: document.getElementById('meshImitationEnabled').checked,
        reference_mesh_file: document.getElementById('referenceMeshFile').value,
        reference_characteristic_length: document.getElementById('referenceCharacteristicLength').value,
        dry_run: document.getElementById('dryRun').checked,
        full_auto_env: document.getElementById('fullAutoEnv').checked
      }};
    }}
    function deploymentPayload() {{
      return {{
        deploy_spaceclaim_executable: document.getElementById('deploySpaceClaimExecutable').value,
        deploy_fluent_executable: document.getElementById('deployFluentExecutable').value,
        deploy_foreground: document.getElementById('deployForeground').checked,
        deploy_solidworks_enabled: document.getElementById('deploySolidWorksEnabled').checked,
        deploy_spaceclaim_enabled: document.getElementById('deploySpaceClaimEnabled').checked,
        deploy_fluent_meshing_enabled: document.getElementById('deployFluentMeshingEnabled').checked,
        deploy_fluent_solver_enabled: document.getElementById('deployFluentSolverEnabled').checked
      }};
    }}
    function parameterTaskPayload() {{
      return {{
        output: document.getElementById('output').value,
        task_id: document.getElementById('paramTaskId').value,
        geometry_type: document.getElementById('paramGeometryType').value,
        unit: 'm',
        diameter: document.getElementById('paramDiameter').value,
        length: document.getElementById('paramLength').value,
        width: document.getElementById('paramWidth').value,
        height: document.getElementById('paramHeight').value,
        characteristic_length: document.getElementById('paramDiameter').value,
        cad_file: document.getElementById('cadFile').value,
        inlet_velocity: document.getElementById('paramInletVelocity').value,
        attack_angle_deg: document.getElementById('paramAttackAngle').value,
        fluid_density: document.getElementById('paramDensity').value,
        fluid_viscosity: document.getElementById('paramViscosity').value,
        fluid_temperature: '288.15',
        fluid_pressure: '101325',
        upstream_length_ratio: document.getElementById('paramUpstream').value,
        downstream_length_ratio: document.getElementById('paramDownstream').value,
        side_length_ratio: document.getElementById('paramSide').value,
        global_size: document.getElementById('paramGlobalSize').value,
        near_body_size: document.getElementById('paramNearBodySize').value,
        boundary_layer_enabled: document.getElementById('paramBoundaryLayer').checked,
        mesh_layers: document.getElementById('paramLayers').value,
        mesh_growth_rate: document.getElementById('paramGrowthRate').value,
        max_skewness: document.getElementById('paramMaxSkewness').value,
        min_orthogonal_quality: document.getElementById('paramMinOrthogonal').value,
        solver_steady: true,
        solver_type: 'pressure_based',
        turbulence_model: document.getElementById('paramTurbulence').value,
        residual_target: document.getElementById('paramResidualTarget').value,
        max_iterations: document.getElementById('paramMaxIterations').value
      }};
    }}
    async function previewParameterTask() {{
      const res = await fetch('/api/task/preview', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(parameterTaskPayload())
      }});
      const data = await res.json();
      document.getElementById('parameterTaskPreview').textContent = JSON.stringify(data, null, 2);
    }}
    async function saveParameterTask() {{
      const res = await fetch('/api/task/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(parameterTaskPayload())
      }});
      const data = await res.json();
      document.getElementById('parameterTaskPreview').textContent = JSON.stringify(data, null, 2);
      if (data.ok && data.input_file) {{
        document.getElementById('input').value = data.input_file;
        document.getElementById('description').value = '';
      }}
      poll();
    }}
    async function loadParameterTask() {{
      const res = await fetch('/api/task/load', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{input: document.getElementById('input').value}})
      }});
      const data = await res.json();
      document.getElementById('parameterTaskPreview').textContent = JSON.stringify(data, null, 2);
      if (data.ok && data.form) {{
        applyParameterTaskForm(data.form);
      }}
    }}
    function applyParameterTaskForm(form) {{
      const values = {{
        paramTaskId: form.task_id,
        paramGeometryType: form.geometry_type,
        paramDiameter: form.diameter || form.characteristic_length,
        paramLength: form.length,
        paramWidth: form.width,
        paramHeight: form.height,
        paramInletVelocity: form.inlet_velocity,
        paramAttackAngle: form.attack_angle_deg,
        paramDensity: form.fluid_density,
        paramViscosity: form.fluid_viscosity,
        paramUpstream: form.upstream_length_ratio,
        paramDownstream: form.downstream_length_ratio,
        paramSide: form.side_length_ratio,
        paramGlobalSize: form.global_size,
        paramNearBodySize: form.near_body_size,
        paramLayers: form.mesh_layers,
        paramGrowthRate: form.mesh_growth_rate,
        paramMaxSkewness: form.max_skewness,
        paramMinOrthogonal: form.min_orthogonal_quality,
        paramTurbulence: form.turbulence_model,
        paramMaxIterations: form.max_iterations,
        paramResidualTarget: form.residual_target
      }};
      for (const [id, value] of Object.entries(values)) {{
        const element = document.getElementById(id);
        if (element && value !== null && value !== undefined) element.value = value;
      }}
      document.getElementById('paramBoundaryLayer').checked = !!form.boundary_layer_enabled;
    }}
    async function refreshCases() {{
      const data = await (await fetch('/api/cases')).json();
      renderCases(data.cases || []);
    }}
    async function createCase() {{
      const res = await fetch('/api/cases/create', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          name: document.getElementById('caseName').value,
          description: document.getElementById('caseDescription').value,
          tags: document.getElementById('caseTags').value,
          input_source: document.getElementById('input').value
        }})
      }});
      const data = await res.json();
      if (data.case && data.case.output) {{
        document.getElementById('output').value = data.case.relative_output || data.case.output;
      }}
      await refreshCases();
      poll();
    }}
    function selectCase(output) {{
      document.getElementById('output').value = output;
      poll();
    }}
    function renderCases(cases) {{
      document.getElementById('caseList').innerHTML = cases.map(item => {{
        const output = JSON.stringify(String(item.relative_output || item.output || ''));
        return `
          <div class="case-item">
            <strong>${{item.name}}</strong>
            <div class="case-meta">${{item.status}} | ${{item.stage || 'no stage'}} | ${{item.relative_output || item.output}}</div>
            <div class="case-actions">
              <button class="secondary" onclick="selectCase(${{output}})">使用</button>
              <button class="secondary" onclick="selectCase(${{output}}); runDiagnostics()">诊断</button>
            </div>
          </div>
        `;
      }}).join('');
    }}
    async function runDeploymentCheck() {{
      const res = await fetch('/api/deploy/check', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(deploymentPayload())
      }});
      const data = await res.json();
      document.getElementById('deploymentStatus').textContent = JSON.stringify(data, null, 2);
    }}
    async function saveDeploymentConfig() {{
      const res = await fetch('/api/deploy/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(deploymentPayload())
      }});
      const data = await res.json();
      document.getElementById('deploymentStatus').textContent = JSON.stringify(data, null, 2);
    }}
    async function runSoftwareSmokeCheck() {{
      const res = await fetch('/api/deploy/smoke', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(deploymentPayload())
      }});
      const data = await res.json();
      document.getElementById('deploymentStatus').textContent = JSON.stringify(data, null, 2);
    }}
    async function runDiagnostics() {{
      const res = await fetch('/api/diagnose', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{output: document.getElementById('output').value}})
      }});
      const data = await res.json();
      document.getElementById('diagnosticsStatus').textContent = JSON.stringify(data, null, 2);
      poll();
    }}
    async function browsePath(kind, targetId, button) {{
      button.disabled = true;
      try {{
        const res = await fetch(`/api/browse?kind=${{encodeURIComponent(kind)}}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '选择路径失败');
        if (data.path) document.getElementById(targetId).value = data.path;
      }} catch (error) {{
        alert(error.message);
      }} finally {{
        button.disabled = false;
      }}
    }}
    async function previewTask() {{
      const res = await fetch('/api/parse', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{description: document.getElementById('description').value}})
      }});
      const parsed = await res.json();
      const preview = document.getElementById('parsePreview');
      if (parsed.missing_fields && parsed.missing_fields.length) {{
        preview.textContent = '需要补充：\\n- ' + parsed.missing_fields.join('\\n- ');
        return;
      }}
      const task = parsed.task;
      const names = {{sphere: '球体', cylinder: '圆柱', box: '长方体', custom_cad: '自定义 CAD'}};
      const params = Object.entries(task.geometry.parameters).map(([key, value]) => `${{key}}: ${{value}} m`).join('\\n');
      preview.textContent =
        `模型：${{names[task.geometry.type] || task.geometry.type}}\\n` +
        `${{params}}\\n入口速度：${{task.motion.inlet_velocity}} m/s\\n` +
        `攻角：${{task.motion.attack_angle_deg}} 度\\n\\n默认设置：\\n- ${{parsed.assumptions.join('\\n- ')}}`;
    }}
    function runFullWorkflow() {{
      return runWorkflow('', '');
    }}
    function runRangeWorkflow() {{
      return runWorkflow(document.getElementById('fromStage').value, document.getElementById('toStage').value);
    }}
    function runStage(stage) {{
      return runWorkflow(stage, stage);
    }}
    async function runWorkflow(fromStage, toStage) {{
      const payload = {{
        ...basePayload(),
        from_stage: fromStage,
        to_stage: toStage
      }};
      document.querySelectorAll('.run-action').forEach(button => button.disabled = true);
      const res = await fetch('/api/run', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
      if (!res.ok) {{
        alert((await res.json()).error || '启动失败');
        document.querySelectorAll('.run-action').forEach(button => button.disabled = false);
      }}
      poll();
    }}
    async function poll() {{
      const data = await (await fetch('/api/state')).json();
      render(data);
      setTimeout(poll, data.running ? 1200 : 3000);
    }}
    function render(data) {{
      const dot = document.getElementById('dot');
      const status = document.getElementById('status');
      dot.className = 'dot';
      if (data.running) {{ dot.classList.add('run'); status.textContent = '正在运行'; }}
      else if (data.error) {{ dot.classList.add('fail'); status.textContent = '失败'; }}
      else if (data.result) {{ dot.classList.add('ok'); status.textContent = data.result.status === 'success' ? '完成' : '结束但有错误'; }}
      else {{ status.textContent = '等待运行'; }}
      document.querySelectorAll('.run-action').forEach(button => button.disabled = !!data.running);
      const p = data.pipeline || {{}};
      const completed = p.stage_outputs || {{}};
      document.querySelectorAll('.stage-item').forEach(item => {{
        const done = !!completed[item.dataset.stage];
        item.classList.toggle('done', done);
        item.querySelector('.stage-state').textContent = done ? '已完成' : '待运行';
      }});
      document.getElementById('summary').textContent = p.stage ? `阶段: ${{p.stage}} | 状态: ${{p.status}} | 输出: ${{(data.request || {{}}).output || ''}}` : '';
      document.getElementById('details').textContent = JSON.stringify(data.result || data.pipeline || {{error: data.error}}, null, 2);
      document.getElementById('artifacts').innerHTML = (data.artifacts || []).map(a => `<tr><td>${{a.path}}</td><td>${{a.size}}</td><td><a href="${{a.url}}" target="_blank">打开</a></td></tr>`).join('');
    }}
    poll();
    refreshCases();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
