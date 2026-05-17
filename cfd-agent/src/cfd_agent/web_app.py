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
from urllib.parse import parse_qs, unquote, urlparse

from cfd_agent.core.models import load_simulation_task
from cfd_agent.core.orchestrator import run_simulation


ROOT = Path.cwd().resolve()
DEFAULT_INPUT = "src/cfd_agent/examples/sphere_external_flow.json"
DEFAULT_OUTPUT = "outputs/sphere_001"
STAGES = ["validate", "solidworks", "spaceclaim", "meshing", "fluent_setup", "solver", "postprocess", "report"]


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
        elif parsed.path == "/files":
            self._send_file(parse_qs(parsed.query).get("path", [""])[0])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
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
        if payload.get("full_auto_env", True):
            os.environ.setdefault("SOLIDWORKS_ENABLED", "true")
            os.environ.setdefault("SPACECLAIM_ENABLED", "true")
            os.environ.setdefault("SPACECLAIM_EXECUTABLE", r"D:\Program Files\ANSYS Inc\v221\scdm\SpaceClaim.exe")
            os.environ.setdefault("FLUENT_EXECUTABLE", r"D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe")
            os.environ.setdefault("FLUENT_SOLVER_ENABLED", "true")
            os.environ.setdefault("CFD_AGENT_GMSH_FALLBACK", "true")

        task = load_simulation_task(_safe_path(payload.get("input", DEFAULT_INPUT)))
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
        output_dir / "meshing" / "mesh.msh.h5",
        output_dir / "meshing" / "mesh_case.cas.h5",
        output_dir / "fluent" / "case.cas.h5",
        output_dir / "fluent" / "case.dat.h5",
        output_dir / "fluent" / "data.dat.h5",
        output_dir / "postprocess" / "residuals.csv",
        output_dir / "postprocess" / "forces.csv",
        output_dir / "report" / "report.md",
    ]
    artifacts = []
    for file in files:
        path = file if file.is_absolute() else ROOT / file
        if path.exists():
            rel = path.resolve().relative_to(ROOT).as_posix()
            artifacts.append({"name": path.name, "path": rel, "size": path.stat().st_size, "url": f"/files?path={rel}"})
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
    input, select {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 9px 10px; font-size: 13px; background: #fff; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .check {{ display: flex; align-items: center; gap: 8px; margin-top: 12px; color: #334155; font-size: 13px; }}
    .check input {{ width: auto; }}
    button {{ width: 100%; border: 0; border-radius: 6px; background: #2563eb; color: white; padding: 11px 12px; font-size: 14px; font-weight: 700; cursor: pointer; margin-top: 16px; }}
    button:disabled {{ background: #94a3b8; cursor: default; }}
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
      <label>输入任务 JSON</label>
      <input id="input" value="{DEFAULT_INPUT}">
      <label>输出目录</label>
      <input id="output" value="{DEFAULT_OUTPUT}">
      <div class="row">
        <div><label>从阶段</label><select id="fromStage"><option value="">从头开始</option>{''.join(f'<option value="{s}">{s}</option>' for s in STAGES)}</select></div>
        <div><label>到阶段</label><select id="toStage"><option value="">跑到最后</option>{''.join(f'<option value="{s}">{s}</option>' for s in STAGES)}</select></div>
      </div>
      <label class="check"><input id="dryRun" type="checkbox"> dry-run，只生成脚本/计划</label>
      <label class="check"><input id="fullAutoEnv" type="checkbox" checked> 自动设置本机 SolidWorks / SpaceClaim / Fluent 路径</label>
      <button id="runBtn" onclick="runWorkflow()">开始运行</button>
      <p class="muted">真实运行会调用商业软件，窗口可能会打开或短暂无响应。当前入口一次只运行一个任务。</p>
    </section>
    <div>
      <section>
        <div class="status"><span id="dot" class="dot"></span><strong id="status">等待运行</strong></div>
        <div id="summary" class="muted"></div>
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
    async function runWorkflow() {{
      const payload = {{
        input: document.getElementById('input').value,
        output: document.getElementById('output').value,
        from_stage: document.getElementById('fromStage').value,
        to_stage: document.getElementById('toStage').value,
        dry_run: document.getElementById('dryRun').checked,
        full_auto_env: document.getElementById('fullAutoEnv').checked
      }};
      document.getElementById('runBtn').disabled = true;
      const res = await fetch('/api/run', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(payload)}});
      if (!res.ok) alert((await res.json()).error || '启动失败');
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
      document.getElementById('runBtn').disabled = !!data.running;
      const p = data.pipeline || {{}};
      document.getElementById('summary').textContent = p.stage ? `阶段: ${{p.stage}} | 状态: ${{p.status}} | 输出: ${{(data.request || {{}}).output || ''}}` : '';
      document.getElementById('details').textContent = JSON.stringify(data.result || data.pipeline || {{error: data.error}}, null, 2);
      document.getElementById('artifacts').innerHTML = (data.artifacts || []).map(a => `<tr><td>${{a.path}}</td><td>${{a.size}}</td><td><a href="${{a.url}}" target="_blank">打开</a></td></tr>`).join('');
    }}
    poll();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
