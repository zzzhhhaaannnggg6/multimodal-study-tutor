"""Browser test fixture service: synthetic guide, disposable private workspace."""
import copy
import os
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mst.guide import generate_study_guide
from mst.io import project_paths
from mst.models import LessonMap
from mst.server import create_server

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
with tempfile.TemporaryDirectory(prefix="mst-browser-") as directory:
    guide = generate_study_guide(LessonMap.from_json(Path(__file__).resolve().parents[1] / "examples/minimal_course/lesson-map.json"))
    guide.lesson_id = "course::" + "a" * 64
    guide.title = "合成测试课程"
    second = copy.deepcopy(guide.units[0])
    second.unit_id = "test::second"
    second.title = "第二个知识点"
    for index, practice in enumerate(second.practice_items):
        practice.unit_id = second.unit_id
        practice.practice_id = f"second::{index}"
    guide.units.append(second)
    guide.write_json(project_paths(directory)["study_guide"])
    server = create_server(directory, port=int(os.environ.get("MST_TEST_PORT", "8877")))
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
