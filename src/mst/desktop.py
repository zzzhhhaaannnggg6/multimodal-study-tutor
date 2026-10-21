"""Private desktop backend. The native parent owns its lifetime via stdin.

No network-facing shutdown API, persistent port, or automatic model resume.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

from .server import create_server


def default_workspace() -> Path:
    if sys.platform != "darwin":
        raise ValueError("此桌面预览版仅支持 macOS。")
    return Path.home() / "Library" / "Application Support" / "Multimodal Study Tutor"


def configure_bundled_tls() -> None:
    if getattr(sys, "frozen", False):
        import certifi
        # Homebrew/system Python certificate paths need not exist on a student's
        # machine. Keep verification enabled using the bundled public roots.
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ.pop("SSL_CERT_DIR", None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, help="Isolated workspace for development checks")
    parser.add_argument("--runtime-check", action="store_true", help="Check bundled PDF reader and verified TLS without network access")
    args = parser.parse_args(argv)
    try:
        configure_bundled_tls()
        if args.runtime_check:
            import ssl
            import pypdf
            context = ssl.create_default_context()
            print(json.dumps({"frozen": bool(getattr(sys, "frozen", False)), "pdf_reader": pypdf.__version__,
                              "tls_roots": len(context.get_ca_certs()), "tls_verify": context.verify_mode == ssl.CERT_REQUIRED,
                              "tls_hostname_check": context.check_hostname}), flush=True)
            return 0
        workspace = (args.workspace or default_workspace()).resolve()
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        server = create_server(workspace, port=0)
    except (OSError, ValueError):
        print(json.dumps({"error": "无法打开课程目录，可能已有应用在使用它。请关闭另一窗口后重试；已有课程不会被删除。"}, ensure_ascii=False), flush=True)
        return 1

    stopping = threading.Event()

    def stop(*_):
        if not stopping.is_set():
            stopping.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    # SIGTERM and parent crash both close the service. Job recovery marks any
    # unfinished generation interrupted; it never silently resends material.
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def watch_parent():
        for line in sys.stdin:
            if line.strip() == "shutdown":
                break
        stop()

    threading.Thread(target=watch_parent, daemon=True).start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/", "pid": os.getpid()}), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
