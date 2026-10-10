import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
import urllib.request

import pytest
import yaml

from researchclaw.config import RCConfig
from researchclaw.llm.client import LLMClient, LLMConfig, create_client_from_yaml


@pytest.mark.parametrize("proxy_url", ["", "http://127.0.0.1:7890"])
@pytest.mark.parametrize("provider", ["openai-compatible", "anthropic"])
def test_proxy_config_reaches_model_clients(tmp_path, proxy_url, provider):
    data = yaml.safe_load(Path("config.researchclaw.example.yaml").read_text(encoding="utf-8"))
    data["llm"].update(proxy_url=proxy_url, provider=provider, reviewer_model="reviewer")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = RCConfig.load(path, check_paths=False)

    for client in (LLMClient.from_rc_config(config), LLMClient.reviewer_from_rc_config(config)):
        assert client.config.proxy_url == proxy_url
        assert (client._opener is not None) == bool(proxy_url)
        if provider == "anthropic":
            assert client._anthropic.proxy_url == proxy_url
    assert create_client_from_yaml(str(path)).config.proxy_url == proxy_url


@pytest.mark.parametrize("wire_api", ["responses", "chat_completions"])
@pytest.mark.parametrize("use_fallback", [False, True])
def test_model_requests_use_local_proxy_without_changing_global_opener(monkeypatch, wire_api, use_fallback):
    requests = []

    class Proxy(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            if use_fallback and len(requests) == 1:
                self.send_error(502)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "status": "completed",
            }).encode())

        def log_message(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
    global_opener = urllib.request._opener
    with HTTPServer(("127.0.0.1", 0), Proxy) as proxy:
        thread = Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            client = LLMClient(LLMConfig(
                base_url="http://model.invalid/v1", api_key="test",
                proxy_url=f"http://127.0.0.1:{proxy.server_port}",
                wire_api=wire_api, fallback_models=[], max_retries=1,
                fallback_url="http://backup.invalid/v1" if use_fallback else "",
            ))
            assert client.chat([{"role": "user", "content": "hello"}]).content == "ok"
        finally:
            proxy.shutdown()
            thread.join()

    endpoint = "/responses" if wire_api == "responses" else "/chat/completions"
    assert requests[0][0] == "http://model.invalid/v1" + endpoint
    assert len(requests) == (2 if use_fallback else 1)
    if use_fallback:
        assert requests[1][0] == "http://backup.invalid/v1" + endpoint
    assert urllib.request._opener is global_opener


@pytest.mark.parametrize("proxy_url", ["", "http://127.0.0.1:7890"])
def test_anthropic_transport_receives_optional_proxy(monkeypatch, proxy_url):
    from researchclaw.llm import anthropic_adapter

    captured = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"content": [{"type": "text", "text": "ok"}]},
        )
        return SimpleNamespace(post=lambda *args, **kw: response, close=lambda: None)

    monkeypatch.setattr(anthropic_adapter.httpx, "Client", make_client)
    adapter = anthropic_adapter.AnthropicAdapter("https://example.invalid", "test", proxy_url=proxy_url)
    response = adapter.chat_completion("claude", [{"role": "user", "content": "hello"}], 100, 1)
    assert response["choices"][0]["message"]["content"] == "ok"
    assert captured["proxy"] == (proxy_url or None)
