"""Dependency-free local server for the bundled student study route."""

from __future__ import annotations

import http.server
import base64
import json
import threading
import webbrowser
from pathlib import Path

from .guide import generate_project_guide
from .ingest import ingest_project
from .io import project_paths, read_json
from .reconstruct import build_scaffold


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(format % args)


def serve(project_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    """Serve ``web/`` and expose the selected guide/map plus local upload API."""

    project = Path(project_dir).resolve()
    package_web = Path(__file__).resolve().parents[2] / "web"
    if not package_web.exists():
        raise FileNotFoundError(f"web assets are missing: {package_web}")
    map_path = project_paths(project)["lesson_map"]
    if not map_path.exists() and (project / "lesson-map.json").exists():
        map_path = project / "lesson-map.json"
    map_data = read_json(map_path) if map_path.exists() else None
    guide_path = project_paths(project)["study_guide"]
    if not guide_path.exists() and (project / "study-guide.json").exists():
        guide_path = project / "study-guide.json"
    guide_data = read_json(guide_path) if guide_path.exists() else None
    state: dict[str, object] = {"map": map_data, "guide": guide_data}

    def send_json(handler: http.server.BaseHTTPRequestHandler, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    class Handler(_Handler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(package_web), **kwargs)

        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0]
            if route == "/lesson-map.json" and state["map"] is not None:
                send_json(self, state["map"])
                return
            if route == "/study-guide.json" and state["guide"] is not None:
                send_json(self, state["guide"])
                return
            super().do_GET()

        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/api/generate":
                send_json(self, {"error": "unknown API route"}, 404)
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 150 * 1024 * 1024:
                    raise ValueError("请求体为空或超过 150 MB")
                raw = self.rfile.read(content_length)
                request = json.loads(raw.decode("utf-8"))
                rows = request.get("files", []) if isinstance(request, dict) else []
                if not isinstance(rows, list) or not rows:
                    raise ValueError("至少需要一个课程文件")
                upload_dir = project / "sources" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                saved: list[Path] = []
                for index, row in enumerate(rows, 1):
                    if not isinstance(row, dict):
                        continue
                    name = Path(str(row.get("name", ""))).name
                    encoded = row.get("data", "")
                    if not name or not isinstance(encoded, str):
                        continue
                    suffix = Path(name).suffix.lower()
                    if not suffix:
                        raise ValueError(f"文件缺少扩展名：{name}")
                    target = upload_dir / f"{index:03d}-{name}"
                    target.write_bytes(base64.b64decode(encoded, validate=True))
                    saved.append(target)
                if not saved:
                    raise ValueError("没有可保存的课程文件")
                ingest_project(project, saved)
                build_scaffold(project)
                guide = generate_project_guide(project)
                state["map"] = read_json(project_paths(project)["lesson_map"])
                state["guide"] = guide.to_dict()
                send_json(self, {"guide": state["guide"], "report": guide.report.to_dict()})
            except Exception as exc:
                send_json(self, {"error": str(exc)}, 400)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Serving study workspace at {url}; press Ctrl-C to stop")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()
