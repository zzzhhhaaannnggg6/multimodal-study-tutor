"""Source discovery and explicitly requested speech ingestion.

Discovery records metadata only. Speech requests use verified temporary copies
and keep local transcript receipts. Original course files are never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import tempfile
from pathlib import Path
from typing import Iterable

from .alignment import align_speech_to_visuals
from .multimodal import annotate_speech_metadata
from .io import project_paths, read_json, write_json
from .models import SpeechSegment, VisualFrame
from .profiles import PROFILES

SUPPORTED_EXTENSIONS = {
    ".pptx": "slides",
    ".ppt": "slides",
    ".pdf": "reading",
    ".docx": "transcript",
    ".txt": "transcript",
    ".md": "reading",
    ".srt": "transcript",
    ".vtt": "transcript",
    ".mp3": "audio",
    ".m4a": "audio",
    ".wav": "audio",
    ".mp4": "video",
}


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(paths: Iterable[str | Path]) -> Iterable[Path]:
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            yield from (item for item in sorted(path.rglob("*")) if item.is_file())
        elif path.is_file():
            yield path
        else:
            raise FileNotFoundError(f"input path does not exist: {path}")


def discover_sources(paths: Iterable[str | Path]) -> list[dict[str, object]]:
    """Build a portable manifest from files or directories.

    Absolute paths are retained only as a local diagnostic field and are never
    used as stable IDs. ``portable_path`` is relative to the supplied root when
    possible; callers can redact ``path`` before publishing a manifest.
    """

    rows: list[dict[str, object]] = []
    seen: set[Path] = set()
    for path in _iter_files(paths):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        suffix = resolved.suffix.lower()
        kind = SUPPORTED_EXTENSIONS.get(suffix, "other")
        stat = resolved.stat()
        rows.append(
            {
                "source_id": f"source::{len(rows) + 1:04d}",
                "kind": kind,
                "name": resolved.name,
                "extension": suffix,
                "mime_type": mimetypes.guess_type(resolved.name)[0],
                "path": str(resolved),
                "size_bytes": stat.st_size,
                "sha256": _sha256(resolved),
            }
        )
    return rows


def init_project(project_dir: str | Path, subject: str = "generic") -> dict[str, object]:
    """Create an empty project directory and portable project manifest."""

    paths = project_paths(project_dir)
    paths["sources"].mkdir(parents=True, exist_ok=True)
    paths["derived"].mkdir(parents=True, exist_ok=True)
    paths["exports"].mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "project_id": paths["root"].name,
        "subject": subject,
        "profile": subject if subject in PROFILES else "generic",
        "source_manifest": [],
        "privacy": {"originals_read_only": True, "publish_originals": False},
    }
    write_json(paths["manifest"], manifest)
    return manifest


def ingest_project(project_dir: str | Path, inputs: Iterable[str | Path]) -> dict[str, object]:
    """Update a project's local manifest with discovered sources."""

    paths = project_paths(project_dir)
    if not paths["manifest"].exists():
        init_project(project_dir)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    rows = discover_sources(inputs)
    manifest["source_manifest"] = rows
    write_json(paths["manifest"], manifest)
    return manifest


def _transcription_rows(value: object) -> list[dict[str, object]]:
    """Reject partial/malformed service output instead of caching lost speech."""
    if not isinstance(value, list) or not value:
        raise ValueError("转写未返回有效片段；请检查录音或服务后重试，已有来源未被覆盖。")
    rows = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError(f"转写第 {index} 段缺少有效文字；未保存这份不完整转写。")
        row = {"text": item["text"], "segment_id": str(item.get("segment_id") or "")}
        start, end = item.get("start"), item.get("end")
        if start is not None or end is not None:
            if (any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in (start, end))
                    or end < start):
                raise ValueError(f"转写第 {index} 段的起止时间无效；未保存这份不完整转写。")
            row.update(start=start, end=end)
        # Page alignment and review status are decided locally. Preserve only
        # speech fields; provider metadata must not claim human verification.
        if isinstance(item.get("speaker"), str):
            row["speaker"] = item["speaker"]
        rows.append(row)
    return rows


def _transcription_receipt(source: dict, provider: object, directory: Path) -> tuple[Path, dict]:
    identity = {"name": str(getattr(provider, "name", "unknown")), "model": str(getattr(provider, "model", ""))}
    # Compatible adapters may distinguish endpoint/options without persisting
    # credentials or their configuration. Only the digest is stored.
    options = str(getattr(provider, "transcription_cache_key", ""))
    identity["options_sha256"] = hashlib.sha256(options.encode()).hexdigest()
    header = {"schema_version": 1, "source_id": source["source_id"], "source_sha256": source["sha256"], "provider": identity}
    digest = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
    return directory / f"{digest}.json", header


def _request_transcription(source: dict, transcribe: object, directory: Path) -> list[dict[str, object]]:
    """Send a checked local snapshot, even if the original changes mid-call."""
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".transcribing-", dir=directory) as temporary:
        snapshot = Path(temporary) / Path(source["path"]).name
        digest = hashlib.sha256()
        with Path(source["path"]).open("rb") as original, snapshot.open("xb") as copied:
            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                digest.update(chunk)
                copied.write(chunk)
        if digest.hexdigest() != source["sha256"]:
            raise ValueError(f"{source.get('name', '录音')}在导入后发生变化；请重新导入，未发送该文件。")
        return _transcription_rows(transcribe(str(snapshot)))


