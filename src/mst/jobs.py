"""Durable, isolated local generation jobs; publish only finished artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .export import export_study_guide
from .guide import StudyGuide, generate_project_guide, validate_study_guide
from .ingest import SUPPORTED_EXTENSIONS, ingest_project, init_project
from .io import active_project_dir, project_paths, read_json, write_json
from .profiles import PROFILES
from .reconstruct import build_scaffold


ACTIVE = {"queued", "running"}
TERMINAL = {"succeeded", "failed", "interrupted"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_FILES = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobBusyError(ValueError):
    def __init__(self, job: dict[str, Any]):
        self.job = job
        super().__init__("已有材料正在处理中，请等待当前任务。")


def decode_uploads(rows: Any) -> list[tuple[str, bytes]]:
    """Validate every input before a job writes any source files."""
    if not isinstance(rows, list) or not rows or len(rows) > MAX_FILES:
        raise ValueError(f"请选择 1–{MAX_FILES} 个课程文件。")
    decoded = []
    total = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("data"), str):
            raise ValueError("文件信息不完整，请重新选择材料。")
        name = row["name"].replace("\\", "/").rsplit("/", 1)[-1]
        if not name or len(name.encode("utf-8")) > 220 or any(ord(c) < 32 for c in name):
            raise ValueError("文件名称无效，请重命名后重试。")
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"暂不支持 {suffix or '无扩展名'} 文件：{name}")
        if suffix == ".ppt":
            raise ValueError("旧版 .ppt 请先另存为 .pptx，再导入。")
        try:
            content = base64.b64decode(row["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"文件传输不完整，请重新选择：{name}") from exc
        if not content:
            raise ValueError(f"文件为空：{name}")
        total += len(content)
        if total > MAX_UPLOAD_BYTES:
            raise ValueError("本次材料合计超过 100 MB，请分课次导入或使用本地文件入口。")
        decoded.append((name, content))
    return decoded


def run_pipeline(workspace: Path, progress: Callable[[str, str], None]) -> StudyGuide:
    sources = sorted((workspace / "sources" / "uploads").iterdir())
    progress("inventory", "正在清点所选材料")
    manifest = ingest_project(workspace, sources)
    scaffold = build_scaffold(workspace, render=True, on_progress=progress)
    if not any(page.get("text", "").strip() for page in scaffold["pages"]) and not any(segment.get("text", "").strip() for segment in scaffold["speech_segments"]):
        issues = scaffold["notes"].get("extraction_issues", [])
        if issues:
            raise ValueError("课件或转写无法打开或解析，请确认文件完整、格式可读后重试。")
        raise ValueError("材料已保存在本机，但没有读到课程文字；请添加教师转写或可提取文字的课件。")
    progress("writing", "正在组织学习讲义")
    guide = generate_project_guide(workspace)
    identity = {"subject": manifest["subject"], "sources": sorted(row["sha256"] for row in manifest["source_manifest"])}
    guide.lesson_id = "course::" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    pending_media = [row for row in manifest["source_manifest"] if row["kind"] in {"audio", "video"}]
    if pending_media:
        guide.report.warnings.append("录音已保存在本地，本次未调用语音模型；需要教师转写才能补入录音内容。")
        if guide.report.status == "complete":
            guide.report.status = "draft"
    progress("checking", "正在检查例题、练习与来源缺口")
    diagnostics = validate_study_guide(guide, strict=True)
    guide.report.missing_fields = list(dict.fromkeys([*guide.report.missing_fields, *(item.path for item in diagnostics.errors)]))
    if diagnostics.errors and guide.report.status == "complete":
        guide.report.status = "draft"
    guide.write_json(project_paths(workspace)["study_guide"])
    write_json(project_paths(workspace)["generation_report"], guide.report.to_dict())
    progress("exporting", "正在保存可阅读和下载的讲义")
    for format in ("md", "html", "json"):
        export_study_guide(workspace, format=format)
    return guide


class JobManager:
    def __init__(self, project: str | Path, runner: Callable = run_pipeline):
        self.project = Path(project).resolve()
        self.directory = self.project / ".study-jobs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._ownership = (self.directory / "server.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._ownership.seek(0)
                self._ownership.write(b"0")
                self._ownership.flush()
                self._ownership.seek(0)
                msvcrt.locking(self._ownership.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._ownership.close()
            raise ValueError("这个课程已在另一个窗口提供服务，请回到原窗口。") from exc
        self.runner = runner
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.jobs: dict[str, dict] = {}
        self.events: dict[str, threading.Event] = {}
        self.workers: dict[str, threading.Thread] = {}
        for path in sorted(self.directory.glob("*/job.json")):
            try:
                record = read_json(path)
            except (ValueError, OSError):
                continue
            if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name) or record.get("job_id") != path.parent.name:
                continue
            if record.get("status") in ACTIVE:
                published = active_project_dir(self.project) == path.parent / "workspace"
                record.update(status="succeeded" if published else "interrupted", message="讲义已保存" if published else "上次处理因服务关闭而中断。原讲义已保留，可以重新生成。", updated_at=_now())
                write_json(path, record)
            self.jobs[record["job_id"]] = record

    def _save(self, record: dict) -> None:
        write_json(self.directory / record["job_id"] / "job.json", record)

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            record = self.jobs.get(job_id)
            return json.loads(json.dumps(record)) if record else None

    def latest(self) -> dict | None:
        with self.lock:
            return self.get(max(self.jobs, key=lambda key: self.jobs[key]["created_at"])) if self.jobs else None

    def submit(self, rows: Any, subject: str = "generic") -> dict:
        if not isinstance(subject, str) or subject not in PROFILES:
            raise ValueError("请选择可用的学科。")
        decoded = decode_uploads(rows)
        with self.lock:
            if self.closed.is_set():
                raise ValueError("服务正在关闭，请稍后重新打开。")
            busy = next((job for job in self.jobs.values() if job["status"] in ACTIVE), None)
            if busy:
                raise JobBusyError(self.get(busy["job_id"]))
            job_id = uuid.uuid4().hex
            workspace = self.directory / job_id / "workspace"
            init_project(workspace, subject)
            uploads = workspace / "sources" / "uploads"
            uploads.mkdir()
            files = []
            for index, (name, content) in enumerate(decoded, 1):
                stored_name = f"{index:03d}-{name}"
                (uploads / stored_name).write_bytes(content)
                files.append({"name": name, "stored_name": stored_name, "size_bytes": len(content)})
            record = {"job_id": job_id, "status": "queued", "stage": "queued", "message": "材料已接收，准备开始", "subject": subject,
                      "created_at": _now(), "updated_at": _now(), "files": files, "history": [], "result_status": None}
            self.jobs[job_id] = record
            self.events[job_id] = threading.Event()
            self._save(record)
            worker = threading.Thread(target=self._execute, args=(job_id,), daemon=True, name=f"study-{job_id[:8]}")
            self.workers[job_id] = worker
            worker.start()
            return self.get(job_id)

    def _execute(self, job_id: str) -> None:
        def progress(stage: str, message: str):
            if self.closed.is_set():
                raise InterruptedError("服务正在关闭，本次生成已中断；材料保留，可以重新生成。")
            with self.lock:
                record = self.jobs[job_id]
                record.update(status="running", stage=stage, message=message, updated_at=_now())
                record["history"].append({"stage": stage, "message": message, "at": record["updated_at"]})
                self._save(record)
        try:
            progress("preparing", "正在准备独立的课程工作区")
            workspace = self.directory / job_id / "workspace"
            guide = self.runner(workspace, progress)
            # Check the saved result, not just a successful return from a model.
            saved = read_json(project_paths(workspace)["study_guide"])
            if saved.get("guide_kind") != "student-study-guide":
                raise ValueError("讲义结果不完整，原有课程没有被替换。")
            paths = project_paths(workspace)
            for key in ("lesson_map", "generation_report"):
                read_json(paths[key])
            for suffix in ("md", "html", "json"):
                if not (paths["exports"] / f"study-guide.{suffix}").is_file():
                    raise ValueError("讲义导出尚未完成，原有课程没有被替换。")
            with self.lock:
                if self.closed.is_set():
                    raise InterruptedError("服务已关闭；本次结果保留在任务记录中，尚未替换原讲义。")
                record = self.jobs[job_id]
                write_json(self.project / ".study-state.json", {"active_run": job_id, "published_at": _now()})
                record.update(status="succeeded", stage="done", message="学习讲义已生成" if guide.report.status == "complete" else "材料草稿已生成，内容缺口仍需补全",
                              result_status=guide.report.status, updated_at=_now())
                try:
                    self._save(record)
                except OSError:
                    # The pointer is already committed; report the valid result
                    # as saved. The durable running record is recovered at boot.
                    record["message"] += "（讲义已保存，任务状态将在下次打开时恢复。）"
        except Exception as exc:
            with self.lock:
                record = self.jobs[job_id]
                message = "课件或转写文件无法打开，请确认文件完整后重新导入。" if isinstance(exc, zipfile.BadZipFile) else str(exc)
                record.update(status="interrupted" if isinstance(exc, InterruptedError) else "failed", message=message, updated_at=_now())
                self._save(record)
        finally:
            self.events[job_id].set()
            with self.lock:
                if self.closed.is_set() and not any(job["status"] in ACTIVE for job in self.jobs.values()):
                    self._ownership.close()

    def retry(self, job_id: str) -> dict:
        record = self.get(job_id)
        if not record or record["status"] not in {"failed", "interrupted"}:
            raise ValueError("只有失败或中断的任务可以重新生成。")
        uploads = self.directory / job_id / "workspace" / "sources" / "uploads"
        if any(Path(item["stored_name"]).name != item["stored_name"] for item in record["files"]):
            raise ValueError("保存的材料记录无效，请重新选择文件。")
        rows = [{"name": item["name"], "data": base64.b64encode((uploads / item["stored_name"]).read_bytes()).decode()} for item in record["files"]]
        return self.submit(rows, record["subject"])

    def active_root(self) -> Path:
        return active_project_dir(self.project)

    def close(self) -> None:
        with self.lock:
            self.closed.set()
            if not any(job["status"] in ACTIVE for job in self.jobs.values()):
                self._ownership.close()
