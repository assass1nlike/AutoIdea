import io
import json
from pathlib import Path
import urllib.request

import pytest
import yaml

from researchclaw.config import RCConfig
from researchclaw.llm.client import LLMClient, LLMConfig, create_client_from_yaml


def sse(*events):
    lines = [": keepalive\r\n\r\n"]
    for event in events:
        value = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
        lines.append(f"data: {value}\r\n\r\n")
    return io.BytesIO("".join(lines).encode("utf-8"))


def chunk(text=None, finish=None):
    return {"model": "served-model", "choices": [{
        "index": 0, "delta": {"content": text}, "finish_reason": finish,
    }]}


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_stream_preserves_text_usage_and_finish(monkeypatch, finish):
    captured = {}

    def open_response(request, timeout):
        captured.update(json.loads(request.data))
        return sse(chunk(), chunk('{"title":"'), chunk('记忆"}'),
                   chunk(finish=finish),
                   {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}},
                   "[DONE]")

    monkeypatch.setattr(urllib.request, "urlopen", open_response)
    client = LLMClient(LLMConfig(base_url="https://example.invalid/v1", api_key="test",
                                stream=True, fallback_models=[]))
    result = client.chat([{"role": "user", "content": "screen"}], json_mode=True)
    assert captured["stream"] is True
    assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"} & captured.keys()
    assert captured["response_format"] == {"type": "json_object"}
    assert json.loads(result.content) == {"title": "记忆"}
    assert result.model == "served-model"
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (20, 8, 28)
    assert result.finish_reason == finish
    assert result.truncated == (finish == "length")


@pytest.mark.parametrize("ending", [[], ["[DONE]"], [chunk(finish="stop")]])
def test_incomplete_stream_is_not_accepted(ending):
    with pytest.raises(ConnectionError):
        LLMClient._read_response(sse(chunk("partial"), *ending), stream=True)


def test_retry_discards_partial_content(monkeypatch):
    replies = iter([sse(chunk("discard this")), sse(chunk("complete", "stop"), "[DONE]")])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: next(replies))
    client = LLMClient(LLMConfig(base_url="https://example.invalid/v1", api_key="test",
                                stream=True, fallback_models=[], retry_base_delay=0))
    assert client.chat([{"role": "user", "content": "hi"}]).content == "complete"


def test_stream_error_uses_existing_api_error_handling(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: sse(
        {"error": {"message": "upstream unavailable", "type": "server_error"}}))
    client = LLMClient(LLMConfig(base_url="https://example.invalid/v1", api_key="test",
                                stream=True, fallback_models=[], max_retries=1))
    with pytest.raises(RuntimeError, match="upstream unavailable"):
        client.chat([{"role": "user", "content": "hi"}])


def test_multiline_sse_event():
    response = io.BytesIO(b'event: message\ndata: {"choices":\ndata: [{"delta":{"content":"ok"},'
                          b'"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    assert LLMClient._read_response(response, stream=True)["choices"][0]["message"]["content"] == "ok"


def test_stream_config_reaches_clients(tmp_path):
    config = yaml.safe_load(Path("config.researchclaw.example.yaml").read_text(encoding="utf-8"))
    config["llm"].update(stream=True, reviewer_model="reviewer")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    rc = RCConfig.load(path, check_paths=False)
    assert rc.llm.stream is True
    assert LLMClient.from_rc_config(rc).config.stream is True
    assert LLMClient.reviewer_from_rc_config(rc).config.stream is True
    assert create_client_from_yaml(str(path)).config.stream is True
