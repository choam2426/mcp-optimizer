# mcp-optimizer

**Claude Code Marketplace 배포를 전제로 정리한 MCP 최적화 플러그인 — 서버 상태 점검, 토큰 낭비 분석, 프로젝트별 설정 축소, 온디맨드 스킬 변환까지 한 번에 제공합니다.**

## 왜 필요한가

MCP 서버가 Claude Code에 연결되면, **사용 여부와 관계없이 도구 스키마가 매 대화마다 컨텍스트에 로드됩니다**.

| 시나리오 | 토큰 비용 |
|----------|-----------|
| Linear MCP (31개 도구) | 대화당 ~3,000+ 토큰 |
| GitHub MCP (20개+ 도구) | 대화당 ~2,000+ 토큰 |
| MCP 서버 3개 연결 | 대화당 ~6,500+ 토큰 |
| 스킬 (호출 시에만 로드) | ~0 토큰 (유휴 시) |

이 때문에 보통 세 가지 문제가 생깁니다.

- 큰 MCP 스키마로 인한 유휴 토큰 낭비
- 고장 난 서버나 중복 도구가 컨텍스트를 오염시키는 문제
- 하나의 프로젝트에 비해 너무 넓은 글로벌 MCP 설정

`mcp-optimizer`는 이 전체 흐름을 하나의 Claude Code 플러그인으로 묶습니다. 공식 플러그인 구조에 맞춰:

- `commands/`에는 사용자가 직접 호출하는 slash command를 넣고
- `skills/`에는 Claude가 자동으로 발견해 쓸 수 있는 Agent Skill을 넣습니다

각 command는 대응하는 skill로 위임하는 얇은 진입점만 두고, 실제 워크플로 로직은 `skills/`에만 유지합니다.

아래 예시는 충돌 없이 확실하게 보이도록 `/mcp-optimizer:<command>` 형식을 사용합니다.

## 포함된 명령

- `/mcp-optimizer:mcp-doctor`
  MCP 서버 연결 상태, 응답 시간, 중복 도구, 누락된 자격 증명을 점검합니다.
- `/mcp-optimizer:mcp-audit`
  Claude Code 세션 기록을 분석해 서버별 토큰 낭비와 최적화 우선순위를 계산합니다.
- `/mcp-optimizer:mcp-optimize`
  현재 프로젝트에 필요한 MCP 서버만 포함하는 `.mcp.json`을 생성합니다.
- `/mcp-optimizer:mcp-to-skills`
  선택한 MCP 도구를 필요할 때만 호출되는 Claude Code 스킬로 변환합니다.

같은 기능은 자연어 요청만으로도 번들된 Skill이 자동으로 잡아줄 수 있습니다.

## Marketplace 설치

1. `mcp-optimizer`가 포함된 marketplace를 추가합니다.
   ```bash
   /plugin marketplace add your-org/claude-plugins
   ```
2. 해당 marketplace에서 플러그인을 설치합니다.
   ```bash
   /plugin install mcp-optimizer@your-org
   ```
3. 필요하면 Claude Code를 재시작한 뒤 `/help`에서 명령이 보이는지 확인합니다.

로컬 개발 중이면 같은 방식으로 `./dev-marketplace` 같은 테스트 marketplace를 붙여 설치하면 됩니다.

## 추천 사용 순서

1. 먼저 서버 상태를 점검합니다.
   ```bash
   /mcp-optimizer:mcp-doctor
   ```
2. 그다음 토큰 낭비를 측정합니다.
   ```bash
   /mcp-optimizer:mcp-audit
   ```
3. 이후 최적화 경로를 고릅니다.
   - MCP는 유지하고 프로젝트 범위만 줄이려면:
     ```bash
     /mcp-optimizer:mcp-optimize
     ```
   - 비용이 큰 도구를 온디맨드 스킬로 바꾸려면:
     ```bash
     /mcp-optimizer:mcp-to-skills npx @linear/mcp-server
     ```

## 어떤 경로를 써야 하나

- 서버 자체는 계속 필요하지만 모든 프로젝트에 필요하지 않다면 `/mcp-optimizer:mcp-optimize`
- 서버 도구가 많지만 실제로 몇 개만 쓴다면 `/mcp-optimizer:mcp-to-skills`
- 프로젝트 범위를 줄이면서 일부 무거운 도구를 스킬로 빼고 싶다면 둘 다 사용

## 예시

```bash
/mcp-optimizer:mcp-doctor
/mcp-optimizer:mcp-audit
/mcp-optimizer:mcp-optimize
/mcp-optimizer:mcp-to-skills npx @linear/mcp-server
Engineering 팀의 open Linear 이슈를 보여줘
```

## 전체 흐름

```text
/mcp-optimizer:mcp-doctor -> 고장 난 서버와 중복 도구를 먼저 정리
/mcp-optimizer:mcp-audit -> 토큰 낭비와 우선순위를 계산
    |
    +-> /mcp-optimizer:mcp-optimize    MCP는 유지하고 프로젝트 범위만 축소
    |
    +-> /mcp-optimizer:mcp-to-skills   선택한 도구를 온디맨드 스킬로 변환
```

## 요구 사항

- Python 3.10+
- Claude Code CLI

## 라이선스

[MIT](LICENSE)
