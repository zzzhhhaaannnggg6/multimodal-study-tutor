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
        transcribe_project_audio(project, Changed())
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
