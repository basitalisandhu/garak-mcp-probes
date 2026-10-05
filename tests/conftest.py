"""Shared helpers: a scripted model, the in-process fake server, and garak attempts built by hand.

Everything here is offline. The scripted model replays a fixed list of replies; the fake server
is the package's own harmless server, connected in process (no subprocess) unless a test asks
for the stdio form.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from garak_mcp_probes.config import (
    DRY_RUN_CANARY,
    AgentConfig,
    ModelConfig,
    PolicyConfig,
    RunConfig,
    ServerConfig,
)
from garak_mcp_probes.model import Reply, ToolRequest

ROOT = Path(__file__).resolve().parents[1]
CANARY = DRY_RUN_CANARY


class ScriptedModel:
    """Replays replies in order. Each script item is a final text (str) or a list of
    ``(function, arguments)`` tool calls, where arguments is a dict or raw JSON text."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.seen: list[list[dict[str, Any]]] = []
        self.tools: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        self.seen.append([dict(m) for m in messages])
        self.tools.append(tools)
        item = self.script.pop(0) if self.script else "done"
        if isinstance(item, str):
            return Reply(text=item)
        calls = [
            ToolRequest(
                id=f"call_{i}",
                name=name,
                arguments=args if isinstance(args, str) else json.dumps(args),
            )
            for i, (name, args) in enumerate(item)
        ]
        return Reply(text=None, tool_calls=calls)


def make_config(policy: PolicyConfig | None = None, max_steps: int = 4) -> RunConfig:
    return RunConfig(
        model=ModelConfig(name="scripted", fake=True),
        servers=[ServerConfig(name="fake", command=["unused"])],
        agent=AgentConfig(max_steps=max_steps),
        policy=policy
        or PolicyConfig(
            deny_tools=["send_report"],
            allow_tools=["echo", "read_note", "list_notes"],
            canaries=[CANARY],
            step_budget=2,
        ),
        source="test",
    )


@pytest.fixture
def fake_server():
    from garak_mcp_probes import fake_server

    fake_server.SENT.clear()
    return fake_server.build_server()


@pytest.fixture
def overrides(fake_server):
    return {"fake": fake_server}


def attempt_with(*notes: dict[str, Any] | None):
    """A garak Attempt with one output per argument; None gives an output without notes."""
    from garak.attempt import Attempt, Message

    a = Attempt(prompt=Message(text="prompt", lang="en"))
    a.outputs = [
        Message(text="out", notes=n) if n is not None else Message(text="out") for n in notes
    ]
    return a


@pytest.fixture
def http_server():
    """The fake server over Streamable HTTP on a loopback port, with a header check. Yields the
    URL and the list of Authorization headers seen."""
    import socket
    import threading
    import time

    import uvicorn

    from garak_mcp_probes import fake_server

    seen: list[str | None] = []
    app = fake_server.build_server().streamable_http_app()

    async def recording(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization")
            seen.append(auth.decode() if auth else None)
        await app(scope, receive, send)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(recording, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp", seen
    finally:
        server.should_exit = True
        thread.join(timeout=5)
