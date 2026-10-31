from __future__ import annotations

import http.client
import json
from typing import Any

import pytest

from ghosts import llm
from ghosts.llm import LLMError, OllamaClient, has_model, http_json, require_local


class FakeTransport:
    """Stands in for the network: records every call and returns a canned reply."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any] | None, float]] = []

    def __call__(self, url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        self.calls.append((url, payload, timeout))
        return self.reply


# --- only local hosts are allowed -------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://localhost:11434/",
        "http://[::1]:11434",
        "https://localhost",
    ],
)
def test_local_hosts_are_accepted(host: str) -> None:
    assert require_local(host) == host.rstrip("/")


@pytest.mark.parametrize(
    "host",
    [
        "https://api.anthropic.com",
        "https://api.openai.com/v1",
        "http://192.168.1.20:11434",
        "http://0.0.0.0:11434",
        "http://localhost.evil.example",
        "http://127.0.0.1.evil.example",
        "ftp://localhost",
        "localhost:11434",
        "",
    ],
)
def test_non_local_hosts_are_refused(host: str) -> None:
    with pytest.raises(ValueError, match="refusing Ollama host"):
        require_local(host)


def test_client_refuses_a_hosted_endpoint() -> None:
    with pytest.raises(ValueError, match="refusing Ollama host"):
        OllamaClient("gemma", host="https://api.example.com")


def test_client_needs_a_model_name() -> None:
    with pytest.raises(ValueError, match="model name is required"):
        OllamaClient("  ")


# --- generate ---------------------------------------------------------------------------------


def test_generate_sends_one_non_streaming_request() -> None:
    transport = FakeTransport({"response": "  A quiet story.  \n"})
    client = OllamaClient("gemma", host="http://localhost:11434/", transport=transport)
    text = client.generate("Tell it.", system="Be kind.", seed=9)
    assert text == "A quiet story."
    [(url, payload, timeout)] = transport.calls
    assert url == "http://localhost:11434/api/generate"
    assert timeout == client.timeout
    assert payload is not None
    assert payload["model"] == "gemma"
    assert payload["prompt"] == "Tell it."
    assert payload["system"] == "Be kind."
    assert payload["stream"] is False
    assert payload["options"]["seed"] == 9
    assert payload["options"]["temperature"] == client.temperature


def test_generate_omits_seed_when_not_given() -> None:
    transport = FakeTransport({"response": "ok"})
    OllamaClient("gemma", transport=transport).generate("hi")
    assert transport.calls[0][1] is not None
    assert "seed" not in transport.calls[0][1]["options"]


@pytest.mark.parametrize("reply", [{}, {"response": ""}, {"response": "  "}, {"response": 3}])
def test_generate_rejects_an_empty_or_odd_reply(reply: dict[str, Any]) -> None:
    client = OllamaClient("gemma", transport=FakeTransport(reply))
    with pytest.raises(LLMError):
        client.generate("hi")


def test_generate_passes_transport_errors_through() -> None:
    def broken(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        raise LLMError("cannot reach Ollama")

    with pytest.raises(LLMError):
        OllamaClient("gemma", transport=broken).generate("hi")


# --- readiness --------------------------------------------------------------------------------


def test_installed_models_reads_the_tag_list() -> None:
    reply = {"models": [{"name": "gemma4:e4b"}, {"name": "llama3:latest"}, {"size": 1}]}
    transport = FakeTransport(reply)
    client = OllamaClient("gemma4:e4b", transport=transport)
    assert client.installed_models() == ("gemma4:e4b", "llama3:latest")
    assert transport.calls[0][0].endswith("/api/tags")
    assert transport.calls[0][1] is None  # a GET, nothing sent


def test_installed_models_rejects_a_bad_list() -> None:
    with pytest.raises(LLMError):
        OllamaClient("gemma", transport=FakeTransport({"models": "none"})).installed_models()


def test_check_ready_passes_when_the_model_is_installed() -> None:
    transport = FakeTransport({"models": [{"name": "gemma4:e4b"}]})
    OllamaClient("gemma4:e4b", transport=transport).check_ready()


def test_check_ready_names_the_missing_model() -> None:
    transport = FakeTransport({"models": [{"name": "llama3:latest"}]})
    with pytest.raises(LLMError, match="ollama pull gemma4:e4b"):
        OllamaClient("gemma4:e4b", transport=transport).check_ready()


def test_has_model_treats_a_bare_name_as_latest() -> None:
    assert has_model(("gemma3:latest",), "gemma3")
    assert not has_model(("gemma4:e4b",), "gemma3")
    assert has_model(("gemma4:e4b",), "gemma4:e4b")


# --- the real transport, with the socket replaced ---------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    def __init__(self, result: bytes | Exception) -> None:
        self.result = result
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return FakeResponse(self.result)


def test_http_json_posts_json_and_parses_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(b'{"response": "hello"}')
    monkeypatch.setattr(llm, "_OPENER", opener)
    assert http_json("http://localhost:11434/api/generate", {"a": 1}, 5.0) == {"response": "hello"}
    request, timeout = opener.requests[0]
    assert timeout == 5.0
    assert json.loads(request.data) == {"a": 1}
    assert request.get_method() == "POST"


def test_http_json_without_a_payload_is_a_get(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = FakeOpener(b"{}")
    monkeypatch.setattr(llm, "_OPENER", opener)
    http_json("http://localhost:11434/api/tags", None, 5.0)
    assert opener.requests[0][0].get_method() == "GET"


@pytest.mark.parametrize(
    "result",
    [
        OSError("refused"),
        TimeoutError("slow"),
        http.client.IncompleteRead(b"par"),  # a cut-off reply is not an OSError
        http.client.BadStatusLine("junk"),
        b"not json",
        b"[1]",
    ],
)
def test_http_json_turns_failures_into_llm_errors(
    monkeypatch: pytest.MonkeyPatch, result: bytes | Exception
) -> None:
    monkeypatch.setattr(llm, "_OPENER", FakeOpener(result))
    with pytest.raises(LLMError):
        http_json("http://localhost:11434/api/tags", None, 5.0)
