import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.receptionist import LlmUnavailableError, OllamaClient, validate_local_ollama_url


def test_ollama_settings_default_to_loopback_and_local_model():
    config = Settings(_env_file=None)

    assert config.ollama_base_url == "http://127.0.0.1:11434"
    assert config.ollama_model == "llama3.1:8b"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://user:password@localhost:11434",
        "http://localhost:11434/v1",
        "http://localhost:invalid",
    ],
)
def test_ollama_url_rejects_non_loopback_or_non_root_urls(url):
    with pytest.raises(ValueError):
        validate_local_ollama_url(url)


def test_settings_reject_non_loopback_ollama_url():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_base_url="http://example.com:11434")


@pytest.mark.asyncio
async def test_ollama_client_uses_local_chat_completions_without_auth_header():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Hello"}}]})

    client = OllamaClient("llama3.1:8b", transport=httpx.MockTransport(handler))

    message = await client.complete(
        [{"role": "user", "content": "Hello"}],
        tools=[{"type": "function", "function": {"name": "search_kb"}}],
    )

    assert message["content"] == "Hello"
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["authorization"] is None
    assert captured["body"]["model"] == "llama3.1:8b"
    assert captured["body"]["tool_choice"] == "auto"
    assert captured["body"]["temperature"] == 0


@pytest.mark.asyncio
async def test_ollama_client_rejects_malformed_completion_response():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []}))
    client = OllamaClient("llama3.1:8b", transport=transport)

    with pytest.raises(LlmUnavailableError, match="malformed"):
        await client.complete([{"role": "user", "content": "Hello"}])
