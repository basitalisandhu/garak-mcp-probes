"""Fuzz and property tests for every input reader: configuration files, garak reports, model
replies, tool-call arguments and command-line values.

The contract: bad input gives a clear error (``ConfigError``, ``ReportError``, ``ModelError``,
an error trace entry or exit code 2), never a traceback, a hang or a crash.
"""

from __future__ import annotations

import contextlib
import json
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from garak_mcp_probes import config, summary
from garak_mcp_probes.cli import main
from garak_mcp_probes.model import ModelError, parse_reply
from garak_mcp_probes.trace import argument_contains

FUZZ = settings(
    max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)

# JSON-shaped values: what a YAML or JSON configuration, a report line or a reply can hold.
scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=20),
)
json_values = st.recursive(
    scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=12), children, max_size=4),
    ),
    max_leaves=25,
)
config_keys = st.sampled_from(["model", "servers", "agent", "policy", "name", "command", "url"])


def _config_like():
    """Mostly well-formed configurations with one part replaced by something random."""
    server = st.fixed_dictionaries(
        {"name": st.one_of(st.just("fake"), json_values)},
        optional={
            "command": st.one_of(st.text(max_size=30), st.lists(st.text(max_size=8), max_size=3)),
            "url": st.one_of(st.just("https://example.test/mcp"), st.text(max_size=30)),
            "timeout": json_values,
            "env": json_values,
            "headers": json_values,
            "allow_http": json_values,
        },
    )
    return st.fixed_dictionaries(
        {},
        optional={
            "model": st.one_of(
                json_values,
                st.fixed_dictionaries(
                    {},
                    optional={
                        "base_url": json_values,
                        "name": json_values,
                        "temperature": json_values,
                        "max_tokens": json_values,
                        "timeout": json_values,
                    },
                ),
            ),
            "servers": st.one_of(json_values, st.lists(server, max_size=3)),
            "agent": json_values,
            "policy": st.one_of(
                json_values,
                st.fixed_dictionaries(
                    {},
                    optional={
                        "deny_tools": json_values,
                        "allow_tools": json_values,
                        "canaries": json_values,
                        "step_budget": json_values,
                    },
                ),
            ),
        },
    )


@FUZZ
@given(data=st.one_of(json_values, _config_like()), dry_run=st.booleans())
def test_parse_only_raises_config_error(data, dry_run):
    try:
        config.parse(data, source="fuzz", dry_run=dry_run)
    except config.ConfigError as exc:
        assert str(exc).startswith("fuzz: ")


@FUZZ
@given(raw=st.binary(max_size=200), suffix=st.sampled_from([".json", ".yaml", ".yml"]))
def test_load_random_bytes_only_raises_config_error(tmp_path, raw, suffix):
    path = tmp_path / f"c{suffix}"
    path.write_bytes(raw)
    with contextlib.suppress(config.ConfigError):
        config.load(path)


@FUZZ
@given(text=st.text(alphabet=string.printable, max_size=200))
def test_load_random_yaml_text_only_raises_config_error(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    with contextlib.suppress(config.ConfigError):
        config.load(path)


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("bad.json", b"\xff\xfe{}", "not UTF-8 text"),
        ("deep.json", b"[" * 100_000 + b"]" * 100_000, "not valid JSON"),
        ("deep.yaml", b"[" * 5_000 + b"]" * 5_000, "not valid YAML"),
    ],
)
def test_undecodable_and_deeply_nested_files(tmp_path, name, content, message):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(config.ConfigError, match=message):
        config.load(path)


def test_mixed_type_yaml_keys_are_reported_not_a_type_error():
    with pytest.raises(config.ConfigError, match="unknown key"):
        config.parse({1: "x", "extra": "y", "servers": [{"name": "s", "command": "x"}]})


def test_unclosed_quote_in_command_string():
    with pytest.raises(config.ConfigError, match=r"servers\[0\]\.command: cannot split"):
        config.parse({"servers": [{"name": "s", "command": "python 'unclosed"}]}, dry_run=True)


@pytest.mark.parametrize("bad", ["http://[::1", "http://localhost:notaport/v1"])
def test_malformed_url(bad):
    with pytest.raises(config.ConfigError, match="not a valid URL"):
        config.parse({"servers": [{"name": "s", "url": bad}]}, dry_run=True)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_numbers_are_rejected(value):
    data = {"servers": [{"name": "s", "command": "x", "timeout": value}]}
    with pytest.raises(config.ConfigError, match=r"servers\[0\]\.timeout"):
        config.parse(data, dry_run=True)


@pytest.mark.parametrize("value", [0, -5])
def test_server_timeout_must_be_positive(value):
    data = {"servers": [{"name": "s", "command": "x", "timeout": value}]}
    with pytest.raises(config.ConfigError, match="positive number of seconds"):
        config.parse(data, dry_run=True)


# garak reports


@FUZZ
@given(lines=st.lists(json_values, max_size=8))
def test_summarise_random_report_lines(tmp_path, lines):
    path = tmp_path / "r.report.jsonl"
    init = {"entry_type": "init", "garak_version": "x", "run": "r"}
    path.write_text("\n".join(json.dumps(x) for x in [init, *lines]) + "\n", encoding="utf-8")
    out = summary.summarise(path)
    summary.to_markdown(out)


