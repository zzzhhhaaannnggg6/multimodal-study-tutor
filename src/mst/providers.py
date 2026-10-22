"""Provider-neutral text generation interfaces.

The deterministic provider is used by tests and offline demos. The optional
OpenAI adapter is intentionally tiny; reconstruction logic remains in the
core package and can be replaced by another provider without changing maps.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import mimetypes
from pathlib import Path
from typing import Any, Protocol

from .speech import (DEFAULT_SPEECH_MODEL, SpeechRequestError,
                     transcription_request_options, transcription_response, validate_audio_file)


class TextModelProvider(Protocol):
    name: str

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        """Return one model completion for a bounded reconstruction task."""


# Backward-compatible name used by the first MVP.
ModelProvider = TextModelProvider


class SpeechProvider(Protocol):
    """Optional adapter that turns audio into timestamped speech segments.

    Results are cached per project/source/name/model. An adapter with additional
    options may expose ``transcription_cache_key`` to distinguish them; only
    its digest is persisted. Times, when present, are finite numeric seconds.
    """

    name: str

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        """Return dictionaries with text and, when available, start/end."""


class VisionProvider(Protocol):
    """Optional adapter that inspects one rendered page image."""

    name: str

    def analyze(self, image_path: str, *, context: str = "") -> dict[str, Any]:
        """Return structured visual cues; never silently assert verification."""


@dataclass
class MockProvider:
    """Stable provider for fixtures and CI; never makes a network request."""

    name: str = "mock"

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        del system, response_format
        return f"[mock completion]\n{user.strip()}"


class OpenAIProvider:
    """Lazy OpenAI Responses adapter, enabled only when the extra is installed."""

    name = "openai"

    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None) -> None:
        self.model = model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "OpenAI support is optional; install multimodal-study-tutor[openai]"
                ) from exc
            self._client = OpenAI()
        return self._client

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
        }
        if response_format == "json":
            kwargs["text"] = {"format": {"type": "json_object"}}
        response = self.client.responses.create(**kwargs)
        output = getattr(response, "output_text", None)
        if not output:
            raise RuntimeError("model returned no text output")
        return str(output)


class OpenAISpeechProvider:
    """Lazy OpenAI transcription adapter.

    The adapter accepts both timestamped segment responses and plain text
    responses.  Plain text is returned as one unresolved segment so callers do
    not invent precise teacher emphasis.
    """

    name = "openai-speech"

    def __init__(self, model: str = DEFAULT_SPEECH_MODEL, client: Any | None = None) -> None:
        self.model = model
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def validate_audio(self, audio_path: str) -> None:
        validate_audio_file(audio_path)

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import DefaultHttpxClient, OpenAI
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise SpeechRequestError(
                    "OpenAI support is optional; install multimodal-study-tutor[openai]"
                ) from exc
            # Retrying an upload may incur another charge. Redirects must not
            # send teacher recordings to a destination the user did not select.
            self._client = OpenAI(max_retries=0, timeout=180, http_client=DefaultHttpxClient(follow_redirects=False))
        return self._client

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        self.validate_audio(audio_path)
        with open(audio_path, "rb") as handle:
            try:
                response = self.client.audio.transcriptions.create(
                    model=self.model, file=handle, **transcription_request_options(self.model))
            except SpeechRequestError:
                raise
            except Exception as exc:
                code = getattr(exc, "status_code", None)
                if not isinstance(code, int):
                    code = None
                messages = {400: "所选模型不接受当前转写参数或录音格式；请核对模型，也可添加 SRT/VTT 转写。",
                            401: "转写密钥无效或已失效，请检查 OPENAI_API_KEY。",
                            403: "该密钥没有调用所选转写模型的权限。",
                            404: "未找到所选转写模型或接口，请核对模型名称。",
                            413: "转写服务拒绝了这段录音的大小，请压缩或分段后重新导入。",
                            429: "转写服务限额或余额不足；已停止请求，请检查账户后重试。"}
                raise SpeechRequestError(messages.get(code, "转写服务未成功返回；请检查网络、模型和密钥后重试。本次没有自动重发录音。")) from None
        try:
            return transcription_response(response)
        except ValueError as exc:
            raise SpeechRequestError(str(exc)) from None


class OpenAIVisionProvider:
    """Lazy OpenAI Responses adapter for rendered slide/page images."""

    name = "openai-vision"

    def __init__(self, model: str = "gpt-5-mini", client: Any | None = None) -> None:
        self.model = model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional extra
                raise RuntimeError(
                    "OpenAI support is optional; install multimodal-study-tutor[openai]"
                ) from exc
            self._client = OpenAI()
        return self._client

    def analyze(self, image_path: str, *, context: str = "") -> dict[str, Any]:
        path = Path(image_path)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        prompt = (
            "分析这张课程页面，只记录看得见的结构，不猜测教师意图。返回 JSON："
            "kind(text/code/formula/diagram/table/mixed/unknown)、summary、"
            "nodes、edges、formulas、code、uncertain。节点和边必须是图中可见文字或关系；"
            "看不清的内容放入 uncertain。" + (f"\n页面文字线索：{context}" if context else "")
        )
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"},
                    ],
                }
            ],
            text={"format": {"type": "json_object"}},
        )
        import json

        raw = getattr(response, "output_text", None)
        if not raw:
            raise RuntimeError("vision model returned no text")
        parsed = json.loads(str(raw))
        if not isinstance(parsed, dict):
            raise RuntimeError("vision model returned a non-object")
        return parsed


__all__ = [
    "ModelProvider",
    "TextModelProvider",
    "SpeechProvider",
    "VisionProvider",
    "MockProvider",
    "OpenAIProvider",
    "OpenAISpeechProvider",
    "OpenAIVisionProvider",
]
