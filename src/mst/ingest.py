"""Input discovery and source-manifest generation.

Ingestion intentionally records metadata only. Original course files remain in
place and are never rewritten or copied into derived output by this module.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Iterable

from .io import project_paths, read_json, write_json

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
        "profile": subject if subject in {"generic", "computer-systems"} else "generic",
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
    existing = {str(item.get("segment_id")) for item in data.get("speech_segments", []) if isinstance(item, dict)}
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
        rows = transcribe(str(source_path))
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            segment_id = str(row.get("segment_id") or f"{source.get('source_id', 'audio')}::s{index:04d}")
            if segment_id in existing:
                continue
            segment = dict(row)
            segment.update({"segment_id": segment_id, "source_id": source.get("source_id"), "media_id": source.get("source_id"), "kind": "lecture", "status": row.get("status", "pending")})
            segments.append(segment)
            existing.add(segment_id)
            added += 1
    data["speech_segments"] = segments
    data["media_segments"] = segments
    data["audio_segments"] = segments
    write_json(map_path, data)
    return added
