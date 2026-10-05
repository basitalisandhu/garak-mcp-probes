"""Run garak against an agent that uses your MCP servers, and detect tool misuse from the trace.

The package adds a garak generator (:mod:`garak_mcp_probes.generators`) that wraps a small agent
loop over MCP tools, and detectors (:mod:`garak_mcp_probes.detectors`) that score the structured
tool-call trace the generator attaches to every output. It contains no probes and no attack text;
prompts come from the probes of the installed garak.
"""

__version__ = "0.1.0"
