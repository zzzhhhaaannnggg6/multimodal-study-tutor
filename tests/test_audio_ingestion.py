"""Synthetic providers must not lose later recordings or overwrite evidence."""

from pathlib import Path

import pytest

from mst.ingest import ingest_project, init_project, transcribe_project_audio
from mst.io import project_paths, read_json, write_json
from mst.reconstruct import build_scaffold


class ReusedSegmentIds:
    name = "synthetic-speech"

    def transcribe(self, audio_path):
        return [{"segment_id": "speech::0001", "text": f"{Path(audio_path).stem}的第一段具体说明。", "start": 1, "end": 3},
                {"segment_id": "speech::0002", "text": f"{Path(audio_path).stem}的第二段课堂补充。", "start": 3, "end": 6}]


def audio_project(tmp_path):
    project = tmp_path / "course"
    init_project(project)
    files = [tmp_path / "前半节.mp3", tmp_path / "后半节.mp4"]
    for file in files:
        file.write_bytes(b"synthetic audio placeholder; never sent to an API")
    ingest_project(project, files)
    build_scaffold(project)
    return project, files


def test_multiple_recordings_keep_all_segments_with_source_specific_ids(tmp_path):
    project, files = audio_project(tmp_path)
    originals = [file.read_bytes() for file in files]
    assert transcribe_project_audio(project, ReusedSegmentIds()) == 4
    path = project_paths(project)["lesson_map"]
    segments = read_json(path)["speech_segments"]
    assert len({row["segment_id"] for row in segments}) == 4
    assert {row["source_id"] for row in segments} == {"source::0001", "source::0002"}
    assert {row["metadata"]["transcription"]["provider_segment_id"] for row in segments} == {"speech::0001", "speech::0002"}
    assert {row["start"] for row in segments} == {1, 3}
    assert all(row["media_id"] == row["source_id"] for row in segments)
    assert transcribe_project_audio(project, ReusedSegmentIds()) == 0
    assert len(read_json(path)["speech_segments"]) == 4
    assert [file.read_bytes() for file in files] == originals


def test_duplicate_provider_ids_within_one_recording_do_not_discard_utterances(tmp_path):
    class DuplicateIds(ReusedSegmentIds):
        def transcribe(self, audio_path):
            rows = super().transcribe(audio_path)
            rows[1]["segment_id"] = rows[0]["segment_id"]
            return rows
    project, _ = audio_project(tmp_path)
    assert transcribe_project_audio(project, DuplicateIds()) == 4


def test_changed_transcription_does_not_silently_replace_or_reuse_old_evidence(tmp_path):
    class Changed(ReusedSegmentIds):
        def transcribe(self, audio_path):
            rows = super().transcribe(audio_path)
            rows[0]["text"] = "这次不同的转写不能继续使用旧的来源标识。"
            return rows
    project, _ = audio_project(tmp_path)
    transcribe_project_audio(project, ReusedSegmentIds())
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="已有转写"):
        transcribe_project_audio(project, Changed(), refresh=True)
    assert path.read_bytes() == previous


def test_legacy_segment_ids_remain_valid_while_missing_recordings_are_added(tmp_path):
    project, files = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    data = read_json(path)
    data["speech_segments"] = [{**row, "source_id": "source::0001", "media_id": "source::0001"}
        for row in ReusedSegmentIds().transcribe(str(files[0]))]
    write_json(path, data)
    assert transcribe_project_audio(project, ReusedSegmentIds()) == 2
    segments = read_json(path)["speech_segments"]
    assert len(segments) == 4
    assert {row["segment_id"] for row in segments[:2]} == {"speech::0001", "speech::0002"}


