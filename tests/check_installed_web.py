"""Run with an installed wheel's Python from outside the source checkout."""
import http.client
import sys
import tempfile
import threading
from pathlib import Path

from mst.server import create_server, web_directory

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
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
print("Installed wheel: HTML, JavaScript and CSS served outside checkout.")
