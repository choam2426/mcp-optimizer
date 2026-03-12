---
description: Analyze MCP token waste from Claude Code session history
argument-hint: "[--scope project|all]"
disable-model-invocation: true
---

Use the bundled `mcp-audit` skill from this plugin to handle this request.

Pass through the user's intent and any relevant options from `$ARGUMENTS`.

Preserve the explicit command semantics:
- `--scope project` analyzes only the current project
- `--scope all` analyzes all available sessions
- if omitted, default to project scope

Do not duplicate the workflow here. Follow the `mcp-audit` skill exactly.
