"""Explicit, single-job text-model connections. Credentials never enter records."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUESTS = 61


class ModelRequestError(RuntimeError):
    """A safe message; never includes a provider's raw error body or headers."""


@dataclass
class GenerationOptions:
    provider: str = "none"
    model: str = ""
    base_url: str = ""
    api_key: str = field(default="", repr=False)

    @classmethod
    def parse(cls, value: Any = None) -> GenerationOptions:
        if value is None:
            return cls()
        if not isinstance(value, dict) or set(value) - {"provider", "model", "base_url", "api_key", "consent"}:
            raise ValueError("生成设置无效，请重新选择生成方式。")
        provider = value.get("provider", "none")
        if provider == "none":
            return cls()  # Local mode ignores credentials and never reads environment keys.
        if not isinstance(provider, str) or provider not in {"openai", "compatible"}:
            raise ValueError("请选择本地草稿、OpenAI 或兼容接口。")
        if value.get("consent") is not True:
            raise ValueError("使用模型前，请确认本次材料发送范围。")
        model = value.get("model", "")
        key = value.get("api_key", "")
        base = value.get("base_url", "")
        if not all(isinstance(item, str) for item in (model, key, base)):
            raise ValueError("请填写模型名称、服务地址和密钥。")
        model, key, base = model.strip(), key.strip(), base.strip().rstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9_./:@-]{1,160}", model):
            raise ValueError("请填写服务提供的模型名称。")
        if len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ValueError("密钥格式无效，请重新粘贴。")
        if provider == "openai":
            if base and base != "https://api.openai.com/v1":
                raise ValueError("其他服务地址请选择兼容接口。")
            base = "https://api.openai.com/v1"
        if not base or len(base) > 500 or any(char.isspace() or ord(char) < 32 for char in base):
            raise ValueError("请填写模型服务的基础地址，例如 https://api.example.com/v1。")
        try:
            parts = urlsplit(base)
            port = parts.port
        except ValueError as exc:
            raise ValueError("模型服务地址无效。") from exc
        del port
        loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
        if not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError("服务地址不能包含用户名、密钥、查询参数或片段。")
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
            raise ValueError("远程模型服务必须使用 HTTPS；本机服务可以使用 HTTP。")
        if parts.path.endswith(("/responses", "/chat/completions")):
            raise ValueError("请填写基础地址，不要加 responses 或 chat/completions。")
        if not key and not loopback:
            raise ValueError("请填写该服务的 API 密钥；本次使用后不会保存。")
        if key and (key in base or key in model):
            raise ValueError("请将密钥只填入密钥栏。")
        return cls(provider, model, base, key)

    def public(self) -> dict:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url,
                "consent": self.provider != "none", "scope": "selected-material-text" if self.provider != "none" else "local"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelRequestError("模型地址发生重定向；请核对服务基础地址后重新确认，尚未向新地址发送材料。")


class HTTPTextProvider:
    """Responses for OpenAI; Chat Completions for explicitly selected compatible services."""

    def __init__(self, options: GenerationOptions):
        self.name = options.provider
        self.model = options.model
        self.base_url = options.base_url
        self._key = options.api_key
        self._opener = build_opener(_NoRedirect())

    def close(self):
        self._key = ""

    def complete(self, *, system: str, user: str, response_format: str = "text") -> str:
        payload = {"model": self.model, "store": False}
        if self.name == "openai":
            endpoint = self.base_url + "/responses"
            payload.update(instructions=system, input=user)
            if response_format == "json":
                payload["text"] = {"format": {"type": "json_object"}}
        else:
            endpoint = self.base_url + "/chat/completions"
            payload["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            if response_format == "json":
                payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise ModelRequestError("本单元材料超过模型发送上限，请按章节拆分；本次没有发送截断内容。")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._key:
            headers["Authorization"] = "Bearer " + self._key
        try:
            with self._opener.open(Request(endpoint, body, headers), timeout=180) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            messages = {401: "密钥无效或已失效，请检查密钥。", 403: "该密钥没有调用所选模型的权限。",
                        404: "未找到模型接口，请检查基础地址与模型名称。", 429: "模型服务限额或余额不足，请检查服务账户后重试。"}
            raise ModelRequestError(messages.get(exc.code, "模型服务返回错误，请稍后重试或更换服务。")) from None
        except (URLError, TimeoutError, OSError):
            raise ModelRequestError("无法连接模型服务或等待超时；请检查地址和网络后重试。") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ModelRequestError("模型返回内容过大，本次没有使用截断结果。")
        try:
            data = json.loads(raw)
            if self.name == "openai":
                if data.get("status") != "completed" or data.get("error"):
                    raise ValueError("incomplete")
                text = "\n".join(part["text"] for item in data.get("output", []) if item.get("type") == "message"
                                 for part in item.get("content", []) if part.get("type") == "output_text" and isinstance(part.get("text"), str))
            else:
                choice = data["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("incomplete")
                text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty")
            return text
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ModelRequestError("模型未返回完整的文字答案；本次结果保留为待补内容。") from None


class ModelSession:
    """Bound requests, report actual progress, and stop resending after a service error."""

    def __init__(self, provider: Any, options: GenerationOptions, progress: Callable):
        self.provider = provider
        self.name = options.provider
        self.options = options
        self.progress = progress
        self.requests = 0
        self.succeeded = 0
        self.checked_units = 0
        self.failure = ""

    def stats(self):
        return {"requests": self.requests, "succeeded": self.succeeded, "checked_units": self.checked_units, "stopped_after_error": bool(self.failure)}

    def record_unit(self, *, usable: bool):
        if usable:
            self.checked_units += 1

    def close(self):
        close = getattr(self.provider, "close", None)
        try:
            if callable(close):
                close()
        finally:
            self.options.api_key = ""

    def complete(self, **kwargs):
        if self.failure:
            raise ModelRequestError(self.failure)
        if self.requests >= MAX_REQUESTS:
            self.failure = "本次模型请求已达章节上限，请拆分材料后继续。"
            raise ModelRequestError(self.failure)
        prompt = json.loads(kwargs["user"])
        message = "正在梳理整课主线" if prompt.get("task") == "plan_course" else "正在展开知识点讲解：" + str(prompt.get("title", "本节内容"))[:100]
        self.progress("writing", message)
        self.requests += 1
        try:
            result = self.provider.complete(**kwargs)
            if not isinstance(result, str) or not result.strip():
                raise ModelRequestError("模型没有返回文字答案。")
            self.succeeded += 1
            return result.replace(self.options.api_key, "[密钥已隐藏]") if self.options.api_key else result
        except Exception as exc:
            self.failure = str(exc) if isinstance(exc, ModelRequestError) else "模型服务暂时不可用，请检查设置后重试。"
            if self.options.api_key:
                self.failure = self.failure.replace(self.options.api_key, "[密钥已隐藏]")
            raise ModelRequestError(self.failure) from None
