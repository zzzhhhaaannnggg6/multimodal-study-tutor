"""Student audio workflow, including isolated retry and private cache carryover."""

import base64
import json

import pytest

from mst.guide import load_project_guide
from mst.io import active_project_dir, project_paths, read_json
from mst.jobs import JobManager
from mst.speech import SpeechRequestError
from mst.web_speech import HTTPAudioProvider, SpeechOptions
from test_jobs import finish, uploads
from fake_speech_service import SpeechService


def settings(url="https://speech.example.com/v1", **changes):
    return {"provider": "compatible", "base_url": url, "model": "whisper-1", "api_key": "synthetic-speech-credential", "consent": True, **changes}


def audio(name="录音.mp3", marker=b"synthetic-recording-only"):
    return {"name": name, "data": base64.b64encode(marker).decode()}


def test_audio_selection_requires_separate_consent_before_creating_a_job(tmp_path):
    manager = JobManager(tmp_path, speech_factory=lambda _: pytest.fail("unconfirmed speech cannot create a provider"))
    try:
        for changes in ({"consent": False}, {"consent": "true"}, {"api_key": ""},
                        {"base_url": "https://speech.example.com/v1/audio/transcriptions"}):
            with pytest.raises(ValueError):
                manager.submit([*uploads(), audio()], speech=settings(**changes))
        with pytest.raises(ValueError, match="没有所选录音"):
            manager.submit(uploads(), speech=settings())
        assert manager.latest() is None
    finally:
        manager.close()


@pytest.mark.parametrize("model,format_,extra", [("whisper-1", "verbose_json", {"timestamp_granularities[]": b"segment"}),
    ("gpt-4o-transcribe", "json", {}), ("gpt-4o-transcribe-diarize", "diarized_json", {"chunking_strategy": b"auto"})])
def test_web_transport_sends_only_selected_recording_bytes_and_keeps_actual_timing(tmp_path, model, format_, extra):
    recording = tmp_path / '课堂"录音.mp3'
    recording.write_bytes(b"synthetic audio: no teacher data")
    with SpeechService() as service:
        options = SpeechOptions.parse(settings(service.base_url, model=model))
        if format_ == "json":
            service.payload = {"text": "这份转写未提供时间。"}
        provider = HTTPAudioProvider(options)
        rows = provider.transcribe(str(recording))
        assert len(service.requests) == 1
        sent = service.requests[0]
        assert sent["path"] == "/v1/audio/transcriptions"
        assert sent["authorization"] == "Bearer synthetic-speech-credential"
        assert sent["filenames"] == [recording.name]
        assert sent["fields"] == {"model": model.encode(), "response_format": format_.encode(), "file": recording.read_bytes(), **extra}
        assert rows[0]["text"] == service.payload["text"]
        if format_ == "json":
            assert "start" not in rows[0] and "end" not in rows[0]
        else:
            assert rows[0]["start"] == 1.25 and rows[0]["end"] == 3.75
        assert "synthetic-speech-credential" not in repr(options) + provider.transcription_cache_key
        assert options.public()["scope"] == "selected-recording-audio"
        provider.close()
        assert not provider._key


@pytest.mark.parametrize("code", [307, 400, 401, 403, 404, 413, 429, 500])
def test_web_audio_errors_do_not_retry_follow_redirects_or_expose_error_body(tmp_path, code):
    recording = tmp_path / "synthetic.mp3"
    recording.write_bytes(b"synthetic only")
    with SpeechService() as service:
        service.code = code
        service.payload = {"error": {"message": "synthetic-speech-credential private-provider-detail"}}
        provider = HTTPAudioProvider(SpeechOptions.parse(settings(service.base_url)))
        with pytest.raises(SpeechRequestError) as error:
            provider.transcribe(str(recording))
        assert "synthetic-speech-credential" not in str(error.value) and "private-provider-detail" not in str(error.value)
        assert len(service.requests) == 1


