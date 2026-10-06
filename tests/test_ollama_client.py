import json
from io import BytesIO
from unittest.mock import patch

from app.agents.llm_client import OllamaLLMClient


def test_ollama_client_posts_json_mode_request():
    client = OllamaLLMClient(
        base_url="http://ollama.local:11434/",
        model="llama3.2",
        timeout=45,
    )
    response_body = json.dumps({"response": '{"summary":"ok"}'}).encode("utf-8")

    with patch("app.agents.llm_client.urlopen", return_value=BytesIO(response_body)) as request:
        result = client.complete("Summarize this", json_mode=True)

    sent_request = request.call_args.args[0]
    assert sent_request.full_url == "http://ollama.local:11434/api/generate"
    assert json.loads(sent_request.data) == {
        "model": "llama3.2",
        "prompt": "Summarize this",
        "stream": False,
        "format": "json",
    }
    assert request.call_args.kwargs["timeout"] == 45
    assert result == '{"summary":"ok"}'