def test_transcriber_cannot_claim_reviewed_teacher_page_alignment(tmp_path):
    class Unreviewed(ReusedSegmentIds):
        def transcribe(self, audio_path):
            rows = super().transcribe(audio_path)
            for row in rows:
                row.update(status="verified", alignment={"status": "aligned", "confidence": "high", "visual_ids": ["p1"]})
            return rows
    project, _ = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    data = read_json(path)
    data["pages"] = [{"visual_id": "p1", "title": "无关课题", "text": "比较文学中的叙事视角。", "status": "covered"}]
    write_json(path, data)
    assert transcribe_project_audio(project, Unreviewed()) == 4
    segments = read_json(path)["speech_segments"]
    assert all(row["status"] == "pending" and row["alignment"]["status"] == "pending" for row in segments)
    assert all(row["metadata"]["alignment_analysis"]["pairing_status"] == "not_verified" for row in segments)


def test_later_recording_failure_preserves_previous_map_atomically(tmp_path):
    class LaterFailure(ReusedSegmentIds):
        def transcribe(self, audio_path):
            if Path(audio_path).suffix == ".mp4":
                raise RuntimeError("synthetic later recording failed")
            return super().transcribe(audio_path)
    project, _ = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    with pytest.raises(RuntimeError, match="later recording failed"):
        transcribe_project_audio(project, LaterFailure())
    assert path.read_bytes() == previous


def test_replaced_recording_cannot_silently_reuse_an_older_source_id(tmp_path):
    project, files = audio_project(tmp_path)
    transcribe_project_audio(project, ReusedSegmentIds())
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    files[0].write_bytes(b"different synthetic recording; transcript happens to match")
    ingest_project(project, files)
    with pytest.raises(ValueError, match="已有转写"):
        transcribe_project_audio(project, ReusedSegmentIds())
    assert path.read_bytes() == previous


class CountingSpeech(ReusedSegmentIds):
    model = "synthetic-v1"

    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path):
        self.calls.append(Path(audio_path).name)
        return super().transcribe(audio_path)


def test_repeated_generation_makes_no_service_calls_even_with_a_new_provider_instance(tmp_path):
    project, _ = audio_project(tmp_path)
    first = CountingSpeech()
    assert transcribe_project_audio(project, first) == 4
    assert len(first.calls) == 2
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    second = CountingSpeech()
    assert transcribe_project_audio(project, second) == 0
    assert second.calls == []
    assert path.read_bytes() == previous


def test_failed_later_recording_retries_only_unfinished_recordings_after_restart(tmp_path):
    class FailsLater(CountingSpeech):
        def transcribe(self, audio_path):
            if Path(audio_path).suffix == ".mp4":
                self.calls.append(Path(audio_path).name)
                raise RuntimeError("synthetic service interruption")
            return super().transcribe(audio_path)
    project, files = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    failed = FailsLater()
    with pytest.raises(RuntimeError, match="service interruption"):
        transcribe_project_audio(project, failed)
    assert path.read_bytes() == previous
    assert len(list((project / "derived/transcriptions").glob("*.json"))) == 1
    resumed = CountingSpeech()
    assert transcribe_project_audio(project, resumed) == 4
    assert resumed.calls == [files[1].name]
    assert len(read_json(path)["speech_segments"]) == 4
    assert not list((project / "derived/transcriptions").glob(".transcribing-*"))


def test_rebuilding_scaffold_reuses_recording_results_without_uploading_again(tmp_path):
    project, _ = audio_project(tmp_path)
    transcribe_project_audio(project, CountingSpeech())
    build_scaffold(project)
    assert read_json(project_paths(project)["lesson_map"])["speech_segments"] == []
    resumed = CountingSpeech()
    assert transcribe_project_audio(project, resumed) == 4
    assert resumed.calls == []


@pytest.mark.parametrize("cached", [False, True])
def test_all_files_checked_before_any_service_call_or_cached_reuse(tmp_path, cached):
    project, files = audio_project(tmp_path)
    if cached:
        transcribe_project_audio(project, CountingSpeech())
    previous = project_paths(project)["lesson_map"].read_bytes()
    files[1].write_bytes(b"changed after import; manifest still has previous hash")
    provider = CountingSpeech()
    with pytest.raises(ValueError, match="导入后发生变化"):
        transcribe_project_audio(project, provider)
    assert provider.calls == []
    assert project_paths(project)["lesson_map"].read_bytes() == previous


