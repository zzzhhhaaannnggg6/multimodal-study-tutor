"""Run with an installed wheel's Python from outside the source checkout."""
import http.client
import base64
import json
import sys
import tempfile
import threading
from pathlib import Path

from mst.server import create_server, web_directory
from mst.evaluation import evaluate_suite
from mst.ingest import ingest_project, init_project, transcribe_project_audio
from mst.io import project_paths, read_json
from mst.reconstruct import build_scaffold
from fake_model_service import FakeModelService
from fake_speech_service import SpeechService

assert Path(sys.prefix).resolve() in web_directory().resolve().parents, web_directory()
with tempfile.TemporaryDirectory(prefix="mst-installed-") as project:
    server = create_server(project, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path, marker in [("/", b"progress.js"), ("/app.js", b"loadGuide"), ("/progress.js", b"reconcile"), ("/styles.css", b"answer-label")]:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", path)
            response = connection.getresponse()
            assert response.status == 200, (path, response.status)
            assert marker in response.read(), path
            connection.close()
        first = server.jobs.submit([{"name": "synthetic.md", "data": base64.b64encode("# 进制\n把二进制 101 转换为十进制。".encode()).decode()}])
        assert server.jobs.events[first["job_id"]].wait(10)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", f"/api/jobs/{first['job_id']}/revise", json.dumps({"keep": [first["files"][0]["stored_name"]]}), {"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 202, response.read()
        revised = json.loads(response.read())["job"]
        connection.close()
        assert server.jobs.events[revised["job_id"]].wait(10)
        revised = server.jobs.get(revised["job_id"])
        assert revised["status"] == "succeeded", revised
        assert revised["materials"][0]["status"] == "text-read"
        assert revised["course_id"] == server.jobs.get(first["job_id"])["course_id"]
        with FakeModelService() as model:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            body = {"files": [{"name": "synthetic-causal.md", "data": base64.b64encode("# 因果解释\n解释变化需要检查条件、机制和对照证据。".encode()).decode()}],
                    "generation": {"provider": "compatible", "base_url": model.base_url, "model": "synthetic", "api_key": "", "consent": True}}
            connection.request("POST", "/api/jobs", json.dumps(body), {"Content-Type": "application/json"})
            response = connection.getresponse()
            assert response.status == 202, response.read()
            generated = json.loads(response.read())["job"]
            connection.close()
            assert server.jobs.events[generated["job_id"]].wait(10)
            generated = server.jobs.get(generated["job_id"])
            assert generated["status"] == "succeeded", generated
            assert generated["generation"]["stats"]["checked_units"] == 1
            assert len(model.requests) == 2
        with SpeechService() as speech:
            files = [{"name": "source.md", "data": base64.b64encode("# 进制\n把二进制 101 转换为十进制。".encode()).decode()},
                     {"name": "synthetic.mp3", "data": base64.b64encode(b"installed-wheel-synthetic-audio").decode()}]
            def submit(path, value):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("POST", path, json.dumps(value), {"Content-Type": "application/json"})
                response = connection.getresponse()
                raw = response.read()
                assert response.status == 202, raw
                job = json.loads(raw)["job"]
                connection.close()
                assert server.jobs.events[job["job_id"]].wait(10)
                job = server.jobs.get(job["job_id"])
                assert job["status"] == "succeeded", job
                return job
            audio_job = submit("/api/jobs", {"files": files, "speech": {"provider": "compatible", "base_url": speech.base_url, "model": "whisper-1", "api_key": "", "consent": True}})
            assert audio_job["speech"]["stats"]["requests"] == 1 and audio_job["materials"][1]["timed_segment_count"] == 1
            cached = submit(f"/api/jobs/{audio_job['job_id']}/revise", {"keep": [item["stored_name"] for item in audio_job["files"]], "speech": {"provider": "none"}})
            assert cached["materials"][1]["timed_segment_count"] == 1
            assert len(speech.requests) == 1 and speech.requests[0]["fields"]["file"] == b"installed-wheel-synthetic-audio"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
print("Installed wheel: HTML, JavaScript and CSS served outside checkout.")
print("Installed wheel: saved material revision and extraction receipts verified.")
print("Installed wheel: explicit model generation verified against loopback-only synthetic API.")
print("Installed wheel: explicit audio transcription and local-only revision verified without a speech SDK.")
with tempfile.TemporaryDirectory(prefix="mst-installed-audio-") as directory:
    root = Path(directory)
    project = root / "course"
    recordings = [root / "part-1.mp3", root / "part-2.mp4"]
    for path in recordings:
        path.write_bytes(b"synthetic placeholder; no real audio or remote service")
    init_project(project)
    ingest_project(project, recordings)
    build_scaffold(project)
    class SyntheticSpeech:
        name = "synthetic-speech"
        calls = 0
        def transcribe(self, path):
            self.calls += 1
            return [{"segment_id": "speech::0001", "text": "说明来自 " + Path(path).name, "start": 1, "end": 3}]
    speech = SyntheticSpeech()
    assert transcribe_project_audio(project, speech) == 2
    assert speech.calls == 2
    assert transcribe_project_audio(project, speech) == 0
    assert speech.calls == 2
    build_scaffold(project)
    assert transcribe_project_audio(project, speech) == 2
    assert speech.calls == 2
    rows = read_json(project_paths(project)["lesson_map"])["speech_segments"]
    assert len({row["segment_id"] for row in rows}) == 2
    assert len({row["source_id"] for row in rows}) == 2
print("Installed wheel: both recordings retained; repeat and scaffold rebuild made no additional speech calls.")
for name in ("number-conversion-v1.json", "number-notation-v1.json", "binary-arithmetic-v1.json"):
    bank = Path(__file__).resolve().parents[1] / "evals" / name
    evaluation = evaluate_suite(bank)
    assert evaluation["failed"] == 0, evaluation
    print(f"Installed wheel: {evaluation['suite_id']} {evaluation['passed']}/{evaluation['total']} supplied synthetic numerical cases passed.")
