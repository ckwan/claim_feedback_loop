import json

import httpx

from app.agents.llm_client import OllamaLLMClient


def client_with(handler, **kw):
    c = OllamaLLMClient(base_url="http://ollama.local:11434/", model="llama3.2", timeout=45, **kw)
    c._client = httpx.Client(base_url="http://ollama.local:11434/", transport=httpx.MockTransport(handler), timeout=45)
    return c


def test_posts_a_non_streaming_generate_request():
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"response": "hello"})

    assert client_with(handler).complete("Summarize this") == "hello"
    assert seen["url"] == "http://ollama.local:11434/api/generate"
    assert seen["body"] == {"model": "llama3.2", "prompt": "Summarize this", "stream": False}


def test_json_mode_asks_ollama_for_valid_json():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": '{"summary":"ok"}'})

    result = client_with(handler).complete("Summarize this", json_mode=True)
    assert seen["body"]["format"] == "json"
    assert result == '{"summary":"ok"}'


def test_timeout_is_configured():
    assert OllamaLLMClient(base_url="http://x", model="m", timeout=45)._client.timeout.read == 45


def test_http_errors_are_raised_not_swallowed():
    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        client_with(lambda r: httpx.Response(500)).complete("x")
