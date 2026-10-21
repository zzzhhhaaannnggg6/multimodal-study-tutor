"""Local student UI with durable jobs and same-origin write boundaries."""

from __future__ import annotations

import http.server
import json
import re
import threading
import webbrowser
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .io import project_paths, read_json, write_json
from .jobs import JobBusyError, JobManager
from .profiles import PROFILES


def web_directory() -> Path:
    checkout = Path(__file__).resolve().parents[2] / "web"
    if (checkout / "index.html").is_file():
        return checkout
    package = distribution("multimodal-study-tutor")
    for item in package.files or []:
        if str(item).endswith("share/multimodal-study-tutor/web/index.html"):
            return Path(package.locate_file(item)).resolve().parent
    raise FileNotFoundError("学习页面文件缺失，请重新安装听课助手。")


def create_server(project_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, *, runner=None, provider_factory=None) -> http.server.ThreadingHTTPServer:
    """Create a local service. Uploads never mutate a published run."""
    project = Path(project_dir).resolve()
    package_web = web_directory()
    jobs = JobManager(project, **({"runner": runner} if runner else {}), **({"provider_factory": provider_factory} if provider_factory else {}))
    progress_lock = threading.Lock()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(package_web), **kwargs)

        def log_message(self, format, *args):
            pass  # Keep source names and request bodies out of logs.

        def reply(self, value, status=200):
            self.send_payload(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

        def send_payload(self, payload, content_type, status=200, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Closing a tab must not cancel a job.

        def trusted_host(self):
            allowed = {"127.0.0.1", "localhost", "[::1]", host}
            return self.headers.get("Host", "") in {f"{name}:{self.server.server_port}" for name in allowed}

        def request_json(self):
            if not self.trusted_host():
                raise PermissionError("请从本地听课助手页面操作。")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                raise PermissionError("请从本地听课助手页面操作。")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请求格式应为 JSON。")
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 140 * 1024 * 1024:
                raise ValueError("材料过大，请将每次上传控制在 100 MB 内。")
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("请求格式无效。")
            return value

        def result_root(self, run_id):
            job = jobs.get(run_id) if isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id) else None
            if not job or job["status"] != "succeeded":
                raise ValueError("这次讲义尚未生成成功。")
            root = (jobs.directory / run_id / "workspace").resolve()
            if not root.is_relative_to(jobs.directory.resolve()):
                raise PermissionError("课程路径无效。")
            return root

        def guide_payload(self, root):
            value = read_json(project_paths(root)["study_guide"])
            if root != project:
                value["_local_run_id"] = root.parent.name
            return value

        def do_GET(self):
            if not self.trusted_host():
                self.reply({"error": "请使用本地服务地址。"}, 403)
                return
            route = unquote(urlsplit(self.path).path)
            try:
                if route == "/api/jobs/latest":
                    self.reply({"job": jobs.latest()})
                elif match := re.fullmatch(r"/api/jobs/([0-9a-f]{32})(/guide)?", route):
                    job = jobs.get(match[1])
                    if not job:
                        self.reply({"error": "未找到这次生成记录。"}, 404)
                    elif match[2]:
                        if job["status"] != "succeeded":
                            self.reply({"error": "这次讲义尚未生成成功。"}, 409)
                        else:
                            self.reply(self.guide_payload(self.result_root(match[1])))
                    else:
                        self.reply({"job": job})
                elif route == "/api/profiles":
                    self.reply({"profiles": list(PROFILES)})
                elif match := re.fullmatch(r"/api/progress/([0-9a-f]{64})", route):
                    path = project / ".study-progress" / f"{match[1]}.json"
                    self.reply(read_json(path) if path.exists() else {"progress": None, "revision": 0})
                elif route in {"/study-guide.json", "/lesson-map.json"}:
                    root = jobs.active_root()
                    path = project_paths(root)["study_guide" if route.startswith("/study") else "lesson_map"]
                    if not path.exists():
                        path = root / route[1:]
                    value = read_json(path)
                    if route == "/study-guide.json" and root != project:
                        value["_local_run_id"] = root.parent.name
                    self.reply(value)
                elif match := re.fullmatch(r"/api/exports/(md|html|json)", route):
                    from .export import export_study_guide
                    with jobs.lock:
                        run_id = parse_qs(urlsplit(self.path).query).get("run", [None])[0]
                        path = export_study_guide(self.result_root(run_id) if run_id else jobs.active_root(), format=match[1])
                        self.send_payload(path.read_bytes(), "application/octet-stream", filename=f"study-guide.{match[1]}")
                elif route.startswith("/assets/") or re.fullmatch(r"/api/jobs/[0-9a-f]{32}/assets/.+", route):
                    if route.startswith("/api/jobs/"):
                        _, _, _, run_id, _, relative = route.split("/", 5)
                        root = self.result_root(run_id)
                    else:
                        root, relative = jobs.active_root(), route[len("/assets/"):]
                    target = (root / relative).resolve()
                    if not target.is_relative_to((root / "derived" / "rendered").resolve()):
                        raise PermissionError("只能查看当前课程的渲染页面。")
                    self.send_payload(target.read_bytes(), {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(target.suffix, "application/octet-stream"))
                elif route in {"/", "/index.html", "/app.js", "/progress.js", "/styles.css"}:
                    super().do_GET()
                else:
                    self.reply({"error": "页面不存在。"}, 404)
            except PermissionError as exc:
                self.reply({"error": str(exc)}, 403)
            except FileNotFoundError:
                self.reply({"error": "还没有可用讲义，请先导入材料。"}, 404)
            except (ValueError, OSError) as exc:
                self.reply({"error": str(exc)}, 400)

        def do_POST(self):
            try:
                request = self.request_json()
                route = urlsplit(self.path).path
                if route in {"/api/jobs", "/api/generate"}:
                    # /api/generate is retained as an asynchronous alias.
                    self.reply({"job": jobs.submit(request.get("files"), request.get("subject", "generic"), generation=request.get("generation"))}, 202)
                elif match := re.fullmatch(r"/api/jobs/([0-9a-f]{32})/retry", route):
                    self.reply({"job": jobs.retry(match[1], generation=request.get("generation"))}, 202)
                elif match := re.fullmatch(r"/api/jobs/([0-9a-f]{32})/revise", route):
                    self.reply({"job": jobs.revise(match[1], request.get("keep"), request.get("files", []), generation=request.get("generation"))}, 202)
                elif match := re.fullmatch(r"/api/progress/([0-9a-f]{64})", route):
                    progress = request.get("progress")
                    if len(json.dumps(request)) > 1024 * 1024 or not isinstance(progress, dict) or progress.get("version") != 2 or progress.get("course_key") != match[1]:
                        raise ValueError("学习记录格式无效或超过 1 MB。")
                    path = project / ".study-progress" / f"{match[1]}.json"
                    with progress_lock:
                        current = read_json(path) if path.exists() else {"revision": 0}
                        if request.get("revision", 0) != current["revision"]:
                            self.reply({"error": "另一个页面已更新进度，本页记录仍保留在浏览器。", **current}, 409)
                            return
                        value = {"revision": current["revision"] + 1, "progress": progress}
                        write_json(path, value)
                    self.reply(value)
                else:
                    self.reply({"error": "操作不存在。"}, 404)
            except JobBusyError as exc:
                self.reply({"error": str(exc), "job": exc.job}, 409)
            except PermissionError as exc:
                self.reply({"error": str(exc)}, 403)
            except (ValueError, OSError) as exc:
                self.reply({"error": str(exc)}, 400)

    class StudyServer(http.server.ThreadingHTTPServer):
        def server_close(self):
            jobs.close()
            super().server_close()

    try:
        server = StudyServer((host, port), Handler)
    except Exception:
        jobs.close()
        raise
    server.jobs = jobs
    return server


def serve(project_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = create_server(project_dir, host, port)
    url = f"http://{host}:{server.server_port}/"
    print(f"自学讲义已打开：{url}；关闭此窗口会停止本地服务。")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
