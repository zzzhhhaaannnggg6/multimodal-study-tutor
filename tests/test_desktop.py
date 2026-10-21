"""Desktop lifetime checks run without macOS UI, on the source backend."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from mst.desktop import configure_bundled_tls, default_workspace
from mst.server import web_directory


def launch(workspace):
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.Popen([sys.executable, "-m", "mst.desktop", "--workspace", str(workspace)],
                             cwd="/tmp", env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert select.select([child.stdout], [], [], 10)[0], "backend did not become ready"
    info = json.loads(child.stdout.readline())
    return child, info


def call(base, route, payload=None):
    request = Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def stop(child, mode="shutdown"):
    if child.poll() is None:
        if mode == "shutdown":
            child.stdin.write(b"shutdown\n"); child.stdin.flush()
        elif mode == "eof":
            child.stdin.close()
        else:
            child.terminate()
    assert child.wait(5) == 0, child.stderr.read().decode()


@pytest.mark.parametrize("mode", ["shutdown", "eof", "signal"])
def test_backend_parent_lifetime_and_restart_preserve_course_and_answers(tmp_path, mode):
    from test_jobs import uploads
    child, info = launch(tmp_path)
    try:
        assert info["url"].startswith("http://127.0.0.1:") and info["pid"] == child.pid
        job = call(info["url"], "api/jobs", {"files": uploads()})["job"]
        for _ in range(100):
            record = call(info["url"], "api/jobs/" + job["job_id"])["job"]
            if record["status"] not in {"queued", "running"}:
                break
            time.sleep(0.03)
        assert record["status"] == "succeeded"
        guide = call(info["url"], "study-guide.json")
        key = "c" * 64
        progress = {"version": 2, "course_key": key, "drafts": {"answer": "刚写的答案 x²"}}
        assert call(info["url"], f"api/progress/{key}", {"revision": 0, "progress": progress})["revision"] == 1
    finally:
        stop(child, mode)
    reopened, ready = launch(tmp_path)
    try:
        assert call(ready["url"], "study-guide.json") == guide
        assert call(ready["url"], f"api/progress/{key}")["progress"] == progress
        assert call(ready["url"], "api/jobs/latest")["job"]["job_id"] == job["job_id"]
    finally:
        stop(reopened)


def test_backend_refuses_concurrent_owner_without_exposing_paths(tmp_path):
    child, _ = launch(tmp_path)
    try:
        other, failure = launch(tmp_path)
        assert other.wait(5) == 1
        assert "error" in failure and str(tmp_path) not in failure["error"]
        assert "另一窗口" in failure["error"]
    finally:
        stop(child)


def test_frozen_web_assets_never_fall_back_to_developer_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(FileNotFoundError, match="应用"):
        web_directory()
    (tmp_path / "web").mkdir()
    (tmp_path / "web/index.html").touch()
    assert web_directory() == tmp_path / "web"


def test_desktop_data_path_is_stable_outside_application(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert default_workspace() == Path.home() / "Library/Application Support/Multimodal Study Tutor"


def test_frozen_tls_uses_bundled_roots_without_disabling_verification(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setitem(sys.modules, "certifi", SimpleNamespace(where=lambda: "/synthetic/bundled/roots.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", "/synthetic/unavailable")
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/unavailable.pem")
    configure_bundled_tls()
    assert os.environ["SSL_CERT_FILE"] == "/synthetic/bundled/roots.pem"
    assert "SSL_CERT_DIR" not in os.environ
