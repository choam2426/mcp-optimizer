# mcp-optimizer

**Marketplace-ready Claude Code plugin for MCP diagnostics, usage analysis, project scoping, and on-demand skill conversion.**

`mcp-optimizer` helps you answer four separate questions:

1. Are my MCP servers healthy?
2. Which servers are actually wasting tokens?
3. Should I keep MCP but scope it to this project?
4. Should I convert a heavy MCP server into local on-demand skills?

It ships both:

- explicit plugin commands in `commands/`
- matching bundled Skills in `skills/`

Each `/mcp-optimizer:*` command is a thin entrypoint that delegates to the corresponding bundled Skill, so the workflow logic stays in one place.

## Why This Exists

When an MCP server is connected to Claude Code, **its tool schemas are loaded into every conversation** whether you use them or not.

| Scenario | Token cost |
|----------|------------|
| Linear MCP (31 tools) | ~3,000+ tokens/conversation |
| GitHub MCP (20+ tools) | ~2,000+ tokens/conversation |
| 3 MCP servers connected | ~6,500+ tokens/conversation |
| Local skill used only when needed | ~0 idle tokens |

That creates three common problems:

- Large MCP schemas waste tokens even when idle.
- Broken or duplicate servers pollute context and slow down sessions.
- Global MCP configs are often broader than a single project needs.

## Installation

### From GitHub (Recommended)

1. Add this repository as a marketplace.

   ```bash
   /plugin marketplace add choam2426/mcp-optimizer
   ```

2. Install the plugin.

   ```bash
   /plugin install mcp-optimizer
   ```

3. Restart Claude Code if prompted, then verify installation.

   ```bash
   /help
   ```

### From Another Marketplace

If `mcp-optimizer` is included in an existing marketplace:

```bash
/plugin marketplace add your-org/claude-plugins
/plugin install mcp-optimizer@your-org
```

## Components At a Glance

| Command | Category | Use it for | Main inputs | Writes files? |
|---------|----------|------------|-------------|---------------|
| `/mcp-optimizer:mcp-doctor` | Diagnostics | Check server health, duplicates, and credentials | `--server`, `--fix` | No |
| `/mcp-optimizer:mcp-audit` | Analysis | Measure token waste from real session usage | `--scope` | No |
| `/mcp-optimizer:mcp-optimize` | Optimization | Create a smaller project-local `.mcp.json` | `--dry-run`, `--min-sessions` | Yes, after confirmation |
| `/mcp-optimizer:mcp-to-skills` | Conversion | Convert an MCP server into local on-demand skills | `<server-command>` | Yes, creates `.claude/skills/...` |

## Recommended Workflow

1. Start with diagnostics:

   ```bash
   /mcp-optimizer:mcp-doctor
   ```

2. Once servers are healthy, measure actual waste:

   ```bash
   /mcp-optimizer:mcp-audit
   ```

3. Choose the execution path that fits your goal:

   - Keep MCP, but only for this project:

     ```bash
     /mcp-optimizer:mcp-optimize
     ```

   - Convert a heavy server into on-demand local skills:

     ```bash
     /mcp-optimizer:mcp-to-skills npx @linear/mcp-server
     ```

The important distinction is:

- `mcp-doctor` is a **diagnostic command**, not an optimization command.
- `mcp-audit` is an **analysis command** that tells you where waste comes from.
- `mcp-optimize` and `mcp-to-skills` are the **actual optimization paths**.

## Command Reference

### Diagnostics: `/mcp-optimizer:mcp-doctor`

Use `mcp-doctor` when you want to inspect MCP server health before changing anything.

What it does:

- tests configured MCP servers
- measures response time
- finds duplicate tool names across servers
- flags missing or suspicious credentials
- suggests concrete remediation steps

Command form:

```bash
/mcp-optimizer:mcp-doctor [--server <name>] [--fix]
```

Arguments:

| Argument | Meaning | Default |
|----------|---------|---------|
| `--server <name>` | Check only one configured MCP server | Check all configured servers |
| `--fix` | Include concrete remediation commands in the report | Off |

Default behavior:

- Runs as a read-only health check.
- Does not modify your config.
- If `--fix` is present, it suggests commands or follow-up actions, but still does not edit anything automatically.

What to expect:

- health report by server
- response times
- duplicate tool findings
- missing credential warnings
- recommended next step, usually `/mcp-optimizer:mcp-audit` after issues are resolved

Examples:

```bash
/mcp-optimizer:mcp-doctor
/mcp-optimizer:mcp-doctor --server github
/mcp-optimizer:mcp-doctor --fix
```

### Analysis: `/mcp-optimizer:mcp-audit`

Use `mcp-audit` when you want evidence about token waste before deciding what to keep, remove, scope, or convert.

What it does:

- reads Claude Code session history
- estimates per-server schema overhead
- shows which tools were used vs never used
- ranks optimization opportunities
- suggests conversion commands for high-waste servers

