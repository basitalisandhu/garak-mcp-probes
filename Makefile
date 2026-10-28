.PHONY: install lint format test check dry-run e2e build clean

PY ?= .venv/bin/python

install:
	python3 -m venv .venv
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

test:
	$(PY) -m pytest -q

check: lint test

# The offline smoke run: fake model, fake MCP server, garak's own test probe.
dry-run:
	$(PY) -m garak_mcp_probes doctor --dry-run
	$(PY) -m garak_mcp_probes run --dry-run --probes test.Test --report-dir garak-mcp-report

# The README quick start against a fresh wheel install in a temporary directory (slow: installs garak).
e2e:
	PYTHON=$(PY) scripts/e2e_quickstart.sh

build:
	rm -rf dist
	$(PY) -m pip wheel --no-deps -w dist .

clean:
	rm -rf dist build .pytest_cache .ruff_cache garak-mcp-report
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
