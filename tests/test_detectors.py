from __future__ import annotations

import pytest

from garak_mcp_probes import detectors as d
from garak_mcp_probes.config import PolicyConfig
from garak_mcp_probes.trace import TRACE_KEY

from .conftest import CANARY, attempt_with

POLICY = PolicyConfig(
    deny_tools=["send_report"],
    allow_tools=["echo", "read_note"],
    canaries=[CANARY],
    step_budget=2,
)


def notes(*calls, stopped="final"):
    return {TRACE_KEY: {"version": 1, "stopped": stopped, "calls": list(calls)}}


def call(tool, args=None, is_error=False, server="fake"):
    return {"server": server, "tool": tool, "arguments": args or {}, "is_error": is_error}


CASES = [
    ("ToolCalled", notes(call("send_report")), notes(call("echo"))),
    (
        "ArgumentContains",
        notes(call("echo", {"text": f"x {CANARY}"})),
        notes(call("echo", {"text": "x"})),
    ),
    ("UnexpectedTool", notes(call("list_notes")), notes(call("echo"), call("read_note"))),
    ("StepBudgetExceeded", notes(call("echo"), call("echo"), call("echo")), notes(call("echo"))),
    ("StepBudgetExceeded", notes(stopped="max_steps"), notes()),
    ("ToolError", notes(call("read_note", is_error=True)), notes(call("read_note"))),
]


@pytest.mark.parametrize(("name", "hit", "miss"), CASES)
def test_each_detector_scores_hit_miss_and_missing_trace(name, hit, miss):
    det = d.ALL[name](policy=POLICY)
    assert list(det.detect(attempt_with(hit, miss, None))) == [1.0, 0.0, None]


def test_detectors_report_under_a_digest_compatible_name():
    for name, cls in d.ALL.items():
        det = cls(policy=POLICY)
        assert det.detectorname == f"garak_mcp.{name}"
        assert det.detectorname.count(".") == 1
        info = cls.plugin_info()
        assert info["description"] and info["hit_desc"] and info["pass_desc"]


def test_applicable_leaves_out_detectors_with_nothing_to_check():
    assert d.applicable(PolicyConfig()) == ["StepBudgetExceeded", "ToolError"]
    assert d.applicable(POLICY) == list(d.ALL)
    assert [x.name for x in d.build(POLICY, ["ToolError"])] == ["ToolError"]


def test_unexpected_tool_without_allow_list_never_fires():
    det = d.UnexpectedTool(policy=PolicyConfig())
    assert list(det.detect(attempt_with(notes(call("anything"))))) == [0.0]
