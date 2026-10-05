# Contributing

Thanks for considering a contribution. The project is small on purpose: an agent loop over MCP tools wrapped as a garak generator, detectors over the tool-call trace, a runner that drives garak in code, and a summary writer. The most useful contributions are new trace detectors, transport problems with a minimal server, and keeping the runner in step with garak releases.

## Set up

Requires Python 3.10 or newer. garak pulls in a large dependency set, so use a virtual environment:

```bash
git clone https://github.com/basitalisandhu/garak-mcp-probes
cd garak-mcp-probes
python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

## Before you open a pull request

```bash
make check      # ruff check, ruff format --check, pytest
make dry-run    # doctor and run with the fake model and the fake MCP server
```

CI runs ruff, the tests and the dry run on Python 3.10, 3.11, 3.12 and 3.13, and builds the container image.

## Where things live

- `src/garak_mcp_probes/config.py`: the configuration format and its validation. A new key needs a row in the README's configuration table and a validation test.
- `src/garak_mcp_probes/mcp_tools.py`: connecting to servers with the MCP Python SDK and turning their tools into function tools.
- `src/garak_mcp_probes/model.py`: the OpenAI-compatible chat completions client (standard library only) and the dry run's fake model.
- `src/garak_mcp_probes/agent.py`: the agent loop and the trace it records.
- `src/garak_mcp_probes/trace.py`: the trace format and the pure checks behind each detector.
- `src/garak_mcp_probes/generators.py` and `detectors.py`: the garak plugin classes. Keep logic out of them; put it in `trace.py` with a test.
- `src/garak_mcp_probes/runner.py` and `summary.py`: the garak run and the summary files.
- `src/garak_mcp_probes/fake_server.py`: the harmless MCP server used by the dry run and the tests.

## Tests

Everything runs offline: tests use the fake server (in process, or over stdio), a scripted model defined in `tests/conftest.py`, garak's own `test.Blank` and `test.Test` probes, and a loopback HTTP endpoint for the model client. No test may reach the network.

Do not commit attack text. No probes, payloads, jailbreak strings or evasion techniques belong here; if a test needs a prompt, use plain text. `tests/test_repo.py` fails on instruction-override phrasing, on secret-shaped strings other than the documented example key id, on em dashes and on model names.

## Style

- `ruff` formats and lints; line length 100.
- Runtime dependencies are `garak` and `mcp` only.
- No model names in code, docs or fixtures; say "your model" or use a placeholder.
- Plain language, British spelling, no em dashes, and no numbers that a test or a command in this repository does not produce.

## Reporting security issues

See [SECURITY.md](SECURITY.md).
