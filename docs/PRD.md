# mcp-optimizer — Product Requirements Document

> A **comprehensive MCP optimization toolkit** for the Claude Code Marketplace that diagnoses token waste, health-checks servers, optimizes configs, and converts MCP tools into Claude Code skills.

## 1. Problem

When an MCP server is connected, **all tool schemas are loaded into the context on every conversation**.

| Scenario | Token cost |
|----------|-----------|
| Linear MCP (31 tools) | ~3,000+ tokens/conversation |
| GitHub MCP (20+ tools) | ~2,000+ tokens/conversation |
| 3 MCP servers connected | ~6,500+ tokens/conversation |
| Skill (loaded only on invocation) | ~0 tokens (idle) |

Additional issues:

- MCP server processes must be **running at all times**
- Per-tool customization is difficult (schemas are locked to the server)

## 2. Solution

The plugin ships both explicit marketplace commands in `commands/` and matching automatic Agent Skills in `skills/`. Each command is only a thin entrypoint that delegates to the matching skill, so the actual workflow logic lives in one place. Four workflows work together as a comprehensive optimization toolkit:

### 2.1 `/mcp-optimizer:mcp-audit` — Diagnostic command + skill

Analyzes session JSONL files to diagnose per-server token waste and recommend conversion priorities.

```
/mcp-optimizer:mcp-audit [--scope project|all]

  1. Discover MCP configuration
     Collect server list from ~/.claude.json, plugins/, .mcp.json
      |
  2. Analyze session JSONL
     session_analyzer.py -> tool call frequency, token usage aggregation
      |
  3. Claude synthesizes results
     Estimated token cost per server vs actual usage -> waste ranking
      |
  4. Output report + conversion suggestions
     Automatically trigger /mcp-optimizer:mcp-to-skills upon user confirmation
```

### 2.2 `/mcp-optimizer:mcp-to-skills` — Conversion command + skill

When the user invokes `/mcp-optimizer:mcp-to-skills`, Claude reads the MCP server's tool schemas and **converts each tool into an individual skill**.

```
/mcp-optimizer:mcp-to-skills npx @linear/mcp-server

  1. Extract tool schemas via mcp_inspect.py
      |
  2. Claude analyzes purpose and parameters of each tool
      |
  3. Generate SKILL.md per tool:
     .claude/skills/linear-list-issues/SKILL.md
     .claude/skills/linear-create-issue/SKILL.md
     ...
      |
  4. Claude discovers them automatically when the user asks for those workflows
```

### 2.3 `/mcp-optimizer:mcp-doctor` — Health check command + skill

Checks all configured MCP servers for connectivity, duplicate tools, and missing credentials. Fix broken things before measuring waste.

```
/mcp-optimizer:mcp-doctor [--server <name>] [--fix]

  1. Enumerate configured MCP servers
     Read from ~/.claude.json, plugins/, .mcp.json
      |
  2. Test real connections
     mcp_doctor.py -> initialize + tools/list per server
      |
  3. Check environment variables
     Detect missing/placeholder credentials
      |
  4. Detect duplicate tools
     Find tool names shared across multiple servers
      |
  5. Output health report + recommendations
     Actionable fixes for broken servers, missing creds, duplicates
```

### 2.4 `/mcp-optimizer:mcp-optimize` — Config optimization command + skill

Reduces token waste without conversion — scopes MCP config to only relevant servers per project.

```
/mcp-optimizer:mcp-optimize [--dry-run] [--min-sessions 5]

  1. Run session analysis (project scope)
     Invoke session_analyzer.py to determine server usage
      |
  2. Score server relevance
     Servers with 0 calls -> removal candidates
      |
  3. Generate minimal .mcp.json
     Only relevant servers, copied verbatim from global config
      |
  4. Write project-local config (after user confirmation)
     Never modifies ~/.claude.json — fully reversible
```

### Decision Tree (recommended flow)

```
/mcp-optimizer:mcp-doctor  →  fix broken servers, duplicates, missing creds
      ↓
/mcp-optimizer:mcp-audit   →  measure token waste
      ↓
      ├── /mcp-optimizer:mcp-optimize     (keep MCP, reduce scope via project .mcp.json)
      └── /mcp-optimizer:mcp-to-skills    (replace MCP with on-demand skills)
```

### Core Principles

1. **Skills that create skills** — Claude understands the schema and writes SKILL.md directly
2. **MCP on-demand** — Does not remove MCP entirely; uses one-shot calls when needed (preserving versatility)
3. **Claude Code marketplace-native** — Distributed as a plugin with thin `commands/` entrypoints and canonical workflow logic in `skills/`