def transcribe_project_audio(project_dir: str | Path, provider: object, *, refresh: bool = False) -> int:
    """Add speech evidence, reusing completed per-recording local receipts.

    A later failure leaves the map unchanged but retains earlier receipts for
    retry. Refresh explicitly calls the service again; changed evidence is
    still rejected rather than overwriting existing references.
    """

    paths = project_paths(project_dir)
    manifest = read_json(paths["manifest"])
    map_path = paths["lesson_map"]
    if not map_path.exists():
        raise FileNotFoundError(f"lesson map does not exist: {map_path}; run study build first")
    data = read_json(map_path)
    existing = {str(item.get("segment_id")): item for item in data.get("speech_segments", []) if isinstance(item, dict)}
    segments = list(data.get("speech_segments", []))
    added = 0
    transcribe = getattr(provider, "transcribe", None)
    if not callable(transcribe):
        raise TypeError("speech provider must implement transcribe(audio_path)")
    sources = [source for source in manifest.get("source_manifest", []) if source.get("kind") in {"audio", "video"}]
    # Preflight the whole batch before any paid call, including cache hits.
    for source in sources:
        if not source.get("path") or not source.get("source_id") or not source.get("sha256"):
            raise ValueError("录音缺少来源标识或文件校验信息，请重新导入材料。")
        if _sha256(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"{source.get('name', '录音')}在导入后发生变化；请重新导入，未发送录音，已有转写未被覆盖。")
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("source_id") != source["source_id"]:
                continue
            old_hash = (segment.get("metadata") or {}).get("transcription", {}).get("source_sha256")
            if old_hash and old_hash != source["sha256"]:
                raise ValueError(f"{source.get('name', '录音')}与已有转写的文件不同；请在新项目中导入，已有来源未被覆盖。")
    directory = paths["derived"] / "transcriptions"
    for source in sources:
        source_id = str(source.get("source_id") or "")
        receipt_path, header = _transcription_receipt(source, provider, directory)
        cached = receipt_path.exists() and not refresh
        if cached:
            try:
                receipt = read_json(receipt_path)
                if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in header.items()):
                    raise ValueError("receipt identity mismatch")
                rows = _transcription_rows(receipt.get("segments"))
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("本地转写记录损坏；可明确选择重新转写，程序未自动上传录音。") from exc
        else:
            rows = _request_transcription(source, transcribe, directory)
        matched_ids = set()
        for index, row in enumerate(rows, 1):
            # Providers often restart numbering for every file. Source and
            # ordinal, rather than that provider-local ID, identify our record.
            segment_id = f"{source_id}::transcription::{index:04d}"
            provider_id = str(row.get("segment_id") or "")
            previous = existing.get(segment_id)
            if previous is None:
                legacy = existing.get(provider_id or f"{source_id}::s{index:04d}")
                if legacy and legacy.get("source_id") == source_id:
                    previous = legacy  # Preserve already referenced legacy IDs.
            if previous is not None:
                matched_ids.add(previous["segment_id"])
                old_hash = (previous.get("metadata") or {}).get("transcription", {}).get("source_sha256")
                if (previous.get("source_id") != source_id or (old_hash and old_hash != source.get("sha256"))
                        or any(previous.get(key) != row.get(key) for key in ("text", "start", "end"))):
                    raise ValueError(f"{source.get('name', '录音')}第 {index} 段与已有转写不同；请核对转写或在新项目中重新导入，已有来源未被覆盖。")
                continue
            metadata = annotate_speech_metadata(row.get("metadata"), str(row.get("text", "")))
            metadata["transcription"] = {"provider": str(getattr(provider, "name", "unknown")),
                "provider_segment_id": provider_id, "segment_index": index,
                "source_sha256": source.get("sha256"), "model": header["provider"]["model"]}
            segment = dict(row)
            segment.pop("alignment", None)  # A transcriber cannot verify page alignment.
            segment.update(
                {
                    "segment_id": segment_id,
                    "source_id": source_id,
                    "media_id": source_id,
                    "kind": "lecture",
                    "status": "pending",
                    "metadata": metadata,
                }
            )
            segments.append(segment)
            existing[segment_id] = segment
            matched_ids.add(segment_id)
            added += 1
        for segment in segments:
            if (isinstance(segment, dict) and segment.get("source_id") == source_id
                    and segment.get("segment_id") not in matched_ids):
                raise ValueError(f"{source.get('name', '录音')}比已有转写缺少片段；请核对，已有来源未被覆盖。")
        # Each recording is durable independently. The lesson map is published
        # only when the entire batch succeeds, so references never see half a run.
        if not cached:
            write_json(receipt_path, {**header, "segments": rows})
    for source in sources:
        if _sha256(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"{source.get('name', '录音')}在处理期间发生变化；已完成的本地转写保留，来源地图未更新，请核对文件。")
    if not added:
        return 0
    pages = [VisualFrame.from_dict(item) for item in data.get("pages", data.get("visual_sources", [])) if isinstance(item, dict)]
    aligned = align_speech_to_visuals(pages, [SpeechSegment.from_dict(item) for item in segments if isinstance(item, dict)])
    data["speech_segments"] = [item.to_dict() for item in aligned]
    data["media_segments"] = data["speech_segments"]
    data["audio_segments"] = data["speech_segments"]
    write_json(map_path, data)
    return added
