# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability") rather than a public issue. Include the version, the garak and mcp versions, the command you ran, and a minimal configuration (with secrets removed) that reproduces the problem.

You will get an acknowledgement within 7 days and a fix or a mitigation plan within 30 days for confirmed issues. Credit is given in the release notes unless you prefer otherwise.

## Scope

garak-mcp-probes starts the stdio servers your configuration names, connects to the Streamable HTTP servers it lists, sends the model endpoint you configure the prompts from the garak probes you select together with those servers' tools, and executes the tool calls the model makes. It writes garak's report and the summary files to the directory you name.

Issues of interest:

- a stdio server receiving environment variables other than the SDK's minimal set and the ones its `env` entry names (model keys in particular);
- the model key, a header value or an `env` value appearing in garak's report, `summary.json`, `summary.md` or the console output;
- a tool call reaching a server or tool other than the one the model's function name maps to;
- plain-HTTP connections to a non-local host without `allow_http`;
- a configuration or report file that makes the tool write outside the report directory, or crash or hang while parsing;
- a detector that scores 0.0 for a trace that shows the behaviour it describes.

Out of scope: what your servers do with the calls they receive and what the model does with garak's prompts; measuring that is the purpose of the tool. Only run it against servers and agents you own or are authorised to test, and run untrusted servers in a container or a sandbox, because `run` and `doctor` execute the stdio commands in your configuration.

The trace records tool arguments in full, so anything the agent passes to a tool ends up in garak's report. Point runs at test data, not at servers holding real secrets.

This repository must not contain probes, injection payloads or jailbreak text. A test (`tests/test_repo.py`) fails on instruction-override phrasing anywhere in the tree; prompts come from the installed garak at run time.
