"""The agent loop: one prompt in, a final answer and a tool-call trace out.

The loop sends the conversation and the MCP tools to the model, runs every tool call the model
asks for through the MCP client, feeds the results back, and stops at a final answer or after
``max_steps`` model calls. Each prompt gets fresh server sessions, so state does not carry from
one garak attempt to the next.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any

from .config import AgentConfig, ServerConfig
from .mcp_tools import ServerError, ToolBinding, connect_all, result_text
from .model import ChatModel, ModelError
from .trace import ToolCall, Trace


async def run_agent(
    messages: list[dict[str, Any]],
    model: ChatModel,
    servers: list[ServerConfig],
    agent: AgentConfig,
    overrides: dict[str, Any] | None = None,
) -> tuple[str | None, Trace]:
    """Run the loop. ``messages`` are chat messages (system, user, assistant) from garak."""
    trace = Trace(max_steps=agent.max_steps)
    convo = [dict(m) for m in messages]
    if agent.system_prompt and not any(m.get("role") == "system" for m in convo):
        convo.insert(0, {"role": "system", "content": agent.system_prompt})
    async with AsyncExitStack() as stack:
        try:
            bindings = await connect_all(stack, servers, overrides)
        except ServerError as exc:
            trace.stopped, trace.error = "connect_error", str(exc)
            return None, trace
        by_name = {b.function: b for b in bindings}
        trace.tools_offered = [f"{b.server}:{b.tool}" for b in bindings]
        specs = [b.spec() for b in bindings]
        for step in range(1, agent.max_steps + 1):
            trace.model_steps = step
            try:
                reply = await asyncio.to_thread(model.complete, convo, specs)
            except ModelError as exc:
                trace.stopped, trace.error = "model_error", str(exc)
                return None, trace
            if not reply.tool_calls:
                trace.stopped = "final"
                return reply.text or "", trace
            convo.append(
                {
                    "role": "assistant",
                    "content": reply.text,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments},
                        }
                        for tc in reply.tool_calls
                    ],
                }
            )
            for tc in reply.tool_calls:
                content = await _call(step, tc.name, tc.arguments, by_name, trace)
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        trace.stopped = "max_steps"
        trace.error = f"no final answer after {agent.max_steps} model calls"
        return None, trace


async def _call(
    step: int, name: str, raw: str, by_name: dict[str, ToolBinding], trace: Trace
) -> str:
    binding = by_name.get(name)
    call = ToolCall(
        step=step,
        server=binding.server if binding else None,
        tool=binding.tool if binding else name,
        function=name,
        arguments=None,
        raw_arguments_chars=len(raw or ""),
    )
    trace.calls.append(call)
    try:
        args = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        args = None
    if not isinstance(args, dict):
        call.is_error, call.error = True, "arguments are not a JSON object"
        return f"Error: {call.error}"
    call.arguments = args
    if binding is None:
        call.is_error, call.error = True, "no such tool"
        return f"Error: no tool named {name}"
    try:
        result = await binding.client.call_tool(binding.tool, args)
    except Exception as exc:
        call.is_error, call.error = True, f"{type(exc).__name__}: {exc}"
        return f"Error: {call.error}"
    text = result_text(result)
    call.result_chars = len(text)
    if getattr(result, "is_error", False):
        call.is_error, call.error = True, "server returned an error result"
    return text


def run_agent_sync(
    messages: list[dict[str, Any]],
    model: ChatModel,
    servers: list[ServerConfig],
    agent: AgentConfig,
    overrides: dict[str, Any] | None = None,
) -> tuple[str | None, Trace]:
    """:func:`run_agent` for synchronous callers such as garak generators."""
    return asyncio.run(run_agent(messages, model, servers, agent, overrides))
