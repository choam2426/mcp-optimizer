---
name: mcp-audit
description: Use when the user wants to measure MCP token waste, rank high-cost servers, or choose between project scoping and skill conversion
---

## Use This Skill When

- The user asks which MCP servers are wasting tokens
- The user wants evidence before removing or converting servers
- The user asks whether to keep MCP, scope it per project, or convert tools to skills

## Purpose

Analyze the user's Claude Code session history (JSONL) to:
- Identify per-MCP-server tool usage frequency
- Estimate token waste from idle tool schemas
- Recommend skill conversion priorities

## Inputs

Infer scope from the user's request. Mirror the explicit command `/mcp-optimizer:mcp-audit`. Default is `project`.
- `--scope project` : analyze sessions for the current project only
- `--scope all` : analyze sessions across all projects

### Step 1: Delegate analysis to a sub-agent

Session data can be large, so **always use the Agent tool** to delegate analysis and report generation. Only the final report text should remain in the main context.

Use the following prompt when invoking the Agent tool:

```
Perform an MCP token waste analysis.

1. Run the following command to get the analysis JSON:
   python3 "${CLAUDE_SKILL_DIR}/scripts/session_analyzer.py" --scope <scope>

   (Actual path for ${CLAUDE_SKILL_DIR}: <absolute path to this skill directory>)

2. Format the JSON result into the report template below and return it:

MCP Token Waste Analysis Report
================================
Scope: {scope} ({sessions_analyzed} sessions, {date_range})

| MCP Server | Tools | Used | Est. Wasted Tokens | Cost/Session | Priority |
|------------|-------|------|--------------------|-------------|----------|
| {name}     | {total} | {used} ({ratio}%) | ~{waste} | {per_session} | {priority} |

Total estimated waste: ~{total_waste} tokens

Recommended Actions:
(list each item from the recommendations array, ranked by priority)

Unmatched Tools:
(show unmatched_mcp_tools if any exist)

Report rules:
- Priority indicators: HIGH = RED, MEDIUM = YELLOW, LOW = GREEN
- Use thousand separators for token counts (e.g., 126,000)
- Show ratios as percentages
- If 0 sessions found, output "No session data available for analysis"
- Include convert_command from recommendations
- Return only the final report text. Do NOT return the raw JSON.
```

### Step 2: Display report

Output the report returned by the sub-agent directly to the user.

### Step 3: Optimization paths

If the report contains recommended actions, present **two optimization paths**:

**Option A: `/mcp-optimizer:mcp-optimize` — Keep MCP, reduce scope**
- Best when: some servers are useful in this project but not all are needed
- Creates a project-local `.mcp.json` with only relevant servers
- Fully reversible (delete `.mcp.json` to revert)
- Suggest this first for users who want minimal disruption

**Option B: `/mcp-optimizer:mcp-to-skills` — Convert to on-demand skills**
- Best when: a server has many tools but only a few are used
- Converts individual MCP tools into slash-command skills
- Skills load only on invocation (zero idle token cost)
- Suggest this for high-waste servers with low usage ratios

Present the options like this:
1. Explain each recommended server and its estimated savings
2. For each server, suggest which path fits better based on usage patterns:
   - High tool count + low usage ratio → `/mcp-optimizer:mcp-to-skills`
   - Server rarely needed in this project → `/mcp-optimizer:mcp-optimize`
3. Ask: "Which approach would you like? [optimize/convert/both]"
4. If "optimize": invoke `/mcp-optimizer:mcp-optimize`
5. If "convert": invoke `/mcp-optimizer:mcp-to-skills` for the recommended servers
6. If "both": run `/mcp-optimizer:mcp-optimize` first, then `/mcp-optimizer:mcp-to-skills` for remaining high-waste servers

## Notes

- Session JSONL format may vary across Claude Code versions
- Token estimates are approximate (~120 tokens per tool schema)
- Actual savings depend on usage patterns
