"""Seeded fuzz, bad-input and scaling tests for every reader: the configuration file, the garak
report, the model's chat completions reply, tool arguments and the trace checks.

Each test runs under a wall-clock limit, so a reader that loops or backtracks fails instead of
hanging CI. None of them needs garak, a model or a network.
"""

from __future__ import annotations

import json
import random
import signal
import time
from contextlib import contextmanager
from typing import Any

import pytest

from garak_mcp_probes import config, model, summary, trace
from garak_mcp_probes.cli import main
from garak_mcp_probes.trace import TRACE_KEY

from .test_summary import output, write_report

SEED = 20261028


@contextmanager
def time_limit(seconds: float):
    """Fail if the block runs longer than `seconds` (POSIX; elsewhere a plain block)."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _raise(signum, frame):
        raise TimeoutError(f"took longer than {seconds}s")

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


SCALARS: list[Any] = [
    None,
    True,
    False,
    0,
    -1,
    1,
    2.5,
    float("inf"),
    "",
    "x",
    "echo",
    "a:b",
    "fake:echo",
    "AKIAIOSFODNN7EXAMPLE",
    "http://localhost:1",
    "https://e.x/v1",
    "python -m x",
    "'unclosed",
    "${NOPE_NOT_SET}",
    "\x00",
    "é",
]
KEYS = [
    "model",
    "servers",
    "agent",
    "policy",
    "name",
    "command",
    "url",
    "env",
    "headers",
    "cwd",
    "timeout",
    "allow_http",
    "base_url",
    "max_steps",
    "deny_tools",
    "allow_tools",
    "canaries",
    "step_budget",
    "api_key",
    "temperature",
    "max_tokens",
    "system_prompt",
    "calls",
    "tool",
    "server",
    "arguments",
    "stopped",
    "outputs",
    "notes",
    TRACE_KEY,
    "choices",
    "message",
    "tool_calls",
    "function",
    "content",
    "text",
    1,
    None,
    True,
]


def _value(rng: random.Random, depth: int = 0) -> Any:
    roll = rng.random()
    if depth > 4 or roll < 0.45:
        return rng.choice(SCALARS)
    if roll < 0.75:
        return {rng.choice(KEYS): _value(rng, depth + 1) for _ in range(rng.randint(0, 5))}
    return [_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]


def _nested(depth: int) -> Any:
    value: Any = "AKIAIOSFODNN7EXAMPLE"
    for _ in range(depth):
        value = {"k": [value]}
    return value


def test_fuzz_config_parse_raises_only_config_error():
    rng = random.Random(SEED)
    with time_limit(60):
        for _ in range(3000):
            data = _value(rng)
            if rng.random() < 0.5:
                data = {"servers": [_value(rng)], **({} if not isinstance(data, dict) else data)}
            for dry_run in (False, True):
                try:
                    config.parse(data, source="fuzz.yaml", dry_run=dry_run)
                except config.ConfigError as exc:
                    assert str(exc).startswith("fuzz.yaml: ")


def test_fuzz_parse_reply_raises_only_model_error():
    rng = random.Random(SEED)
    with time_limit(30):
        for _ in range(3000):
            payload = {"choices": [{"message": _value(rng)}]} if rng.random() < 0.7 else _value(rng)
            try:
                reply = model.parse_reply(payload)
            except model.ModelError:
                continue
            assert reply.text is None or isinstance(reply.text, str)
            assert all(
                isinstance(c.name, str) and isinstance(c.arguments, str) for c in reply.tool_calls
            )


def test_fuzz_trace_checks_never_raise():
    rng = random.Random(SEED)
    with time_limit(30):
        for _ in range(3000):
            t = _value(rng)
            t = t if isinstance(t, dict) else {"calls": t}
            trace.tool_called(t, ["echo", "fake:send_report"])
            trace.unexpected_tool(t, ["echo"])
            trace.argument_contains(t, ["AKIAIOSFODNN7EXAMPLE"])
            trace.step_budget_exceeded(t, 2)
            trace.tool_error(t)
            trace.from_message({"notes": {TRACE_KEY: t}})


def test_fuzz_summary_of_malformed_attempts(tmp_path):
    rng = random.Random(SEED)
    with time_limit(60):
        for i in range(300):
            attempts = [
                (_value(rng), rng.choice([2, 1, "2", None]), _value(rng), _value(rng))
                for _ in range(rng.randint(0, 4))
            ]
            path = write_report(tmp_path / f"r{i}.jsonl", attempts)
            result = summary.summarise(path)
            summary.to_markdown(result)


def test_argument_contains_reads_arguments_deeper_than_the_recursion_limit():
    t = {"calls": [{"tool": "send", "arguments": _nested(5_000)}]}
    with time_limit(10):
        assert trace.argument_contains(t, ["AKIAIOSFODNN7EXAMPLE"])


def test_agent_treats_too_deeply_nested_arguments_as_not_json():
    import asyncio

    from garak_mcp_probes.agent import _call
    from garak_mcp_probes.trace import Trace

    t = Trace(max_steps=1)
    text = asyncio.run(_call(1, "echo", "[" * 100_000, {}, t))
    assert text == "Error: arguments are not a JSON object"
    assert t.calls[0].is_error


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize(
    ("name", "data", "needle"),
    [
        ("c.yaml", b"servers:\n  - name: caf\xe9\n", "not UTF-8 text (byte 0xe9 at offset 22)"),
        ("c.json", b"[" * 100_000, "nested too deeply"),
        ("c.yaml", b"[" * 100_000, "not valid YAML"),
        ("c.yaml", b"1: x\nservers: []\n", "unknown key(s) 1"),
        ("c.yaml", b'servers:\n  - name: s\n    command: "python -m \'x"\n', "cannot split"),
    ],
)
def test_bad_config_files_exit_2_with_a_message(tmp_path, capsys, name, data, needle):
    path = _write(tmp_path, name, data)
    with time_limit(30):
        rc = main(["doctor", "--config", str(path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.startswith(f"garak-mcp: {path}")
    assert needle in err


def test_utf8_bom_config_is_read(tmp_path):
    path = _write(
        tmp_path,
        "c.json",
        b"\xef\xbb\xbf" + json.dumps({"servers": [{"name": "s", "command": ["python"]}]}).encode(),
    )
    assert config.load(path, dry_run=True).servers[0].name == "s"


@pytest.mark.parametrize(
    ("data", "needle"),
    [
        (b"\xff\xfe{\x00", "not UTF-8 text"),
        (b"[" * 100_000 + b"\n", "line 1 is nested too deeply"),
        (b'{"entry_type": "attempt"}\n', "no init entry"),
        (b"not json\n", "line 1 is not JSON"),
    ],
)
def test_bad_reports_raise_report_error(tmp_path, data, needle):
    path = _write(tmp_path, "r.jsonl", data)
    with pytest.raises(summary.ReportError, match=None) as info:
        summary.summarise(path)
    assert needle in str(info.value)


def test_wrong_typed_report_fields_count_as_empty(tmp_path):
    path = write_report(
        tmp_path / "r.jsonl",
        [
            ("p", 2, 5, {"garak_mcp.ToolCalled": "1.0"}),
            ("p", 2, [{"notes": {TRACE_KEY: {"calls": "abc"}}}], ["not", "a", "dict"]),
            ("p", 2, [output(1)], {"garak_mcp.ToolCalled": [True, "x", 1.0, None, [1]]}),
        ],
    )
    result = summary.summarise(path)
    p = result["probes"]["p"]
    assert p["attempts"] == 3 and p["outputs"] == 2 and p["tool_calls"] == 1
    assert p["detectors"]["ToolCalled"] == {"scored": 1, "hits": 1}


def test_summary_scales_linearly(tmp_path):
    """10x the attempts should cost about 10x the time, not 100x."""

    def timed(n: int) -> float:
        attempts = [
            (f"p{i % 7}", 2, [output(3)], {"garak_mcp.ToolCalled": [1.0]}) for i in range(n)
        ]
        path = write_report(tmp_path / f"r{n}.jsonl", attempts)
        start = time.perf_counter()
        result = summary.summarise(path)
        summary.to_markdown(result)
        assert result["totals"]["attempts"] == n
        return time.perf_counter() - start

    with time_limit(60):
        small, large = timed(2_000), timed(20_000)
    assert large < max(small, 0.005) * 40


def test_argument_contains_scales_linearly():
    def timed(n: int) -> float:
        t = {"calls": [{"tool": "x", "arguments": {"a": ["b" * 50] * 20}} for _ in range(n)]}
        start = time.perf_counter()
        trace.argument_contains(t, ["AKIAIOSFODNN7EXAMPLE", "zzzzzz"])
        return time.perf_counter() - start

    with time_limit(60):
        small, large = timed(500), timed(5_000)
    assert large < max(small, 0.005) * 40


def test_argument_contains_is_linear_in_nesting_depth():
    """The recursive walk copied every list on the way up: depth 200 to 2,000 took 0.013s to
    0.92s. The iterative walk keeps 10x the depth near 10x the time."""

    def timed(depth: int) -> float:
        value: Any = ["AKIAIOSFODNN7EXAMPLE"] * 10
        for _ in range(depth):
            value = {"k": [value, "x" * 10]}
        t = {"calls": [{"tool": "x", "arguments": value}] * 20}
        start = time.perf_counter()
        trace.argument_contains(t, ["zzzzzz"])
        return time.perf_counter() - start

    with time_limit(60):
        small, large = timed(200), timed(2_000)
    assert large < max(small, 0.002) * 40
