"""The agent loop and the garak generator against the fake server, with a scripted model."""

from __future__ import annotations

from garak.attempt import Conversation, Message, Turn

from garak_mcp_probes import fake_server
from garak_mcp_probes.agent import run_agent_sync
from garak_mcp_probes.config import AgentConfig, ServerConfig, dry_run_config
from garak_mcp_probes.generators import MCPAgentGenerator
from garak_mcp_probes.model import FakeEchoModel
from garak_mcp_probes.trace import TRACE_KEY

from .conftest import CANARY, ScriptedModel, make_config

USER = [{"role": "user", "content": "summarise my notes"}]
SERVERS = [ServerConfig(name="fake", command=["unused"])]


def run(script, overrides, max_steps=4, system_prompt=None):
    model = ScriptedModel(script)
    text, trace = run_agent_sync(
        USER,
        model,
        SERVERS,
        AgentConfig(max_steps=max_steps, system_prompt=system_prompt),
        overrides,
    )
    return text, trace.as_dict(), model


def test_trace_records_tool_arguments_result_size_and_final_text(overrides):
    text, trace, model = run(
        [[("fake__list_notes", {})], [("fake__read_note", {"name": "meeting"})], "Done."],
        overrides,
    )
    assert text == "Done."
    assert trace["stopped"] == "final" and trace["model_steps"] == 3
    assert trace["tools_offered"] == [
        "fake:echo",
        "fake:list_notes",
        "fake:read_note",
        "fake:send_report",
    ]
    assert [(c["tool"], c["arguments"]) for c in trace["calls"]] == [
        ("list_notes", {}),
        ("read_note", {"name": "meeting"}),
    ]
    expected = len(fake_server.DEFAULT_NOTES["meeting"])
    assert trace["calls"][1]["result_chars"] == expected
    assert not any(c["is_error"] for c in trace["calls"])
    # The model saw the tool result in the conversation; the trace keeps only its size.
    assert model.seen[-1][-1] == {
        "role": "tool",
        "tool_call_id": "call_0",
        "content": fake_server.DEFAULT_NOTES["meeting"],
    }
    assert "content" not in trace["calls"][1]


def test_function_specs_follow_chat_completions_shape(overrides):
    _, _, model = run(["ok"], overrides)
    spec = next(s for s in model.tools[0] if s["function"]["name"] == "fake__read_note")
    assert spec["type"] == "function"
    assert spec["function"]["parameters"]["type"] == "object"
    assert "name" in spec["function"]["parameters"]["properties"]


def test_server_error_result_is_recorded(overrides):
    _, trace, _ = run([[("fake__read_note", {"name": "missing"})], "sorry"], overrides)
    assert trace["calls"][0]["is_error"] is True
    assert trace["calls"][0]["error"]


def test_unknown_tool_and_bad_arguments_are_errors(overrides):
    _, trace, _ = run([[("fake__nope", {}), ("fake__echo", "{not json")], "ok"], overrides)
    unknown, bad = trace["calls"]
    assert (
        unknown["server"] is None
        and unknown["tool"] == "fake__nope"
        and unknown["error"] == "no such tool"
    )
    assert bad["arguments"] is None and bad["error"] == "arguments are not a JSON object"


def test_max_steps_stops_the_loop(overrides):
    text, trace, _ = run([[("fake__echo", {"text": "a"})]] * 5, overrides, max_steps=2)
    assert text is None
    assert trace["stopped"] == "max_steps" and len(trace["calls"]) == 2


def test_system_prompt_is_prepended(overrides):
    _, _, model = run(["ok"], overrides, system_prompt="You help with notes.")
    assert model.seen[0][0] == {"role": "system", "content": "You help with notes."}


def test_send_report_only_records(overrides):
    run([[("fake__send_report", {"recipient": "ops", "body": f"key {CANARY}"})], "sent"], overrides)
    expected = {"recipient": "ops", "body_chars": 4 + len(CANARY), "body": f"key {CANARY}"}
    sent = list(fake_server.SENT)
    assert sent == [expected]


def test_connect_error_is_reported_not_raised():
    bad = [ServerConfig(name="gone", command=["/nonexistent/garak-mcp-test-binary"])]
    text, trace = run_agent_sync(USER, FakeEchoModel(), bad, AgentConfig())
    assert text is None
    assert trace.stopped == "connect_error" and "gone" in (trace.error or "")


def test_fake_echo_model_calls_echo_once(overrides):
    text, trace = run_agent_sync(USER, FakeEchoModel(), SERVERS, AgentConfig(), overrides)
    assert text == "echo: summarise my notes"
    assert [c["tool"] for c in trace.as_dict()["calls"]] == ["echo"]


def test_generator_returns_message_with_trace_notes(overrides):
    model = ScriptedModel([[("fake__send_report", {"recipient": "x", "body": CANARY})], "ok"])
    gen = MCPAgentGenerator(settings=make_config(), model=model, server_overrides=overrides)
    conv = Conversation([Turn("system", Message("be brief")), Turn("user", Message("hello"))])
    [out] = gen.generate(conv, 1)
    assert isinstance(out, Message) and out.text == "ok"
    calls = out.notes[TRACE_KEY]["calls"]
    assert calls[0]["tool"] == "send_report" and calls[0]["arguments"]["body"] == CANARY
    assert model.seen[0][:2] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]
    assert gen.fullname == "mcp_agent:scripted+fake"


def test_generator_default_is_the_dry_run():
    gen = MCPAgentGenerator()
    assert gen.settings.model.fake and gen.settings.servers[0].name == "fake"
    assert isinstance(gen.chat_model, FakeEchoModel)
    assert dry_run_config().policy.canaries == [CANARY]


def test_stdio_fake_server_end_to_end():
    cfg = dry_run_config()
    text, trace = run_agent_sync(
        [{"role": "user", "content": "ping"}], FakeEchoModel(), cfg.servers, cfg.agent
    )
    assert text == "echo: ping", trace.error
    assert trace.calls[0].server == "fake" and trace.calls[0].result_chars == 4


def test_streamable_http_server_with_header_from_environment(http_server, monkeypatch):
    url, seen = http_server
    monkeypatch.setenv("GMCP_TEST_HTTP_TOKEN", "test-value")
    servers = [
        ServerConfig(
            name="web", url=url, headers={"Authorization": "Bearer ${GMCP_TEST_HTTP_TOKEN}"}
        )
    ]
    text, trace = run_agent_sync(
        [{"role": "user", "content": "over http"}], FakeEchoModel(), servers, AgentConfig()
    )
    assert text == "echo: over http", trace.error
    assert trace.tools_offered[0].startswith("web:")
    assert seen and all(h == "Bearer test-value" for h in seen)


def test_missing_header_variable_is_a_connect_error(http_server, monkeypatch):
    url, _ = http_server
    monkeypatch.delenv("GMCP_TEST_UNSET_TOKEN", raising=False)
    servers = [
        ServerConfig(name="web", url=url, headers={"Authorization": "${GMCP_TEST_UNSET_TOKEN}"})
    ]
    text, trace = run_agent_sync(
        [{"role": "user", "content": "x"}], FakeEchoModel(), servers, AgentConfig()
    )
    assert text is None and trace.stopped == "connect_error"
    assert "GMCP_TEST_UNSET_TOKEN is not set" in (trace.error or "")
