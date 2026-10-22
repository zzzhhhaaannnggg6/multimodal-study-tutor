"""Playback uses original recording identity and supports real media seeking."""

import http.client
import json

import pytest

from audio_fixtures import silent_wav
from fake_speech_service import SpeechService
from mst.io import project_paths, read_json, write_json
from mst.recordings import seconds
from test_server import service, request
from test_jobs import finish, uploads
from test_web_speech import audio, settings


def recording_job(service):
    data = silent_wav()
    with SpeechService() as speech:
        job = finish(service.jobs, service.jobs.submit([*uploads(), audio("课堂.wav", data)], speech=settings(speech.base_url)))
    assert job["status"] == "succeeded"
    guide = json.loads(request(service, "GET", f"/api/jobs/{job['job_id']}/guide")[1])
    link = next(iter(guide["_local_recordings"].values()))
    return job, link, data


def media_request(service, path, method="GET", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", service.server_port, timeout=5)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def test_audio_links_are_local_pinned_and_do_not_leak_into_exports(service):
    job, link, data = recording_job(service)
    assert link["start"] == 1.25 and link["end"] == 3.75
    assert link["name"] == "课堂.wav"
    assert link["url"].startswith(f"/api/jobs/{job['job_id']}/recordings/")
    code, headers, body = media_request(service, link["url"])
    assert code == 200 and body == data
    assert headers["Content-Type"] == "audio/wav"
    assert headers["Cache-Control"] == "no-store" and headers["Accept-Ranges"] == "bytes"
    for extension in ("html", "md", "json"):
        code, body = request(service, "GET", f"/api/exports/{extension}")
        assert code == 200 and b"_local_recordings" not in body and link["url"].encode() not in body
    finish(service.jobs, service.jobs.submit(uploads("# Another lesson\nOther content")))
    assert request(service, "GET", link["url"])[1] == data
    assert json.loads(request(service, "GET", "/study-guide.json")[1])["_local_recordings"] == {}


@pytest.mark.parametrize("range_,expected", [("bytes=0-1", (0, 1)), ("bytes=44-", (44, None)),
    ("bytes=-20", (-20, None)), ("bytes=0-99999999", (0, None))])
def test_actual_range_and_head_do_not_send_the_entire_recording(service, range_, expected):
    _, link, data = recording_job(service)
    code, headers, body = media_request(service, link["url"], headers={"Range": range_})
    start, end = expected
    assert code == 206
    assert body == (data[start:] if end is None else data[start:end + 1])
    assert int(headers["Content-Length"]) == len(body)
    assert headers["Content-Range"].endswith(f"/{len(data)}")
    code, head, body = media_request(service, link["url"], "HEAD", {"Range": range_})
    assert code == 206 and body == b"" and head["Content-Length"] == headers["Content-Length"]


@pytest.mark.parametrize("range_", ["bytes=999999-", "bytes=5-4", "bytes=-0", "bytes=", "bytes=0-1,4-5", "items=1-2"])
def test_bad_ranges_are_explicit_416_and_do_not_return_audio(service, range_):
    _, link, data = recording_job(service)
    code, headers, body = media_request(service, link["url"], headers={"Range": range_})
    assert code == 416 and body == b"" and headers["Content-Range"] == f"bytes */{len(data)}"


def test_replaced_or_symlinked_recordings_never_play_under_old_source(service, tmp_path):
    _, link, data = recording_job(service)
    assert media_request(service, link["url"])[0] == 200  # Populate verified-byte cache.
    root = service.jobs.active_root()
    source = read_json(project_paths(root)["manifest"])["source_manifest"][-1]
    from pathlib import Path
    target = Path(source["path"])
    target.write_bytes(data[:-1] + b"X")
    code, _, body = media_request(service, link["url"])
    assert code == 409 and body != data
    target.unlink()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(data)
    target.symlink_to(outside)
    assert media_request(service, link["url"])[0] == 409
    assert json.loads(request(service, "GET", "/study-guide.json")[1])["_local_recordings"] == {}


def test_unknown_tokens_foreign_hosts_and_file_paths_cannot_fetch_sources(service):
    _, link, _ = recording_job(service)
    assert media_request(service, link["url"], headers={"Host": "attacker.example"})[0] == 403
    assert media_request(service, link["url"], "HEAD", {"Host": "attacker.example"})[0] == 403
    assert media_request(service, link["url"], headers={"Origin": "https://attacker.example"})[0] == 403
    assert media_request(service, link["url"], headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert media_request(service, "/api/recordings/" + "f" * 64)[0] == 409
    assert media_request(service, "/api/recordings/../../project.json")[0] == 404


def test_transcript_is_not_paired_by_name_and_missing_times_are_not_invented(service):
    _, _, _ = recording_job(service)
    root = service.jobs.active_root()
    path = project_paths(root)["lesson_map"]
    lesson = read_json(path)
    # Legacy aliases are both updated to avoid reloading the other copy.
    segments = lesson["speech_segments"]
    source_id = segments[0]["source_id"]
    for key in ("speech_segments", "audio_segments"):
        for segment in lesson.get(key, []):
            segment["start"] = None
            segment["end"] = None
    write_json(path, lesson)
    assert json.loads(request(service, "GET", "/study-guide.json")[1])["_local_recordings"] == {}
    for key in ("speech_segments", "audio_segments"):
        for segment in lesson.get(key, []):
            segment.update(start=1, end=3, source_id=source_id + "-similar-transcript")
    write_json(path, lesson)
    assert json.loads(request(service, "GET", "/study-guide.json")[1])["_local_recordings"] == {}


def test_authoritative_start_is_used_and_inferred_end_stays_open(service):
    _, _, _ = recording_job(service)
    root = service.jobs.active_root()
    path = project_paths(root)["lesson_map"]
    lesson = read_json(path)
    for key in ("speech_segments", "audio_segments"):
        for segment in lesson.get(key, []):
            segment.update(start="00:00:02.5", end=4)
            segment["metadata"]["end_inferred"] = True
    write_json(path, lesson)
    link = next(iter(json.loads(request(service, "GET", "/study-guide.json")[1])["_local_recordings"].values()))
    assert link["start"] == 2.5 and link["end"] is None


@pytest.mark.parametrize("value,expected", [(0, 0), ("01:02:03.125", 3723.125), ("1:02", 62),
    (None, None), (True, None), (-1, None), (float("nan"), None), ("1:99", None), ("约十分钟", None)])
def test_stored_timestamp_conversion(value, expected):
    assert seconds(value) == expected


def test_legacy_cli_project_uses_explicit_manifest_and_recording_hash(service, tmp_path):
    from mst.ingest import init_project, ingest_project, transcribe_project_audio
    from mst.reconstruct import build_scaffold
    from mst.guide import generate_project_guide
    root = service.jobs.project
    source = tmp_path / "cli.wav"
    source.write_bytes(silent_wav())
    init_project(root)
    ingest_project(root, [source])
    build_scaffold(root)
    class Provider:
        name = "synthetic-local"
        def transcribe(self, path):
            return [{"text": "课堂解释", "start": 1, "end": 3}]
    transcribe_project_audio(root, Provider())
    generate_project_guide(root)
    guide = json.loads(request(service, "GET", "/study-guide.json")[1])
    link = next(iter(guide["_local_recordings"].values()))
    assert link["url"].startswith("/api/recordings/")
    assert media_request(service, link["url"])[2] == source.read_bytes()
