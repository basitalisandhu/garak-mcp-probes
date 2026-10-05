from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from garak_mcp_probes.config import ModelConfig
from garak_mcp_probes.model import (
    FakeEchoModel,
    ModelError,
    OpenAICompatibleModel,
    make_model,
    parse_reply,
)

TOOLS = [
    {
        "type": "function",
        "function": {"name": "fake__echo", "description": "", "parameters": {"type": "object"}},
    }
]


def test_parse_reply_text_and_tool_calls():
    r = parse_reply({"choices": [{"message": {"content": "hi"}}]})
    assert r.text == "hi" and r.tool_calls == []
    r = parse_reply(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "a",
                                "type": "function",
                                "function": {"name": "fake__echo", "arguments": '{"text": "x"}'},
                            },
                            {"function": {"name": "fake__list_notes", "arguments": {}}},
                        ],
                    }
                }
            ]
        }
    )
    assert r.text is None
    assert [(c.id, c.name, c.arguments) for c in r.tool_calls] == [
        ("a", "fake__echo", '{"text": "x"}'),
        ("call_1", "fake__list_notes", "{}"),
    ]
    assert (
        parse_reply(
            {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"text": "b"}]}}]}
        ).text
        == "ab"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": "x"}]},
        {"choices": [{"message": {"tool_calls": [{"function": {}}]}}]},
    ],
)
def test_parse_reply_rejects_malformed(payload):
    with pytest.raises(ModelError):
        parse_reply(payload)


def test_fake_echo_model():
    m = FakeEchoModel()
    first = m.complete([{"role": "user", "content": "hello"}], TOOLS)
    assert first.tool_calls[0].name == "fake__echo" and json.loads(
        first.tool_calls[0].arguments
    ) == {"text": "hello"}
    second = m.complete(
        [{"role": "user", "content": "hello"}, {"role": "tool", "content": "hello"}], TOOLS
    )
    assert second.text == "echo: hello" and not second.tool_calls
    assert m.complete([{"role": "user", "content": "plain"}], []).text == "plain"
    assert isinstance(make_model(ModelConfig(fake=True)), FakeEchoModel)


@pytest.fixture
def chat_endpoint():
    """A loopback chat completions endpoint that records requests."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(
                {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
            )
            if body["model"] == "broken":
                self.send_response(500)
                self.end_headers()
                return
            payload = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1/", seen
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_openai_compatible_request(chat_endpoint, monkeypatch):
    url, seen = chat_endpoint
    monkeypatch.setenv("GMCP_TEST_MODEL_KEY", "test-value")
    m = OpenAICompatibleModel(
        ModelConfig(base_url=url, name="local-model", api_key_env="GMCP_TEST_MODEL_KEY")
    )
    assert m.complete([{"role": "user", "content": "hi"}], TOOLS).text == "OK"
    req = seen[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer test-value"
    assert req["body"]["model"] == "local-model" and req["body"]["tools"] == TOOLS
    assert req["body"]["temperature"] == 0.0 and req["body"]["max_tokens"] == 512


def test_openai_compatible_errors(chat_endpoint, monkeypatch):
    url, _ = chat_endpoint
    with pytest.raises(ModelError, match="HTTP 500"):
        OpenAICompatibleModel(ModelConfig(base_url=url, name="broken")).complete([], [])
    monkeypatch.delenv("GMCP_TEST_UNSET", raising=False)
    with pytest.raises(ModelError, match="GMCP_TEST_UNSET is not set"):
        OpenAICompatibleModel(
            ModelConfig(base_url=url, name="m", api_key_env="GMCP_TEST_UNSET")
        ).complete([], [])
    body = OpenAICompatibleModel(
        ModelConfig(base_url=url, name="m", temperature=None, max_tokens=None)
    ).body([], [])
    assert body == {"model": "m", "messages": []}
