"""Provider-neutral text generation interfaces.

The deterministic provider is used by tests and offline demos. The optional
OpenAI adapter is intentionally tiny; reconstruction logic remains in the
core package and can be replaced by another provider without changing maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class TextModelProvider(Protocol):
    name: str

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        """Return one model completion for a bounded reconstruction task."""


# Backward-compatible name used by the first MVP.
ModelProvider = TextModelProvider


class SpeechProvider(Protocol):
    """Optional adapter that turns audio into timestamped speech segments."""

    name: str

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        """Return dictionaries with text and, when available, start/end."""


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

    def __init__(self, model: str = "gpt-4o-transcribe", client: Any | None = None) -> None:
        self.model = model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "OpenAI support is optional; install multimodal-study-tutor[openai]"
                ) from exc
            self._client = OpenAI()
        return self._client

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        with open(audio_path, "rb") as handle:
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=handle,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        segments = getattr(response, "segments", None)
        if segments:
            rows: list[dict[str, Any]] = []
            for index, segment in enumerate(segments, 1):
                if isinstance(segment, dict):
                    row = dict(segment)
                else:
                    row = {"start": getattr(segment, "start", None), "end": getattr(segment, "end", None), "text": getattr(segment, "text", "")}
                row.setdefault("segment_id", f"speech::{index:04d}")
                rows.append(row)
            return rows
        text = getattr(response, "text", "")
        return [{"segment_id": "speech::0001", "text": str(text), "status": "unresolved"}]


__all__ = ["ModelProvider", "TextModelProvider", "SpeechProvider", "MockProvider", "OpenAIProvider", "OpenAISpeechProvider"]
