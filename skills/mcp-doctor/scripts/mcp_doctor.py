#!/usr/bin/env python3
"""
mcp_doctor.py — MCP Health Check & Config Diagnosis

Enumerate configured MCP servers, attempt real connections,
check environment variables, detect duplicate tools, and output
a structured JSON health report.

Usage:
    python3 mcp_doctor.py [--timeout 15] [--server <name>]
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


# ── JSON-RPC helpers ──────────────────────────────────────────────────────

_request_id = 0


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


def jsonrpc_request(method: str, params: dict | None = None) -> dict:
    msg = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def jsonrpc_notification(method: str, params: dict | None = None) -> dict:
    msg = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


# ── MCP config loading ───────────────────────────────────────────────────

def find_claude_home() -> Path:
    return Path.home() / ".claude"


def load_mcp_config(claude_home: Path) -> list[dict]:
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

    # 3) project-local .mcp.json
    local_mcp = Path.cwd() / ".mcp.json"
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


# ── stdio transport (simplified for health check) ────────────────────────

def send_message(proc: subprocess.Popen, message: dict):
    """MCP stdio transport: Content-Length framing."""
    body = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    proc.stdin.write(header)
    proc.stdin.write(body)
    proc.stdin.flush()


def _read_exact(stream, length: int) -> bytes:
    """스트림에서 정확히 지정한 바이트 수만큼 읽는다."""
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(proc: subprocess.Popen, timeout: float = 15) -> dict | None:
    result = {"value": None, "error": None}

    def _read():
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip(b"\r\n")
                if not line:
                    continue

                raw_message = None
                if b":" in line and not line.startswith((b"{", b"[")):
                    headers = {}
                    header_line = line
                    while True:
                        name, sep, value = header_line.partition(b":")
                        if sep:
                            headers[name.strip().lower()] = value.strip()
                        next_line = proc.stdout.readline()
                        if not next_line or next_line in (b"\n", b"\r\n"):
                            break
                        header_line = next_line.rstrip(b"\r\n")

                    length_value = headers.get(b"content-length")
                    if not length_value:
                        continue

                    try:
                        length = int(length_value)
                    except ValueError:
                        continue

                    body = _read_exact(proc.stdout, length)
                    if len(body) != length:
                        result["error"] = f"Unexpected EOF reading MCP message body ({len(body)}/{length} bytes)"
                        return

                    try:
                        raw_message = body.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                else:
                    try:
                        raw_message = line.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                try:
                    msg = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue

                if "id" not in msg:
                    continue

                result["value"] = msg
                return
        except Exception as e:
            result["error"] = str(e)

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout=timeout)

    if reader.is_alive():
        return None

    if result["error"]:
        return None

    return result["value"]


# ── Health check per server ──────────────────────────────────────────────

def check_server_stdio(name: str, config: dict, timeout: float) -> dict:
    """Health-check a stdio MCP server: initialize + tools/list."""
    cmd = config.get("command", "")
    args = config.get("args", [])
    argv = [str(cmd), *(str(a) for a in args)] if cmd else []

    if not argv:
        return {
            "name": name,
            "status": "error",
            "error": "No command configured",
            "tools_count": 0,
            "tools": [],
            "response_time_ms": 0,
            "missing_env_vars": _check_env_vars(config),
        }

    # Prepare environment
    env = os.environ.copy()
    env_config = config.get("env", {})
    missing_env = _check_env_vars(config)
    env.update(env_config)

    start_time = time.time()

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
    except OSError as e:
        return {
            "name": name,
            "status": "error",
            "error": f"Failed to start: {e}",
            "tools_count": 0,
            "tools": [],
            "response_time_ms": 0,
            "missing_env_vars": missing_env,
        }

    try:
        # initialize
        init_req = jsonrpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-doctor", "version": "0.1.0"},
        })
        send_message(proc, init_req)
        init_resp = read_message(proc, timeout=timeout)

        if not init_resp:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "name": name,
                "status": "timeout",
                "error": f"Timeout after {timeout}s waiting for initialize",
                "tools_count": 0,
                "tools": [],
                "response_time_ms": elapsed,
                "missing_env_vars": missing_env,
            }

        if "error" in init_resp and "result" not in init_resp:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "name": name,
                "status": "error",
                "error": f"Initialize error: {init_resp.get('error')}",
                "tools_count": 0,
                "tools": [],
                "response_time_ms": elapsed,
                "missing_env_vars": missing_env,
            }

        # initialized notification
        send_message(proc, jsonrpc_notification("notifications/initialized"))

        # tools/list
        tools_req = jsonrpc_request("tools/list", {})
        send_message(proc, tools_req)
        tools_resp = read_message(proc, timeout=timeout)

        elapsed = int((time.time() - start_time) * 1000)

        if not tools_resp:
            return {
                "name": name,
                "status": "timeout",
                "error": f"Timeout after {timeout}s waiting for tools/list",
                "tools_count": 0,
                "tools": [],
                "response_time_ms": elapsed,
                "missing_env_vars": missing_env,
            }

        if "error" in tools_resp and "result" not in tools_resp:
            return {
                "name": name,
                "status": "error",
                "error": f"tools/list error: {tools_resp.get('error')}",
                "tools_count": 0,
                "tools": [],
                "response_time_ms": elapsed,
                "missing_env_vars": missing_env,
            }

        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = [t.get("name", "unknown") for t in tools]

        return {
            "name": name,
            "status": "healthy",
            "error": None,
            "tools_count": len(tools),
            "tools": tool_names,
            "response_time_ms": elapsed,
            "missing_env_vars": missing_env,
        }

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass


def check_server_http(name: str, config: dict, timeout: float) -> dict:
    """Health-check an HTTP MCP server."""
    import urllib.request
    import urllib.error

    url = config.get("url", "")
    if not url:
        return {
            "name": name,
            "status": "error",
            "error": "No URL configured",
            "tools_count": 0,
            "tools": [],
            "response_time_ms": 0,
            "missing_env_vars": _check_env_vars(config),
        }

    headers = {"Content-Type": "application/json"}
    missing_env = _check_env_vars(config)
    start_time = time.time()

    def _post(data: dict) -> dict:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    # initialize
    init_req = jsonrpc_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-doctor", "version": "0.1.0"},
    })
    init_resp = _post(init_req)

    if "error" in init_resp and "result" not in init_resp:
        elapsed = int((time.time() - start_time) * 1000)
        return {
            "name": name,
            "status": "unreachable",
            "error": str(init_resp["error"]),
            "tools_count": 0,
            "tools": [],
            "response_time_ms": elapsed,
            "missing_env_vars": missing_env,
        }

    # initialized notification
    try:
        _post(jsonrpc_notification("notifications/initialized"))
    except Exception:
        pass

    # tools/list
    tools_req = jsonrpc_request("tools/list", {})
    tools_resp = _post(tools_req)

    elapsed = int((time.time() - start_time) * 1000)

    if "error" in tools_resp and "result" not in tools_resp:
        return {
            "name": name,
            "status": "error",
            "error": f"tools/list error: {tools_resp['error']}",
            "tools_count": 0,
            "tools": [],
            "response_time_ms": elapsed,
            "missing_env_vars": missing_env,
        }

    tools = tools_resp.get("result", {}).get("tools", [])
    tool_names = [t.get("name", "unknown") for t in tools]

    return {
        "name": name,
        "status": "healthy",
        "error": None,
        "tools_count": len(tools),
        "tools": tool_names,
        "response_time_ms": elapsed,
        "missing_env_vars": missing_env,
    }


def _check_env_vars(config: dict) -> list[str]:
    """Check if environment variables declared in config are actually set."""
    missing = []
    env_config = config.get("env", {})
    for key, value in env_config.items():
        # If the value references an env var pattern or is empty, check if it's set
        if not value or value.startswith("${") or value.startswith("$"):
            if not os.environ.get(key):
                missing.append(key)
        # If value is a placeholder like <YOUR_KEY>, flag it
        elif value.startswith("<") and value.endswith(">"):
            missing.append(key)
    return missing


# ── Duplicate detection ──────────────────────────────────────────────────

def find_duplicate_tools(server_results: list[dict]) -> list[dict]:
    """Find tool names that appear across multiple servers."""
    tool_to_servers = {}
    for server in server_results:
        for tool in server.get("tools", []):
            if tool not in tool_to_servers:
                tool_to_servers[tool] = []
            tool_to_servers[tool].append(server["name"])

    duplicates = []
    for tool, servers in tool_to_servers.items():
        if len(servers) > 1:
            duplicates.append({"tool_name": tool, "servers": servers})

    return sorted(duplicates, key=lambda d: d["tool_name"])


# ── Recommendations ──────────────────────────────────────────────────────

def generate_recommendations(server_results: list[dict], duplicates: list[dict]) -> list[dict]:
    """Generate actionable recommendations from health check results."""
    recommendations = []

    for server in server_results:
        # Broken servers
        if server["status"] in ("unreachable", "timeout", "error"):
            recommendations.append({
                "type": "remove_broken",
                "server": server["name"],
                "reason": f"Server is {server['status']}: {server.get('error', 'unknown error')}",
            })

        # Missing env vars
        if server.get("missing_env_vars"):
            recommendations.append({
                "type": "fix_credentials",
                "server": server["name"],
                "missing": server["missing_env_vars"],
                "reason": f"Missing environment variables: {', '.join(server['missing_env_vars'])}",
            })

    # Duplicate tools
    for dup in duplicates:
        recommendations.append({
            "type": "resolve_duplicate",
            "tool": dup["tool_name"],
            "servers": dup["servers"],
            "reason": f"Tool '{dup['tool_name']}' is provided by {len(dup['servers'])} servers: {', '.join(dup['servers'])}",
        })

    return recommendations


# ── Main ─────────────────────────────────────────────────────────────────

def run_doctor(timeout: float = 15, target_server: str | None = None) -> dict:
    """Run the full health check and return structured JSON report."""
    claude_home = find_claude_home()
    all_servers = load_mcp_config(claude_home)

    if not all_servers:
        return {
            "check_summary": {
                "servers_total": 0,
                "servers_healthy": 0,
                "servers_unhealthy": 0,
                "duplicate_tools_found": 0,
                "missing_env_vars": 0,
            },
            "servers": [],
            "duplicate_tools": [],
            "recommendations": [],
            "message": "No MCP servers configured. Searched ~/.claude.json, plugins, and .mcp.json",
        }

    # Filter to single server if requested
    if target_server:
        all_servers = [s for s in all_servers if s["name"] == target_server]
        if not all_servers:
            return {
                "check_summary": {
                    "servers_total": 0,
                    "servers_healthy": 0,
                    "servers_unhealthy": 0,
                    "duplicate_tools_found": 0,
                    "missing_env_vars": 0,
                },
                "servers": [],
                "duplicate_tools": [],
                "recommendations": [],
                "message": f"Server '{target_server}' not found in MCP configuration",
            }

    # Check each server
    server_results = []
    for server in all_servers:
        server_type = server["type"]
        name = server["name"]
        config = server["config"]
        source = server["source"]

        if server_type == "http":
            result = check_server_http(name, config, timeout)
        elif server_type == "command":
            result = check_server_stdio(name, config, timeout)
        else:
            result = {
                "name": name,
                "status": "error",
                "error": f"Unknown server type: {server_type}",
                "tools_count": 0,
                "tools": [],
                "response_time_ms": 0,
                "missing_env_vars": _check_env_vars(config),
            }

        result["source"] = source
        server_results.append(result)

    # Detect duplicates
    duplicates = find_duplicate_tools(server_results)

    # Generate recommendations
    recommendations = generate_recommendations(server_results, duplicates)

    # Summary
    healthy = sum(1 for s in server_results if s["status"] == "healthy")
    unhealthy = len(server_results) - healthy
    total_missing_env = sum(len(s.get("missing_env_vars", [])) for s in server_results)

    return {
        "check_summary": {
            "servers_total": len(server_results),
            "servers_healthy": healthy,
            "servers_unhealthy": unhealthy,
            "duplicate_tools_found": len(duplicates),
            "missing_env_vars": total_missing_env,
        },
        "servers": server_results,
        "duplicate_tools": duplicates,
        "recommendations": recommendations,
    }


def main():
    parser = argparse.ArgumentParser(
        description="MCP Health Check - diagnose broken servers, duplicates, and missing credentials"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="Per-server timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Check a single server by name (default: check all)",
    )
    args = parser.parse_args()

    result = run_doctor(timeout=args.timeout, target_server=args.server)
    sys.stdout.buffer.write(json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

    # Exit with error code if any servers are unhealthy
    if result["check_summary"]["servers_unhealthy"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
