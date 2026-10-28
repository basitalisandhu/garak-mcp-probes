#!/usr/bin/env bash
# Run the README quick start against a fresh install in a temporary directory.
#
# Usage: scripts/e2e_quickstart.sh [path/to/garak_mcp_probes-*.whl]
# Without an argument the wheel is built first. The quick start is the offline dry run (fake
# model, fake MCP server, garak's own test probe), so no model, key or outside server is used.
# Installing garak downloads its large dependency set, so this takes a few minutes.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
python="${PYTHON:-python3}"
wheel="${1:-}"
if [ -z "$wheel" ]; then
  rm -rf "$repo/dist"
  "$python" -m pip wheel --quiet --no-deps -w "$repo/dist" "$repo"
  wheel="$(ls "$repo"/dist/garak_mcp_probes-*.whl)"
fi
wheel="$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
"$python" -m venv "$work/.venv"
# shellcheck disable=SC1091
. "$work/.venv/bin/activate"
pip install --quiet --disable-pip-version-check "$wheel"
cd "$work"

step() { printf '\n$ %s\n' "$*"; }

step garak-mcp doctor --dry-run
garak-mcp doctor --dry-run

step garak-mcp run --dry-run --probes test.Test --report-dir garak-mcp-report
garak-mcp run --dry-run --probes test.Test --report-dir garak-mcp-report | tee run.txt
grep -q '^| `test.Test` |' run.txt
test -s garak-mcp-report/summary.json
test -s garak-mcp-report/summary.md
report="$(ls garak-mcp-report/garak-mcp.*.report.jsonl)"
ls garak-mcp-report/garak-mcp.*.report.html >/dev/null

step garak-mcp summarise "$report" -o resummary
garak-mcp summarise "$report" -o resummary
python - garak-mcp-report/summary.json resummary/summary.json <<'PY'
import json, sys
first, second = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
for key in ("probes", "totals", "threshold", "garak_version"):
    assert first[key] == second[key], key
print("summarise matches the run summary")
PY

printf '\nquick start OK (%s)\n' "$(garak-mcp --version)"
