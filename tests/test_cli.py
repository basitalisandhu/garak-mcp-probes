from __future__ import annotations

import json
import subprocess
import sys

import pytest

from garak_mcp_probes import __version__
from garak_mcp_probes.cli import main

from .conftest import ROOT


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage: garak-mcp" in out and "Run garak against your MCP servers" in out
    for cmd in ("run", "summarise", "doctor", "list-probes"):
        assert cmd in out


@pytest.mark.parametrize("cmd", ["run", "summarise", "doctor", "list-probes"])
def test_subcommand_help(cmd, capsys):
    with pytest.raises(SystemExit) as exc:
        main([cmd, "--help"])
    assert exc.value.code == 0
    assert f"usage: garak-mcp {cmd}" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"garak-mcp {__version__}"


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "usage: garak-mcp" in capsys.readouterr().out


def test_console_script_module_entry_point():
    out = subprocess.run(
        [sys.executable, "-m", "garak_mcp_probes", "--help"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert out.returncode == 0 and "usage: garak-mcp" in out.stdout


def test_run_without_config_exits_2(capsys):
    assert main(["run", "--probes", "test.Blank"]) == 2
    assert "--config is required" in capsys.readouterr().err


def test_bad_config_exits_2(tmp_path, capsys):
    bad = tmp_path / "c.json"
    bad.write_text(json.dumps({"servers": []}), encoding="utf-8")
    assert main(["doctor", "--config", str(bad)]) == 2
    assert "servers: expected a non-empty list" in capsys.readouterr().err


def test_unknown_detector_and_probe_exit_2(tmp_path, capsys):
    assert main(["run", "--dry-run", "--probes", "test.Blank", "--detectors", "Nope"]) == 2
    assert "unknown detector(s) Nope" in capsys.readouterr().err
    assert main(["run", "--dry-run", "--probes", "no_such_probe_module", "-o", str(tmp_path)]) == 2
    assert "unknown probe" in capsys.readouterr().err


def test_doctor_dry_run(capsys):
    assert main(["doctor", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "ok   server fake (stdio): 4 tool(s)" in out
    assert "echo, list_notes, read_note, send_report" in out
    assert "ok   model fake-echo" in out


def test_doctor_reports_failures(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps(
            {
                "model": {"base_url": "http://127.0.0.1:9/v1", "name": "m", "timeout": 2},
                "servers": [{"name": "gone", "command": ["/nonexistent/garak-mcp-test-binary"]}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["doctor", "--config", str(cfg)]) == 1
    out = capsys.readouterr().out
    assert "FAIL server gone (stdio)" in out and "FAIL model m at http://127.0.0.1:9/v1" in out


def test_run_dry_run_writes_summaries(tmp_path, capsys):
    assert (
        main(
            [
                "run",
                "--dry-run",
                "--probes",
                "test.Blank",
                "--report-dir",
                str(tmp_path),
                "--fail-on-hit",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "| `test.Blank` | 1 | 1 | 0 / 1 | 0 / 1 | 0 / 1 | 0 / 1 | 0 / 1 |" in out
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["config"] == "built-in dry run"
    assert (tmp_path / "summary.md").exists()


def test_run_with_probe_detectors_flag(tmp_path, capsys):
    args = ["run", "--dry-run", "--probes", "test.Blank", "--report-dir", str(tmp_path)]
    assert main([*args, "--with-probe-detectors"]) == 0
    assert "any.AnyOutput" in capsys.readouterr().out
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["probe_detectors"] is True
    assert "any.AnyOutput" in summary["totals"]["detectors"]


def test_list_probes_passes_through(capsys):
    assert main(["list-probes"]) == 0
    assert "probes: " in capsys.readouterr().out


def _summary_report(tmp_path, scores):
    from .test_summary import output, write_report

    return write_report(
        tmp_path / "garak.report.jsonl",
        [("dan.Dan_11_0", 2, [output(1)], {"garak_mcp.ToolCalled": scores})],
    )


def test_summarise_existing_report(tmp_path, capsys):
    report = _summary_report(tmp_path, [0.0])
    out_dir = tmp_path / "out"
    assert main(["summarise", str(report), "-o", str(out_dir), "--fail-on-hit"]) == 0
    printed = capsys.readouterr().out
    assert "| `dan.Dan_11_0` | 1 | 1 | 0 / 1 |" in printed
    data = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert data["probes"]["dan.Dan_11_0"]["detectors"]["ToolCalled"] == {"scored": 1, "hits": 0}
    assert (out_dir / "summary.md").read_text(encoding="utf-8").startswith("# garak-mcp summary")


def test_summarise_threshold_and_fail_on_hit(tmp_path, capsys):
    report = _summary_report(tmp_path, [0.6])
    out_dir = str(tmp_path / "out")
    assert main(["summarise", str(report), "-o", out_dir, "--fail-on-hit"]) == 1
    assert (
        main(["summarize", str(report), "-o", out_dir, "--threshold", "0.7", "--fail-on-hit"]) == 0
    )
    data = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert data["threshold"] == 0.7
    assert data["totals"]["detectors"]["ToolCalled"] == {"scored": 1, "hits": 0}


def test_summarise_default_output_directory(tmp_path, monkeypatch):
    report = _summary_report(tmp_path, [1.0])
    monkeypatch.chdir(tmp_path)
    assert main(["summarise", str(report)]) == 0
    assert (tmp_path / "garak-mcp-summary" / "summary.json").exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "cannot read"), ("not json\n", "line 1 is not JSON"), ("{}\n", "no init entry")],
)
def test_summarise_bad_report_exits_2(tmp_path, capsys, content, message):
    path = tmp_path / "r.jsonl"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert main(["summarise", str(path), "-o", str(tmp_path / "out")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("garak-mcp: ") and message in err
