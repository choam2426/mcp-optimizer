#!/usr/bin/env python3
"""
session_analyzer.py — MCP 토큰 낭비 분석기

세션 JSONL 파일을 파싱하여 MCP 서버별 도구 사용 빈도,
토큰 소비량, 낭비 추정치를 산출한다.

Usage:
    python3 session_analyzer.py --scope project|all [--project-dir <path>]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ── 빌트인 도구 목록 (Claude Code 네이티브 도구) ──────────────────────────
BUILTIN_TOOLS = {
    # Core tools
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "Agent", "Skill", "WebFetch", "WebSearch",
    # Task / Plan tools
    "AskUserQuestion", "TaskCreate", "TaskUpdate", "TaskGet",
    "TaskList", "TaskOutput", "TaskStop",
    "NotebookEdit", "ToolSearch",
    "ExitPlanMode", "EnterPlanMode",
    "ExitWorktree", "EnterWorktree",
    # Cron tools
    "CronCreate", "CronDelete", "CronList",
    # TodoWrite (legacy)
    "TodoWrite", "TodoRead",
}

# ── 토큰 추정 상수 ────────────────────────────────────────────────────────
# MCP 도구 스키마 1개당 평균 토큰 수 (name + description + inputSchema)
AVG_TOKENS_PER_TOOL_SCHEMA = 120
# 설정에도 세션에도 도구 정보가 없는 서버의 기본 추정 도구 수
DEFAULT_TOOLS_PER_SERVER = 15


def find_claude_home() -> Path:
    """~/.claude 경로를 반환한다."""
    return Path.home() / ".claude"


def find_project_sessions(claude_home: Path, project_dir: str | None, scope: str) -> list[Path]:
    """세션 JSONL 파일 목록을 수집한다."""
    projects_dir = claude_home / "projects"
    if not projects_dir.exists():
        return []

    if scope == "project":
        # 현재 프로젝트 디렉토리에 해당하는 세션 찾기
        # Claude는 프로젝트 경로를 해시/인코딩하여 하위 폴더로 사용
        if project_dir:
            target = Path(project_dir).resolve()
        else:
            target = Path.cwd().resolve()

        # projects/ 하위 폴더명은 프로젝트 경로를 인코딩한 형태
        # 드라이브 문자 포함 경로: A:-01_CodeSpace-mcp-to-skills 같은 형태
        target_str = str(target)
        encoded_candidates = _encode_project_path(target_str)

        sessions = []
        for candidate in encoded_candidates:
            candidate_dir = projects_dir / candidate
            if candidate_dir.exists():
                sessions.extend(candidate_dir.glob("*.jsonl"))

        # 후보를 못 찾으면 모든 프로젝트 폴더에서 경로가 포함된 것 탐색
        if not sessions:
            for d in projects_dir.iterdir():
                if d.is_dir():
                    # 폴더명에 프로젝트 경로 일부가 포함되어 있는지 확인
                    normalized = d.name.replace("-", "/").replace("_", "/").lower()
                    target_parts = target.name.lower()
                    if target_parts in normalized or target_parts in d.name.lower():
                        sessions.extend(d.glob("*.jsonl"))

        return sorted(sessions)

    else:  # scope == "all"
        return sorted(projects_dir.glob("**/*.jsonl"))


def _encode_project_path(path_str: str) -> list[str]:
    """프로젝트 경로를 Claude가 사용하는 폴더명 형태로 변환한다.
    여러 후보를 반환 (정확한 인코딩 방식이 버전마다 다를 수 있으므로).
    """
    # Windows: A:\01_CodeSpace\foo → A--01_CodeSpace-foo
    # Unix: /home/user/foo → -home-user-foo
    candidates = []

    # 방식 1: 구분자를 하이픈으로 치환
    encoded = path_str.replace(":\\", "-").replace("\\", "-").replace("/", "-")
    candidates.append(encoded)

    # 방식 2: 콜론 제거
    encoded2 = path_str.replace(":", "").replace("\\", "-").replace("/", "-")
    candidates.append(encoded2)

    return candidates


def parse_session(filepath: Path) -> dict:
    """단일 세션 JSONL 파일을 파싱한다.

    Returns:
        {
            "tool_calls": {"tool_name": count, ...},
            "input_tokens": int,
            "output_tokens": int,
            "timestamps": [str, ...],
        }
    """
    result = {
        "tool_calls": defaultdict(int),
        "input_tokens": 0,
        "output_tokens": 0,
        "timestamps": [],
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                _process_entry(entry, result)
    except (OSError, IOError):
        pass

    return result


def _process_entry(entry: dict, result: dict):
    """JSONL 엔트리 하나를 처리한다."""
    # 타임스탬프 수집
    ts = entry.get("timestamp")
    if ts:
        result["timestamps"].append(ts)

    # 토큰 사용량 집계 (assistant 메시지의 usage 필드)
    usage = entry.get("usage")
    if usage:
        result["input_tokens"] += usage.get("input_tokens", 0)
        result["output_tokens"] += usage.get("output_tokens", 0)

    # 도구 호출 추출
    # 방식 1: content 배열 내 tool_use 블록
    content = entry.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                result["tool_calls"][tool_name] += 1

    # 방식 2: role=tool_use (일부 포맷)
    if entry.get("type") == "tool_use" or entry.get("role") == "tool_use":
        tool_name = entry.get("name", "unknown")
        result["tool_calls"][tool_name] += 1


def load_mcp_config(claude_home: Path, project_dir: Path | None = None) -> list[dict]:
    """MCP 설정에서 서버 목록을 읽는다.

    탐색 경로:
    - ~/.claude.json (mcpServers 필드)
    - ~/.claude/plugins/external_plugins/*/.mcp.json
    - 프로젝트별 .mcp.json (project_dir 기준, 기본: cwd)
    """
    servers = []

    # 1) ~/.claude.json 의 mcpServers
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

    # 2) external_plugins 내 .mcp.json
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

    # 3) 프로젝트 로컬 .mcp.json (project_dir 기준)
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

    # 중복 서버명 제거 (첫 번째 우선)
    seen = set()
    unique = []
    for s in servers:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)
    return unique


def _detect_server_type(config: dict) -> str:
    """MCP 서버 설정에서 트랜스포트 타입을 판별한다."""
    if "url" in config:
        return "http"
    if "command" in config:
        return "command"
    return "unknown"


def analyze(sessions_data: list[dict], mcp_servers: list[dict]) -> dict:
    """세션 데이터와 MCP 서버 목록을 크로스레퍼런스하여 분석 결과를 생성한다."""

    # ── 전체 도구 호출 집계 ────────────────────────────────────────────
    total_tool_calls = defaultdict(int)
    total_input_tokens = 0
    total_output_tokens = 0
    all_timestamps = []

    for session in sessions_data:
        for tool, count in session["tool_calls"].items():
            total_tool_calls[tool] += count
        total_input_tokens += session["input_tokens"]
        total_output_tokens += session["output_tokens"]
        all_timestamps.extend(session["timestamps"])

    # ── MCP vs 빌트인 분리 ────────────────────────────────────────────
    mcp_tool_calls = {}
    for tool, count in total_tool_calls.items():
        if tool not in BUILTIN_TOOLS:
            mcp_tool_calls[tool] = count

    # ── 날짜 범위 ─────────────────────────────────────────────────────
    date_range = _compute_date_range(all_timestamps)
    num_sessions = len(sessions_data)

    # ── MCP 서버별 분석 ───────────────────────────────────────────────
    server_results = []
    for server in mcp_servers:
        server_name = server["name"]

        # MCP 서버 도구 목록 추정 (설정에서 가져올 수 있으면 사용, 없으면 세션 데이터 기반)
        tools_from_config = server.get("config", {}).get("tools", [])
        if tools_from_config:
            all_tools = set(tools_from_config)
        else:
            # 세션에서 해당 서버 접두사가 붙은 도구 찾기
            all_tools = set()
            for tool in mcp_tool_calls:
                if _tool_belongs_to_server(tool, server_name):
                    all_tools.add(tool)

        # 사용된 도구
        tools_used = set()
        tools_calls_total = 0
        for tool in mcp_tool_calls:
            if _tool_belongs_to_server(tool, server_name) or tool in all_tools:
                tools_used.add(tool)
                tools_calls_total += mcp_tool_calls[tool]
                all_tools.add(tool)

        tools_never_used = sorted(all_tools - tools_used)
        tools_total = len(all_tools)

        # 도구가 0개로 관측된 서버는 기본 추정치 사용
        # (설정에 등록되어 있으므로 매 세션 로드되지만 한 번도 호출되지 않은 경우)
        tools_total_for_estimate = tools_total if tools_total > 0 else DEFAULT_TOOLS_PER_SERVER

        # 토큰 낭비 추정
        # 매 세션마다 서버의 전체 스키마가 로드된다고 가정
        estimated_schema_tokens = tools_total_for_estimate * AVG_TOKENS_PER_TOOL_SCHEMA
        estimated_waste_tokens = estimated_schema_tokens * num_sessions

        # 실제 사용 빈도
        calls_per_session = round(tools_calls_total / max(num_sessions, 1), 2)

        server_results.append({
            "name": server_name,
            "type": server["type"],
            "source": server.get("source", ""),
            "config": server.get("config", {}),
            "estimated_schema_tokens": estimated_schema_tokens,
            "tools_total": tools_total,
            "tools_total_estimated": tools_total == 0,
            "tools_used": sorted(tools_used),
            "tools_never_used": tools_never_used,
            "total_sessions_loaded": num_sessions,
            "total_calls": tools_calls_total,
            "estimated_waste_tokens": estimated_waste_tokens,
            "calls_per_session": calls_per_session,
        })

    # ── 추천 생성 ─────────────────────────────────────────────────────
    recommendations = _generate_recommendations(server_results)

    # ── 낭비 순으로 정렬 ──────────────────────────────────────────────
    server_results.sort(key=lambda s: s["estimated_waste_tokens"], reverse=True)

    # 출력에서 config 제거 (env vars 등 민감 정보 노출 방지)
    output_results = []
    for s in server_results:
        out = {k: v for k, v in s.items() if k != "config"}
        output_results.append(out)

    return {
        "scan_summary": {
            "sessions_analyzed": num_sessions,
            "date_range": date_range,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "mcp_tools_detected": len(mcp_tool_calls),
            "builtin_tools_filtered": len(
                [t for t in total_tool_calls if t in BUILTIN_TOOLS]
            ),
        },
        "mcp_servers": output_results,
        "recommendations": recommendations,
        "unmatched_mcp_tools": sorted(
            set(mcp_tool_calls.keys())
            - {t for s in server_results for t in s["tools_used"]}
            - {t for s in server_results for t in s["tools_never_used"]}
        ),
    }


def _tool_belongs_to_server(tool_name: str, server_name: str) -> bool:
    """도구 이름이 특정 MCP 서버에 속하는지 추정한다.

    MCP 도구 명명 패턴:
    - mcp__servername__toolname  (정확한 MCP 접두사)
    - servername_toolname        (구분자 기반)
    - servername-toolname        (구분자 기반)

    구분자(_,-)를 경계로 매칭하여 'git'이 'github_*'에 오매칭되는 것을 방지.
    """
    # 정확한 MCP 접두사 패턴: mcp__servername__toolname
    mcp_prefix = f"mcp__{server_name}__"
    if tool_name.startswith(mcp_prefix):
        return True

    # 대소문자 무시 MCP 접두사
    mcp_prefix_lower = f"mcp__{server_name.lower()}__"
    if tool_name.lower().startswith(mcp_prefix_lower):
        return True

    # 구분자 기반 매칭: 서버 이름 뒤에 반드시 _ 또는 -가 와야 함
    name_lower = server_name.lower()
    tool_lower = tool_name.lower()
    for sep in ("_", "-"):
        if tool_lower.startswith(name_lower + sep):
            return True

    return False


def _compute_date_range(timestamps: list[str]) -> list[str]:
    """타임스탬프 목록에서 날짜 범위를 반환한다."""
    if not timestamps:
        return ["unknown", "unknown"]

    dates = []
    for ts in timestamps:
        try:
            # ISO 8601 형식 시도
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            dates.append(dt.strftime("%Y-%m-%d"))
        except (ValueError, AttributeError):
            # epoch ms 시도
            try:
                dt = datetime.fromtimestamp(int(ts) / 1000)
                dates.append(dt.strftime("%Y-%m-%d"))
            except (ValueError, TypeError, OSError):
                continue

    if not dates:
        return ["unknown", "unknown"]

    return [min(dates), max(dates)]


def _generate_recommendations(server_results: list[dict]) -> list[dict]:
    """서버 분석 결과에서 변환 추천을 생성한다."""
    recommendations = []

    for server in server_results:
        tools_total = server["tools_total"]
        tools_used_count = len(server["tools_used"])
        waste = server["estimated_waste_tokens"]
        is_estimated = server.get("tools_total_estimated", False)

        # 추정치 사용 시 (미사용 서버): 도구 수를 기본값으로 간주
        effective_tools = tools_total if tools_total > 0 else DEFAULT_TOOLS_PER_SERVER
        usage_ratio = tools_used_count / max(effective_tools, 1)

        # 미사용 서버: 도구 관측 0개지만 낭비는 있으므로 high로 추천
        if is_estimated and waste > 0:
            priority = "high"
            reason = (
                f"Server configured but never used across all analyzed sessions. "
                f"Estimated ~{server['estimated_schema_tokens']:,} tokens/session wasted "
                f"(based on ~{DEFAULT_TOOLS_PER_SERVER} tools default estimate)"
            )
        elif usage_ratio < 0.3 and waste > 50000:
            priority = "high"
            reason = (
                f"{tools_total} tools loaded, only {tools_used_count} used "
                f"({usage_ratio:.0%}), ~{server['estimated_schema_tokens']:,} tokens/session wasted"
            )
        elif usage_ratio < 0.6 and waste > 20000:
            priority = "medium"
            reason = (
                f"{tools_total} tools loaded, {tools_used_count} used "
                f"({usage_ratio:.0%}), moderate token waste"
            )
        elif waste > 10000:
            priority = "low"
            reason = (
                f"{tools_total} tools, {tools_used_count} used "
                f"({usage_ratio:.0%}), minor optimization possible"
            )
        else:
            continue

        recommendations.append({
            "server": server["name"],
            "priority": priority,
            "reason": reason,
            "estimated_savings": waste,
            "tools_to_convert": server["tools_used"] if server["tools_used"] else ["(all)"],
            "tools_to_drop": server["tools_never_used"],
            "convert_command": f"/mcp-optimizer:mcp-to-skills {_guess_server_command(server)}",
        })

    # 우선순위 정렬: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: (priority_order.get(r["priority"], 9), -r["estimated_savings"]))

    return recommendations


def _guess_server_command(server: dict) -> str:
    """서버 설정에서 실행 명령어를 추정한다."""
    config = server.get("config", {})

    # command 타입
    if "command" in config:
        cmd = config["command"]
        args = config.get("args", [])
        if args:
            return f"{cmd} {' '.join(str(a) for a in args)}"
        return cmd

    # url 타입
    if "url" in config:
        return config["url"]

    return f"<{server['name']} server command>"


def main():
    parser = argparse.ArgumentParser(
        description="MCP 토큰 낭비 분석기 — 세션 JSONL을 파싱하여 MCP 서버별 사용 현황을 분석"
    )
    parser.add_argument(
        "--scope",
        choices=["project", "all"],
        default="project",
        help="분석 범위: project(현재 프로젝트) 또는 all(전체)",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="프로젝트 디렉토리 경로 (scope=project일 때 사용, 기본: 현재 디렉토리)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="결과 JSON 파일 경로 (기본: stdout)",
    )
    args = parser.parse_args()

    claude_home = find_claude_home()

    # 1. 세션 파일 수집
    session_files = find_project_sessions(claude_home, args.project_dir, args.scope)
    if not session_files:
        result = {
            "error": None,
            "scan_summary": {
                "sessions_analyzed": 0,
                "date_range": ["unknown", "unknown"],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "mcp_tools_detected": 0,
                "builtin_tools_filtered": 0,
            },
            "mcp_servers": [],
            "recommendations": [],
            "unmatched_mcp_tools": [],
            "message": f"No session files found for scope={args.scope}. "
                       f"Searched in {claude_home / 'projects'}",
        }
        _output(result, args.output)
        return

    # 2. 세션 파싱
    sessions_data = []
    for sf in session_files:
        sessions_data.append(parse_session(sf))

    # 3. MCP 설정 읽기
    mcp_servers = load_mcp_config(claude_home, project_dir=args.project_dir)

    # 4. 분석
    result = analyze(sessions_data, mcp_servers)

    # 5. 출력
    _output(result, args.output)


def _output(data: dict, filepath: str | None):
    """결과를 JSON으로 출력한다."""
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    if filepath:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Results written to {filepath}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(json_str.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