def test_recording_uploaded_from_verified_snapshot_and_original_not_rewritten(tmp_path):
    project, files = audio_project(tmp_path)
    originals = {file.name: file.read_bytes() for file in files}
    snapshots = []
    class CheckSnapshot(CountingSpeech):
        def transcribe(self, audio_path):
            snapshot = Path(audio_path)
            assert snapshot not in files
            assert snapshot.read_bytes() == originals[snapshot.name]
            snapshots.append(snapshot)
            return super().transcribe(audio_path)
    assert transcribe_project_audio(project, CheckSnapshot()) == 4
    assert all(not snapshot.exists() for snapshot in snapshots)
    assert {file.name: file.read_bytes() for file in files} == originals


def test_original_replaced_during_call_does_not_change_uploaded_snapshot(tmp_path):
    project, files = audio_project(tmp_path)
    originals = files[0].read_bytes()
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    class ReplaceOriginal(CountingSpeech):
        def transcribe(self, audio_path):
            if Path(audio_path).name == files[0].name:
                files[0].write_bytes(b"replacement made after snapshot")
                assert Path(audio_path).read_bytes() == originals
            return super().transcribe(audio_path)
    with pytest.raises(ValueError, match="处理期间发生变化"):
        transcribe_project_audio(project, ReplaceOriginal())
    assert path.read_bytes() == previous
    provider = CountingSpeech()
    with pytest.raises(ValueError, match="导入后发生变化"):
        transcribe_project_audio(project, provider)
    assert provider.calls == []


@pytest.mark.parametrize("rows", [[], [None], [{"text": ""}], [{"text": 42}],
    [{"text": "课堂内容", "start": 3, "end": 1}], [{"text": "课堂内容", "start": 1}],
    [{"text": "课堂内容", "start": True, "end": 4}], [{"text": "课堂内容", "start": 0, "end": float("nan")}],
    [{"text": "课堂内容", "start": -1, "end": 3}]])
def test_invalid_service_output_is_neither_cached_nor_published(tmp_path, rows):
    class Invalid(CountingSpeech):
        def transcribe(self, audio_path):
            return rows
    project, _ = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="转写"):
        transcribe_project_audio(project, Invalid())
    assert path.read_bytes() == previous
    assert not list((project / "derived/transcriptions").glob("*.json"))
    assert not list((project / "derived/transcriptions").glob(".transcribing-*"))


def test_plain_text_transcription_is_cached_without_fabricated_times(tmp_path):
    class Untimed(CountingSpeech):
        def transcribe(self, audio_path):
            self.calls.append(Path(audio_path).name)
            return [{"text": "课堂原话没有提供时间，不能捏造定位。"}]
    project, _ = audio_project(tmp_path)
    provider = Untimed()
    assert transcribe_project_audio(project, provider) == 2
    assert transcribe_project_audio(project, provider) == 0
    assert len(provider.calls) == 2
    rows = read_json(project_paths(project)["lesson_map"])["speech_segments"]
    assert all(row.get("start") is None and row.get("end") is None for row in rows)


def test_explicit_refresh_calls_again_but_different_content_preserves_map_and_receipt(tmp_path):
    project, _ = audio_project(tmp_path)
    provider = CountingSpeech()
    transcribe_project_audio(project, provider)
    assert transcribe_project_audio(project, provider, refresh=True) == 0
    assert len(provider.calls) == 4
    before = {file: file.read_bytes() for file in (project / "derived/transcriptions").glob("*.json")}
    previous = project_paths(project)["lesson_map"].read_bytes()
    class Different(CountingSpeech):
        def transcribe(self, audio_path):
            return [{"text": "内容已经改变。", "start": 1, "end": 3}]
    with pytest.raises(ValueError, match="已有转写"):
        transcribe_project_audio(project, Different(), refresh=True)
    assert project_paths(project)["lesson_map"].read_bytes() == previous
    assert {file: file.read_bytes() for file in before} == before


