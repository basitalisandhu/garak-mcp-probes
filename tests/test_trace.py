from __future__ import annotations

from garak_mcp_probes import trace as t

from .conftest import CANARY


def call(tool, server="notes", arguments=None, is_error=False):
    return {
        "step": 1,
        "server": server,
        "tool": tool,
        "function": f"{server}__{tool}",
        "arguments": arguments if arguments is not None else {},
        "is_error": is_error,
    }


def tr(*calls, stopped="final"):
    return {"version": 1, "stopped": stopped, "calls": list(calls)}


def test_matches_bare_and_server_qualified_entries():
    c = call("send_report", server="notes")
    assert t.matches(c, "send_report")
    assert t.matches(c, "notes:send_report")
    assert not t.matches(c, "mail:send_report")
    assert not t.matches(c, "send")


def test_tool_called_returns_only_denied_calls():
    trace = tr(call("echo"), call("send_report"))
    assert [c["tool"] for c in t.tool_called(trace, ["send_report"])] == ["send_report"]
    assert t.tool_called(trace, []) == []
    assert t.tool_called(tr(), ["send_report"]) == []


def test_unexpected_tool_needs_an_allow_list():
    trace = tr(call("echo"), call("delete_all"), call("ghost", server=None))
    assert t.unexpected_tool(trace, None) == []
    assert [c["tool"] for c in t.unexpected_tool(trace, ["echo"])] == ["delete_all", "ghost"]
    assert t.unexpected_tool(trace, ["echo", "delete_all", "ghost"]) == []


def test_argument_contains_searches_nested_values_and_keys():
    nested = call("send_report", arguments={"body": {"lines": ["x", f"key={CANARY};"]}})
    keyed = call("echo", arguments={CANARY: 1})
    clean = call("echo", arguments={"text": "hello", "n": 3, "flag": True})
    hits = t.argument_contains(tr(nested, keyed, clean), [CANARY])
    assert hits == [nested, keyed]
    assert t.argument_contains(tr(call("echo", arguments={"text": CANARY.lower()})), [CANARY]) == []


def test_argument_contains_handles_unparsed_arguments():
    bad = call("echo")
    bad["arguments"] = None
    assert t.argument_contains(tr(bad), [CANARY]) == []


def test_step_budget_exceeded():
    assert t.step_budget_exceeded(tr(stopped="max_steps"), None)
    assert not t.step_budget_exceeded(tr(call("echo"), call("echo")), None)
    assert not t.step_budget_exceeded(tr(call("echo"), call("echo")), 2)
    assert t.step_budget_exceeded(tr(call("echo"), call("echo"), call("echo")), 2)


def test_tool_error():
    bad = call("read_note", is_error=True)
    assert t.tool_error(tr(call("echo"), bad)) == [bad]
    assert t.tool_error(tr(call("echo"))) == []


def test_malformed_traces_are_treated_as_empty():
    assert t.tool_called({"calls": "nope"}, ["x"]) == []
    assert t.tool_error({"calls": [1, None, "x"]}) == []


def test_from_message_reads_notes_from_objects_and_dicts():
    class M:
        notes = {t.TRACE_KEY: {"calls": []}}

    assert t.from_message(M()) == {"calls": []}
    assert t.from_message({"notes": {t.TRACE_KEY: {"calls": []}}}) == {"calls": []}
    assert t.from_message({"notes": {}}) is None
    assert t.from_message(None) is None


def test_trace_as_dict_round_trips_through_json():
    import json

    trace = t.Trace(max_steps=3)
    trace.calls.append(t.ToolCall(1, "notes", "echo", "notes__echo", {"text": "hi"}, 15, 2))
    d = json.loads(json.dumps(trace.as_dict()))
    assert d["version"] == t.TRACE_VERSION
    assert d["calls"][0]["tool"] == "echo" and d["calls"][0]["result_chars"] == 2
    assert trace.calls[0].qualified == "notes:echo"
