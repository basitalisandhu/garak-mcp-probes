"""Repository hygiene: no attack text or secrets are committed, docs match the code, house style."""

from __future__ import annotations

import re
from pathlib import Path

from garak_mcp_probes import __version__
from garak_mcp_probes import detectors as dets

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "garak-mcp-report",
}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".json", ".txt", ".cfg", ""}

# Instruction-override phrasing of the kind prompt-injection payloads use. Assembled from parts so
# that this file does not contain the phrases it looks for. garak's probes provide prompts at run
# time; none of that text belongs in this repository.
FORBIDDEN = [
    " ".join(words)
    for words in (
        ("ignore", "previous", "instructions"),
        ("ignore", "all", "previous"),
        ("ignore", "the", "above"),
        ("disregard", "previous"),
        ("disregard", "the", "above"),
        ("forget", "your", "instructions"),
        ("new", "instructions:"),
        ("system", "override"),
        ("developer", "mode", "enabled"),
        ("do", "anything", "now"),
        ("important", "instructions", "from", "me"),
        ("this", "is", "an", "important", "message"),
    )
]

# Secret shapes. The documented example access key id is the only allowed match.
ALLOWED_SECRET = "AKIA" + "IOSFODNN7EXAMPLE"
SECRET_SHAPES = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
]


# Model names and identifiers: none belong in repository files. Stems are stored reversed so that
# this file does not contain the names it looks for; each pairs with the suffix that must follow.
def _w(reversed_word: str) -> str:
    return reversed_word[::-1]


_TIERS = "|".join(_w(x) for x in ("supo", "tennos", "ukiah"))
_MODEL_PATTERNS = (
    (_w("tpg"), r"-?\d"),
    (_w("edualc"), rf"-(?:\d|{_TIERS})"),
    (rf"(?:{_TIERS})", r"[ -]\d"),
    (_w("amall"), r"-?\d"),
    (_w("inimeg"), "-"),
    (_w("lartsim"), "-"),
    (_w("lartxim"), ""),
    (_w("newq"), ""),
    (_w("keespeed"), ""),
    (_w("ammeg"), ""),
)
MODEL_NAMES = re.compile(
    r"\b(?:" + "|".join(stem + suffix for stem, suffix in _MODEL_PATTERNS) + ")", re.IGNORECASE
)


def text_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
        and p.suffix in TEXT_SUFFIXES
    ]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def test_no_instruction_override_phrases_are_committed():
    hits = []
    for path in text_files():
        text = re.sub(r"\s+", " ", read(path).lower())
        hits += [f"{path.relative_to(ROOT)}: {phrase!r}" for phrase in FORBIDDEN if phrase in text]
    assert hits == []


def test_forbidden_list_is_not_empty_and_lowercase():
    assert len(FORBIDDEN) >= 10 and all(p == p.lower() for p in FORBIDDEN)


def test_no_secret_shaped_strings():
    hits = []
    for path in text_files():
        for shape in SECRET_SHAPES:
            hits += [
                f"{path.relative_to(ROOT)}: {m.group(0)[:8]}..."
                for m in shape.finditer(read(path))
                if m.group(0) != ALLOWED_SECRET
            ]
    assert hits == []


def test_no_model_names():
    hits = []
    for path in text_files():
        hits += [
            f"{path.relative_to(ROOT)}: {m.group(0)}" for m in MODEL_NAMES.finditer(read(path))
        ]
    assert hits == []


def test_no_em_dashes_anywhere():
    em_dash = chr(0x2014)
    assert [str(p.relative_to(ROOT)) for p in text_files() if em_dash in read(p)] == []


def test_readme_title_and_disclaimer():
    lines = read(ROOT / "README.md").splitlines()
    assert lines[0] == (
        "# Run garak against your MCP servers: a generator and detectors that show when a probe "
        "makes an agent misuse a tool"
    )
    assert "own or are authorised to test" in read(ROOT / "README.md")


def test_readme_documents_every_detector_and_config_key():
    readme = read(ROOT / "README.md")
    for name in dets.ALL:
        assert f"| `{name}` |" in readme, name
    for key in (
        "model.base_url",
        "model.name",
        "model.api_key_env",
        "agent.max_steps",
        "agent.system_prompt",
        "servers[].command",
        "servers[].url",
        "servers[].headers",
        "policy.deny_tools",
        "policy.allow_tools",
        "policy.canaries",
        "policy.step_budget",
    ):
        assert f"`{key}`" in readme, key


def test_version_is_consistent():
    pyproject = read(ROOT / "pyproject.toml")
    assert re.search(rf'^version = "{re.escape(__version__)}"$', pyproject, re.M)
    assert f"## [{__version__}] - 2026-10-05" in read(ROOT / "CHANGELOG.md")


def test_dependencies_are_garak_and_mcp_only():
    pyproject = read(ROOT / "pyproject.toml")
    block = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.M | re.S).group(1)
    names = re.findall(r'"([A-Za-z0-9_.-]+)', block)
    assert names == ["garak", "mcp"]
    assert '"garak>=0.16.0,<0.18"' in block


def test_good_first_issues_has_six_tasks():
    doc = read(ROOT / "docs" / "good-first-issues.md")
    assert len(re.findall(r"^## \d+\. ", doc, re.M)) == 6


def test_actions_are_pinned_by_sha():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in read(wf).splitlines():
            if "uses:" in line:
                assert re.search(r"@[0-9a-f]{40} # v", line), f"{wf.name}: {line.strip()}"