Command form:

```bash
/mcp-optimizer:mcp-audit [--scope project|all]
```

Arguments:

| Argument | Meaning | Default |
|----------|---------|---------|
| `--scope project` | Analyze sessions for the current project only | Yes |
| `--scope all` | Analyze sessions across all projects Claude can inspect | No |

Default behavior:

- If no scope is provided, `project` scope is used.
- The command only analyzes available session history. It does not modify config or generated skills.

What to expect:

- ranked token waste by MCP server
- total estimated waste
- unused tool ratios
- recommendations for `/mcp-optimizer:mcp-optimize` and `/mcp-optimizer:mcp-to-skills`

Examples:

```bash
/mcp-optimizer:mcp-audit
/mcp-optimizer:mcp-audit --scope project
/mcp-optimizer:mcp-audit --scope all
```

### Optimization: `/mcp-optimizer:mcp-optimize`

Use `mcp-optimize` when you still want MCP, but not every global server should load in this project.

What it does:

- analyzes which servers look relevant to the current project
- proposes a reduced project-local `.mcp.json`
- estimates token savings
- writes the file only after confirmation

Command form:

```bash
/mcp-optimizer:mcp-optimize [--dry-run] [--min-sessions <N>]
```

Arguments:

| Argument | Meaning | Default |
|----------|---------|---------|
| `--dry-run` | Show the optimization plan without writing `.mcp.json` | Safe planning behavior |
| `--min-sessions <N>` | Require at least `N` sessions before making stronger recommendations | `5` |

Default behavior:

- Treats optimization as a plan-first workflow.
- Shows the proposed `.mcp.json` before writing.
- Writes only the project-local `.mcp.json`.
- Never modifies global Claude config such as `~/.claude.json`.

What to expect:

- keep/remove recommendation per MCP server
- estimated savings per session
- full proposed `.mcp.json`
- confirmation step before writing

Examples:

```bash
/mcp-optimizer:mcp-optimize
/mcp-optimizer:mcp-optimize --dry-run
/mcp-optimizer:mcp-optimize --min-sessions 10
```

### Conversion: `/mcp-optimizer:mcp-to-skills`

Use `mcp-to-skills` when a server has many tools but you only need a few of them on demand.

What it does:

- inspects the target MCP server
- reads tool schemas
- generates one local Claude Code skill per tool
- defaults to proxy mode unless native mode is clearly better

Command form:

```bash
/mcp-optimizer:mcp-to-skills <server-command>
```

Arguments:

| Argument | Meaning | Required |
|----------|---------|----------|
| `<server-command>` | MCP server command to inspect and convert, such as `npx @linear/mcp-server` | Yes |

Default behavior:

- Requires a concrete MCP server command.
- Writes generated local skills under `.claude/skills/`.
- Prefers proxy mode by default.

What to expect:

- detected service name
- generated skill directories
- per-tool descriptions
- example natural-language requests for the generated skills

Examples:

```bash
/mcp-optimizer:mcp-to-skills npx @linear/mcp-server
/mcp-optimizer:mcp-to-skills uvx mcp-server-gitlab
```

## Command Vs Skill

This plugin exposes the same workflows in two forms:

- `commands/`: explicit user-invoked commands such as `/mcp-optimizer:mcp-audit`
- `skills/`: bundled Skills Claude can discover automatically from natural-language requests

In this repository:

- the command is the public explicit entrypoint
- the matching Skill is the canonical workflow implementation
- the command delegates to the matching Skill instead of duplicating instructions

That means you can either:

- invoke the command directly, or
- ask in natural language and let Claude discover the bundled Skill

## Generated Local Skills

`/mcp-optimizer:mcp-to-skills` creates local skills under `.claude/skills/`.

Important points:

- Generated local skills are **not** namespaced as `/mcp-optimizer:*`.
- They are separate local skills for your project or working tree.
- Claude should discover them when the user asks for that workflow in natural language.

Example request after conversion:

```text
List open Linear issues for the Engineering team
```

## Example Scenarios

| Situation | Start with | Why |
|-----------|------------|-----|
| "I think one of my MCP servers is broken" | `/mcp-optimizer:mcp-doctor` | Diagnose health before optimizing |
| "I want to know where token waste is coming from" | `/mcp-optimizer:mcp-audit` | Measure actual usage and waste |
| "This project should not load every global MCP server" | `/mcp-optimizer:mcp-optimize` | Keep MCP but scope it locally |
| "This server is too heavy, but I still need a few tools" | `/mcp-optimizer:mcp-to-skills` | Convert tools into local on-demand skills |

## Requirements And Notes

- Python 3.10+
- Claude Code installed and running
- MCP server environment variables must already be available when using `mcp-doctor` or `mcp-to-skills`
- `mcp-audit` depends on available Claude Code session history
- `mcp-optimize` only writes a project-local `.mcp.json`

## License

[MIT](LICENSE)
