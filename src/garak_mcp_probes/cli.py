"""The ``garak-mcp`` command line: ``run``, ``summarise``, ``doctor`` and ``list-probes``.

Exit codes: 0 success; 1 ``run`` or ``summarise`` with ``--fail-on-hit`` found hits, or ``doctor``
found a failing check; 2 usage, configuration or setup error.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, RunConfig, dry_run_config, load

DESCRIPTION = (
    "Run garak against your MCP servers: a generator that puts garak's probes through an agent "
    "using your MCP tools, and detectors that show when a probe makes the agent misuse a tool. "
    "For servers and agents you own or are authorised to test."
)


def _config(args: argparse.Namespace) -> RunConfig:
    if args.dry_run:
        base = load(args.config, dry_run=True) if args.config else None
        return dry_run_config(base)
    if not args.config:
        raise ConfigError("--config is required unless --dry-run is given")
    return load(args.config)


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", "-c", help="run configuration, YAML or JSON")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="use the built-in fake model and fake MCP server (no network, no keys); "
        "the policy and agent settings of --config still apply",
    )


def _threshold(text: str) -> float:
    """``--threshold``: a number from 0 to 1 (garak's detector scores use that range)."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number from 0 to 1, got {text!r}") from None
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError(f"expected a number from 0 to 1, got {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="garak-mcp", description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"garak-mcp {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = sub.add_parser(
        "run",
        help="run garak probes through the agent and write garak's report plus summaries",
        description="Run garak probes through the MCP agent; write garak's report, "
        "summary.json and summary.md to --report-dir.",
    )
    _add_config_args(run)
    run.add_argument(
        "--probes", "-p", required=True, help="garak probe spec, for example 'dan' or 'test.Test'"
    )
    run.add_argument("--report-dir", "-o", default="garak-mcp-report", help="output directory")
    run.add_argument(
        "--generations", "-g", type=int, default=1, help="outputs per prompt (default 1)"
    )
    run.add_argument("--seed", type=int, default=None, help="garak run seed")
    run.add_argument(
        "--detectors",
        help="comma-separated subset of ToolCalled, ArgumentContains, UnexpectedTool, "
        "StepBudgetExceeded, ToolError (default: every detector the policy configures)",
    )
    run.add_argument(
        "--with-probe-detectors",
        action="store_true",
        help="also run each probe's own garak text detectors (its primary and extended "
        "detectors) next to the trace detectors; any that cannot load are skipped with a warning",
    )
    run.add_argument(
        "--threshold", type=_threshold, default=0.5, help="score that counts as a hit (default 0.5)"
    )
    run.add_argument(
        "--fail-on-hit", action="store_true", help="exit 1 when any detector scored a hit"
    )

    summarise = sub.add_parser(
        "summarise",
        aliases=["summarize"],
        help="write summary.json and summary.md for an existing garak report, without a run",
        description="Read a garak JSONL report (from garak-mcp run or garak itself) and write "
        "summary.json and summary.md. Nothing is run and nothing connects to a server or model.",
    )
    summarise.add_argument("report", help="garak report file, *.report.jsonl")
    summarise.add_argument(
        "--report-dir",
        "-o",
        default="garak-mcp-summary",
        help="output directory (default garak-mcp-summary; a separate directory, so the "
        "summary a run wrote next to its report is not overwritten)",
    )
    summarise.add_argument(
        "--threshold", type=_threshold, default=0.5, help="score that counts as a hit (default 0.5)"
    )
    summarise.add_argument(
        "--fail-on-hit", action="store_true", help="exit 1 when any detector scored a hit"
    )

    doctor = sub.add_parser(
        "doctor",
        help="check the servers connect and list tools, and the model answers",
        description="Connect to every configured MCP server and list its tools, then send the "
        "model endpoint one short request. No probes run.",
    )
    _add_config_args(doctor)

    sub.add_parser(
        "list-probes",
        help="list garak's probes (passes through to garak --list_probes)",
        description="Print garak's probe list, as `garak --list_probes` does.",
    )
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    from . import detectors, runner

    cfg = _config(args)
    names = None
    if args.detectors:
        names = [n.strip() for n in args.detectors.split(",") if n.strip()]
        unknown = [n for n in names if n not in detectors.ALL]
        if unknown:
            raise ConfigError(f"--detectors: unknown detector(s) {', '.join(unknown)}")
    if args.generations < 1:
        raise ConfigError("--generations: expected a positive integer")
    result = runner.run(
        cfg,
        args.probes,
        args.report_dir,
        generations=args.generations,
        seed=args.seed,
        detector_names=names,
        threshold=args.threshold,
        probe_detectors=args.with_probe_detectors,
    )
    from .summary import to_markdown

    print(to_markdown(result.summary))
    print(f"garak report: {result.report}")
    print(f"summary: {result.summary_json} and {result.summary_md}")
    hits = sum(d["hits"] for d in result.summary["totals"]["detectors"].values())
    return 1 if args.fail_on_hit and hits else 0


def _cmd_summarise(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .summary import summarise, to_markdown, write

    report = Path(args.report)
    result = summarise(report, args.threshold)
    js, md = write(result, args.report_dir)
    print(to_markdown(result))
    print(f"summary: {js} and {md}")
    hits = sum(d["hits"] for d in result["totals"]["detectors"].values())
    return 1 if args.fail_on_hit and hits else 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor

    checks = doctor.run(_config(args))
    print(doctor.render(checks))
    return 0 if all(c.ok for c in checks) else 1


def _cmd_list_probes() -> int:
    import garak.cli

    garak.cli.main(["--list_probes"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command in ("summarise", "summarize"):
            return _cmd_summarise(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        return _cmd_list_probes()
    except ConfigError as exc:
        print(f"garak-mcp: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        from .runner import RunError
        from .summary import ReportError

        if isinstance(exc, (RunError, ReportError)):
            print(f"garak-mcp: {exc}", file=sys.stderr)
            return 2
        raise
