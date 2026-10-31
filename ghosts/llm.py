"""Local-only client for Ollama (build stage 3).

Only build-time code may use this module. It talks to an Ollama server on this machine and
refuses any other host, so a typo can never send text to a hosted model API. The standard
library is enough: no HTTP package is needed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

log = logging.getLogger(__name__)

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 300.0  # seconds per model call
DEFAULT_TEMPERATURE = 0.6
DEFAULT_MAX_TOKENS = 400
LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})

# (url, JSON payload or None for a GET, timeout in seconds) -> parsed JSON object.
Transport = Callable[[str, dict[str, Any] | None, float], dict[str, Any]]

# An empty ProxyHandler means "never use a proxy": local calls must stay on this machine.
_OPENER = build_opener(ProxyHandler({}))


class LLMError(RuntimeError):
    """The local model could not be reached or gave an unusable answer."""


class TextGenerator(Protocol):
    """Anything that can turn a prompt into text; the real one is OllamaClient."""

    def generate(self, prompt: str, *, system: str = "", seed: int | None = None) -> str:
        """Return the model's reply to ``prompt``."""


def require_local(host: str) -> str:
    """Return ``host`` without a trailing slash, or raise ValueError if it is not local."""
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTNAMES:
        raise ValueError(
            f"refusing Ollama host {host!r}: only localhost, 127.0.0.1 or ::1 are allowed"
        )
    return host.rstrip("/")


def http_json(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    """POST ``payload`` as JSON (or GET when it is None) and return the parsed JSON object."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read()
    except (OSError, HTTPException) as exc:  # refused, timed out, HTTP error, cut-off reply
        raise LLMError(f"cannot reach Ollama at {url}: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Ollama sent invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Ollama sent an unexpected reply (not a JSON object)")
    return parsed


def has_model(installed: tuple[str, ...], wanted: str) -> bool:
    """True if ``wanted`` is installed; a bare name such as ``gemma3`` means ``gemma3:latest``."""
    return wanted in installed or f"{wanted}:latest" in installed


@dataclass(frozen=True)
class OllamaClient:
    """Generate text with a model served by a local Ollama."""

    model: str
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    transport: Transport = field(default=http_json, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("an Ollama model name is required")
        object.__setattr__(self, "host", require_local(self.host))

    def generate(self, prompt: str, *, system: str = "", seed: int | None = None) -> str:
        """Ask the model once (no streaming) and return its stripped reply."""
        options: dict[str, Any] = {"temperature": self.temperature, "num_predict": self.max_tokens}
        if seed is not None:
            options["seed"] = seed
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "think": False,
            "options": options,
        }
        reply = self.transport(f"{self.host}/api/generate", payload, self.timeout)
        text = reply.get("response")

        if not isinstance(text, str) or not text.strip():
            done_reason = reply.get("done_reason", "unknown")
            thinking = reply.get("thinking", "")

            raise LLMError(
                f"Ollama returned no story "
                f"(done_reason={done_reason}, "
                f"thinking_tokens_present={bool(thinking)})"
            )
        return text.strip()

    def installed_models(self) -> tuple[str, ...]:
        """Names of the models this Ollama has downloaded."""
        reply = self.transport(f"{self.host}/api/tags", None, min(self.timeout, 10.0))
        models = reply.get("models")
        if not isinstance(models, list):
            raise LLMError("Ollama sent an unexpected model list")
        return tuple(m["name"] for m in models if isinstance(m, dict) and "name" in m)

    def check_ready(self) -> None:
        """Raise LLMError unless Ollama is running and has this model."""
        if not has_model(self.installed_models(), self.model):
            raise LLMError(f"model {self.model!r} is not installed; run: ollama pull {self.model}")