def test_shortened_refresh_cannot_leave_stale_trailing_segments(tmp_path):
    class Shorter(CountingSpeech):
        def transcribe(self, audio_path):
            return super().transcribe(audio_path)[:1]
    project, _ = audio_project(tmp_path)
    transcribe_project_audio(project, CountingSpeech())
    previous = project_paths(project)["lesson_map"].read_bytes()
    with pytest.raises(ValueError, match="缺少片段"):
        transcribe_project_audio(project, Shorter(), refresh=True)
    assert project_paths(project)["lesson_map"].read_bytes() == previous


def test_new_model_does_not_reuse_previous_model_receipts(tmp_path):
    project, _ = audio_project(tmp_path)
    transcribe_project_audio(project, CountingSpeech())
    provider = CountingSpeech()
    provider.model = "synthetic-v2"
    assert transcribe_project_audio(project, provider) == 0
    assert len(provider.calls) == 2
    receipts = [read_json(file) for file in (project / "derived/transcriptions").glob("*.json")]
    assert {receipt["provider"]["model"] for receipt in receipts} == {"synthetic-v1", "synthetic-v2"}


def test_adapter_options_separate_receipts_without_storing_private_configuration(tmp_path):
    project, _ = audio_project(tmp_path)
    first = CountingSpeech()
    first.transcription_cache_key = "synthetic-private-config-1"
    assert transcribe_project_audio(project, first) == 4
    second = CountingSpeech()
    second.transcription_cache_key = "synthetic-private-config-2"
    assert transcribe_project_audio(project, second) == 0
    assert len(second.calls) == 2
    receipts = list((project / "derived/transcriptions").glob("*.json"))
    assert len(receipts) == 4
    assert all("synthetic-private-config" not in receipt.read_text() for receipt in receipts)


def test_legacy_transcription_cannot_silently_retain_missing_trailing_speech(tmp_path):
    class Shorter(ReusedSegmentIds):
        def transcribe(self, audio_path):
            return super().transcribe(audio_path)[:1]
    project, files = audio_project(tmp_path)
    path = project_paths(project)["lesson_map"]
    data = read_json(path)
    data["speech_segments"] = [{**row, "source_id": "source::0001", "media_id": "source::0001"}
        for row in ReusedSegmentIds().transcribe(str(files[0]))]
    write_json(path, data)
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="缺少片段"):
        transcribe_project_audio(project, Shorter())
    assert path.read_bytes() == previous


def test_damaged_cache_never_silently_triggers_paid_retranscription(tmp_path):
    project, _ = audio_project(tmp_path)
    transcribe_project_audio(project, CountingSpeech())
    receipt = next((project / "derived/transcriptions").glob("*.json"))
    write_json(receipt, {"schema_version": "damaged"})
    provider = CountingSpeech()
    with pytest.raises(ValueError, match="本地转写记录损坏"):
        transcribe_project_audio(project, provider)
    assert provider.calls == []
    assert transcribe_project_audio(project, provider, refresh=True) == 0
    assert len(provider.calls) == 2


def test_refresh_cli_requires_explicit_speech_provider(tmp_path, capsys):
    from mst.cli import main
    with pytest.raises(SystemExit) as failure:
        main(["generate", str(tmp_path), "--refresh-transcription"])
    assert failure.value.code == 2
    assert "requires an explicit --speech-provider" in capsys.readouterr().err


def test_generate_cli_reuses_transcription_and_forwards_explicit_refresh(tmp_path, monkeypatch, capsys):
    from mst.cli import main
    from mst import providers
    project, _ = audio_project(tmp_path)
    provider = CountingSpeech()
    monkeypatch.setattr(providers, "OpenAISpeechProvider", lambda model: provider)
    args = ["generate", str(project), "--speech-provider", "openai"]
    assert main(args) == 0
    assert len(provider.calls) == 2
    assert "Added 4 audio segment(s)" in capsys.readouterr().out
    assert project_paths(project)["study_guide"].is_file()
    assert main(args) == 0
    assert len(provider.calls) == 2
    assert "Added 0 audio segment(s)" in capsys.readouterr().out
    assert main([*args, "--refresh-transcription"]) == 0
    assert len(provider.calls) == 4
