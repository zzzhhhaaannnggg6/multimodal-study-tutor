"""Disposable loopback audio service for SDK, browser, wheel and native checks."""

import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SpeechService:
    def __init__(self):
        self.requests = []
        self.code = 200
        self.fail_on_call = set()
        self.payload = {"text": "最低位对齐后再逐列计算。", "language": "zh", "duration": 4,
                        "segments": [{"id": 0, "start": 1.25, "end": 3.75, "text": "最低位对齐后再逐列计算。", "speaker": "A"}]}
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                message = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
                parts = list(message.iter_parts())
                fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in parts}
                service.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                                         "fields": fields, "filenames": [part.get_filename() for part in parts if part.get_filename()]})
                payload = json.dumps(service.payload, ensure_ascii=False).encode()
                code = 401 if self.path.startswith("/reject/") else 500 if len(service.requests) in service.fail_on_call else service.code
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                if code == 307:
                    self.send_header("Location", service.base_url + "/redirected")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
