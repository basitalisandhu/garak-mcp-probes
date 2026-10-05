"""Summarise a garak JSONL report: per probe, attempts and hits per detector.

This reads the report garak wrote and nothing else, so it can run on any report from a
``garak-mcp run``. garak's own report and HTML digest stay the authoritative record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .trace import from_message

ATTEMPT_COMPLETE = 2
DETECTOR_PREFIX = "garak_mcp."


class ReportError(ValueError):
    """The report file is missing or not a garak JSONL report."""


def _entries(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReportError(f"{path}: cannot read: {exc.strerror or exc}") from exc
    entries = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise ReportError(f"{path}: line {n} is not JSON") from exc
        if isinstance(entry, dict):
            entries.append(entry)
    if not any(e.get("entry_type") == "init" for e in entries):
        raise ReportError(f"{path}: no init entry; is this a garak report?")
    return entries


def short_detector(name: str) -> str:
    return name[len(DETECTOR_PREFIX) :] if name.startswith(DETECTOR_PREFIX) else name


def summarise(report: str | Path, threshold: float = 0.5) -> dict[str, Any]:
    """Count completed attempts, scored outputs and hits (score >= threshold) per probe and
    detector, plus tool calls seen in the traces."""
    path = Path(report)
    entries = _entries(path)
    init = next(e for e in entries if e.get("entry_type") == "init")
    probes: dict[str, dict[str, Any]] = {}
    for e in entries:
        if e.get("entry_type") != "attempt" or e.get("status") != ATTEMPT_COMPLETE:
            continue
        probe = str(e.get("probe_classname") or "unknown")
        p = probes.setdefault(
            probe, {"attempts": 0, "outputs": 0, "tool_calls": 0, "no_trace": 0, "detectors": {}}
        )
        p["attempts"] += 1
        outputs = e.get("outputs") or []
        p["outputs"] += len(outputs)
        for out in outputs:
            trace = from_message(out) if isinstance(out, dict) else None
            if trace is None:
                p["no_trace"] += 1
            else:
                p["tool_calls"] += len(trace.get("calls") or [])
        for det, scores in (e.get("detector_results") or {}).items():
            d = p["detectors"].setdefault(short_detector(det), {"scored": 0, "hits": 0})
            for s in scores or []:
                if s is None:
                    continue
                d["scored"] += 1
                if float(s) >= threshold:
                    d["hits"] += 1
    return {
        "report": path.name,
        "garak_version": init.get("garak_version"),
        "run": init.get("run"),
        "threshold": threshold,
        "probes": dict(sorted(probes.items())),
        "totals": _totals(probes),
    }


def _totals(probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {"attempts": 0, "outputs": 0, "tool_calls": 0, "detectors": {}}
    for p in probes.values():
        for k in ("attempts", "outputs", "tool_calls"):
            totals[k] += p[k]
        for det, d in p["detectors"].items():
            agg = totals["detectors"].setdefault(det, {"scored": 0, "hits": 0})
            agg["scored"] += d["scored"]
            agg["hits"] += d["hits"]
    return totals


def to_markdown(summary: dict[str, Any]) -> str:
    detectors = sorted(summary["totals"]["detectors"])
    lines = [
        "# garak-mcp summary",
        "",
        f"Report: `{summary['report']}` (garak {summary.get('garak_version') or 'unknown'}, "
        f"run `{summary.get('run') or 'unknown'}`). A hit is a detector score of "
        f"{summary['threshold']} or more; each cell is hits / scored outputs.",
        "",
    ]
    if not summary["probes"]:
        return "\n".join([*lines, "No completed attempts in the report.", ""])
    header = ["Probe", "Attempts", "Tool calls", *detectors]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    rows = [*summary["probes"].items(), ("**Total**", summary["totals"])]
    for name, p in rows:
        cells = [
            f"`{name}`" if not name.startswith("**") else name,
            str(p["attempts"]),
            str(p["tool_calls"]),
        ]
        for det in detectors:
            d = p["detectors"].get(det)
            cells.append(f"{d['hits']} / {d['scored']}" if d else "-")
        lines.append("| " + " | ".join(cells) + " |")
    if summary.get("skipped_probes"):
        lines += [
            "",
            "Skipped intent probes: " + ", ".join(f"`{p}`" for p in summary["skipped_probes"]),
        ]
    return "\n".join([*lines, ""])


def write(summary: dict[str, Any], out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js, md = out / "summary.json", out / "summary.md"
    js.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md.write_text(to_markdown(summary), encoding="utf-8")
    return js, md
