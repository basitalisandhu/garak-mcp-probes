"""garak driven in code, offline: garak's own test probe, the fake server, and a scripted model."""

from __future__ import annotations

import json

import pytest

from garak_mcp_probes import runner
from garak_mcp_probes.generators import MCPAgentGenerator

from .conftest import CANARY, ScriptedModel, make_config


def test_run_writes_garak_report_and_summaries_with_hits(tmp_path, overrides):
    cfg = make_config()
    model = ScriptedModel(
        [[("fake__send_report", {"recipient": "x", "body": f"key {CANARY}"})], "sent"]
    )
    gen = MCPAgentGenerator(settings=cfg, model=model, server_overrides=overrides)
    result = runner.run(cfg, "test.Blank", tmp_path, generations=2, generator=gen)

    assert result.report.exists() and result.report.suffix == ".jsonl"
    assert result.report.with_suffix(".html").exists()
    probe = result.summary["probes"]["test.Blank"]
    assert probe["attempts"] == 1 and probe["outputs"] == 2 and probe["tool_calls"] == 1
    hits = {k: (v["hits"], v["scored"]) for k, v in probe["detectors"].items()}
    assert hits == {
        "ToolCalled": (1, 2),
        "ArgumentContains": (1, 2),
        "UnexpectedTool": (1, 2),
        "StepBudgetExceeded": (0, 2),
        "ToolError": (0, 2),
    }
    on_disk = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert on_disk["policy"]["deny_tools"] == ["send_report"]
    assert "| `test.Blank` | 1 | 1 | 1 / 2 |" in result.summary_md.read_text(encoding="utf-8")

    entries = [json.loads(line) for line in result.report.read_text(encoding="utf-8").splitlines()]
    attempts = [e for e in entries if e.get("entry_type") == "attempt" and e.get("status") == 2]
    traces = [o["notes"]["mcp_trace"] for o in attempts[0]["outputs"]]
    assert traces[0]["calls"][0]["tool"] == "send_report"
    cache = [e for e in entries if e.get("entry_type") == "plugin_cache"]
    assert any(
        "detectors.garak_mcp.ToolCalled" in e["plugin_cache"].get("detectors", {}) for e in cache
    )


def test_detector_subset(tmp_path, overrides):
    cfg = make_config()
    gen = MCPAgentGenerator(settings=cfg, model=ScriptedModel(["fine"]), server_overrides=overrides)
    result = runner.run(cfg, "test.Blank", tmp_path, detector_names=["ToolError"], generator=gen)
    assert list(result.summary["probes"]["test.Blank"]["detectors"]) == ["ToolError"]


def test_unknown_probe_is_an_error(tmp_path):
    with pytest.raises(runner.RunError, match="unknown probe"):
        runner.resolve_probes("no_such_probe_module")
    with pytest.raises(runner.RunError):
        runner.run(make_config(), "no_such_probe_module", tmp_path)
