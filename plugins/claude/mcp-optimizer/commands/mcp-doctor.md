---
description: Health-check configured MCP servers and report broken connections
argument-hint: "[--server <name>] [--fix]"
disable-model-invocation: true
---

Use the bundled `mcp-doctor` skill from this plugin to handle this request.

Pass through the user's intent and any relevant options from `$ARGUMENTS`.

Preserve the explicit command semantics:
- `--server <name>` checks only one configured server
- `--fix` asks for concrete remediation commands in the final report

Do not duplicate the workflow here. Follow the `mcp-doctor` skill exactly.
