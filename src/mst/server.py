"""Dependency-free local server for the bundled timeline demo."""

from __future__ import annotations

import http.server
import json
import threading
import webbrowser
from pathlib import Path

from .io import project_paths, read_json


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(format % args)


def serve(project_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    """Serve ``web/`` and expose the selected lesson map as ``/lesson-map.json``."""

    project = Path(project_dir).resolve()
    package_web = Path(__file__).resolve().parents[2] / "web"
    if not package_web.exists():
        raise FileNotFoundError(f"web assets are missing: {package_web}")
    map_path = project_paths(project)["lesson_map"]
    if not map_path.exists() and (project / "lesson-map.json").exists():
        map_path = project / "lesson-map.json"
    map_data = read_json(map_path) if map_path.exists() else None
    class Handler(_Handler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(package_web), **kwargs)

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] == "/lesson-map.json" and map_data is not None:
                payload = json.dumps(map_data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

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
