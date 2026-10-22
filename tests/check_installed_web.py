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
from fake_model_service import FakeModelService

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
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
print("Installed wheel: HTML, JavaScript and CSS served outside checkout.")
print("Installed wheel: saved material revision and extraction receipts verified.")
print("Installed wheel: explicit model generation verified against loopback-only synthetic API.")
for name in ("number-conversion-v1.json", "number-notation-v1.json"):
    bank = Path(__file__).resolve().parents[1] / "evals" / name
    evaluation = evaluate_suite(bank)
    assert evaluation["failed"] == 0, evaluation
    print(f"Installed wheel: {evaluation['suite_id']} {evaluation['passed']}/{evaluation['total']} supplied synthetic numerical cases passed.")
