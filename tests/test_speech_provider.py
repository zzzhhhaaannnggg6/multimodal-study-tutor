"""Actual SDK multipart requests to loopback; no real recording or paid call."""

import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from mst.providers import OpenAISpeechProvider
from mst.speech import MAX_SPEECH_BYTES, SpeechRequestError, transcription_response


class SpeechService:
    def __init__(self):
        self.requests = []
        self.code = 200
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
                self.send_response(service.code)
                self.send_header("Content-Type", "application/json")
                if service.code == 307:
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


@pytest.mark.parametrize("model,format_,extra", [(None, "verbose_json", {"timestamp_granularities[]": b"segment"}),
    ("gpt-4o-transcribe", "json", {}), ("gpt-4o-mini-transcribe", "json", {}),
    ("gpt-4o-transcribe-diarize", "diarized_json", {"chunking_strategy": b"auto"}),
    ("explicit-user-model", "json", {})])
def test_actual_sdk_upload_preserves_user_model_filename_bytes_and_request_format(tmp_path, monkeypatch, model, format_, extra):
    pytest.importorskip("openai")
    recording = tmp_path / "课堂录音.mp3"
    recording.write_bytes(b"SYNTHETIC: no real audio or teacher data")
    with SpeechService() as service:
        monkeypatch.setenv("OPENAI_BASE_URL", service.base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-speech-key")
        provider = OpenAISpeechProvider() if model is None else OpenAISpeechProvider(model)
        if format_ == "json":
            service.payload = {"text": "文字没有提供时间定位。"}
        try:
            rows = provider.transcribe(str(recording))
            assert len(service.requests) == 1
            sent = service.requests[0]
            assert sent["path"] == "/v1/audio/transcriptions"
            assert sent["authorization"] == "Bearer synthetic-private-speech-key"
            assert sent["filenames"] == [recording.name]
            assert sent["fields"] == {"model": (model or "whisper-1").encode(), "response_format": format_.encode(), "file": recording.read_bytes(), **extra}
            assert rows[0]["segment_id"] == "speech::0001"
            if format_ == "json":
                assert rows == [{"segment_id": "speech::0001", "text": "文字没有提供时间定位。"}]
            else:
                assert rows[0]["start"] == 1.25 and rows[0]["end"] == 3.75
                assert rows[0]["speaker"] == "A"
        finally:
            provider.client.close()


@pytest.mark.parametrize("code", [307, 400, 401, 403, 404, 413, 429, 500])
def test_actual_sdk_does_not_retry_or_follow_redirects_or_expose_service_error(tmp_path, monkeypatch, code):
    pytest.importorskip("openai")
    recording = tmp_path / "synthetic.wav"
    recording.write_bytes(b"not real audio")
    with SpeechService() as service:
        service.code = code
        service.payload = {"error": {"message": "synthetic-private-speech-key provider-internal-detail", "type": "test_error"}}
        monkeypatch.setenv("OPENAI_BASE_URL", service.base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-speech-key")
        provider = OpenAISpeechProvider()
        try:
            with pytest.raises(SpeechRequestError) as error:
                provider.transcribe(str(recording))
            assert "synthetic-private" not in str(error.value) and "provider-internal-detail" not in str(error.value)
            assert len(service.requests) == 1
        finally:
            provider.client.close()


@pytest.mark.parametrize("response", [{"text": "课堂原文"}, "课堂原文", SimpleNamespace(text="课堂原文")])
def test_untimed_response_keeps_text_without_inventing_time(response):
    assert transcription_response(response) == [{"segment_id": "speech::0001", "text": "课堂原文"}]


def test_sdk_object_and_dict_segments_keep_speaker_but_drop_service_review_claims():
    raw = {"text": "课堂原文", "start": 0.5, "end": 2.75, "speaker": "A", "status": "verified", "alignment": {"status": "aligned"}}
    for response in ({"segments": [raw]}, SimpleNamespace(segments=[SimpleNamespace(**raw)])):
        assert transcription_response(response) == [{"segment_id": "speech::0001", "text": "课堂原文", "start": 0.5, "end": 2.75, "speaker": "A"}]


@pytest.mark.parametrize("response", [None, {}, {"text": None}, {"text": 3}, {"text": " "}, {"segments": {}},
    {"segments": [None], "text": "不要默默跳过坏片段"}, {"segments": [{"text": ""}], "text": "不要用整段文字掩盖丢段"},
    {"segments": [{"text": "原话", "start": 1}]}, {"segments": [{"text": "原话", "start": 2, "end": 1}]},
    {"segments": [{"text": "原话", "start": True, "end": 3}]}, {"text": "原话", "error": {"message": "secret"}}])
def test_malformed_results_cannot_be_cached_as_success(response):
    with pytest.raises(ValueError, match="转写"):
        transcription_response(response)


@pytest.mark.parametrize("kind", ["empty", "oversize", "unsupported"])
def test_invalid_recording_is_rejected_without_constructing_sdk_client(tmp_path, kind):
    recording = tmp_path / ("synthetic.txt" if kind == "unsupported" else "synthetic.mp3")
    with recording.open("wb") as handle:
        if kind == "oversize":
            handle.truncate(MAX_SPEECH_BYTES + 1)
        elif kind != "empty":
            handle.write(b"not real audio")
    provider = OpenAISpeechProvider()
    with pytest.raises(SpeechRequestError):
        provider.transcribe(str(recording))
    assert provider._client is None


def test_actual_sdk_ingestion_guide_exports_and_cache_reuse_preserve_each_recording(tmp_path, monkeypatch):
    pytest.importorskip("openai")
    from mst.export import export_study_guide
    from mst.guide import generate_project_guide
    from mst.ingest import transcribe_project_audio
    from mst.io import project_paths, read_json
    from mst.materials import material_results
    from test_audio_ingestion import audio_project

    project, files = audio_project(tmp_path)
    with SpeechService() as service:
        monkeypatch.setenv("OPENAI_BASE_URL", service.base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-speech-key")
        provider = OpenAISpeechProvider()
        try:
            assert transcribe_project_audio(project, provider) == 2
            assert len(service.requests) == 2
            assert transcribe_project_audio(project, provider) == 0
            assert len(service.requests) == 2
            saved = read_json(project_paths(project)["lesson_map"])
            assert len({row["segment_id"] for row in saved["speech_segments"]}) == 2
            assert {row["source_id"] for row in saved["speech_segments"]} == {"source::0001", "source::0002"}
            assert all(row["start"] == 1.25 and row["end"] == 3.75 and row["status"] == "pending" for row in saved["speech_segments"])
            receipts = material_results(project, [{"stored_name": file.name, "name": file.name, "size_bytes": file.stat().st_size} for file in files])
            assert all(row["status"] == "text-read" and row["label"] == "转写已读取" and row["timed_segment_count"] == 1 for row in receipts)
            guide = generate_project_guide(project)
            assert guide.report.total_segments == 2 and guide.report.status != "complete"
            timed = [ref for ref in guide.source_index if ref.start is not None]
            assert len(timed) == 2 and all(ref.start == 1.25 and ref.end == 3.75 for ref in timed)
            for format_ in ("md", "html", "json"):
                assert "最低位对齐" in export_study_guide(project, format=format_).read_text(encoding="utf-8")
            assert all(b"synthetic-private-speech-key" not in path.read_bytes() for path in project.rglob("*") if path.is_file())
        finally:
            provider.close()
            assert provider._client is None


@pytest.mark.parametrize("payload", [{"text": None}, {"text": "课堂原话", "segments": [None]},
    {"text": "课堂原话", "segments": [{"text": "课堂原话", "start": 3, "end": 1}]}])
def test_actual_sdk_success_status_with_invalid_content_never_publishes_or_caches(tmp_path, monkeypatch, payload):
    pytest.importorskip("openai")
    from mst.ingest import transcribe_project_audio
    from mst.io import project_paths
    from test_audio_ingestion import audio_project

    project, _ = audio_project(tmp_path)
    previous = project_paths(project)["lesson_map"].read_bytes()
    with SpeechService() as service:
        service.payload = payload
        monkeypatch.setenv("OPENAI_BASE_URL", service.base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-speech-key")
        provider = OpenAISpeechProvider()
        try:
            with pytest.raises(SpeechRequestError):
                transcribe_project_audio(project, provider)
            assert len(service.requests) == 1
            assert project_paths(project)["lesson_map"].read_bytes() == previous
            assert not list((project / "derived/transcriptions").glob("*.json"))
        finally:
            provider.close()
