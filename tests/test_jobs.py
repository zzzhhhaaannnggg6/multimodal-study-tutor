from __future__ import annotations

import base64
import threading
from pathlib import Path

import pytest

from mst.cli import main
from mst.guide import load_project_guide
from mst.io import active_project_dir, read_json, write_json
from mst.jobs import JobBusyError, JobManager, decode_uploads, run_pipeline


def uploads(text="结构与功能\n函数由输入经过运算得到输出。"):
    return [{"name": "课程.md", "data": base64.b64encode(text.encode()).decode()}]


def finish(manager, job):
    assert manager.events[job["job_id"]].wait(5), "local generation did not finish"
    return manager.get(job["job_id"])


def test_jobs_keep_original_uploads_publish_all_formats_and_export_via_cli(tmp_path):
    manager = JobManager(tmp_path)
    try:
        first = finish(manager, manager.submit(uploads()))
        assert first["status"] == "succeeded", first
        original = active_project_dir(tmp_path)
        source = next((original / "sources/uploads").iterdir())
        content = source.read_bytes()
        second = finish(manager, manager.submit(uploads("# 第二节\n关系与过程"), "mathematics"))
        assert second["status"] == "succeeded", second
        assert original != active_project_dir(tmp_path)
        assert source.read_bytes() == content
        assert load_project_guide(tmp_path).subject == "mathematics"
        for suffix in ("md", "html", "json"):
            target = tmp_path / f"download.{suffix}"
            assert main(["export", str(tmp_path), "--format", suffix, "--output", str(target)]) == 0
            assert target.stat().st_size > 0
        assert main(["validate", "--project", str(tmp_path)]) == 0
    finally:
        manager.close()


def test_failure_does_not_replace_course_and_retry_uses_saved_inputs(tmp_path):
    manager = JobManager(tmp_path)
    try:
        finish(manager, manager.submit(uploads()))
        previous = active_project_dir(tmp_path)
        def fail(workspace, progress):
            raise ValueError("合成输入无法解析")
        manager.runner = fail
        failed = finish(manager, manager.submit(uploads("# 下节\n第二份材料")))
        assert failed["status"] == "failed"
        assert active_project_dir(tmp_path) == previous
        manager.runner = run_pipeline
        retried = finish(manager, manager.retry(failed["job_id"]))
        assert retried["status"] == "succeeded"
        assert retried["job_id"] != failed["job_id"]
    finally:
        manager.close()


def test_concurrency_ownership_and_close_cannot_publish_in_flight_result(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def held(workspace, progress):
        entered.set()
        assert release.wait(5)
        return run_pipeline(workspace, progress)
    manager = JobManager(tmp_path, held)
    job = manager.submit(uploads())
    try:
        assert entered.wait(5)
        with pytest.raises(JobBusyError):
            manager.submit(uploads())
        with pytest.raises(ValueError, match="另一个窗口"):
            JobManager(tmp_path)
        manager.close()
        with pytest.raises(ValueError, match="另一个窗口"):
            JobManager(tmp_path)
        release.set()
        assert finish(manager, job)["status"] == "interrupted"
        assert not (tmp_path / ".study-state.json").exists()
    finally:
        release.set()
        manager.workers[job["job_id"]].join(5)
        manager.close()
    reopened = JobManager(tmp_path)
    reopened.close()


def test_restart_marks_unpublished_job_interrupted_and_preserves_materials(tmp_path):
    job_id = "a" * 32
    directory = tmp_path / ".study-jobs" / job_id
    source = directory / "workspace/sources/uploads/001-课程.md"
    source.parent.mkdir(parents=True)
    source.write_text("原始材料", encoding="utf-8")
    write_json(directory / "job.json", {"job_id": job_id, "status": "running", "created_at": "2026-01-01", "history": []})
    manager = JobManager(tmp_path)
    try:
        assert manager.latest()["status"] == "interrupted"
        assert source.read_text(encoding="utf-8") == "原始材料"
    finally:
        manager.close()


@pytest.mark.parametrize("rows", [[], [{"name": "bad.ppt", "data": "YQ=="}], [{"name": "x.md", "data": "invalid!"}], [{"name": "x.md", "data": ""}], [{"name": "script.exe", "data": "YQ=="}]])
def test_upload_validation_leaves_no_partial_job(tmp_path, rows):
    manager = JobManager(tmp_path)
    try:
        with pytest.raises(ValueError):
            manager.submit(rows)
        assert manager.latest() is None
        assert not list((tmp_path / ".study-jobs").glob("*/workspace"))
    finally:
        manager.close()


def test_filename_normalization_and_pointer_traversal(tmp_path):
    assert decode_uploads([{"name": "../../课程.md", "data": "YQ=="}]) == [("课程.md", b"a")]
    write_json(tmp_path / ".study-state.json", {"active_run": "../../other"})
    with pytest.raises(ValueError, match="无效"):
        active_project_dir(tmp_path)


def test_atomic_json_failure_preserves_previous_record(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    write_json(path, {"old": "内容"})
    def unavailable(*args):
        raise OSError("disk failure")
    monkeypatch.setattr("mst.io.os.replace", unavailable)
    with pytest.raises(OSError):
        write_json(path, {"new": True})
    assert read_json(path) == {"old": "内容"}
    assert list(tmp_path.iterdir()) == [path]


def test_partly_broken_input_remains_draft_with_visible_missing_source(tmp_path):
    manager = JobManager(tmp_path)
    try:
        job = finish(manager, manager.submit([*uploads(), {"name": "broken.pptx", "data": base64.b64encode(b"not-a-zip").decode()}]))
        assert job["status"] == "succeeded", job
        guide = load_project_guide(tmp_path)
        assert guide.report.status != "complete"
        assert any("broken.pptx" in warning for warning in guide.report.warnings)
    finally:
        manager.close()


def test_unreadable_upload_cannot_replace_a_valid_course(tmp_path):
    manager = JobManager(tmp_path)
    try:
        finish(manager, manager.submit(uploads()))
        previous = active_project_dir(tmp_path)
        job = finish(manager, manager.submit([{"name": "broken.pptx", "data": "YnJva2Vu"}]))
        assert job["status"] == "failed" and "无法打开" in job["message"]
        assert active_project_dir(tmp_path) == previous
    finally:
        manager.close()


def test_restart_recovers_publication_commit_point(tmp_path):
    manager = JobManager(tmp_path)
    job = finish(manager, manager.submit(uploads()))
    manager.close()
    path = tmp_path / ".study-jobs" / job["job_id"] / "job.json"
    record = read_json(path)
    record["status"] = "running"  # Process died after pointer commit, before job save.
    write_json(path, record)
    manager = JobManager(tmp_path)
    try:
        assert manager.latest()["status"] == "succeeded"
        assert load_project_guide(tmp_path).units
    finally:
        manager.close()


def test_status_save_failure_after_publication_does_not_hide_saved_result(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    save = manager._save
    def fail_final_status(record):
        if record["status"] == "succeeded":
            raise OSError("simulated metadata write failure")
        save(record)
    monkeypatch.setattr(manager, "_save", fail_final_status)
    try:
        job = finish(manager, manager.submit(uploads()))
        assert job["status"] == "succeeded"
        assert load_project_guide(tmp_path).units
    finally:
        manager.close()
