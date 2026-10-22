"""Speech request contracts and lossless, unreviewed transcript normalization."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any


DEFAULT_SPEECH_MODEL = "whisper-1"
# A product bound, not a claim about every transcription service's file limit.
MAX_SPEECH_BYTES = 24 * 1024 * 1024


class SpeechRequestError(RuntimeError):
    """Safe to display: excludes raw service responses and credentials."""


def validate_audio_file(audio_path: str) -> None:
    path = Path(audio_path)
    if path.suffix.lower() not in {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}:
        raise SpeechRequestError("这份录音格式暂不支持转写；请另存为 MP3、M4A 或 WAV，或添加 SRT/VTT 转写。")
    size = path.stat().st_size
    if not size:
        raise SpeechRequestError("录音文件为空，请检查文件或添加教师转写；本次未上传。")
    if size > MAX_SPEECH_BYTES:
        raise SpeechRequestError("本工具当前每段录音转写上限为 24 MB；请压缩或分段后重新导入，也可添加 SRT/VTT。整批尚未上传。")


def transcription_request_options(model: str) -> dict[str, Any]:
    if model == "whisper-1":
        return {"response_format": "verbose_json", "timestamp_granularities": ["segment"]}
    if model == "gpt-4o-transcribe-diarize":
        return {"response_format": "diarized_json", "chunking_strategy": "auto"}
    # Other named models do not inherit Whisper's timestamp capability. Keep
    # the user's model choice, and accept missing timing without inventing it.
    return {"response_format": "json"}


def transcription_rows(value: object) -> list[dict[str, Any]]:
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
        # Review and page alignment are decided locally, never by the service.
        if isinstance(item.get("speaker"), str):
            row["speaker"] = item["speaker"]
        rows.append(row)
    return rows


def transcription_response(response: Any) -> list[dict[str, Any]]:
    """Accept SDK objects, compatible JSON dictionaries, or unlocated text."""
    def get(obj, field, default=None):
        return obj.get(field, default) if isinstance(obj, dict) else getattr(obj, field, default)

    if get(response, "error"):
        raise ValueError("转写服务返回错误；未保存这份转写。")
    segments = get(response, "segments")
    if segments is not None and not isinstance(segments, list):
        raise ValueError("转写片段格式无效；未保存这份转写。")
    if segments:
        rows = []
        for index, segment in enumerate(segments, 1):
            rows.append({"segment_id": f"speech::{index:04d}",
                         **{key: get(segment, key) for key in ("text", "start", "end", "speaker")}})
        return transcription_rows(rows)
    text = response if isinstance(response, str) else get(response, "text")
    return transcription_rows([{"segment_id": "speech::0001", "text": text}])


__all__ = ["DEFAULT_SPEECH_MODEL", "MAX_SPEECH_BYTES", "SpeechRequestError",
           "transcription_request_options", "transcription_response", "transcription_rows", "validate_audio_file"]
