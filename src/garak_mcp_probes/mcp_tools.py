"""Connect to the configured MCP servers with the official Python SDK and expose their tools as
function tools for a chat completions model.

Each server keeps the SDK's minimal child environment (stdio) plus the variables its ``env``
entry names; ``${VAR}`` in ``env`` and ``headers`` values is read from our environment at connect
time, so tokens stay out of the file. Plain HTTP is refused for non-local hosts unless the server
entry sets ``allow_http`` (checked when the file is loaded).
"""

from __future__ import annotations

import re
import tempfile
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from .config import ServerConfig, expand_env

FUNCTION_NAME = re.compile(r"[^A-Za-z0-9_-]")


class ServerError(Exception):
    """A server could not be started, reached or listed."""


@dataclass
class ToolBinding:
    function: str  # the name the model sees
    server: str
    tool: str
    description: str
    input_schema: dict[str, Any]
    client: Any

    def spec(self) -> dict[str, Any]:
        schema = self.input_schema if isinstance(self.input_schema, dict) else {}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.function,
                "description": self.description or f"{self.tool} on MCP server {self.server}",
                "parameters": schema,
            },
        }


def function_name(server: str, tool: str) -> str:
    """``server__tool`` with characters outside ``[A-Za-z0-9_-]`` replaced, at most 64 long."""
    return FUNCTION_NAME.sub("_", f"{server}__{tool}")[:64]


async def _target(
    stack: AsyncExitStack, server: ServerConfig, override: Any = None, errlog: Any = None
) -> Any:
    if override is not None:
        return override
    if server.command:
        from mcp import StdioServerParameters, stdio_client

        env = {k: expand_env(v, f"servers.{server.name}.env.{k}") for k, v in server.env.items()}
        params = StdioServerParameters(
            command=server.command[0], args=server.command[1:], env=env or None, cwd=server.cwd
        )
        return stdio_client(params, errlog=errlog) if errlog is not None else params
    assert server.url is not None
    if not server.headers:
        return server.url
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    headers = {
        k: expand_env(v, f"servers.{server.name}.headers.{k}") for k, v in server.headers.items()
    }
    # The SDK does not close an HTTP client it did not create, so the stack owns this one.
    http = await stack.enter_async_context(
        httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30.0, read=300.0))
    )
    return streamable_http_client(server.url, http_client=http)


def _describe(exc: BaseException) -> str:
    inner = getattr(exc, "exceptions", None)
    if inner:  # ExceptionGroup from a task group: report the first leaf
        return _describe(inner[0])
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


async def connect_all(
    stack: AsyncExitStack, servers: list[ServerConfig], overrides: dict[str, Any] | None = None
) -> list[ToolBinding]:
    """Connect to every server, list its tools and return one binding per tool.

    ``overrides`` maps a server name to an in-process server object; tests use it to skip the
    subprocess. Any failure raises :class:`ServerError` naming the server.
    """
    from mcp import Client

    bindings: list[ToolBinding] = []
    seen: dict[str, str] = {}
    for server in servers:
        # A stdio server's stderr goes to a temporary file (garak's console stays readable, and
        # the last line explains a failed start).
        errlog = stack.enter_context(tempfile.TemporaryFile("w+", encoding="utf-8"))  # noqa: SIM115
        try:
            target = await _target(stack, server, (overrides or {}).get(server.name), errlog)
            client = await stack.enter_async_context(
                Client(target, read_timeout_seconds=server.timeout)
            )
            tools = await _list_all(client)
        except Exception as exc:
            errlog.seek(0)
            tail = [line.strip() for line in errlog.read().splitlines() if line.strip()][-1:]
            hint = f"; stderr: {tail[0]}" if tail else ""
            raise ServerError(
                f"server {server.name} ({server.target}): {_describe(exc)}{hint}"
            ) from exc
        for tool in tools:
            fn = function_name(server.name, tool.name)
            if fn in seen:
                raise ServerError(
                    f"server {server.name}: tool {tool.name} maps to function {fn}, "
                    f"already used by {seen[fn]}"
                )
            seen[fn] = f"{server.name}:{tool.name}"
            bindings.append(
                ToolBinding(
                    function=fn,
                    server=server.name,
                    tool=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.input_schema or {}),
                    client=client,
                )
            )
    return bindings


async def _list_all(client: Any) -> list[Any]:
    tools: list[Any] = []
    cursor = None
    for _ in range(1000):
        result = await client.list_tools(cursor=cursor) if cursor else await client.list_tools()
        tools.extend(result.tools)
        cursor = getattr(result, "next_cursor", None)
        if not cursor:
            return tools
    raise ServerError("tools/list returned more than 1000 pages")


def result_text(result: Any) -> str:
    """Join the text blocks of a ``tools/call`` result; other block types are summarised."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(str(getattr(block, "text", "")))
        else:
            parts.append(f"[{getattr(block, 'type', 'unknown')} content]")
    if not parts and getattr(result, "structured_content", None) is not None:
        import json

        parts.append(json.dumps(result.structured_content, ensure_ascii=False))
    return "\n".join(parts)