## 3. Competitive Landscape (as of 2026-03)

| Project | Working? | MCP dependency | Distribution |
|---------|----------|----------------|-------------|
| GBSOSS/mcp-to-skill-converter (130+) | **No** — mock data, executor bugs | Retained (subprocess) | CLI tool |
| Myst4ke/mcp-to-skills-converter | **No** — only 1 of 4 stages implemented | Retained (planned) | CLI tool |
| Smithery.ai | Yes (commercial SaaS) | Cloud MCP proxy | SaaS |
| **mcp-optimizer (this project)** | **Yes** | **on-demand (one-shot)** | **Claude Code Marketplace** |

## 4. Architecture

### 4.1 Project Structure

```
.claude-plugin/
  plugin.json               <- Marketplace manifest
commands/
  mcp-doctor.md             <- Explicit slash command: /mcp-optimizer:mcp-doctor
  mcp-audit.md              <- Explicit slash command: /mcp-optimizer:mcp-audit
  mcp-optimize.md           <- Explicit slash command: /mcp-optimizer:mcp-optimize
  mcp-to-skills.md          <- Explicit slash command: /mcp-optimizer:mcp-to-skills
skills/
  mcp-doctor/
    SKILL.md                <- Automatic health-check skill discovered by Claude
    scripts/
      mcp_doctor.py         <- MCP server connectivity & config diagnosis
  mcp-audit/
    SKILL.md                <- Automatic audit skill discovered by Claude
    scripts/
      session_analyzer.py   <- Session JSONL parsing + MCP token waste analysis
  mcp-optimize/
    SKILL.md                <- Automatic optimization skill discovered by Claude
    scripts/
      mcp_optimizer.py      <- Project-scoped MCP config generation
  mcp-to-skills/
    SKILL.md                <- Automatic conversion skill discovered by Claude
    scripts/
      mcp_inspect.py        <- Extract tool schemas from MCP server
      mcp_call.py           <- MCP one-shot call (for proxy mode)
docs/
  PRD.md                    <- Product Requirements Document
README.md                   <- English README
README.ko.md                <- Korean README
LICENSE                     <- MIT License
```

### 4.2 Plugin Command + Skill Pairing

```yaml
---
name: mcp-to-skills
description: Use when the user wants to convert expensive MCP tools into on-demand Claude Code skills
---
```

The explicit command lives at `/mcp-optimizer:mcp-to-skills`, while the matching Skill allows Claude to discover the same workflow automatically. Together they instruct Claude to:

1. Extract tool schemas from the MCP server via `mcp_inspect.py`
2. Analyze the purpose and parameters of each tool
3. Choose execution mode (proxy/native)
4. Generate `.claude/skills/{service}-{tool-name}/SKILL.md`

### 4.3 Helper Scripts

Claude cannot use the MCP protocol directly, so helper scripts are required.

**mcp_inspect.py** — Schema extraction (used once during conversion)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/mcp_inspect.py \
  --server "npx @linear/mcp-server"
```

```json
{
  "server": "linear",
  "tools": [
    {
      "name": "list_issues",
      "description": "List issues with filters",
      "inputSchema": {
        "type": "object",
        "properties": {
          "teamName": { "type": "string", "description": "Team name to filter" },
          "status": { "type": "string" }
        },
        "required": []
      }
    }
  ]
}
```

**mcp_call.py** — One-shot call (used by generated skills on every invocation)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/mcp_call.py \
  --server "npx @linear/mcp-server" \
  --tool "list_issues" \
  --args '{"teamName": "Engineering"}'
```

Sequence: start MCP server -> initialize -> tools/call -> output result -> shut down server

Implementation constraints:

- Python stdlib only
- Default timeout: 30 seconds
- Supports stdio + HTTP transports

### 4.4 Session Analysis Script (`session_analyzer.py`)

**Input**: `--scope project|all`, `--project-dir <path>` (optional)
**Output**: JSON (stdout)

Core logic:

1. **Collect session files**: scan for JSONL files under `~/.claude/projects/`
2. **Filter built-in tools**: fixed list including `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`, `Agent`, `Skill`, etc.
3. **Parse JSONL**: `type="assistant"` -> aggregate tokens from usage field; extract tool names from `tool_use` blocks in content arrays
4. **Cross-reference MCP config**: read server list from `mcpServers` in `~/.claude.json` and `.mcp.json` files under `plugins/external_plugins/`
5. **Estimate token waste**: ~120 tokens per tool schema x number of tools x number of sessions

Output JSON structure:

