"""``python -m garak_mcp_probes`` runs the ``garak-mcp`` command line."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
