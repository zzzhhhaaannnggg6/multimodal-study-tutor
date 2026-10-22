"""Input discovery and source-manifest generation.

Ingestion intentionally records metadata only. Original course files remain in
place and are never rewritten or copied into derived output by this module.
"""

from __future__ import annotations

import hashlib
import mimetypes
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
    import json

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    rows = discover_sources(inputs)
    manifest["source_manifest"] = rows
    write_json(paths["manifest"], manifest)
    return manifest


def transcribe_project_audio(project_dir: str | Path, provider: object) -> int:
    """Add provider-generated timestamped segments for local audio/video files."""

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
    for source in manifest.get("source_manifest", []):
        if source.get("kind") not in {"audio", "video"}:
            continue
        source_path = source.get("path")
        if not source_path:
            continue
        source_id = str(source.get("source_id") or "")
        if not source_id:
            raise ValueError("录音缺少来源标识，请重新导入材料。")
        rows = transcribe(str(source_path))
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
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
                old_hash = (previous.get("metadata") or {}).get("transcription", {}).get("source_sha256")
                if (previous.get("source_id") != source_id or (old_hash and old_hash != source.get("sha256"))
                        or any(previous.get(key) != row.get(key) for key in ("text", "start", "end"))):
                    raise ValueError(f"{source.get('name', '录音')}第 {index} 段与已有转写不同；请核对转写或在新项目中重新导入，已有来源未被覆盖。")
                continue
            metadata = annotate_speech_metadata(row.get("metadata"), str(row.get("text", "")))
            metadata["transcription"] = {"provider": str(getattr(provider, "name", "unknown")),
                "provider_segment_id": provider_id, "segment_index": index,
                "source_sha256": source.get("sha256")}
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
            added += 1
    pages = [VisualFrame.from_dict(item) for item in data.get("pages", data.get("visual_sources", [])) if isinstance(item, dict)]
    aligned = align_speech_to_visuals(pages, [SpeechSegment.from_dict(item) for item in segments if isinstance(item, dict)])
    data["speech_segments"] = [item.to_dict() for item in aligned]
    data["media_segments"] = data["speech_segments"]
    data["audio_segments"] = data["speech_segments"]
    write_json(map_path, data)
    return added
