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
from .ingest import SUPPORTED_EXTENSIONS, copy_transcription_receipts, ingest_project, init_project, transcribe_project_audio
from .io import active_project_dir, project_paths, read_json, write_json
from .materials import material_results
from .profiles import PROFILES
from .reconstruct import build_scaffold
from .web_models import GenerationOptions, HTTPTextProvider, ModelRequestError, ModelSession
from .web_speech import HTTPAudioProvider, SpeechOptions, SpeechSession


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


def run_pipeline(workspace: Path, progress: Callable[[str, str], None], *, provider=None, speech=None) -> StudyGuide:
    sources = sorted((workspace / "sources" / "uploads").iterdir())
    progress("inventory", "正在清点所选材料")
    manifest = ingest_project(workspace, sources)
    scaffold = build_scaffold(workspace, render=True, on_progress=progress)
    media = [row for row in manifest["source_manifest"] if row["kind"] in {"audio", "video"}]
    if speech and not media:
        raise ValueError("本次没有所选录音，请添加录音，或关闭录音转写后生成。")
    if media:
        transcribe_project_audio(workspace, speech, on_progress=speech.report_recording if speech else
                                 lambda source, cached: progress("transcribing", f"正在读取本机已有转写：{source['name']}"))
        scaffold = read_json(project_paths(workspace)["lesson_map"])
    if not any(page.get("text", "").strip() for page in scaffold["pages"]) and not any(segment.get("text", "").strip() for segment in scaffold["speech_segments"]):
        issues = scaffold["notes"].get("extraction_issues", [])
        if issues:
            raise ValueError("课件或转写无法打开或解析，请确认文件完整、格式可读后重试。")
        raise ValueError("材料已保存在本机，但没有读到课程文字；请添加教师转写或可提取文字的课件。")
    progress("writing", "正在组织学习讲义")
    guide = generate_project_guide(workspace, provider)
    if isinstance(provider, ModelSession) and not provider.checked_units:
        raise ModelRequestError(provider.failure or "模型未生成通过完整性检查的知识点；原讲义未替换。可改选‘本地草稿’核对材料。")
    identity = {"subject": manifest["subject"], "sources": sorted(row["sha256"] for row in manifest["source_manifest"])}
    guide.lesson_id = manifest.get("web_course_id") or "course::" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    transcribed = {row.get("source_id") for row in scaffold["speech_segments"]}
    pending_media = [row for row in media if row["source_id"] not in transcribed]
    if pending_media:
        guide.report.warnings.append(f"{len(pending_media)} 份录音尚未转写，内容未进入讲义；可添加对应转写，或主动选择录音转写服务。")
        if guide.report.status == "complete":
            guide.report.status = "draft"
    untimed = sum(row.get("source_id") in {source["source_id"] for source in media} and row.get("start") is None
                  for row in scaffold["speech_segments"])
    if untimed:
        guide.report.warnings.append(f"{untimed} 段录音转写没有时间戳，保留为待定位文字，不能精确回听核对。")
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
    def __init__(self, project: str | Path, runner: Callable = run_pipeline, *, provider_factory=HTTPTextProvider, speech_factory=HTTPAudioProvider):
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
        self.provider_factory = provider_factory
        self.speech_factory = speech_factory
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
            record["materials"] = material_results(path.parent / "workspace", record.get("files", []))
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

    def submit(self, rows: Any, subject: str = "generic", *, generation=None, speech=None) -> dict:
        return self._submit(rows, subject, generation=generation, speech=speech)

    def _submit(self, rows: Any, subject: str, *, parent: dict | None = None, generation=None, speech=None, retained_names=None) -> dict:
        options = GenerationOptions.parse(generation)
        speech_options = SpeechOptions.parse(speech)
        if not isinstance(subject, str) or subject not in PROFILES:
            raise ValueError("请选择可用的学科。")
        decoded = decode_uploads(rows)
        if speech_options.provider != "none" and not any(SUPPORTED_EXTENSIONS.get(Path(name).suffix.lower()) in {"audio", "video"} for name, _ in decoded):
            raise ValueError("本次没有所选录音，请添加录音，或关闭录音转写后生成。")
        with self.lock:
            if self.closed.is_set():
                raise ValueError("服务正在关闭，请稍后重新打开。")
            busy = next((job for job in self.jobs.values() if job["status"] in ACTIVE), None)
            if busy:
                raise JobBusyError(self.get(busy["job_id"]))
            job_id = uuid.uuid4().hex
            workspace = self.directory / job_id / "workspace"
            manifest = init_project(workspace, subject)
            course_id = parent.get("course_id") if parent else None
            if course_id:
                manifest["web_course_id"] = course_id
            manifest["generation"] = options.public()
            manifest["speech"] = speech_options.public()
            write_json(project_paths(workspace)["manifest"], manifest)
            uploads = workspace / "sources" / "uploads"
            uploads.mkdir()
            files = []
            for index, (name, content) in enumerate(decoded, 1):
                stored_name = f"{index:03d}-{name}"
                (uploads / stored_name).write_bytes(content)
                files.append({"name": name, "stored_name": stored_name, "size_bytes": len(content)})
            record = {"job_id": job_id, "status": "queued", "stage": "queued", "message": "材料已接收，准备开始", "subject": subject,
                      "created_at": _now(), "updated_at": _now(), "files": files, "history": [], "result_status": None,
                      "parent_job_id": parent["job_id"] if parent else None, "course_id": course_id,
                      "generation": options.public(),
                      "speech": speech_options.public(),
                      "retained_sources": {files[index]["stored_name"]: key for index, key in enumerate(retained_names or [])},
                      "materials": material_results(workspace, files)}
            self.jobs[job_id] = record
            self.events[job_id] = threading.Event()
            self._save(record)
            worker = threading.Thread(target=self._execute, args=(job_id, options, speech_options), daemon=True, name=f"study-{job_id[:8]}")
            self.workers[job_id] = worker
            worker.start()
            return self.get(job_id)

    def _execute(self, job_id: str, options: GenerationOptions, speech_options: SpeechOptions) -> None:
        session = speech_session = None
        def progress(stage: str, message: str):
            if self.closed.is_set():
                raise InterruptedError("服务正在关闭，本次生成已中断；材料保留，可以重新生成。")
            with self.lock:
                record = self.jobs[job_id]
                if stage == "writing":
                    record["materials"] = material_results(self.directory / job_id / "workspace", record["files"])
                record.update(status="running", stage=stage, message=message, updated_at=_now())
                record["history"].append({"stage": stage, "message": message, "at": record["updated_at"]})
                self._save(record)
        try:
            progress("preparing", "正在准备独立的课程工作区")
            workspace = self.directory / job_id / "workspace"
            record = self.jobs[job_id]
            if record["parent_job_id"] and record["retained_sources"]:
                ingest_project(workspace, sorted((workspace / "sources" / "uploads").iterdir()))
                copy_transcription_receipts(self.directory / record["parent_job_id"] / "workspace", workspace, record["retained_sources"])
            kwargs = {}
            if options.provider != "none":
                session = ModelSession(self.provider_factory(options), options, progress)
                kwargs["provider"] = session
            if speech_options.provider != "none":
                names = {item["stored_name"]: item["name"] for item in record["files"]}
                speech_session = SpeechSession(self.speech_factory(speech_options), speech_options, progress, names)
                kwargs["speech"] = speech_session
            guide = self.runner(workspace, progress, **kwargs)
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
                if session:
                    record["generation"]["stats"] = session.stats()
                if speech_session:
                    record["speech"]["stats"] = speech_session.stats()
                record["materials"] = material_results(workspace, record["files"])
                write_json(self.project / ".study-state.json", {"active_run": job_id, "published_at": _now()})
                record.update(status="succeeded", stage="done", message="学习讲义已生成" if guide.report.status == "complete" else "材料草稿已生成，内容缺口仍需补全",
                              result_status=guide.report.status, course_id=guide.lesson_id, updated_at=_now())
                if session and guide.report.status != "complete":
                    record["message"] = "模型讲解已保存，仍有待核验内容" if not session.failure else "部分模型讲解已保存，服务中断的内容仍待补全"
                try:
                    self._save(record)
                except OSError:
                    # The pointer is already committed; report the valid result
                    # as saved. The durable running record is recovered at boot.
                    record["message"] += "（讲义已保存，任务状态将在下次打开时恢复。）"
        except Exception as exc:
            with self.lock:
                record = self.jobs[job_id]
                if session:
                    record["generation"]["stats"] = session.stats()
                if speech_session:
                    record["speech"]["stats"] = speech_session.stats()
                record["materials"] = material_results(self.directory / job_id / "workspace", record["files"])
                message = "课件或转写文件无法打开，请确认文件完整后重新导入。" if isinstance(exc, zipfile.BadZipFile) else str(exc)
                for key in (options.api_key, speech_options.api_key):
                    if key:
                        message = message.replace(key, "[密钥已隐藏]")
                record.update(status="interrupted" if isinstance(exc, InterruptedError) else "failed", message=message, updated_at=_now())
                self._save(record)
        finally:
            for connection in (session, speech_session):
                try:
                    if connection:
                        connection.close()
                except Exception:
                    pass  # A provider's cleanup cannot prevent durable job completion.
            options.api_key = ""
            speech_options.api_key = ""
            self.events[job_id].set()
            with self.lock:
                if self.closed.is_set() and not any(job["status"] in ACTIVE for job in self.jobs.values()):
                    self._ownership.close()

    def retry(self, job_id: str, *, generation=None, speech=None) -> dict:
        record = self.get(job_id)
        if not record or record["status"] not in {"failed", "interrupted"}:
            raise ValueError("只有失败或中断的任务可以重新生成。")
        if generation is None and record.get("generation", {}).get("provider", "none") != "none":
            raise ValueError("模型任务重试需要重新选择生成方式并确认发送范围；密钥没有保存。")
        if speech is None and record.get("speech", {}).get("provider", "none") != "none":
            raise ValueError("转写任务重试需要重新选择转写方式并确认录音发送范围；密钥没有保存。")
        return self.revise(job_id, [item["stored_name"] for item in record["files"]], [], generation=generation, speech=speech)

    def revise(self, job_id: str, keep: Any, rows: Any, *, generation=None, speech=None) -> dict:
        """Rebuild a saved import without altering its uploads or published guide."""
        record = self.get(job_id)
        if not record or record["status"] not in TERMINAL:
            raise ValueError("请等待材料处理结束，再补充或替换。")
        files = record.get("files", [])
        known = {item["stored_name"]: item for item in files}
        if not isinstance(keep, list) or any(not isinstance(key, str) or key not in known for key in keep) or len(set(keep)) != len(keep):
            raise ValueError("请从这次已保存的材料中选择需要保留的文件。")
        if any(Path(key).name != key or "\\" in key or key in {".", ".."} for key in keep):
            raise ValueError("保存的材料记录无效，请重新选择文件。")
        keep = [key for key in known if key in keep]  # Preserve source order after rechecking a box.
        if not isinstance(rows, list):
            raise ValueError("新增文件信息无效，请重新选择。")
        # Validate additions before reading/copying retained private files.
        additions = decode_uploads(rows) if rows else []
        if len(keep) + len(additions) > MAX_FILES:
            raise ValueError(f"本课材料不能超过 {MAX_FILES} 个。")
        uploads = (self.directory / job_id / "workspace" / "sources" / "uploads").resolve()
        retained = []
        total = sum(len(content) for _, content in additions)
        for key in keep:
            path = uploads / key
            if not path.resolve().is_relative_to(uploads):
                raise ValueError("保存的材料路径无效，请重新选择文件。")
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise ValueError(f"本机保存的材料已不可用，请重新添加：{known[key]['name']}") from exc
            total += size
            if total > MAX_UPLOAD_BYTES:
                raise ValueError("保留和新增的材料合计超过 100 MB，请分课次导入。")
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ValueError(f"无法读取本机保存的材料，请重新添加：{known[key]['name']}") from exc
            retained.append({"name": known[key]["name"], "data": base64.b64encode(content).decode()})
        if not record.get("course_id") and record["status"] == "succeeded":
            record["course_id"] = read_json(project_paths(uploads.parent.parent)["study_guide"]).get("lesson_id")
        return self._submit([*retained, *rows], record["subject"], parent=record, generation=generation, speech=speech, retained_names=keep)

    def active_root(self) -> Path:
        return active_project_dir(self.project)

    def close(self) -> None:
        with self.lock:
            self.closed.set()
            if not any(job["status"] in ACTIVE for job in self.jobs.values()):
                self._ownership.close()
