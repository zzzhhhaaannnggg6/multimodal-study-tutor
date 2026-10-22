"""Local recording lookup: explicit speech provenance, never filename guessing."""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from pathlib import Path

from .io import project_paths, read_json


MEDIA_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".mp4": "video/mp4"}


def seconds(value):
    """Accept stored seconds or explicit HH:MM:SS timestamps; reject guesses."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"\d+(?::[0-5]\d){0,2}(?:\.\d+)?", value):
            return None
        parts = value.split(":")
        value = sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def byte_range(value, size):
    """One bounded HTTP byte range, including open and suffix requests."""
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value) if len(value) < 128 else None
    if not match or not size:
        raise ValueError("录音请求的字节范围无效。")
    left, right = match.groups()
    if not left:
        if not right or int(right) == 0:
            raise ValueError("录音请求的字节范围无效。")
        return max(0, size - int(right)), size - 1
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError("录音请求的字节范围无效。")
    return start, end


class RecordingLibrary:
    """Resolve selected files and check their bytes before serving any range."""

    def __init__(self):
        self._verified = {}
        self._lock = threading.Lock()

    def sources(self, root):
        path = project_paths(root)["manifest"]
        if not path.is_file():
            return {}
        rows = read_json(path).get("source_manifest", [])
        result = {}
        repeated = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("kind") not in {"audio", "video"}:
                continue
            source_id, digest = row.get("source_id"), row.get("sha256")
            if not isinstance(source_id, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                continue
            if source_id in result:
                repeated.add(source_id)
            result[source_id] = row
        return {key: row for key, row in result.items() if key not in repeated}

    @staticmethod
    def token(source):
        return hashlib.sha256((source["source_id"] + "\0" + source["sha256"]).encode()).hexdigest()

    @staticmethod
    def path(source):
        raw = source.get("path")
        if not isinstance(raw, str) or not raw:
            raise ValueError("本机录音位置缺失，请重新导入录音。")
        target = Path(raw)
        # Discovery stores canonical paths. Replacing one with a symlink must
        # not make a lesson serve another file, even if its extension matches.
        if (not target.is_absolute() or target != target.resolve() or not target.is_file()
                or target.suffix.lower() not in MEDIA_TYPES):
            raise ValueError("本机录音已移动或不可用，请重新导入录音。")
        return target

    def links(self, root, refs, prefix):
        map_path = project_paths(root)["lesson_map"]
        if not map_path.is_file():
            return {}
        from .models import LessonMap
        segments = LessonMap.from_dict(read_json(map_path)).speech_segments
        wanted = {row.get("ref") for row in refs if isinstance(row, dict)}
        sources = self.sources(root)
        result, duplicates = {}, set()
        for segment in segments:
            if segment.segment_id not in wanted:
                continue
            source = sources.get(segment.source_id)
            if not source:
                continue  # A transcript with a similar name is not an audio link.
            transcription = segment.metadata.get("transcription", {})
            if transcription.get("source_sha256") != source["sha256"]:
                continue
            start = seconds(segment.start)
            end = None if segment.metadata.get("end_inferred") else seconds(segment.end)
            if start is None or (end is not None and end <= start):
                continue
            try:
                self.path(source)
            except (ValueError, OSError):
                continue
            if segment.segment_id in result:
                duplicates.add(segment.segment_id)
            result[segment.segment_id] = {"url": prefix + self.token(source), "name": source.get("name", "课堂录音"),
                                          "start": start, "end": end, "status": segment.status}
        return {key: row for key, row in result.items() if key not in duplicates}

    def open(self, root, token):
        source = next((row for row in self.sources(root).values() if self.token(row) == token), None)
        if source is None:
            raise ValueError("未找到这份课程录音，请重新打开讲义或导入录音。")
        path = self.path(source)
        handle = path.open("rb")
        try:
            before = os.fstat(handle.fileno())
            identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            key = (str(path), source["sha256"])
            with self._lock:
                if self._verified.get(key) != identity:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(256 * 1024), b""):
                        digest.update(chunk)
                    after = os.fstat(handle.fileno())
                    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    if (digest.hexdigest() != source["sha256"] or identity != after_identity or not before.st_size):
                        raise ValueError("本机录音已变化，无法核对原时间段；请重新导入，原讲义仍保留。")
                    self._verified[key] = identity
            handle.seek(0)
            return handle, before.st_size, MEDIA_TYPES[path.suffix.lower()]
        except Exception:
            handle.close()
            raise
