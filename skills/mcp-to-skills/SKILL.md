---
name: mcp-to-skills
description: Use when the user wants to convert expensive MCP tools into on-demand Claude Code skills
---

## Use This Skill When

- The user has a large MCP server but only uses a few tools
- The user wants zero idle token cost until a tool is invoked
- The user asks to convert an MCP server command into local Claude Code skills

## Purpose

Read tool schemas from an MCP server and convert each tool into an independent Claude Code skill.
Converted skills are written under `.claude/skills/{service}-{tool-name}/SKILL.md` and are discovered automatically by Claude when the user asks for that workflow.

## Inputs

Infer the MCP server command from the user's request. The explicit command equivalent is `/mcp-optimizer:mcp-to-skills <server-command>`.

Example: `/mcp-optimizer:mcp-to-skills npx @linear/mcp-server`

### Step 1: Extract MCP server schemas

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/mcp_inspect.py" --server "<resolved server command from the user's request>"
```

This returns the full tool list and each tool's inputSchema.

### Step 2: Analyze tools and determine execution mode

For each tool:

1. **Purpose analysis**: determine the tool's role from its description and inputSchema
2. **Execution mode selection**:
   - **Proxy mode** (default): one-shot MCP server call via `mcp_call.py`
   - **Native mode**: for well-known APIs (GitHub, Linear, etc.), generate skills that call the API directly

   | Condition | Mode |
   |-----------|------|
   | Default / unknown API | Proxy |
   | Well-known service + official REST API | Native |
   | Local resource access (files, DB, etc.) | Proxy only |

### Step 3: Generate SKILL.md files

Generate a `.claude/skills/{service}-{tool-name}/SKILL.md` file for each tool.

**Proxy mode SKILL.md template:**

```markdown
---
name: {service}-{tool-name}
description: {tool description}
---

Infer the required parameters from the user's request.

## Parameters

{parameter list and descriptions extracted from inputSchema}

## Execution

\`\`\`bash
python3 "{resolved absolute path to plugin mcp_call.py}" \
  --server "{server command}" \
  --tool "{tool_name}" \
  --args '{parameter JSON}'
\`\`\`

## Output

Extract key data from the response and present in a user-friendly format.
{tool-specific output formatting guidance}
```

**Generation rules:**
- Extract service name from MCP server name (e.g., `@linear/mcp-server` -> `linear`)
- Convert tool names from snake_case to kebab-case (e.g., `list_issues` -> `list-issues`)
- Keep descriptions in English
- Design skills to accept natural-language requests without relying on slash-command variables
- Resolve the plugin helper path during generation and write the concrete absolute path to `mcp_call.py` into each generated local skill
- Do not leave `${CLAUDE_SKILL_DIR}` or `${CLAUDE_PLUGIN_ROOT}` placeholders inside generated local skills

### Step 4: Report results

Display the generated skill list to the user:

```
{N} skills generated successfully!

| Skill Directory | Description | Mode |
|-----------------|-------------|------|
| .claude/skills/{service}-{tool} | {description} | Proxy/Native |

Example natural-language requests:
  - List open issues for the Engineering team in Linear
  - Create a GitHub issue titled "Broken deploy"
```

## Notes

- Running `mcp_inspect.py` starts the MCP server, so required environment variables (API keys, etc.) must be set
- Timeouts: 30s for schema extraction, 30s for tool calls
- Verify that the mcp_call.py path in generated skills is correct
