---
description: Generate a project-local .mcp.json with only relevant MCP servers
argument-hint: "[--dry-run] [--min-sessions <N>]"
disable-model-invocation: true
---

Use the bundled `mcp-optimize` skill from this plugin to handle this request.

Pass through the user's intent and any relevant options from `$ARGUMENTS`.

Preserve the explicit command semantics:
- `--dry-run` shows the plan without writing files
- `--min-sessions <N>` sets the confidence threshold
- default to a dry run unless the user is explicitly confirming a write

Do not duplicate the workflow here. Follow the `mcp-optimize` skill exactly.
