---
name: mcp-doctor
description: Use when the user wants to health-check MCP servers, diagnose broken connections, or find duplicate tools and missing credentials
---

## Use This Skill When

- The user asks why an MCP server is failing, timing out, or not appearing
- The user wants to verify MCP setup before optimizing token usage
- The user mentions duplicate MCP tools or missing credentials

## Purpose

Run a comprehensive health check on configured MCP servers to:
- Test real connections (initialize + tools/list) per server
- Measure response times
- Detect missing environment variables / credentials
- Find duplicate tool names across servers
- Provide actionable fix recommendations

## Inputs

Infer options from the user's request. Mirror the explicit command `/mcp-optimizer:mcp-doctor`:
- `--server <name>` : check a single server (default: check all)
- `--fix` : include actionable fix commands in output

### Step 1: Delegate health check to a sub-agent

MCP server connections can be slow, so **always use the Agent tool** to delegate the check and report generation. Only the final report should remain in the main context.

Use the following prompt when invoking the Agent tool:

```
Perform an MCP server health check.

1. Run the following command to get the health check JSON:
   python3 "${CLAUDE_SKILL_DIR}/scripts/mcp_doctor.py" [--server <name>] [--timeout 15]

   (Actual path for ${CLAUDE_SKILL_DIR}: <absolute path to this skill directory>)

2. Format the JSON result into the report template below and return it:

MCP Server Health Report
=========================

| Server | Source | Status | Tools | Response Time | Issues |
|--------|--------|--------|-------|---------------|--------|
| {name} | {source} | {status} | {tools_count} | {response_time_ms}ms | {issues} |

Summary: {servers_healthy}/{servers_total} servers healthy

Duplicate Tools:
(list each duplicate with the servers that provide it, or "None found")

Recommendations:
(list each recommendation with type, server/tool, and reason)
(if --fix was requested, include specific fix commands for each issue:
  - remove_broken: show how to remove from config
  - fix_credentials: show which env vars to set
  - resolve_duplicate: suggest which server to keep)

Report rules:
- Status indicators: healthy = GREEN, timeout = YELLOW, unreachable/error = RED
- Show response times in ms
- Group recommendations by type (broken, credentials, duplicates)
- If 0 servers found, output "No MCP servers configured"
- Return only the final report text. Do NOT return the raw JSON.
```

### Step 2: Display report

Output the report returned by the sub-agent directly to the user.

### Step 3: Next steps

After the report:
1. If there are unhealthy servers and `--fix` was specified, provide the specific fix commands
2. If all servers are healthy (or after fixes), suggest:
   - "Run `/mcp-optimizer:mcp-audit` to measure token waste and find optimization opportunities"
3. If there are duplicate tools, explain the impact (token waste from redundant schemas)

## Notes

- Per-server timeout is 15 seconds (vs 30s for full inspection) to keep total check time reasonable
- Environment variable checks only flag variables that appear empty, use placeholder values, or reference other env vars
- The doctor never modifies any configuration — it only reads and reports
