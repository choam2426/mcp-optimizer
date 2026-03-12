#!/usr/bin/env python3
"""
mcp_optimizer.py — MCP Config Optimization (Non-Conversion)

Analyze session history to determine which MCP servers are relevant
to the current project, then generate a minimal project-scoped .mcp.json.

Usage:
    python3 mcp_optimizer.py [--project-dir <path>] [--dry-run] [--min-sessions 5]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ── MCP config loading (self-contained copy) ─────────────────────────────

def find_claude_home() -> Path:
    return Path.home() / ".claude"


def load_mcp_config(claude_home: Path, project_dir: Path | None = None) -> list[dict]:
    """Load MCP server list from all config sources."""
    servers = []

    # 1) ~/.claude.json
    claude_json = claude_home.parent / ".claude.json"
    if not claude_json.exists():
        claude_json = claude_home / "claude.json"
    if claude_json.exists():
        try:
            with open(claude_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            mcp_servers = data.get("mcpServers", {})
            for name, config in mcp_servers.items():
                servers.append({
                    "name": name,
                    "type": _detect_server_type(config),
                    "config": config,
                    "source": str(claude_json),
                })
        except (json.JSONDecodeError, OSError):
            pass

    # 2) external_plugins
    plugins_dir = claude_home / "plugins" / "external_plugins"
    if plugins_dir.exists():
        for mcp_file in plugins_dir.glob("**/.mcp.json"):
            try:
                with open(mcp_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mcp_servers = data.get("mcpServers", {})
                for name, config in mcp_servers.items():
                    servers.append({
                        "name": name,
                        "type": _detect_server_type(config),
                        "config": config,
                        "source": str(mcp_file),
                    })
            except (json.JSONDecodeError, OSError):
                pass

    # 3) project-local .mcp.json (project_dir 기준)
    base_dir = Path(project_dir).resolve() if project_dir else Path.cwd()
    local_mcp = base_dir / ".mcp.json"
    if local_mcp.exists():
        try:
            with open(local_mcp, "r", encoding="utf-8") as f:
                data = json.load(f)
            mcp_servers = data.get("mcpServers", {})
            for name, config in mcp_servers.items():
                servers.append({
                    "name": name,
                    "type": _detect_server_type(config),
                    "config": config,
                    "source": str(local_mcp),
                })
        except (json.JSONDecodeError, OSError):
            pass

    # Deduplicate (first occurrence wins)
    seen = set()
    unique = []
    for s in servers:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    return unique


def _detect_server_type(config: dict) -> str:
    if "url" in config:
        return "http"
    if "command" in config:
        return "command"
    return "unknown"


# Token estimate constants
AVG_TOKENS_PER_TOOL_SCHEMA = 120
DEFAULT_TOOLS_PER_SERVER = 15


def run_session_analysis(project_dir: str | None, scope: str = "project") -> dict | None:
    """Invoke session_analyzer.py as subprocess and parse JSON output.

    This avoids duplicating all session parsing logic.
    """
    # Locate session_analyzer.py relative to this script
    script_dir = Path(__file__).resolve().parent
    analyzer_path = script_dir / ".." / ".." / "mcp-audit" / "scripts" / "session_analyzer.py"
    analyzer_path = analyzer_path.resolve()

    if not analyzer_path.exists():
        return None

    cmd = [sys.executable, str(analyzer_path), "--scope", scope]
    if project_dir:
        cmd.extend(["--project-dir", project_dir])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 and not result.stdout.strip():
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def optimize(
    session_data: dict | None,
    mcp_servers: list[dict],
    min_sessions: int = 5,
    project_dir: str | None = None,
) -> dict:
    """Analyze server relevance and generate optimization plan."""

    # Extract global-only servers (not from project .mcp.json)
    base_dir = Path(project_dir).resolve() if project_dir else Path.cwd()
    project_mcp = str(base_dir / ".mcp.json")
    global_servers = [s for s in mcp_servers if s["source"] != project_mcp]

    if not global_servers:
        return {
            "analysis": {
                "global_servers": 0,
                "project_relevant_servers": 0,
                "tokens_saved_per_session": 0,
            },
            "project_config": {"mcpServers": {}},
            "removal_candidates": [],
            "estimated_savings": {"tokens_per_session": 0, "percent_reduction": 0},
            "message": "No global MCP servers found to optimize",
        }

    # If no session data, we can't determine relevance
    sessions_analyzed = 0
    server_usage = {}

    if session_data and "mcp_servers" in session_data:
        sessions_analyzed = session_data.get("scan_summary", {}).get("sessions_analyzed", 0)

        for server_info in session_data["mcp_servers"]:
            server_usage[server_info["name"]] = {
                "total_calls": server_info.get("total_calls", 0),
                "tools_used": server_info.get("tools_used", []),
                "tools_total": server_info.get("tools_total", 0),
                "estimated_schema_tokens": server_info.get("estimated_schema_tokens", 0),
            }

    low_confidence = sessions_analyzed < min_sessions

    # Score each server's relevance
    relevant_servers = {}
    removal_candidates = []
    total_global_tokens = 0

    for server in global_servers:
        name = server["name"]
        usage = server_usage.get(name, {})
        total_calls = usage.get("total_calls", 0)
        tools_used = usage.get("tools_used", [])
        tools_total = usage.get("tools_total", 0)
        # 도구 수가 0이면 기본 추정치 사용 — 미사용 서버도 낭비 산출
        tools_for_estimate = tools_total if tools_total > 0 else DEFAULT_TOOLS_PER_SERVER
        schema_tokens = usage.get("estimated_schema_tokens", tools_for_estimate * AVG_TOKENS_PER_TOOL_SCHEMA)

        total_global_tokens += schema_tokens

        if total_calls > 0:
            # Server is used in this project — include in project config
            relevant_servers[name] = server["config"]
        else:
            # Server has 0 calls — candidate for removal from project scope
            removal_candidates.append({
                "server": name,
                "reason": f"0 calls across {sessions_analyzed} sessions",
                "savings": schema_tokens,
            })

    # Calculate savings
    relevant_tokens = sum(
        server_usage.get(name, {}).get("estimated_schema_tokens",
            _estimate_tokens(config))
        for name, config in relevant_servers.items()
    )
    tokens_saved = total_global_tokens - relevant_tokens
    percent_reduction = round(
        (tokens_saved / max(total_global_tokens, 1)) * 100
    )

    result = {
        "analysis": {
            "global_servers": len(global_servers),
            "project_relevant_servers": len(relevant_servers),
            "tokens_saved_per_session": tokens_saved,
        },
        "project_config": {
            "mcpServers": relevant_servers,
        },
        "removal_candidates": sorted(removal_candidates, key=lambda r: -r["savings"]),
        "estimated_savings": {
            "tokens_per_session": tokens_saved,
            "percent_reduction": percent_reduction,
        },
    }

    if low_confidence:
        result["warning"] = (
            f"Only {sessions_analyzed} sessions analyzed (minimum recommended: {min_sessions}). "
            f"Results may not accurately reflect actual usage patterns."
        )

    return result


def _estimate_tokens(config: dict) -> int:
    """Rough token estimate when we don't have session data for a server."""
    # Assume a moderate number of tools if we can't determine
    return 15 * AVG_TOKENS_PER_TOOL_SCHEMA


def write_project_config(project_config: dict, project_dir: str | None) -> str:
    """Write .mcp.json to the project directory."""
    target_dir = Path(project_dir) if project_dir else Path.cwd()
    mcp_path = target_dir / ".mcp.json"
    with open(mcp_path, "w", encoding="utf-8") as f:
        json.dump(project_config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return str(mcp_path)


def main():
    parser = argparse.ArgumentParser(
        description="MCP Config Optimizer - scope MCP servers to the current project"
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory path (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show optimization plan without writing .mcp.json",
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=5,
        help="Minimum sessions for confident analysis (default: 5)",
    )
    args = parser.parse_args()

    claude_home = find_claude_home()
    mcp_servers = load_mcp_config(claude_home, project_dir=args.project_dir)

    # Run session analysis via subprocess
    session_data = run_session_analysis(args.project_dir, scope="project")

    # Generate optimization plan
    result = optimize(session_data, mcp_servers, min_sessions=args.min_sessions,
                      project_dir=args.project_dir)

    if not args.dry_run and result["project_config"]["mcpServers"]:
        written_path = write_project_config(result["project_config"], args.project_dir)
        result["written_to"] = written_path

    result["dry_run"] = args.dry_run
    sys.stdout.buffer.write(json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
