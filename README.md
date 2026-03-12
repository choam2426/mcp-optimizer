# mcp-optimizer

**Marketplace-ready Claude Code plugin for MCP optimization — health-check servers, measure token waste, scope configs per project, and convert heavy tools into on-demand skills.**

## Why This Exists

When an MCP server is connected to Claude Code, **its tool schemas are loaded into every conversation** whether you use them or not.

| Scenario | Token cost |
|----------|-----------|
| Linear MCP (31 tools) | ~3,000+ tokens/conversation |
| GitHub MCP (20+ tools) | ~2,000+ tokens/conversation |
| 3 MCP servers connected | ~6,500+ tokens/conversation |
| Skill (loaded only on invocation) | ~0 tokens (idle) |

That creates three practical problems:

- Idle token waste from large MCP schemas
- Broken or duplicate servers polluting context and slowing sessions
- Global MCP configs that are too broad for a single project

`mcp-optimizer` packages the full optimization workflow into one Claude Code plugin. Per the official plugin model, it ships both:

- explicit slash commands in `commands/`
- matching Agent Skills in `skills/` for automatic discovery

Each command is a thin entrypoint that delegates to the matching skill, so the workflow logic lives in one place.

Examples below use the fully qualified marketplace-safe command form `/mcp-optimizer:<command>`.

## Included Commands

- `/mcp-optimizer:mcp-doctor`
  Tests configured MCP servers, checks response times, finds duplicate tools, and flags missing credentials.
- `/mcp-optimizer:mcp-audit`
  Analyzes Claude Code session history to estimate token waste and rank optimization opportunities.
- `/mcp-optimizer:mcp-optimize`
  Generates a project-local `.mcp.json` with only the MCP servers relevant to the current project.
- `/mcp-optimizer:mcp-to-skills`
  Converts MCP tools into on-demand Claude Code skills so they load only when invoked.

Claude can also discover the bundled Skills automatically when a user asks for the same workflows in natural language.

## Install From a Marketplace

1. Add a marketplace that includes `mcp-optimizer`.
   ```bash
   /plugin marketplace add your-org/claude-plugins
   ```
2. Install the plugin from that marketplace.
   ```bash
   /plugin install mcp-optimizer@your-org
   ```
3. Restart Claude Code if prompted, then run `/help` and confirm the commands appear.

For local development, follow the same flow with a local test marketplace such as `./dev-marketplace`.

## Recommended Flow

1. Check server health first:
   ```bash
   /mcp-optimizer:mcp-doctor
   ```
2. Measure waste:
   ```bash
   /mcp-optimizer:mcp-audit
   ```
3. Choose an optimization path:
   - Keep MCP but reduce scope:
     ```bash
     /mcp-optimizer:mcp-optimize
     ```
   - Replace heavy MCP usage with on-demand skills:
     ```bash
     /mcp-optimizer:mcp-to-skills npx @linear/mcp-server
     ```

## Which Path To Use?

- Use `/mcp-optimizer:mcp-optimize` when the server is useful, but not for every project.
- Use `/mcp-optimizer:mcp-to-skills` when a server has many tools but you only use a few of them.
- Use both when you want a smaller project MCP config and on-demand skills for the remaining high-cost tools.

## Example

```bash
/mcp-optimizer:mcp-doctor
/mcp-optimizer:mcp-audit
/mcp-optimizer:mcp-optimize
/mcp-optimizer:mcp-to-skills npx @linear/mcp-server
List open Linear issues for the Engineering team
```

## How It Fits Together

```text
/mcp-optimizer:mcp-doctor -> fix broken servers and duplicate tools
/mcp-optimizer:mcp-audit -> measure token waste and identify priorities
    |
    +-> /mcp-optimizer:mcp-optimize    keep MCP, reduce project scope
    |
    +-> /mcp-optimizer:mcp-to-skills   convert selected tools to on-demand skills
```

## Requirements

- Python 3.10+
- Claude Code CLI

## License

[MIT](LICENSE)
