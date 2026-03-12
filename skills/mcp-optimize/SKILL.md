---
name: mcp-optimize
description: Use when the user wants to keep MCP but scope it to the current project with a smaller .mcp.json
---

## Use This Skill When

- The user wants to reduce idle MCP cost without converting tools to skills
- The user asks for a project-local `.mcp.json`
- The user wants the lowest-risk, reversible optimization path

## Purpose

Reduce MCP token waste without converting to skills — keep MCP, but scope it to only the servers relevant to this project by generating a minimal project-local `.mcp.json`.

This is the non-conversion alternative: instead of replacing MCP tools with skills, it reduces the number of MCP servers loaded per project.

## Inputs

Infer options from the user's request. Mirror the explicit command `/mcp-optimizer:mcp-optimize`:
- `--dry-run` : show optimization plan without writing files (default behavior unless user confirms)
- `--min-sessions 5` : confidence threshold for analysis

### Step 1: Delegate analysis to a sub-agent

Session analysis can be slow, so **always use the Agent tool** to delegate analysis and report generation. Only the final report should remain in the main context.

Use the following prompt when invoking the Agent tool:

```
Perform an MCP config optimization analysis.

1. Run the following command to get the optimization JSON:
   python3 "${CLAUDE_SKILL_DIR}/scripts/mcp_optimizer.py" --dry-run [--min-sessions <N>]

   (Actual path for ${CLAUDE_SKILL_DIR}: <absolute path to this skill directory>)

2. Format the JSON result into the report template below and return it:

MCP Optimization Plan
======================

Current: {global_servers} global MCP servers loaded every session
Optimized: {project_relevant_servers} servers scoped to this project

| Server | Status | Est. Tokens/Session |
|--------|--------|---------------------|
| {name} | Keep / Remove | {tokens} |

Removal Candidates:
(list each with reason and token savings)

Estimated Savings: ~{tokens_saved} tokens/session ({percent_reduction}% reduction)

Proposed .mcp.json:
(show the project_config content)

(if warning present, show it prominently)

Report rules:
- Use thousand separators for token counts
- Show "Keep" servers in GREEN, "Remove" servers in YELLOW
- If 0 global servers found, output "No global MCP servers to optimize"
- Return only the final report text. Do NOT return the raw JSON.
- Include the full JSON content of the proposed .mcp.json
```

### Step 2: Display report and ask for confirmation

1. Output the report returned by the sub-agent
2. Explain that this will create a project-local `.mcp.json` that overrides global config
3. Emphasize reversibility: "Delete `.mcp.json` to revert to your global config"
4. Ask: "Would you like to write this `.mcp.json`? [Y/n]"

### Step 3: Write config (if confirmed)

If the user confirms:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/mcp_optimizer.py" [--min-sessions <N>]
```

(Without `--dry-run`, this writes the `.mcp.json` file)

Then confirm: "`.mcp.json` written. Restart Claude Code for changes to take effect."

### Step 4: Next steps

After optimization, suggest:
- "Run `/mcp-optimizer:mcp-audit` to verify the improvement in token usage"
- If there are still high-waste servers among the kept ones: "Consider `/mcp-optimizer:mcp-to-skills` to convert remaining high-waste servers to on-demand skills"

## Notes

- **Never modifies `~/.claude.json`** — only creates project-local `.mcp.json`
- Fully reversible: delete `.mcp.json` to revert
- Warns when fewer than 5 sessions are available (low confidence)
- Uses `session_analyzer.py` from the bundled audit workflow via subprocess to avoid code duplication
- If a project `.mcp.json` already exists, it will be overwritten (after user confirmation)
