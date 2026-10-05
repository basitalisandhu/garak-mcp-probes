# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/basitalisandhu/garak-mcp-probes/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/basitalisandhu/garak-mcp-probes/releases/tag/v0.1.0
