"""Scaling checks: ten times the input should take roughly ten times as long, not a hundred.

Each test times a base size and ten times that size, takes the best of a few runs, and fails if
the ratio is beyond what linear work plus noise explains. The bound (35) sits between linear
(about 10) and quadratic (about 100), so a slow CI machine does not fail it but a quadratic
regression does.
"""

from __future__ import annotations

import gc
import json
import time
from collections.abc import Callable

from garak_mcp_probes import config, summary
from garak_mcp_probes.trace import TRACE_KEY, argument_contains

LINEAR_BOUND = 35


def best_time(fn: Callable[[], object], repeat: int = 5) -> float:
    best = float("inf")
    gc.collect()
    gc.disable()  # a collection landing in one timing skews the ratio on a busy runner
    try:
        for _ in range(repeat):
            start = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - start)
    finally:
        gc.enable()
    return max(best, 1e-6)


def ratio(make: Callable[[int], Callable[[], object]], n: int) -> float:
    small, large = make(n), make(10 * n)
    small()  # warm up
    return best_time(large) / best_time(small)


def test_argument_contains_is_linear_in_nesting_depth():
    def make(depth: int):
        deep: object = "no canary here"
        for _ in range(depth):
            deep = {"k": [deep]}
        trace = {"calls": [{"tool": "t", "arguments": deep}]}
        return lambda: argument_contains(trace, ["AKIAIOSFODNN7EXAMPLE"])

    assert ratio(make, 2_000) < LINEAR_BOUND


def test_argument_contains_is_linear_in_calls():
    def make(n: int):
        calls = [{"tool": "t", "arguments": {"a": f"value {i}", "b": [i, None]}} for i in range(n)]
        return lambda: argument_contains({"calls": calls}, ["AKIAIOSFODNN7EXAMPLE", "canary-2"])

    assert ratio(make, 2_000) < LINEAR_BOUND


def test_duplicate_server_check_is_linear():
    def make(n: int):
        data = {"servers": [{"name": f"s{i}", "command": "x"} for i in range(n)]}
        return lambda: config.parse(data, dry_run=True)

    assert ratio(make, 300) < LINEAR_BOUND


def test_summarise_is_linear_in_report_size(tmp_path):
    def make(n: int):
        path = tmp_path / f"r{n}.jsonl"
        out = {"text": "x", "notes": {TRACE_KEY: {"calls": [{"tool": "echo"}]}}}
        lines = [{"entry_type": "init"}] + [
            {
                "entry_type": "attempt",
                "status": 2,
                "probe_classname": f"p.P{i % 20}",
                "outputs": [out],
                "detector_results": {"garak_mcp.ToolCalled": [float(i % 2)]},
            }
            for i in range(n)
        ]
        path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        return lambda: summary.summarise(path)

    assert ratio(make, 2_000) < LINEAR_BOUND