def test_web_transcription_enters_guide_and_exports_and_never_stores_key(tmp_path):
    with SpeechService() as service:
        manager = JobManager(tmp_path)
        try:
            job = finish(manager, manager.submit([*uploads(), audio()], speech=settings(service.base_url)))
            assert job["status"] == "succeeded", job
            assert job["speech"]["stats"] == {"requests": 1, "succeeded": 1, "segments": 1, "reused_recordings": 0, "stopped_after_error": False}
            assert job["materials"][-1]["label"] == "转写已读取"
            assert job["materials"][-1]["timed_segment_count"] == 1
            assert any(item["stage"] == "transcribing" for item in job["history"])
            guide = load_project_guide(tmp_path)
            assert guide.report.total_segments == 1
            assert any(ref.start == 1.25 and ref.end == 3.75 for ref in guide.source_index)
            assert all("最低位对齐" in (manager.active_root() / "exports" / f"study-guide.{format_}").read_text() for format_ in ("html", "md", "json"))
            assert "结构".encode() not in service.requests[0]["fields"]["file"]
            assert all(b"synthetic-speech-credential" not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
        finally:
            manager.close()


def test_failed_later_recording_restart_retry_reuses_only_completed_audio(tmp_path):
    with SpeechService() as service:
        manager = JobManager(tmp_path)
        try:
            finish(manager, manager.submit(uploads()))
            original = active_project_dir(tmp_path)
            service.fail_on_call = {2}
            rows = [*uploads(), audio("上半节.mp3", b"synthetic-first-recording"), audio("下半节.mp3", b"synthetic-second-recording")]
            failed = finish(manager, manager.submit(rows, speech=settings(service.base_url)))
            assert failed["status"] == "failed" and failed["speech"]["stats"]["requests"] == 2
            assert active_project_dir(tmp_path) == original
            assert len(service.requests) == 2
            assert not read_json(project_paths(manager.directory / failed["job_id"] / "workspace")["lesson_map"])["speech_segments"]
            with pytest.raises(ValueError, match="重新选择转写"):
                manager.retry(failed["job_id"])
            manager.close()
            manager = JobManager(tmp_path)
            assert len(service.requests) == 2
            resumed = finish(manager, manager.retry(failed["job_id"], speech=settings(service.base_url)))
            assert resumed["status"] == "succeeded", resumed
            assert resumed["speech"]["stats"]["requests"] == 1 and resumed["speech"]["stats"]["reused_recordings"] == 1
            assert len(service.requests) == 3 and service.requests[-1]["fields"]["file"] == b"synthetic-second-recording"
            assert load_project_guide(tmp_path).report.total_segments == 2
        finally:
            manager.close()


def test_local_revision_restores_selected_receipt_after_source_id_changes_without_a_provider(tmp_path, monkeypatch):
    with SpeechService() as service:
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads("# 不再保留的课件\nUnselectedPrivateMarker"), audio("保留录音.mp3")], speech=settings(service.base_url)))
            assert first["status"] == "succeeded"
            assert len(service.requests) == 1
            manager.speech_factory = lambda _: pytest.fail("local mode must not create a speech connection")
            monkeypatch.setenv("OPENAI_API_KEY", "unused-environment-key")
            revised = finish(manager, manager.revise(first["job_id"], [first["files"][-1]["stored_name"]], uploads("# 新课件\n最低位对齐后再逐列计算。")))
            assert revised["status"] == "succeeded", revised
            assert len(service.requests) == 1
            assert revised["speech"]["provider"] == "none"
            assert revised["materials"][0]["label"] == "转写已读取"
            saved = read_json(project_paths(manager.active_root())["lesson_map"])
            assert saved["speech_segments"][0]["source_id"] == "source::0001"
            assert load_project_guide(tmp_path).report.total_segments == 1
            assert "UnselectedPrivateMarker" not in json.dumps(saved, ensure_ascii=False)
            assert all(b"unused-environment-key" not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
        finally:
            manager.close()


def test_source_remap_also_reuses_receipt_when_explicitly_transcribing(tmp_path):
    with SpeechService() as service:
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads(), audio()], speech=settings(service.base_url)))
            kept = [first["files"][-1]["stored_name"]]
            revised = finish(manager, manager.revise(first["job_id"], kept, uploads(), speech=settings(service.base_url)))
            assert revised["status"] == "succeeded", revised
            assert len(service.requests) == 1
            assert revised["speech"]["stats"]["requests"] == 0 and revised["speech"]["stats"]["reused_recordings"] == 1
        finally:
            manager.close()


def test_different_speech_endpoint_does_not_reuse_another_services_cache(tmp_path):
    with SpeechService() as first_service, SpeechService() as second_service:
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads(), audio()], speech=settings(first_service.base_url)))
            revised = finish(manager, manager.revise(first["job_id"], [row["stored_name"] for row in first["files"]], [], speech=settings(second_service.base_url)))
            assert revised["status"] == "succeeded"
            assert len(first_service.requests) == len(second_service.requests) == 1
        finally:
            manager.close()


