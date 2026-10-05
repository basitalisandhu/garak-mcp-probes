"""The summary writer over a garak-shaped JSONL report built in the test."""

from __future__ import annotations

import json

import pytest

from garak_mcp_probes import summary as s
from garak_mcp_probes.trace import TRACE_KEY


def output(n_calls):
    calls = [{"tool": "echo", "server": "fake", "arguments": {}}] * n_calls
    return {"text": "x", "notes": {TRACE_KEY: {"version": 1, "stopped": "final", "calls": calls}}}


def write_report(path, attempts):
    lines = [
        {"entry_type": "start_run setup"},
        {"entry_type": "init", "garak_version": "0.17.0", "run": "run-1", "start_time": "t"},
    ]
    for probe, status, outputs, results in attempts:
        lines.append(
            {
                "entry_type": "attempt",
                "probe_classname": probe,
                "status": status,
                "outputs": outputs,
                "detector_results": results,
            }
        )
    lines.append({"entry_type": "completion", "run": "run-1"})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def report(tmp_path):
    return write_report(
        tmp_path / "garak.report.jsonl",
        [
            (
                "dan.Dan_11_0",
                2,
                [output(1), output(2)],
                {"garak_mcp.ToolCalled": [1.0, 0.0], "garak_mcp.ToolError": [0.0, None]},
            ),
            ("dan.Dan_11_0", 2, [output(0)], {"garak_mcp.ToolCalled": [0.0]}),
            (
                "dan.Dan_11_0",
                1,
                [output(5)],
                {"garak_mcp.ToolCalled": [1.0]},
            ),  # not complete: ignored
            (
                "encoding.InjectHex",
                2,
                [{"text": "y", "notes": {}}],
                {"garak_mcp.ToolCalled": [None], "other.Det": [0.7]},
            ),
        ],
    )


def test_summarise_counts_attempts_hits_and_tool_calls(report):
    out = s.summarise(report)
    dan = out["probes"]["dan.Dan_11_0"]
    assert dan["attempts"] == 2 and dan["outputs"] == 3 and dan["tool_calls"] == 3
    assert dan["detectors"]["ToolCalled"] == {"scored": 3, "hits": 1}
    assert dan["detectors"]["ToolError"] == {"scored": 1, "hits": 0}
    hexp = out["probes"]["encoding.InjectHex"]
    assert hexp["no_trace"] == 1 and hexp["detectors"]["ToolCalled"] == {"scored": 0, "hits": 0}
    assert hexp["detectors"]["other.Det"] == {"scored": 1, "hits": 1}
    assert out["totals"]["attempts"] == 3
    assert out["totals"]["detectors"]["ToolCalled"] == {"scored": 3, "hits": 1}
    assert out["garak_version"] == "0.17.0" and out["run"] == "run-1"
    assert list(out["probes"]) == ["dan.Dan_11_0", "encoding.InjectHex"]


def test_threshold(report):
    assert (
        s.summarise(report, threshold=0.8)["probes"]["encoding.InjectHex"]["detectors"][
            "other.Det"
        ]["hits"]
        == 0
    )


def test_markdown_and_files(report, tmp_path):
    out = s.summarise(report)
    md = s.to_markdown(out)
    assert "| Probe | Attempts | Tool calls | ToolCalled | ToolError | other.Det |" in md
    assert "| `dan.Dan_11_0` | 2 | 3 | 1 / 3 | 0 / 1 | - |" in md
    assert "| **Total** | 3 | 3 | 1 / 3 | 0 / 1 | 1 / 1 |" in md
    js, mdp = s.write(out, tmp_path / "out")
    assert json.loads(js.read_text(encoding="utf-8")) == out
    assert mdp.read_text(encoding="utf-8") == md


def test_markdown_lists_skipped_probes(report):
    out = s.summarise(report)
    out["skipped_probes"] = ["some.IntentProbe"]
    assert "Skipped intent probes: `some.IntentProbe`" in s.to_markdown(out)


def test_empty_report(tmp_path):
    out = s.summarise(write_report(tmp_path / "r.jsonl", []))
    assert out["probes"] == {} and "No completed attempts" in s.to_markdown(out)


def test_report_errors(tmp_path):
    with pytest.raises(s.ReportError, match="cannot read"):
        s.summarise(tmp_path / "missing.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"entry_type": "init"}\nnot json\n', encoding="utf-8")
    with pytest.raises(s.ReportError, match="line 2 is not JSON"):
        s.summarise(bad)
    no_init = tmp_path / "noinit.jsonl"
    no_init.write_text('{"entry_type": "attempt"}\n', encoding="utf-8")
    with pytest.raises(s.ReportError, match="no init entry"):
        s.summarise(no_init)
