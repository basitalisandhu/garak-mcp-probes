"""Drive garak in code: load its base config, start a run with garak's own report file, run the
selected probes through :class:`MCPAgentGenerator`, score with the trace detectors, end the run,
and summarise the report.

garak's command line cannot load a generator or detectors from outside the ``garak`` package, so
this module does what ``garak.cli`` does for a run, using garak's own functions
(``command.start_run``, the base ``Harness``, ``command.end_run``).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RunConfig


class RunError(Exception):
    """The probe selection or the run setup is invalid."""


@dataclass
class RunResult:
    report: Path
    summary_json: Path
    summary_md: Path
    summary: dict[str, Any]
    skipped: list[str]


def resolve_probes(spec: str) -> list[str]:
    """Resolve a garak probe spec (``dan``, ``encoding.InjectBase64,promptinject``) with garak's
    own parser. Unknown entries are an error."""
    from garak import _config

    names, rejected = _config.parse_plugin_spec(spec, "probes")
    if rejected:
        raise RunError(f"unknown probe(s): {', '.join(rejected)}")
    if not names:
        raise RunError(f"probe spec {spec!r} selects no probes")
    return list(names)


def _prepare_config(report_dir: Path, generations: int, seed: int | None) -> Any:
    from garak import _config

    _config.load_base_config()
    now = datetime.datetime.now()
    _config.transient.starttime = now
    _config.transient.starttime_iso = now.isoformat()
    _config.system.lite = False  # skips a hint in start_run that reads command-line arguments
    _config.system.verbose = 0
    _config.system.parallel_attempts = False
    _config.system.parallel_requests = False
    _config.run.generations = generations
    _config.run.seed = seed
    _config.reporting.report_dir = str(report_dir.resolve())
    _config.reporting.report_prefix = "garak-mcp." + now.strftime("%Y%m%dT%H%M%S")
    return _config


def _cache_entry_guard() -> None:
    """garak writes a plugin_cache entry describing each plugin into the report, and its HTML
    digest reads detector descriptions from it. garak's cache only knows plugins inside the garak
    package, so describe ours here and pass the rest to garak."""
    import json

    import garak
    import garak.harnesses.base as hb
    from garak import _config

    original = getattr(hb, "_emit_plugin_cache_entry", None)
    if original is None or getattr(original, "_garak_mcp", False):
        return

    def emit(*plugins: Any) -> None:
        ours = [p for p in plugins if type(p).__module__.startswith("garak_mcp_probes")]
        original(*[p for p in plugins if p not in ours])
        detectors = {
            "detectors." + p.detectorname: type(p).plugin_info()
            for p in ours
            if hasattr(type(p), "plugin_info")
        }
        if detectors:
            entry = {
                "entry_type": "plugin_cache",
                "run": _config.transient.run_id,
                "plugin_cache": {"detectors": detectors, "version": garak.__version__},
            }
            _config.transient.reportfile.write(json.dumps(entry, ensure_ascii=False) + "\n")

    emit._garak_mcp = True  # type: ignore[attr-defined]
    hb._emit_plugin_cache_entry = emit


def run(
    cfg: RunConfig,
    probe_spec: str,
    report_dir: str | Path,
    generations: int = 1,
    seed: int | None = None,
    detector_names: list[str] | None = None,
    threshold: float = 0.5,
    generator: Any = None,
) -> RunResult:
    from garak import _plugins, command
    from garak.evaluators import ThresholdEvaluator
    from garak.harnesses.base import Harness
    from garak.probes import base as probes_base

    from . import detectors as dets
    from . import summary as summ
    from .generators import MCPAgentGenerator

    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    garak_config = _prepare_config(out, generations, seed)
    garak_config.run.eval_threshold = threshold
    probe_names = resolve_probes(probe_spec)
    detectors = dets.build(cfg.policy, detector_names)
    if not detectors:
        raise RunError("no detectors selected")
    gen = generator or MCPAgentGenerator(settings=cfg, config_root=garak_config)
    _cache_entry_guard()
    intent_probe = getattr(probes_base, "IntentProbe", None)

    # garak caches plugin instances per process; drop them so this run's settings (generations,
    # seed) reach the probes even when an earlier run in the same process loaded them.
    cache = getattr(getattr(_plugins, "PluginProvider", None), "_instance_cache", None)
    if isinstance(cache, dict):
        cache.clear()

    skipped: list[str] = []
    command.start_run()
    try:
        harness = Harness(config_root=garak_config)
        evaluator = ThresholdEvaluator(threshold)
        for name in probe_names:
            probe = _plugins.load_plugin(name, config_root=garak_config)
            if intent_probe is not None and isinstance(probe, intent_probe):
                # garak picks detectors for intent probes by name from its own package, which
                # cannot include these; skip rather than run them unscored.
                logging.warning("garak-mcp: skipping intent probe %s", name)
                skipped.append(name)
                continue
            harness.run(gen, [probe], detectors, evaluator)
    finally:
        report = Path(garak_config.transient.report_filename)
        command.end_run()
    summary = summ.summarise(report, threshold)
    summary["skipped_probes"] = skipped
    summary["policy"] = cfg.policy.as_dict()
    summary["config"] = cfg.source
    js, md = summ.write(summary, out)
    return RunResult(
        report=report, summary_json=js, summary_md=md, summary=summary, skipped=skipped
    )