def test_audio_and_text_connections_are_independent_and_apply_their_own_scopes(tmp_path):
    from fake_model_service import FakeModelService
    from test_web_models import settings as text_settings
    with SpeechService() as speech, FakeModelService() as text:
        manager = JobManager(tmp_path)
        try:
            job = finish(manager, manager.submit([*uploads("# 因果解释\n解释变化需要检查条件、机制和对照证据。"), audio(marker=b"PrivateAudioByteMarker")],
                                                 generation=text_settings(text.base_url), speech=settings(speech.base_url)))
            assert job["status"] == "succeeded", job
            assert job["generation"]["stats"]["checked_units"] == 1 and job["speech"]["stats"]["succeeded"] == 1
            assert speech.requests[0]["fields"]["file"] == b"PrivateAudioByteMarker"
            assert "因果".encode() not in speech.requests[0]["fields"]["file"]
            assert "PrivateAudioByteMarker" not in json.dumps(text.requests)
            assert "synthetic-speech-credential" not in json.dumps(job) and "synthetic-private-credential" not in json.dumps(job)
        finally:
            manager.close()


def test_partial_transcription_can_be_recovered_in_local_mode_without_retrying_service(tmp_path):
    with SpeechService() as service:
        service.fail_on_call = {2}
        manager = JobManager(tmp_path)
        try:
            failed = finish(manager, manager.submit([*uploads(), audio("first.mp3"), audio("second.mp3")], speech=settings(service.base_url)))
            assert failed["status"] == "failed" and len(service.requests) == 2
            recovered = finish(manager, manager.retry(failed["job_id"], speech={"provider": "none"}))
            assert recovered["status"] == "succeeded", recovered
            assert len(service.requests) == 2
            assert recovered["materials"][1]["timed_segment_count"] == 1
            assert recovered["materials"][2]["status"] == "transcription-needed"
            assert load_project_guide(tmp_path).report.total_segments == 1
            assert any("1 份录音尚未转写" in item for item in load_project_guide(tmp_path).report.warnings)
        finally:
            manager.close()


def test_corrupt_selected_receipt_stops_revision_before_any_new_upload(tmp_path):
    from mst.io import write_json
    with SpeechService() as service:
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads(), audio()], speech=settings(service.base_url)))
            previous = manager.active_root()
            receipt = next((previous / "derived/transcriptions").glob("*.json"))
            write_json(receipt, {"schema_version": "broken"})
            failed = finish(manager, manager.revise(first["job_id"], [item["stored_name"] for item in first["files"]], [], speech=settings(service.base_url)))
            assert failed["status"] == "failed" and "本地转写记录损坏" in failed["message"]
            assert manager.active_root() == previous and len(service.requests) == 1
        finally:
            manager.close()


def test_different_cached_versions_need_an_explicit_choice_and_can_be_selected_without_upload(tmp_path):
    with SpeechService() as first_service, SpeechService() as second_service:
        second_service.payload = {"text": "另一份有效转写，没有时间定位。"}
        manager = JobManager(tmp_path)
        try:
            first = finish(manager, manager.submit([*uploads(), audio()], speech=settings(first_service.base_url)))
            second = finish(manager, manager.revise(first["job_id"], [row["stored_name"] for row in first["files"]], [], speech=settings(second_service.base_url)))
            assert second["status"] == "succeeded"
            local = finish(manager, manager.revise(second["job_id"], [row["stored_name"] for row in second["files"]], []))
            assert local["status"] == "failed" and "多份不同的本地转写" in local["message"]
            assert len(first_service.requests) == len(second_service.requests) == 1
            selected = finish(manager, manager.retry(local["job_id"], speech=settings(first_service.base_url)))
            assert selected["status"] == "succeeded", selected
            assert selected["speech"]["stats"]["requests"] == 0
            assert len(first_service.requests) == len(second_service.requests) == 1
            assert load_project_guide(tmp_path).report.total_segments == 1
            assert all("另一份" not in (ref.quote or "") for ref in load_project_guide(tmp_path).source_index)
        finally:
            manager.close()


def test_untimed_web_transcription_stays_unlocated_and_reports_the_gap(tmp_path):
    with SpeechService() as service:
        service.payload = {"text": "这份讲解尚无实际时间戳。"}
        manager = JobManager(tmp_path)
        try:
            job = finish(manager, manager.submit([*uploads(), audio()], speech=settings(service.base_url, model="gpt-4o-transcribe")))
            assert job["status"] == "succeeded", job
            assert job["materials"][1]["segment_count"] == 1 and job["materials"][1]["timed_segment_count"] == 0
            guide = load_project_guide(tmp_path)
            assert guide.report.status != "complete"
            assert any("没有时间戳" in warning for warning in guide.report.warnings)
            assert all(ref.start is None and ref.end is None for ref in guide.source_index if "实际时间戳" in (ref.quote or ""))
        finally:
            manager.close()
