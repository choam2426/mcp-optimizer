---
description: Convert MCP tools into on-demand Claude Code skills
argument-hint: "<server-command>"
disable-model-invocation: true
---

Use the bundled `mcp-to-skills` skill from this plugin to handle this request.

Pass through the MCP server command from `$ARGUMENTS`.

Preserve the explicit command semantics:
- `$ARGUMENTS` is the target MCP server command to inspect and convert
- generated artifacts should be local skills under `.claude/skills/`
- default to proxy mode unless the corresponding skill decides native mode is clearly better

Do not duplicate the workflow here. Follow the `mcp-to-skills` skill exactly.
