#!/usr/bin/env python3
"""
mcp_inspect.py — MCP 서버에서 도구 스키마를 추출한다.

MCP 서버를 시작하고 initialize → tools/list 프로토콜을 수행한 뒤,
도구 목록과 inputSchema를 JSON으로 출력하고 서버를 종료한다.

Usage:
    python3 mcp_inspect.py --server "npx @linear/mcp-server"
    python3 mcp_inspect.py --server "node server.js" --timeout 60
    python3 mcp_inspect.py --url "http://localhost:3000/mcp"
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading


# ── JSON-RPC helpers ──────────────────────────────────────────────────────

_request_id = 0


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


def jsonrpc_request(method: str, params: dict | None = None) -> dict:
    """JSON-RPC 2.0 요청 메시지를 생성한다."""
    msg = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def jsonrpc_notification(method: str, params: dict | None = None) -> dict:
    """JSON-RPC 2.0 알림 메시지를 생성한다 (id 없음)."""
    msg = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


# ── stdio transport ───────────────────────────────────────────────────────

def send_message(proc: subprocess.Popen, message: dict):
    """MCP 서버에 JSON-RPC 메시지를 전송한다 (stdio transport, Content-Length framing)."""
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


def read_message(proc: subprocess.Popen, timeout: float = 30) -> dict | None:
    """MCP 서버에서 JSON-RPC 응답을 읽는다.

    notification은 건너뛰고 id가 있는 response만 반환한다.
    """
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

                # notification은 건너뛰기 (id 없음)
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
        return None  # 타임아웃

    if result["error"]:
        print(f"Read error: {result['error']}", file=sys.stderr)
        return None

    return result["value"]


def inspect_stdio(server_cmd: str, timeout: float = 30, env_vars: dict | None = None) -> dict:
    """stdio 트랜스포트로 MCP 서버를 inspect한다.

    Args:
        server_cmd: MCP 서버 실행 명령어 (예: "npx @linear/mcp-server")
        timeout: 타임아웃 (초)
        env_vars: 추가 환경변수

    Returns:
        {"server": str, "tools": [...], "server_info": {...}}
    """
    # 환경변수 준비
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    # 서버 시작
    try:
        proc = subprocess.Popen(
            server_cmd,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
    except OSError as e:
        return {"error": f"Failed to start server: {e}", "server": server_cmd, "tools": []}

    try:
        # ① initialize
        init_req = jsonrpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "mcp-optimizer-inspector",
                "version": "0.1.0",
            },
        })
        send_message(proc, init_req)
        init_resp = read_message(proc, timeout=timeout)

        if not init_resp:
            return {
                "error": "Timeout waiting for initialize response",
                "server": server_cmd,
                "tools": [],
            }

        if "error" in init_resp and "result" not in init_resp:
            return {
                "error": f"Initialize error: {init_resp['error']}",
                "server": server_cmd,
                "tools": [],
            }

        server_info = init_resp.get("result", {}).get("serverInfo", {})

        # ② initialized notification
        send_message(proc, jsonrpc_notification("notifications/initialized"))

        # ③ tools/list
        tools_req = jsonrpc_request("tools/list", {})
        send_message(proc, tools_req)
        tools_resp = read_message(proc, timeout=timeout)

        if not tools_resp:
            return {
                "error": "Timeout waiting for tools/list response",
                "server": server_cmd,
                "server_info": server_info,
                "tools": [],
            }

        if "error" in tools_resp and "result" not in tools_resp:
            return {
                "error": f"tools/list error: {tools_resp['error']}",
                "server": server_cmd,
                "server_info": server_info,
                "tools": [],
            }

        tools = tools_resp.get("result", {}).get("tools", [])

        # 서버 이름 추출
        server_name = server_info.get("name", _extract_server_name(server_cmd))

        return {
            "server": server_name,
            "server_command": server_cmd,
            "server_info": server_info,
            "tools": tools,
            "tools_count": len(tools),
        }

    finally:
        # 서버 종료
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


# ── HTTP transport ────────────────────────────────────────────────────────

def inspect_http(url: str, timeout: float = 30) -> dict:
    """HTTP 트랜스포트로 MCP 서버를 inspect한다.

    Note: stdlib의 urllib만 사용.
    """
    import urllib.request
    import urllib.error

    headers = {"Content-Type": "application/json"}

    def _post(data: dict) -> dict:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {"error": str(e)}

    # ① initialize
    init_req = jsonrpc_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "mcp-optimizer-inspector",
            "version": "0.1.0",
        },
    })
    init_resp = _post(init_req)

    if "error" in init_resp and "result" not in init_resp:
        return {"error": f"Initialize error: {init_resp['error']}", "server": url, "tools": []}

    server_info = init_resp.get("result", {}).get("serverInfo", {})

    # ② initialized notification (fire and forget)
    try:
        _post(jsonrpc_notification("notifications/initialized"))
    except Exception:
        pass

    # ③ tools/list
    tools_req = jsonrpc_request("tools/list", {})
    tools_resp = _post(tools_req)

    if "error" in tools_resp and "result" not in tools_resp:
        return {
            "error": f"tools/list error: {tools_resp['error']}",
            "server": url,
            "server_info": server_info,
            "tools": [],
        }

    tools = tools_resp.get("result", {}).get("tools", [])
    server_name = server_info.get("name", url)

    return {
        "server": server_name,
        "server_command": url,
        "server_info": server_info,
        "tools": tools,
        "tools_count": len(tools),
    }


# ── Utilities ─────────────────────────────────────────────────────────────

_LAUNCHER_TOKENS = {
    "npx", "uvx", "pnpm", "pnpx", "bunx",
    "node", "python", "python3",
}


def _normalize_service_name(token: str) -> str:
    scope = ""
    is_scoped_package = token.startswith("@") and "/" in token
    is_path_like = not is_scoped_package and (token.startswith((".", "/", "..")) or "/" in token)

    if is_scoped_package:
        scope, token = token.split("/", 1)
        scope = scope[1:]
    elif is_path_like:
        token = os.path.basename(token)

    if "." in token:
        token = token.rsplit(".", 1)[0]

    if not is_path_like:
        for suffix in ("-mcp-server", "-mcp", "-server"):
            if token.endswith(suffix):
                token = token[: -len(suffix)]
                break

        for prefix in ("mcp-server-", "server-", "mcp-"):
            if token.startswith(prefix):
                token = token[len(prefix):]
                break

    if token and token not in ("mcp", "server"):
        return token
    if scope:
        return scope
    return token


def _extract_server_name(server_cmd: str) -> str:
    """서버 명령어에서 서비스 이름을 추출한다.

    예: "npx @linear/mcp-server" → "linear"
         "npx @modelcontextprotocol/server-github" → "github"
         "npx @anthropic/mcp-server-slack" → "slack"
         "uvx mcp-server-gitlab" → "gitlab"
         "node ./my-server.js" → "my-server"
    """
    try:
        parts = shlex.split(server_cmd)
    except ValueError:
        parts = server_cmd.split()

    candidates = []
    for part in parts:
        if not part or part in _LAUNCHER_TOKENS or part.startswith("-"):
            continue
        if "=" in part and not part.startswith(("@", ".", "/", "..")):
            key, _, _ = part.partition("=")
            if key and key[0].isalpha() and key.replace("_", "").isalnum():
                continue
        candidates.append(part)

    for part in candidates:
        name = _normalize_service_name(part)
        if name and name not in ("mcp", "server"):
            return name

    if candidates:
        fallback = os.path.basename(candidates[-1])
        if "." in fallback:
            fallback = fallback.rsplit(".", 1)[0]
        return fallback

    return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="MCP 서버에서 도구 스키마를 추출한다."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--server",
        help="MCP 서버 실행 명령어 (stdio transport)",
    )
    group.add_argument(
        "--url",
        help="MCP 서버 URL (HTTP transport)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="타임아웃 (초, 기본: 30)",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="추가 환경변수 (KEY=VALUE 형식, 여러 번 사용 가능)",
    )
    args = parser.parse_args()

    # 환경변수 파싱
    env_vars = {}
    for kv in args.env:
        if "=" in kv:
            k, v = kv.split("=", 1)
            env_vars[k] = v

    # 실행
    if args.server:
        result = inspect_stdio(args.server, timeout=args.timeout, env_vars=env_vars or None)
    else:
        result = inspect_http(args.url, timeout=args.timeout)

    sys.stdout.buffer.write(json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

    # 에러가 있으면 비정상 종료
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
