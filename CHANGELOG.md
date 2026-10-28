# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-28

### Added

- `garak-mcp summarise REPORT [--threshold X] [-o DIR] [--fail-on-hit]` (also `summarize`) writes `summary.json` and `summary.md` for a report from an earlier run without running anything. A missing or non-garak file exits 2 with the reason (#3).
- README "Troubleshooting" table with the real messages and their fixes.
- `scripts/e2e_quickstart.sh` runs the README quick start (dry run, then `summarise` on its report) against a freshly installed wheel in a temporary directory; CI runs it.
- Seeded, time-limited fuzz tests over the configuration reader, the report reader, the chat completions reply parser and the trace checks, with scaling tests.

### Fixed

- A configuration file that is not UTF-8, JSON or YAML nested deeper than Python's recursion limit, a YAML key that is not a string (`1: x`) or a string `command` with an unclosed quote stopped `run` and `doctor` with a Python traceback; each is now a configuration error (exit 2) naming the file. A UTF-8 byte order mark is accepted.
- The report reader stopped with a traceback on a non-UTF-8 or too deeply nested report, and on attempts whose `outputs`, `detector_results` or scores had the wrong type; fields of the wrong type now count as empty and the rest is a `ReportError`.
- A model reply whose `tool_calls` was not a list, or whose function name was not a string, raised `TypeError` instead of `ModelError`; a reply nested too deeply raised `RecursionError`.
- Tool-call arguments nested too deeply to parse are recorded as "arguments are not a JSON object" instead of failing the attempt.
- `ArgumentContains` walked arguments recursively and copied each level: nested arguments 2,000 levels deep took 0.92 s per 20 calls (0.013 s at 200 levels) and deeper ones crashed. The walk is now iterative and linear (0.02 s at 2,000 levels).

## [0.2.0] - 2026-10-20

### Added

- `garak-mcp run --with-probe-detectors` also runs each probe's own garak text detectors (its `primary_detector` and `extended_detectors`) next to the trace detectors. A detector that cannot load is skipped, logged once and listed under `detector_warnings` in `summary.json` and `summary.md` (#1).

### Fixed

- The OpenAI-compatible client failed the whole run with a `TypeError` when a reply's content parts included one with `"text": null` or no text (an image part, for example); such parts are now skipped.
- The fake server's `read_note` raised `ValueError` for an unknown note, which the MCP SDK hides from the client as a generic failure and logs with a traceback; it now raises the SDK's `ToolError`, so the model sees `no note named '...'`.

### Changed

- README first screen: who the project is for, a three-line quick start that starts with a virtual environment, and a real dry-run output sample.

## [0.1.0] - 2026-10-05

### Added

- `garak_mcp_probes.generators.MCPAgentGenerator`: a garak generator that runs each prompt through an agent loop over the tools of one or more MCP servers (stdio or Streamable HTTP, official MCP Python SDK) with an OpenAI-compatible chat completions endpoint, a step limit, fresh server sessions per prompt, and a structured tool-call trace in each output's notes.
- Detectors over the trace: `ToolCalled`, `ArgumentContains`, `UnexpectedTool`, `StepBudgetExceeded` and `ToolError`, reported in garak as `garak_mcp.<Name>` and described in the report's plugin cache so garak's HTML digest renders them.
- `garak-mcp run`: drives garak in code with the generator and detectors, writes garak's JSONL report and HTML digest, `summary.json` and `summary.md`; `--fail-on-hit` for CI gates.
- `garak-mcp doctor` (servers connect and list tools, the model answers) and `garak-mcp list-probes` (garak's probe list).
- `--dry-run`: a built-in fake model that echoes and a built-in fake MCP server with harmless tools, so everything runs without network or keys.
- YAML and JSON configuration with key-path errors, `${VAR}` for headers and server environment, and no API keys in files.
- CI on Python 3.10 to 3.13 with a dry-run smoke test; container image `ghcr.io/basitalisandhu/garak-mcp-probes` published on version tags with an SPDX SBOM, a build provenance attestation and a keyless cosign signature.

Tested against garak 0.17.0 and mcp 2.3.0.

[Unreleased]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/basitalisandhu/garak-mcp-probes/releases/tag/v0.1.0
