# Good first issues

Issues the maintainer intends to open under the `good first issue` label, written out so they can be filed in one sitting. Each is self-contained and has acceptance criteria that `make check` can verify. Read [CONTRIBUTING.md](../CONTRIBUTING.md) first: `ruff` must pass, tests run offline, and no attack text is committed.

## 1. Optionally run the probe's own text detectors

**Context.** `garak-mcp run` scores only the trace. garak probes name a primary or recommended text detector, and some users want both views in one report.

**Acceptance criteria.**

- `run --with-probe-detectors` loads each probe's `primary_detector` (and `extended_detectors` if set) with garak's plugin loader and runs them alongside the trace detectors.
- Detectors that cannot load (for example, ones that need a model download offline) are skipped with a warning listed in `summary.json`.
- A test uses `test.Test`, whose primary detector needs no download.

## 2. `ArgumentMatches`: a regular-expression detector

**Context.** Canary strings catch planted values; teams also want to catch shapes, such as an argument that looks like a URL to a host outside an allow-list.

**Acceptance criteria.**

- `policy.argument_patterns` takes a list of regular expressions, validated at load time with the key path in the error.
- The check lives in `trace.py` as a pure function with tests; the detector class only binds it.
- The README's configuration and detectors tables gain a row each.

## 3. `garak-mcp summarise REPORT`

**Context.** `summary.py` can summarise any report the runner wrote, but there is no command for an existing report.

**Acceptance criteria.**

- `garak-mcp summarise path/to/report.jsonl [--threshold X] [-o DIR]` writes `summary.json` and `summary.md` without running anything.
- Exit code 2 for a missing or non-garak file, with the message from `ReportError`.
- Tests reuse the report builder in `tests/test_summary.py`.

## 4. Per-call detail in `summary.md`

**Context.** A hit count says which probe to look at, not which call. Reviewers want the offending calls listed.

**Acceptance criteria.**

- `summary.md` gains a "Hits" section: for each hit, probe, attempt sequence number, detector, and the tool calls that triggered it (server, tool, argument keys; argument values truncated to 80 characters).
- `--no-hit-detail` turns the section off.
- Tests cover truncation and the off switch.

## 5. Reuse server sessions across prompts (opt-in)

**Context.** Every prompt starts stdio servers afresh, which isolates attempts but is slow for servers with long start-up times.

**Acceptance criteria.**

- `servers[].reuse_session: true` keeps one session open for the whole run, on a background event loop.
- The README's Limits section explains that state can then carry from one attempt to the next.
- A test checks that the fake server starts once for a run of `test.Test` with reuse on (count via `GARAK_MCP_FAKE_LOG` or a fixture).

## 6. JSON Schema for the configuration file

**Context.** Editors can validate YAML against a schema, which catches typos before a run.

**Acceptance criteria.**

- `docs/config.schema.json` describes every key in `config.py`, with the same defaults and limits.
- A test loads both example configurations, validates them against the schema with a small hand-written checker or `jsonschema` if it is already installed (it is a dependency of the MCP SDK), and fails if a key in `config.py` is missing from the schema.
