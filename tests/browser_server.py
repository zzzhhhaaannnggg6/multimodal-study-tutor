"""Browser test fixture service: synthetic guide, disposable private workspace."""
import copy
import base64
import os
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mst.guide import GuideSourceRef, generate_study_guide
from mst.ingest import init_project, ingest_project
from mst.io import project_paths, write_json
from mst.models import LessonMap
from mst.server import create_server
from fake_model_service import FakeModelService, FixtureTeachingProvider
from fake_speech_service import SpeechService
from audio_fixtures import silent_wav

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
with FakeModelService() as model, SpeechService() as speech, tempfile.TemporaryDirectory(prefix="mst-browser-") as directory:
    guide = generate_study_guide(LessonMap.from_json(Path(__file__).resolve().parents[1] / "examples/minimal_course/lesson-map.json"), FixtureTeachingProvider())
    guide.lesson_id = "course::" + "a" * 64
    guide.title = "合成测试课程"
    # Tiny synthetic PNGs keep browser checks independent of PDF extras.
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkJkAAAAASUVORK5CYII=")
    for index, number in enumerate((1, 2, 10)):
        path = Path(directory) / f"derived/rendered/synthetic/page-{number:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(png)
        ref = copy.deepcopy(guide.units[0].source_refs[0])
        ref.ref = f"synthetic::page{number}"
        ref.kind = "material"; ref.page = number; ref.image_path = str(path.relative_to(directory))
        guide.units[0].source_refs.append(ref)
        guide.source_index.append(copy.deepcopy(ref))
    second = copy.deepcopy(guide.units[0])
    second.unit_id = "test::second"
    second.title = "第二个知识点"
    second.prerequisite_ids = [guide.units[0].unit_id]
    second.source_refs = [ref for ref in second.source_refs if not ref.image_path]
    for index, practice in enumerate(second.practice_items):
        practice.unit_id = second.unit_id
        practice.practice_id = f"second::{index}"
    guide.units.append(second)
    recording_paths = [Path(directory) / "合成课堂.wav", Path(directory) / "另一份录音.wav"]
    for index, path in enumerate(recording_paths):
        path.write_bytes(silent_wav(6 + index))
    init_project(directory)
    manifest = ingest_project(directory, recording_paths)
    segments = []
    for index, (start, end, status) in enumerate([(1.25, 3.75, "aligned"), (0.5, 1.5, "pending"), (None, None, "pending")]):
        source = manifest["source_manifest"][index % 2]
        ref = GuideSourceRef(kind="classroom_transcript", label="教师补充" if status == "aligned" else "语音配对待确认",
                             ref=f"fixture::recording::{index}", start=start, end=end, quote=f"合成课堂片段 {index}", status=status)
        guide.source_index.append(ref)
        if status == "aligned":
            guide.units[0].source_refs.append(copy.deepcopy(ref))
        segments.append({"segment_id": ref.ref, "source_id": source["source_id"], "media_id": source["source_id"],
                         "text": ref.quote, "start": start, "end": end, "status": status,
                         "metadata": {"transcription": {"source_sha256": source["sha256"]}}})
    write_json(project_paths(directory)["lesson_map"], {"speech_segments": segments})
    payload = guide.to_dict()
    payload["_test_model_url"] = model.base_url
    payload["_test_speech_url"] = speech.base_url
    write_json(project_paths(directory)["study_guide"], payload)
    server = create_server(directory, port=int(os.environ.get("MST_TEST_PORT", "8877")))
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
