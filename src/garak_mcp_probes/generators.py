"""The garak generator: each prompt runs through the agent loop over your MCP servers.

garak passes a ``Conversation``; the generator sends its turns to the model with the MCP tools,
runs the tool calls, and returns the final text as a garak ``Message`` whose ``notes`` hold the
tool-call trace under ``"mcp_trace"``. garak writes those notes into its JSONL report with every
attempt, and the detectors in :mod:`garak_mcp_probes.detectors` score them.

garak loads plugins only from its own namespace, so this generator is constructed in code (the
``garak-mcp run`` command does it) rather than named with ``--target_type``.
"""

from __future__ import annotations

import logging
from typing import Any

from garak import _config
from garak.attempt import Conversation, Message
from garak.generators.base import Generator

from .agent import run_agent_sync
from .config import RunConfig, dry_run_config
from .model import ChatModel, make_model
from .trace import TRACE_KEY


class MCPAgentGenerator(Generator):
    """An agent that answers each prompt with the tools of one or more MCP servers"""

    generator_family_name = "mcp_agent"
    supports_multiple_generations = False
    parallel_capable = False  # sessions and subprocesses are opened per prompt, in this process
    modality: dict = {"in": {"text"}, "out": {"text"}}

    def __init__(
        self,
        name: str = "",
        config_root: Any = _config,
        settings: RunConfig | None = None,
        model: ChatModel | None = None,
        server_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.settings = settings or dry_run_config()
        self.chat_model = model or make_model(self.settings.model)
        self.server_overrides = server_overrides
        servers = ",".join(s.name for s in self.settings.servers)
        super().__init__(name or f"{self.settings.model.name}+{servers}", config_root=config_root)

    def _messages(self, prompt: Conversation) -> list[dict[str, Any]]:
        out = []
        for turn in prompt.turns:
            text = turn.content.text if turn.content is not None else None
            out.append({"role": turn.role, "content": text or ""})
        return out

    def _call_model(
        self, prompt: Conversation, generations_this_call: int = 1
    ) -> list[Message | None]:
        text, trace = run_agent_sync(
            self._messages(prompt),
            self.chat_model,
            self.settings.servers,
            self.settings.agent,
            self.server_overrides,
        )
        if trace.error:
            logging.warning("garak-mcp: %s: %s", trace.stopped, trace.error)
        return [Message(text=text, notes={TRACE_KEY: trace.as_dict()})]


DEFAULT_CLASS = "MCPAgentGenerator"
