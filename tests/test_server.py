from __future__ import annotations

import http.client
import json
import threading

import pytest

from mst.io import active_project_dir
from mst.server import create_server
from test_jobs import uploads


@pytest.fixture
def service(tmp_path):
    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(5)


def request(service, method, path, value=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", service.server_port, timeout=5)
    connection.request(method, path, json.dumps(value) if value is not None else None,
                       {"Content-Type": "application/json", **(headers or {})})
    response = connection.getresponse()
    body = response.read()
    status = response.status
    connection.close()
    return status, body


def test_http_supplement_uses_explicit_retained_files_and_reports_each_outcome(service):
    first = service.jobs.submit(uploads())
    assert service.jobs.events[first["job_id"]].wait(5)
    code, body = request(service, "POST", f"/api/jobs/{first['job_id']}/revise",
                         {"keep": [first["files"][0]["stored_name"]], "files": [{"name": "录音.mp3", "data": "YXVkaW8="}]})
    assert code == 202
    revised = json.loads(body)["job"]
    assert service.jobs.events[revised["job_id"]].wait(5)
    code, body = request(service, "GET", f"/api/jobs/{revised['job_id']}")
    revised = json.loads(body)["job"]
    assert code == 200 and revised["status"] == "succeeded"
    assert revised["materials"][-1]["status"] == "transcription-needed"
    for payload in ({"keep": ["../../private"]}, {"keep": []}, {"keep": None}):
        assert request(service, "POST", f"/api/jobs/{first['job_id']}/revise", payload)[0] == 400
    assert request(service, "POST", f"/api/jobs/{first['job_id']}/revise", {"keep": []},
                   {"Origin": "https://example.com"})[0] == 403


def test_failed_scan_pages_can_be_previewed_without_publishing_or_exposing_other_files(service):
    import base64
    pytest.importorskip("pypdfium2")
    pytest.importorskip("pypdf")
    from pdf_fixtures import visual_pdf
    first = service.jobs.submit(uploads())
    assert service.jobs.events[first["job_id"]].wait(10)
    previous = request(service, "GET", "/study-guide.json")[1]
    job = service.jobs.submit([{"name": "扫描.pdf", "data": base64.b64encode(visual_pdf(2, text=False)).decode()}])
    assert service.jobs.events[job["job_id"]].wait(10)
    job = service.jobs.get(job["job_id"])
    assert job["status"] == "failed" and request(service, "GET", "/study-guide.json")[1] == previous
    image = job["materials"][0]["preview_pages"][0]["image_path"]
    route = f"/api/jobs/{job['job_id']}/assets/"
    from urllib.parse import quote
    code, png = request(service, "GET", route + quote(image))
    assert code == 200 and png.startswith(b"\x89PNG\r\n\x1a\n")
    assert request(service, "GET", route + "derived/lesson-map.json")[0] == 403
    assert request(service, "GET", f"/api/jobs/{job['job_id']}/guide")[0] == 409
    assert request(service, "GET", f"/api/exports/html?run={job['job_id']}")[0] == 400


@pytest.mark.parametrize("link_root", [False, True])
def test_preview_route_rejects_symlinks_escaping_the_course(service, tmp_path, link_root):
    job = service.jobs.submit(uploads())
    assert service.jobs.events[job["job_id"]].wait(5)
    root = service.jobs.active_root()
    rendered = root / "derived/rendered"
    private = tmp_path / "private.png"
    private.write_bytes(b"private-outside-course")
    if link_root:
        rendered.symlink_to(tmp_path, target_is_directory=True)
    else:
        rendered.mkdir(parents=True)
        (rendered / "private.png").symlink_to(private)
        (rendered / "other.txt").write_text("not a preview")
        assert request(service, "GET", "/assets/derived/rendered/other.txt")[0] == 403
    for prefix in ("/assets/", f"/api/jobs/{job['job_id']}/assets/"):
        code, body = request(service, "GET", prefix + "derived/rendered/private.png")
        assert code == 403 and b"private-outside-course" not in body


def test_http_upload_disconnect_status_refresh_exports_and_asset_boundary(service):
    assert request(service, "GET", "/study-guide.json")[0] == 404
    code, body = request(service, "POST", "/api/jobs", {"files": uploads(), "subject": "generic"})
    assert code == 202
    job = json.loads(body)["job"]
    assert service.jobs.events[job["job_id"]].wait(5)
    code, body = request(service, "GET", f"/api/jobs/{job['job_id']}")
    assert code == 200 and json.loads(body)["job"]["status"] == "succeeded"
    assert request(service, "GET", "/study-guide.json")[0] == 200
    assert request(service, "GET", "/lesson-map.json")[0] == 200
    for suffix in ("md", "html", "json"):
        code, body = request(service, "GET", f"/api/exports/{suffix}")
        assert code == 200 and body
    root = active_project_dir(service.jobs.project)
    rendered = root / "derived/rendered/p001.png"
    rendered.parent.mkdir(parents=True, exist_ok=True)
    rendered.write_bytes(b"synthetic-image")
    assert request(service, "GET", "/assets/derived/rendered/p001.png")[1] == b"synthetic-image"
    assert request(service, "GET", "/assets/derived/lesson-map.json")[0] == 403
    assert request(service, "GET", "/assets/derived/rendered/../../../project.json")[0] == 403
    assert request(service, "GET", "/api/jobs/" + "f" * 32)[0] == 404
    second = service.jobs.submit(uploads("# 第二次导入\n新材料"))
    assert service.jobs.events[second["job_id"]].wait(5)
    code, body = request(service, "GET", f"/api/jobs/{job['job_id']}/assets/derived/rendered/p001.png")
    assert code == 200 and body == b"synthetic-image"
    code, body = request(service, "GET", f"/api/jobs/{job['job_id']}/guide")
    original = json.loads(body)
    assert code == 200 and original["_local_run_id"] == job["job_id"]
    code, body = request(service, "GET", f"/api/exports/json?run={job['job_id']}")
    assert code == 200 and json.loads(body)["lesson_id"] == original["lesson_id"]
    assert json.loads(request(service, "GET", "/study-guide.json")[1])["lesson_id"] != original["lesson_id"]


def test_static_assets_and_local_service_boundaries(service):
    for path in ("/", "/progress.js", "/app.js", "/styles.css"):
        assert request(service, "GET", path)[0] == 200
    assert request(service, "GET", "/api/jobs/latest", headers={"Host": "attacker.example"})[0] == 403
    assert request(service, "POST", "/api/jobs", {"files": uploads()}, {"Origin": "https://other.example"})[0] == 403
    assert request(service, "POST", "/api/jobs", {"files": uploads()}, {"Content-Type": "text/plain"})[0] == 400
    assert service.jobs.latest() is None
    assert request(service, "GET", "/../pyproject.toml")[0] == 404


def test_progress_is_persistent_and_stale_tabs_cannot_overwrite(service):
    key = "a" * 64
    path = f"/api/progress/{key}"
    progress = {"version": 2, "course_key": key, "drafts": {"q1": {"text": "中文公式 x² 与代码 addi x5, x0, 10"}}}
    assert json.loads(request(service, "GET", path)[1])["revision"] == 0
    assert request(service, "POST", path, {"progress": progress, "revision": 0})[0] == 200
    assert json.loads(request(service, "GET", path)[1])["progress"] == progress
    assert request(service, "POST", path, {"progress": {**progress, "drafts": {}}, "revision": 0})[0] == 409
    assert json.loads(request(service, "GET", path)[1])["progress"] == progress
    assert request(service, "POST", "/api/progress/" + "b" * 64, {"progress": progress})[0] == 400
