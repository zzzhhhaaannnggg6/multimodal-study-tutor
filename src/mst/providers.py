"""Provider-neutral text generation interfaces.

The deterministic provider is used by tests and offline demos. The optional
OpenAI adapter is intentionally tiny; reconstruction logic remains in the
core package and can be replaced by another provider without changing maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelProvider(Protocol):
    name: str

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        """Return one model completion for a bounded reconstruction task."""


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
