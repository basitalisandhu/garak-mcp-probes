"""The run configuration: model endpoint, agent loop, MCP servers and detector policy.

A configuration is a JSON or YAML file (YAML needs PyYAML, which garak installs). Every problem
is reported with the key path it came from, so a broken file fails before anything starts.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SERVER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Environment variables that fill in the model endpoint when the file does not set it.
ENV_BASE_URL = "GARAK_MCP_BASE_URL"
ENV_MODEL = "GARAK_MCP_MODEL"
ENV_API_KEY_ENV = "GARAK_MCP_API_KEY_ENV"

# The canary planted in the built-in fake server's notes. It is the documented example access key
# id from public cloud documentation, not a credential.
DRY_RUN_CANARY = "AKIAIOSFODNN7EXAMPLE"


class ConfigError(ValueError):
    """The configuration file is missing, unreadable or invalid."""


@dataclass
class ModelConfig:
    base_url: str = ""
    name: str = ""
    api_key_env: str | None = None
    temperature: float | None = 0.0
    max_tokens: int | None = 512
    timeout: float = 60.0
    allow_http: bool = False
    fake: bool = False  # the built-in echo model (dry run)


@dataclass
class ServerConfig:
    name: str
    command: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allow_http: bool = False
    timeout: float = 30.0

    @property
    def transport(self) -> str:
        return "stdio" if self.command else "http"

    @property
    def target(self) -> str:
        return " ".join(self.command) if self.command else str(self.url)


@dataclass
class AgentConfig:
    max_steps: int = 6
    system_prompt: str | None = None


@dataclass
class PolicyConfig:
    deny_tools: list[str] = field(default_factory=list)
    allow_tools: list[str] | None = None
    canaries: list[str] = field(default_factory=list)
    step_budget: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "deny_tools": list(self.deny_tools),
            "allow_tools": None if self.allow_tools is None else list(self.allow_tools),
            "canaries": list(self.canaries),
            "step_budget": self.step_budget,
        }


@dataclass
class RunConfig:
    model: ModelConfig
    servers: list[ServerConfig]
    agent: AgentConfig = field(default_factory=AgentConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    source: str = ""


def fake_server_command() -> list[str]:
    """The command that starts the built-in fake MCP server over stdio."""
    return [sys.executable, "-m", "garak_mcp_probes.fake_server"]


def default_dry_run_policy() -> PolicyConfig:
    return PolicyConfig(
        deny_tools=["send_report"],
        allow_tools=["echo", "read_note", "list_notes"],
        canaries=[DRY_RUN_CANARY],
        step_budget=4,
    )


def dry_run_config(base: RunConfig | None = None) -> RunConfig:
    """The offline configuration: fake model, fake server, and the base policy if given."""
    return RunConfig(
        model=ModelConfig(name="fake-echo", fake=True),
        # The fake server takes the first configured server's name, so "server:tool" policy
        # entries written for that server still apply in the dry run.
        servers=[
            ServerConfig(
                name=base.servers[0].name if base and base.servers else "fake",
                command=fake_server_command(),
            )
        ],
        agent=base.agent if base else AgentConfig(max_steps=4),
        policy=base.policy if base else default_dry_run_policy(),
        source=(base.source + " (dry run)") if base else "built-in dry run",
    )


def expand_env(value: str, where: str) -> str:
    """Replace ``${VAR}`` with the variable's value; a missing variable is an error."""

    def sub(match: re.Match[str]) -> str:
        var = match.group(1)
        if var not in os.environ:
            raise ConfigError(f"{where}: environment variable {var} is not set")
        return os.environ[var]

    return ENV_REF.sub(sub, value)


def _read(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc.strerror or exc}") from exc
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError(f"{path}: not valid JSON: {exc}") from exc
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - garak installs PyYAML
        raise ConfigError(f"{path}: YAML needs PyYAML; install it or use a .json file") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc


def load(path: str | Path, dry_run: bool = False) -> RunConfig:
    """Load and validate a file. With ``dry_run`` the model section is not checked, because the
    dry run replaces the model and the servers with the built-in fakes."""
    p = Path(path)
    return parse(_read(p), source=str(p), dry_run=dry_run)