```json
{
  "scan_summary": {
    "sessions_analyzed": 42,
    "date_range": ["2026-01-15", "2026-03-12"],
    "total_input_tokens": 1250000
  },
  "mcp_servers": [
    {
      "name": "github",
      "type": "http",
      "estimated_schema_tokens": 2500,
      "tools_total": 20,
      "tools_used": ["search_repos", "create_issue"],
      "tools_never_used": ["list_gists"],
      "total_sessions_loaded": 42,
      "total_calls": 15,
      "estimated_waste_tokens": 95000,
      "calls_per_session": 0.36
    }
  ],
  "recommendations": [
    {
      "server": "linear",
      "priority": "high",
      "reason": "31 tools loaded, only 2 used, ~3000 tokens/session wasted",
      "estimated_savings": 120000,
      "convert_command": "/mcp-optimizer:mcp-to-skills npx @linear/mcp-server"
    }
  ]
}
```

Implementation constraints: Python stdlib only, 60-second timeout

## 5. Execution Modes

### 5.1 Proxy Mode — Universal, default

One-shot MCP server call via `mcp_call.py`. **Works with any MCP server immediately.**

Example generated SKILL.md:

```markdown
---
name: linear-list-issues
description: List Linear issues with filters
---

Infer conditions such as team name and status from the user's request to query Linear issues.

## Execution

\`\`\`bash
python3 {resolved absolute path to plugin mcp_call.py} \
  --server "npx @linear/mcp-server" \
  --tool "list_issues" \
  --args '{"teamName": "<team>", "status": "<status>"}'
\`\`\`

## Output

Extract issue list from response and format as table:
Issue ID, Title, Status, Assignee, Priority
```

### 5.2 Native Mode — Optional optimization

Claude generates skills that call APIs directly. No MCP runtime needed.

Selection criteria:

| Condition | Mode |
|-----------|------|
| Default / unknown API | **Proxy** |
| Well-known service (Linear, GitHub, etc.) | **Native** |
| MCP server accesses local resources | **Proxy only** |

## 6. Generated SKILL.md Format

```yaml
---
name: {service}-{tool-name}
description: {MCP tool description}
---
```

- Receives user intent via natural-language requests
- Generated at `.claude/skills/{service}-{tool-name}/SKILL.md`
- Triggered automatically when the user asks for the workflow in natural language

## 7. Distribution

### Claude Code Marketplace

- Register **all four commands and matching skills** as a single marketplace package
- Users install -> `/mcp-optimizer:mcp-doctor` to health-check -> `/mcp-optimizer:mcp-audit` to diagnose -> `/mcp-optimizer:mcp-optimize` or `/mcp-optimizer:mcp-to-skills` to optimize
- Popular MCP server conversions can also be registered as **pre-built skill packs**

## 8. Milestones

### v0.1 — MVP

- [ ] `mcp_inspect.py` — stdio transport
- [ ] `mcp_call.py` — one-shot call
- [ ] `SKILL.md` — `mcp-to-skills` conversion skill
- [ ] `session_analyzer.py` — session JSONL parsing + MCP token waste analysis
- [ ] `SKILL.md` — `mcp-audit` diagnostic skill
- [ ] `/mcp-optimizer:mcp-audit` -> `/mcp-optimizer:mcp-to-skills` chained flow verification
- [ ] Linear MCP -> skill conversion end-to-end verification

### v0.2 — Optimization Toolkit

- [ ] `mcp_doctor.py` — MCP server health check & config diagnosis
- [ ] `SKILL.md` — `mcp-doctor` health check skill
- [ ] `mcp_optimizer.py` — project-scoped MCP config optimization
- [ ] `SKILL.md` — `mcp-optimize` config optimization skill
- [ ] `/mcp-optimizer:mcp-audit` updated with two-path routing (optimize vs convert)
- [ ] Decision tree flow: doctor → audit → optimize/convert
- [ ] HTTP transport verification
- [ ] Generation quality tuning

### v0.3 — Refinement & Launch

- [ ] Native mode support
- [ ] GitHub, Slack MCP additional verification
- [ ] Claude Code Marketplace registration
- [ ] Pre-built skill packs (Linear, GitHub, Slack)
- [ ] README, usage guide

## 9. Open Questions

1. **mcp_call.py universality** — Can one-shot calls work reliably across all MCP servers?
2. **Generation quality** — How do we ensure consistent quality of the SKILL.md files the meta skill generates?
3. **Credential forwarding** — How does mcp_call.py pass through API keys when the MCP server expects them as environment variables?
4. **License** — MIT vs Apache 2.0
