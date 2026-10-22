"""Explicit audio-only HTTP connections, usable by the bundled desktop runtime."""

from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .speech import (DEFAULT_SPEECH_MODEL, SpeechRequestError, transcription_request_options,
                     transcription_response, transcription_rows, validate_audio_file)
from .web_models import GenerationOptions


MAX_SPEECH_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass
class SpeechOptions(GenerationOptions):
    @classmethod
    def parse(cls, value=None):
        if isinstance(value, dict) and value.get("provider", "none") != "none" and "model" not in value:
            value = {**value, "model": DEFAULT_SPEECH_MODEL}
        try:
            return super().parse(value)
        except ValueError as exc:
            message = str(exc).replace("生成设置", "转写设置").replace("材料发送范围", "录音发送范围").replace("本地草稿", "本机已有转写")
            raise ValueError(message) from None

    def public(self):
        return {**super().public(), "scope": "selected-recording-audio" if self.provider != "none" else "local-saved-transcripts"}


class _NoSpeechRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpeechRequestError("转写地址发生重定向；请核对服务地址后重新确认，尚未向新地址发送录音。")


class HTTPAudioProvider:
    def __init__(self, options: SpeechOptions):
        self.name = options.provider + "-speech"
        self.model = options.model
        self.base_url = options.base_url
        self._key = options.api_key
        self.transcription_cache_key = json.dumps({"base_url": self.base_url, "request": transcription_request_options(self.model)}, sort_keys=True)
        self._opener = build_opener(_NoSpeechRedirect())

    def close(self):
        self._key = ""

    def validate_audio(self, audio_path):
        validate_audio_file(audio_path)

    def transcribe(self, audio_path):
        self.validate_audio(audio_path)
        path = Path(audio_path)
        content = path.read_bytes()
        boundary = "mst-" + uuid.uuid4().hex
        while boundary.encode() in content:
            boundary = "mst-" + uuid.uuid4().hex
        chunks = []
        fields = {"model": self.model, **transcription_request_options(self.model)}
        for field, value in fields.items():
            for item in value if isinstance(value, list) else [value]:
                name = field + "[]" if isinstance(value, list) else field
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{item}\r\n'.encode())
        filename = path.name.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode(),
                       content, f"\r\n--{boundary}--\r\n".encode()])
        headers = {"Content-Type": "multipart/form-data; boundary=" + boundary, "Accept": "application/json"}
        if self._key:
            headers["Authorization"] = "Bearer " + self._key
        try:
            with self._opener.open(Request(self.base_url + "/audio/transcriptions", b"".join(chunks), headers), timeout=180) as response:
                raw = response.read(MAX_SPEECH_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            messages = {400: "转写模型不接受当前录音或请求格式，请核对模型，也可添加 SRT/VTT 转写。",
                        401: "转写密钥无效或已失效，请检查密钥。", 403: "该密钥没有调用所选转写模型的权限。",
                        404: "未找到转写接口或模型，请检查服务基础地址与模型名称。",
                        413: "转写服务拒绝了录音大小，请压缩或分段后重新导入。",
                        429: "转写服务限额或余额不足；已停止请求，请检查账户后重试。"}
            raise SpeechRequestError(messages.get(exc.code, "转写服务返回错误；已停止请求，没有自动重发录音。")) from None
        except (URLError, TimeoutError, OSError):
            raise SpeechRequestError("无法连接转写服务或等待超时；请检查地址和网络后重试，没有自动重发录音。") from None
        if len(raw) > MAX_SPEECH_RESPONSE_BYTES:
            raise SpeechRequestError("转写结果超过本工具上限，本次没有使用截断文字；请将录音分段后重试。")
        try:
            return transcription_response(json.loads(raw))
        except (ValueError, TypeError):
            raise SpeechRequestError("服务未返回有效转写或时间格式不正确；未保存这份转写，请检查服务或添加 SRT/VTT。") from None


class SpeechSession:
    def __init__(self, provider, options: SpeechOptions, progress, names=None):
        self.provider, self.options, self.progress = provider, options, progress
        self.name, self.model = provider.name, provider.model
        self.transcription_cache_key = getattr(provider, "transcription_cache_key", "")
        self.names = names or {}
        self.requests = self.succeeded = self.segments = self.reused = self.recordings = 0
        self.failure = ""

    def stats(self):
        return {"requests": self.requests, "succeeded": self.succeeded, "segments": self.segments,
                "reused_recordings": self.reused, "stopped_after_error": bool(self.failure)}

    def report_recording(self, source, cached):
        self.recordings += 1
        name = self.names.get(source["name"], source["name"])
        if cached:
            self.reused += 1
        self.progress("transcribing", f"{'正在复用已保存的转写' if cached else '正在转写录音'} {self.recordings}：{name}")

    def validate_audio(self, audio_path):
        validate = getattr(self.provider, "validate_audio", None)
        if callable(validate):
            validate(audio_path)

    def transcribe(self, audio_path):
        if self.failure:
            raise SpeechRequestError(self.failure)
        self.requests += 1
        try:
            rows = transcription_rows(self.provider.transcribe(audio_path))
            self.succeeded += 1
            self.segments += len(rows)
            return rows
        except Exception as exc:
            message = str(exc) if isinstance(exc, SpeechRequestError) else "转写服务未成功返回有效片段；已停止请求，请核对设置后重试。"
            self.failure = message.replace(self.options.api_key, "[密钥已隐藏]") if self.options.api_key else message
            raise SpeechRequestError(self.failure) from None

    def close(self):
        close = getattr(self.provider, "close", None)
        try:
            if callable(close):
                close()
        finally:
            self.options.api_key = ""
