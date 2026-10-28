# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-10-28

### Added

- `garak-mcp summarise REPORT [-o DIR] [--threshold X] [--fail-on-hit]` (also spelt `summarize`) writes `summary.json` and `summary.md` for an existing garak report without running anything; a missing, unreadable or non-garak file exits 2 with a one-line message (#3).
- README: a Troubleshooting section, and a CI job that follows the quick start exactly in a fresh virtual environment.
- Fuzz and property tests (Hypothesis) for the configuration loader, the report reader, model replies, tool-call arguments and command-line values, and scaling tests that fail on quadratic work.

### Fixed

- A tool call whose arguments were nested a few thousand levels deep crashed the run with `RecursionError` inside the `ArgumentContains` detector; the argument walk is now iterative and linear in the size of the arguments (it was quadratic in the nesting depth).
- Configuration files that were not UTF-8, JSON or YAML nested too deeply, a `command` string with an unclosed quote, a malformed URL such as `http://[::1`, or YAML keys of mixed types (`1:` next to `name:`) ended in a traceback; each is now a `ConfigError` naming the file and key.
- `NaN` and infinite numbers, and a zero or negative `servers[].timeout`, were accepted; they are now rejected with the key path.
- A model reply whose `tool_calls` was not a list, or whose function name was not a string, raised `TypeError` mid-run; it is now a model error recorded in the trace (`stopped: model_error`).
- Tool-call arguments or model responses nested too deeply to decode are recorded as an error instead of raising `RecursionError`.
- The report reader no longer raises on non-UTF-8 files, a directory passed as the report, outputs that are not a list, or detector scores that are not numbers (they are skipped).
- `--threshold` accepts only a number from 0 to 1; `nan` and values outside that range exit 2.
- The duplicate server name check was quadratic in the number of servers.

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

[Unreleased]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/basitalisandhu/garak-mcp-probes/releases/tag/v0.1.0