attempt_like = st.fixed_dictionaries(
    {"entry_type": st.just("attempt"), "status": st.just(2)},
    optional={
        "probe_classname": json_values,
        "outputs": json_values,
        "detector_results": st.one_of(
            json_values, st.dictionaries(st.text(max_size=8), json_values, max_size=3)
        ),
    },
)


@FUZZ
@given(attempts=st.lists(attempt_like, max_size=6))
def test_summarise_malformed_attempts_never_crash(tmp_path, attempts):
    path = tmp_path / "r.report.jsonl"
    init = {"entry_type": "init"}
    path.write_text("\n".join(json.dumps(x) for x in [init, *attempts]) + "\n", encoding="utf-8")
    out = summary.summarise(path)
    assert out["totals"]["attempts"] == len(attempts)
    summary.to_markdown(out)


@FUZZ
@given(raw=st.binary(max_size=200))
def test_summarise_random_bytes_only_raises_report_error(tmp_path, raw):
    path = tmp_path / "r.report.jsonl"
    path.write_bytes(raw)
    with contextlib.suppress(summary.ReportError):
        summary.summarise(path)


def test_summarise_directory_and_bad_encoding(tmp_path):
    with pytest.raises(summary.ReportError, match="is a directory"):
        summary.summarise(tmp_path)
    bad = tmp_path / "r.jsonl"
    bad.write_bytes(b'{"entry_type": "init"}\n\xff\n')
    with pytest.raises(summary.ReportError, match="not UTF-8"):
        summary.summarise(bad)


def test_summarise_ignores_non_numeric_scores(tmp_path):
    path = tmp_path / "r.jsonl"
    entries = [
        {"entry_type": "init"},
        {
            "entry_type": "attempt",
            "status": 2,
            "probe_classname": "p.Q",
            "outputs": "not a list",
            "detector_results": {"garak_mcp.ToolCalled": [1.0, "high", True, None, 0.0]},
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    p = summary.summarise(path)["probes"]["p.Q"]
    assert p["outputs"] == 0
    assert p["detectors"]["ToolCalled"] == {"scored": 2, "hits": 1}


# model replies and tool arguments


@FUZZ
@given(payload=json_values)
def test_parse_reply_only_raises_model_error(payload):
    with contextlib.suppress(ModelError):
        parse_reply(payload)


@FUZZ
@given(
    message=st.fixed_dictionaries(
        {},
        optional={"content": json_values, "tool_calls": json_values},
    )
)
def test_parse_reply_message_shapes(message):
    try:
        reply = parse_reply({"choices": [{"message": message}]})
    except ModelError:
        return
    assert reply.text is None or isinstance(reply.text, str)
    for call in reply.tool_calls:
        assert isinstance(call.name, str) and isinstance(call.arguments, str)


@pytest.mark.parametrize("tool_calls", [5, "abc", {"a": 1}])
def test_tool_calls_that_are_not_a_list(tool_calls):
    with pytest.raises(ModelError, match="tool_calls is not a list"):
        parse_reply({"choices": [{"message": {"tool_calls": tool_calls}}]})


def test_tool_call_name_must_be_a_string():
    msg = {"tool_calls": [{"function": {"name": 7, "arguments": "{}"}}]}
    with pytest.raises(ModelError, match="no function name"):
        parse_reply({"choices": [{"message": msg}]})


@FUZZ
@given(arguments=json_values, canary=st.text(min_size=1, max_size=8))
def test_argument_contains_matches_a_planted_canary(arguments, canary):
    planted = {"wrapper": [arguments, {"key": f"xx{canary}yy"}]}
    trace = {"calls": [{"tool": "t", "arguments": planted}]}
    assert argument_contains(trace, [canary])


def test_deeply_nested_arguments_do_not_hit_the_recursion_limit():
    deep: object = "AKIAIOSFODNN7EXAMPLE"
    for _ in range(50_000):
        deep = {"k": [deep]}
    trace = {"calls": [{"tool": "t", "arguments": deep}]}
    assert argument_contains(trace, ["AKIAIOSFODNN7EXAMPLE"])


def test_agent_records_deeply_nested_raw_arguments_as_an_error():
    import asyncio

    from garak_mcp_probes.agent import _call
    from garak_mcp_probes.trace import Trace

    trace = Trace(max_steps=1)
    raw = "[" * 100_000 + "]" * 100_000
    content = asyncio.run(_call(1, "fake__echo", raw, {}, trace))
    assert content.startswith("Error:") and trace.calls[0].is_error


# command-line values


@pytest.mark.parametrize("value", ["nan", "inf", "-0.1", "1.5", "high"])
def test_threshold_outside_0_to_1_exits_2(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--dry-run", "--probes", "test.Blank", "--threshold", value])
    assert exc.value.code == 2
    assert "expected a number from 0 to 1" in capsys.readouterr().err


@FUZZ
@given(argv=st.lists(st.text(alphabet=string.ascii_letters + "-=. ", max_size=12), max_size=4))
def test_random_argv_for_summarise_exits_cleanly(argv, capsys):
    try:
        code = main(["summarise", *argv])
    except SystemExit as exc:  # argparse usage errors
        code = exc.code
    capsys.readouterr()
    assert code in (0, 1, 2)