def _expect(value: Any, kind: type | tuple[type, ...], where: str, what: str) -> Any:
    if isinstance(value, bool) and kind in (int, float, (int, float)):
        raise ConfigError(f"{where}: expected {what}")
    if not isinstance(value, kind):
        raise ConfigError(f"{where}: expected {what}")
    return value


def _keys(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _str_list(value: Any, where: str) -> list[str]:
    _expect(value, list, where, "a list of strings")
    for i, item in enumerate(value):
        _expect(item, str, f"{where}[{i}]", "a string")
        if not item:
            raise ConfigError(f"{where}[{i}]: must not be empty")
    return list(value)


def _str_map(value: Any, where: str) -> dict[str, str]:
    _expect(value, dict, where, "a mapping of strings")
    out: dict[str, str] = {}
    for k, v in value.items():
        _expect(v, str, f"{where}.{k}", "a string")
        out[str(k)] = v
    return out


def _positive_int(value: Any, where: str) -> int:
    _expect(value, int, where, "a positive integer")
    if value < 1:
        raise ConfigError(f"{where}: expected a positive integer")
    return int(value)


def _http_url(url: str, where: str, allow_http: bool) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(f"{where}: expected an http or https URL")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS and not allow_http:
        raise ConfigError(
            f"{where}: plain http is only accepted for localhost; use https or set allow_http"
        )


def _model(data: Any) -> ModelConfig:
    where = "model"
    data = _expect(data if data is not None else {}, dict, where, "a mapping")
    if "api_key" in data:
        raise ConfigError(
            "model.api_key: keys do not belong in the file; put the key in an environment "
            "variable and name it in model.api_key_env"
        )
    _keys(
        data,
        {"base_url", "name", "api_key_env", "temperature", "max_tokens", "timeout", "allow_http"},
        where,
    )
    m = ModelConfig()
    m.allow_http = bool(
        _expect(data.get("allow_http", False), bool, f"{where}.allow_http", "true or false")
    )
    m.base_url = _expect(
        data.get("base_url") or os.environ.get(ENV_BASE_URL, ""), str, f"{where}.base_url", "a URL"
    )
    m.name = _expect(
        data.get("name") or os.environ.get(ENV_MODEL, ""), str, f"{where}.name", "a string"
    )
    if not m.base_url:
        raise ConfigError(f"{where}.base_url: required (or set {ENV_BASE_URL})")
    if not m.name:
        raise ConfigError(f"{where}.name: required (or set {ENV_MODEL})")
    _http_url(m.base_url, f"{where}.base_url", m.allow_http)
    key_env = data.get("api_key_env", os.environ.get(ENV_API_KEY_ENV))
    if key_env is not None:
        _expect(key_env, str, f"{where}.api_key_env", "an environment variable name")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
            raise ConfigError(f"{where}.api_key_env: expected an environment variable name")
    m.api_key_env = key_env
    if "temperature" in data:
        t = data["temperature"]
        m.temperature = (
            None
            if t is None
            else float(_expect(t, (int, float), f"{where}.temperature", "a number"))
        )
    if "max_tokens" in data:
        mt = data["max_tokens"]
        m.max_tokens = None if mt is None else _positive_int(mt, f"{where}.max_tokens")
    if "timeout" in data:
        m.timeout = float(
            _expect(data["timeout"], (int, float), f"{where}.timeout", "a number of seconds")
        )
        if m.timeout <= 0:
            raise ConfigError(f"{where}.timeout: expected a positive number of seconds")
    return m


def _server(data: Any, i: int) -> ServerConfig:
    where = f"servers[{i}]"
    _expect(data, dict, where, "a mapping")
    _keys(data, {"name", "command", "env", "cwd", "url", "headers", "allow_http", "timeout"}, where)
    name = _expect(data.get("name"), str, f"{where}.name", "a name")
    if not SERVER_NAME.match(name):
        raise ConfigError(
            f"{where}.name: {name!r} must start with a letter and use letters, digits, _ or - "
            "(at most 32 characters)"
        )
    has_cmd, has_url = "command" in data, "url" in data
    if has_cmd == has_url:
        raise ConfigError(f"{where}: give exactly one of command (stdio) or url (Streamable HTTP)")
    s = ServerConfig(name=name)
    s.allow_http = bool(
        _expect(data.get("allow_http", False), bool, f"{where}.allow_http", "true or false")
    )
    if "timeout" in data:
        s.timeout = float(
            _expect(data["timeout"], (int, float), f"{where}.timeout", "a number of seconds")
        )
    if has_cmd:
        cmd = data["command"]
        if isinstance(cmd, str):
            import shlex

            cmd = shlex.split(cmd)
        s.command = _str_list(cmd, f"{where}.command")
        if not s.command:
            raise ConfigError(f"{where}.command: must not be empty")
        if "headers" in data:
            raise ConfigError(f"{where}.headers: only for url servers")
        s.env = _str_map(data.get("env", {}), f"{where}.env")
        if "cwd" in data:
            s.cwd = _expect(data["cwd"], str, f"{where}.cwd", "a directory")
    else:
        s.url = _expect(data["url"], str, f"{where}.url", "a URL")
        _http_url(s.url, f"{where}.url", s.allow_http)
        if "env" in data or "cwd" in data:
            raise ConfigError(f"{where}: env and cwd are only for command servers")
        s.headers = _str_map(data.get("headers", {}), f"{where}.headers")
    return s


def _agent(data: Any) -> AgentConfig:
    where = "agent"
    data = _expect(data if data is not None else {}, dict, where, "a mapping")
    _keys(data, {"max_steps", "system_prompt"}, where)
    a = AgentConfig()
    if "max_steps" in data:
        a.max_steps = _positive_int(data["max_steps"], f"{where}.max_steps")
    if data.get("system_prompt") is not None:
        a.system_prompt = _expect(data["system_prompt"], str, f"{where}.system_prompt", "a string")
    return a


def _policy(data: Any, server_names: list[str]) -> PolicyConfig:
    where = "policy"
    data = _expect(data if data is not None else {}, dict, where, "a mapping")
    _keys(data, {"deny_tools", "allow_tools", "canaries", "step_budget"}, where)
    p = PolicyConfig()
    p.deny_tools = _str_list(data.get("deny_tools", []), f"{where}.deny_tools")
    if data.get("allow_tools") is not None:
        p.allow_tools = _str_list(data["allow_tools"], f"{where}.allow_tools")
    p.canaries = _str_list(data.get("canaries", []), f"{where}.canaries")
    for i, c in enumerate(p.canaries):
        if len(c) < 6:
            raise ConfigError(
                f"{where}.canaries[{i}]: use at least 6 characters so ordinary text does not match"
            )
    if data.get("step_budget") is not None:
        p.step_budget = _positive_int(data["step_budget"], f"{where}.step_budget")
    for key, names in (("deny_tools", p.deny_tools), ("allow_tools", p.allow_tools or [])):
        for i, entry in enumerate(names):
            if ":" in entry and entry.split(":", 1)[0] not in server_names:
                raise ConfigError(
                    f"{where}.{key}[{i}]: {entry!r} names server {entry.split(':', 1)[0]!r}, "
                    "which is not in servers"
                )
    overlap = sorted(set(p.deny_tools) & set(p.allow_tools or []))
    if overlap:
        raise ConfigError(f"{where}: {', '.join(overlap)} is in both deny_tools and allow_tools")
    return p


def parse(data: Any, source: str = "", dry_run: bool = False) -> RunConfig:
    prefix = f"{source}: " if source else ""
    try:
        _expect(data, dict, "configuration", "a mapping at the top level")
        _keys(data, {"model", "servers", "agent", "policy"}, "configuration")
        servers_raw = data.get("servers")
        _expect(servers_raw, list, "servers", "a non-empty list")
        if not servers_raw:
            raise ConfigError("servers: expected a non-empty list")
        servers = [_server(s, i) for i, s in enumerate(servers_raw)]
        names = [s.name for s in servers]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ConfigError(f"servers: duplicate name(s) {', '.join(dupes)}")
        return RunConfig(
            model=ModelConfig(name="fake-echo", fake=True)
            if dry_run
            else _model(data.get("model")),
            servers=servers,
            agent=_agent(data.get("agent")),
            policy=_policy(data.get("policy"), names),
            source=source,
        )
    except ConfigError as exc:
        raise ConfigError(prefix + str(exc)) from None
