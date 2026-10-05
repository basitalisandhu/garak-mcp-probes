"""``garak-mcp doctor``: check that every server connects and lists tools, and that the model
endpoint answers, without running any probe."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from .config import RunConfig
from .mcp_tools import ServerError, connect_all
from .model import ModelError, make_model


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    tools: list[str] = field(default_factory=list)


async def _server(cfg: RunConfig, index: int, overrides: dict[str, Any] | None) -> Check:
    server = cfg.servers[index]
    label = f"server {server.name} ({server.transport})"
    async with AsyncExitStack() as stack:
        try:
            bindings = await connect_all(stack, [server], overrides)
        except ServerError as exc:
            return Check(label, False, str(exc))
        except Exception as exc:  # configuration errors such as an unset ${VAR}
            return Check(label, False, str(exc))
    tools = [b.tool for b in bindings]
    return Check(label, True, f"{len(tools)} tool(s)", tools)


def _model(cfg: RunConfig) -> Check:
    label = f"model {cfg.model.name}" + ("" if cfg.model.fake else f" at {cfg.model.base_url}")
    try:
        reply = make_model(cfg.model).complete([{"role": "user", "content": "Reply with OK."}], [])
    except ModelError as exc:
        return Check(label, False, str(exc))
    text = (reply.text or "").strip().replace("\n", " ")
    return Check(label, True, f"answered ({len(text)} characters)")


def run(cfg: RunConfig, overrides: dict[str, Any] | None = None) -> list[Check]:
    checks = [asyncio.run(_server(cfg, i, overrides)) for i in range(len(cfg.servers))]
    checks.append(_model(cfg))
    return checks


def render(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        if c.tools:
            lines.append("     " + ", ".join(c.tools))
    return "\n".join(lines)
