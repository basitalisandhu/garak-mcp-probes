"""Print the README's quick start (its first ``bash`` code block) as a shell script.

The only change is the install line: the ``git+https`` URL becomes this checkout, so CI tests the
code under review rather than main. Everything else runs exactly as written. Used by the
``readme-quickstart`` CI job and by ``tests/test_repo.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_URL = "git+https://github.com/basitalisandhu/garak-mcp-probes"


def quickstart(readme: str) -> list[str]:
    match = re.search(r"^```bash\n(.*?)^```", readme, re.M | re.S)
    if not match:
        raise SystemExit("README.md has no bash code block")
    return [line for line in match.group(1).splitlines() if line.strip()]


def as_script(lines: list[str], checkout: Path = ROOT) -> str:
    out = []
    for line in lines:
        if INSTALL_URL in line:
            line = re.sub(r'"garak-mcp-probes @ git\+https://[^"]+"', f'"{checkout}"', line)
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> int:
    sys.stdout.write(as_script(quickstart((ROOT / "README.md").read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
