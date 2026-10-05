"""Model clients for the agent loop: an OpenAI-compatible chat completions client written with the
standard library, and the built-in fake model used by the dry run.

No vendor SDK is used. The endpoint is any server that implements ``POST {base_url}/chat/completions``
with function tools, which most hosted and local inference servers offer.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import __version__
from .config import ModelConfig


class ModelError(Exception):
    """The model endpoint could not be reached or answered with something unusable."""


@dataclass
class ToolRequest:
    id: str
    name: str
    arguments: str  # JSON text as the model produced it


@dataclass
class Reply:
    text: str | None
    tool_calls: list[ToolRequest] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply: ...


class OpenAICompatibleModel:
    """Chat completions over HTTP. The API key is read from the variable ``api_key_env`` names."""

    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg
        self.url = cfg.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"garak-mcp-probes/{__version__}",
        }
        if self.cfg.api_key_env:
            key = os.environ.get(self.cfg.api_key_env)
            if not key:
                raise ModelError(f"environment variable {self.cfg.api_key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def body(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.cfg.name, "messages": messages}
        if tools:
            body["tools"] = tools
        if self.cfg.temperature is not None:
            body["temperature"] = self.cfg.temperature
        if self.cfg.max_tokens is not None:
            body["max_tokens"] = self.cfg.max_tokens
        return body

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        data = json.dumps(self.body(messages, tools)).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ModelError(f"{self.url}: HTTP {exc.code} {exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ModelError(f"{self.url}: {exc}") from exc
        except ValueError as exc:
            raise ModelError(f"{self.url}: response is not JSON") from exc
        return parse_reply(payload)


def parse_reply(payload: Any) -> Reply:
    """Read ``choices[0].message`` from a chat completions response."""
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError("response has no choices[0].message") from exc
    if not isinstance(message, dict):
        raise ModelError("choices[0].message is not an object")
    calls = []
    for i, tc in enumerate(message.get("tool_calls") or []):
        fn = tc.get("function") if isinstance(tc, dict) else None
        if not isinstance(fn, dict) or not fn.get("name"):
            raise ModelError(f"tool_calls[{i}] has no function name")
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args if args is not None else {})
        calls.append(
            ToolRequest(id=str(tc.get("id") or f"call_{i}"), name=fn["name"], arguments=args)
        )
    content = message.get("content")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return Reply(text=content if isinstance(content, str) else None, tool_calls=calls)


class FakeEchoModel:
    """The dry-run model. It needs no network and does one fixed thing: if a tool named ``echo``
    is offered, it calls it once with the last user message, then answers with what came back;
    otherwise it answers with the last user message. It never calls any other tool."""

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        last_user = next(
            (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), ""
        )
        if messages and messages[-1].get("role") == "tool":
            return Reply(text=f"echo: {messages[-1].get('content', '')}")
        echo = next(
            (
                t["function"]["name"]
                for t in tools
                if t["function"]["name"] == "echo" or t["function"]["name"].endswith("__echo")
            ),
            None,
        )
        if echo is None:
            return Reply(text=str(last_user))
        return Reply(
            text=None,
            tool_calls=[
                ToolRequest(id="call_0", name=echo, arguments=json.dumps({"text": last_user}))
            ],
        )


def make_model(cfg: ModelConfig) -> ChatModel:
    return FakeEchoModel() if cfg.fake else OpenAICompatibleModel(cfg)
