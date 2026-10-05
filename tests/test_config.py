from __future__ import annotations

import json

import pytest

from garak_mcp_probes import config as c
from garak_mcp_probes.config import ConfigError

from .conftest import ROOT


def base(**over):
    data = {
        "model": {"base_url": "http://127.0.0.1:8000/v1", "name": "local-model"},
        "servers": [{"name": "notes", "command": ["python", "-m", "server"]}],
    }
    data.update(over)
    return data


def test_minimal_config_and_defaults():
    cfg = c.parse(base())
    assert cfg.model.name == "local-model" and cfg.model.api_key_env is None
    assert cfg.agent.max_steps == 6
    assert cfg.servers[0].transport == "stdio" and cfg.servers[0].target == "python -m server"
    assert cfg.policy.allow_tools is None and cfg.policy.deny_tools == []


def test_example_configs_load():
    for name in ("config.yaml", "config.json"):
        cfg = c.load(ROOT / "examples" / name, dry_run=True)
        assert cfg.servers and cfg.policy.deny_tools


def test_yaml_and_json_files(tmp_path):
    y = tmp_path / "c.yaml"
    y.write_text(
        "model:\n  base_url: https://models.example.test/v1\n  name: m\n  api_key_env: MODEL_KEY\n"
        "servers:\n  - name: remote\n    url: https://mcp.example.test/mcp\n"
        "    headers: {Authorization: 'Bearer ${TOKEN}'}\n"
        "policy:\n  deny_tools: ['remote:delete']\n  canaries: [CANARY-TEST-0001]\n",
        encoding="utf-8",
    )
    cfg = c.load(y)
    assert cfg.servers[0].transport == "http" and cfg.servers[0].headers["Authorization"].endswith(
        "}"
    )
    assert cfg.model.api_key_env == "MODEL_KEY"
    j = tmp_path / "c.json"
    j.write_text(json.dumps(base()), encoding="utf-8")
    assert c.load(j).servers[0].name == "notes"


def test_command_string_is_split():
    cfg = c.parse(base(servers=[{"name": "s", "command": "python -m server --flag 'a b'"}]))
    assert cfg.servers[0].command == ["python", "-m", "server", "--flag", "a b"]


def test_model_from_environment(monkeypatch):
    monkeypatch.setenv(c.ENV_BASE_URL, "https://models.example.test/v1")
    monkeypatch.setenv(c.ENV_MODEL, "env-model")
    cfg = c.parse({"servers": [{"name": "s", "command": ["x"]}]})
    assert cfg.model.name == "env-model"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "a mapping at the top level"),
        (base(extra=1), "unknown key(s) extra"),
        (base(servers=[]), "servers: expected a non-empty list"),
        ({"model": base()["model"]}, "servers: expected a non-empty list"),
        (base(servers=[{"name": "s"}]), "exactly one of command"),
        (
            base(servers=[{"name": "s", "command": ["x"], "url": "https://h.test"}]),
            "exactly one of command",
        ),
        (base(servers=[{"name": "1bad", "command": ["x"]}]), "must start with a letter"),
        (
            base(servers=[{"name": "s", "command": ["x"]}, {"name": "s", "command": ["y"]}]),
            "duplicate name(s) s",
        ),
        (
            base(servers=[{"name": "s", "url": "http://mcp.example.test/mcp"}]),
            "plain http is only accepted for localhost",
        ),
        (base(servers=[{"name": "s", "url": "ftp://h.test"}]), "expected an http or https URL"),
        (
            base(servers=[{"name": "s", "command": ["x"], "headers": {"A": "b"}}]),
            "only for url servers",
        ),
        (
            base(servers=[{"name": "s", "url": "https://h.test/mcp", "env": {"A": "b"}}]),
            "only for command servers",
        ),
        (base(servers=[{"name": "s", "command": []}]), "must not be empty"),
        (
            base(servers=[{"name": "s", "command": ["x"], "env": {"A": 1}}]),
            "servers[0].env.A: expected a string",
        ),
        (base(model={"name": "m"}), "model.base_url: required"),
        (base(model={"base_url": "https://h.test/v1"}), "model.name: required"),
        (base(model={"base_url": "http://models.example.test/v1", "name": "m"}), "plain http"),
        (
            base(model={"base_url": "https://h.test/v1", "name": "m", "api_key": "x"}),
            "keys do not belong in the file",
        ),
        (
            base(model={"base_url": "https://h.test/v1", "name": "m", "api_key_env": "not a name"}),
            "environment variable name",
        ),
        (
            base(model={"base_url": "https://h.test/v1", "name": "m", "timeout": 0}),
            "positive number",
        ),
        (
            base(model={"base_url": "https://h.test/v1", "name": "m", "max_tokens": True}),
            "positive integer",
        ),
        (base(agent={"max_steps": 0}), "agent.max_steps: expected a positive integer"),
        (base(agent={"steps": 3}), "unknown key(s) steps"),
        (
            base(policy={"deny_tools": "send_report"}),
            "policy.deny_tools: expected a list of strings",
        ),
        (base(policy={"deny_tools": ["other:send"]}), "names server 'other'"),
        (
            base(policy={"deny_tools": ["a"], "allow_tools": ["a"]}),
            "in both deny_tools and allow_tools",
        ),
        (base(policy={"canaries": ["abc"]}), "at least 6 characters"),
        (base(policy={"step_budget": -1}), "policy.step_budget: expected a positive integer"),
    ],
)
def test_validation_errors(data, message, monkeypatch):
    monkeypatch.delenv(c.ENV_BASE_URL, raising=False)
    monkeypatch.delenv(c.ENV_MODEL, raising=False)
    with pytest.raises(ConfigError) as exc:
        c.parse(data, source="cfg.yaml")
    assert message in str(exc.value)
    assert str(exc.value).startswith("cfg.yaml: ")


def test_file_errors(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        c.load(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        c.load(bad)
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("a: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        c.load(bad_yaml)


def test_dry_run_skips_the_model_and_swaps_servers(tmp_path):
    y = tmp_path / "c.yaml"
    y.write_text(
        "servers:\n  - name: notes\n    command: [python, server.py]\n"
        "policy:\n  deny_tools: [send_report]\n  step_budget: 9\n",
        encoding="utf-8",
    )
    cfg = c.dry_run_config(c.load(y, dry_run=True))
    assert cfg.model.fake and [s.name for s in cfg.servers] == ["notes"]
    assert cfg.policy.step_budget == 9
    assert cfg.servers[0].command == c.fake_server_command()


def test_expand_env(monkeypatch):
    monkeypatch.setenv("GMCP_TEST_TOKEN", "value")
    assert c.expand_env("Bearer ${GMCP_TEST_TOKEN}", "h") == "Bearer value"
    monkeypatch.delenv("GMCP_TEST_TOKEN")
    with pytest.raises(ConfigError, match="GMCP_TEST_TOKEN is not set"):
        c.expand_env("${GMCP_TEST_TOKEN}", "servers.s.headers.A")
