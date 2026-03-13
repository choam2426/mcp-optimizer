#!/usr/bin/env python3
"""
mcp_call.py — MCP 서버에 one-shot 도구 호출을 수행한다.

서버 시작 → initialize → tools/call → 결과 출력 → 서버 종료

Usage:
    python3 mcp_call.py --server "npx @linear/mcp-server" \
        --tool "list_issues" \
        --args '{"teamName": "Engineering"}'

    python3 mcp_call.py --url "http://localhost:3000/mcp" \
        --tool "search_repos" \
        --args '{"query": "claude"}'
"""

import argparse
import json
import os
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


# ── stdio transport ───────────────────────────────────────────────────────

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


def read_message(proc: subprocess.Popen, timeout: float = 30) -> dict | None:
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
        print(f"Read error: {result['error']}", file=sys.stderr)
        return None

    return result["value"]


def call_stdio(server_cmd: str, tool_name: str, tool_args: dict,
               timeout: float = 30, env_vars: dict | None = None) -> dict:
    """stdio 트랜스포트로 MCP 도구를 호출한다."""
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

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
        return {"error": f"Failed to start server: {e}"}

    try:
        # ① initialize
        send_message(proc, jsonrpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "mcp-optimizer-caller",
                "version": "0.1.0",
            },
        }))
        init_resp = read_message(proc, timeout=timeout)

        if not init_resp:
            return {"error": "Timeout waiting for initialize response"}

        if "error" in init_resp and "result" not in init_resp:
            return {"error": f"Initialize error: {init_resp['error']}"}

        # ② initialized notification
        send_message(proc, jsonrpc_notification("notifications/initialized"))

        # ③ tools/call
        send_message(proc, jsonrpc_request("tools/call", {
            "name": tool_name,
            "arguments": tool_args,
        }))
        call_resp = read_message(proc, timeout=timeout)

        if not call_resp:
            return {"error": f"Timeout waiting for tools/call response (tool: {tool_name})"}

        if "error" in call_resp and "result" not in call_resp:
            return {"error": f"tools/call error: {call_resp['error']}"}

        return call_resp.get("result", {})

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


# ── HTTP transport ────────────────────────────────────────────────────────

def call_http(url: str, tool_name: str, tool_args: dict, timeout: float = 30) -> dict:
    """HTTP 트랜스포트로 MCP 도구를 호출한다."""
    import urllib.request
    import urllib.error

    headers = {"Content-Type": "application/json"}

    def _post(data: dict) -> dict:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        # ① initialize
        init_resp = _post(jsonrpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "mcp-optimizer-caller",
                "version": "0.1.0",
            },
        }))

        if "error" in init_resp and "result" not in init_resp:
            return {"error": f"Initialize error: {init_resp['error']}"}

        # ② initialized notification
        try:
            _post(jsonrpc_notification("notifications/initialized"))
        except Exception:
            pass

        # ③ tools/call
        call_resp = _post(jsonrpc_request("tools/call", {
            "name": tool_name,
            "arguments": tool_args,
        }))

        if "error" in call_resp and "result" not in call_resp:
            return {"error": f"tools/call error: {call_resp['error']}"}

        return call_resp.get("result", {})

    except Exception as e:
        return {"error": str(e)}


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MCP 서버에 one-shot 도구 호출을 수행한다."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--server", help="MCP 서버 실행 명령어 (stdio)")
    group.add_argument("--url", help="MCP 서버 URL (HTTP)")

    parser.add_argument("--tool", required=True, help="호출할 도구 이름")
    parser.add_argument("--args", default="{}", help="도구 인자 (JSON 문자열)")
    parser.add_argument("--timeout", type=float, default=30, help="타임아웃 (초)")
    parser.add_argument(
        "--env", action="append", default=[],
        help="추가 환경변수 (KEY=VALUE, 여러 번 사용 가능)",
    )

    args = parser.parse_args()

    # 인자 파싱
    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid --args JSON: {e}"}))
        sys.exit(1)

    # 환경변수
    env_vars = {}
    for kv in args.env:
        if "=" in kv:
            k, v = kv.split("=", 1)
            env_vars[k] = v

    # 호출
    if args.server:
        result = call_stdio(
            args.server, args.tool, tool_args,
            timeout=args.timeout, env_vars=env_vars or None,
        )
    else:
        result = call_http(args.url, args.tool, tool_args, timeout=args.timeout)

    sys.stdout.buffer.write(json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
