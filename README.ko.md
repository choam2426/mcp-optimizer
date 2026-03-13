# mcp-optimizer

**MCP 진단, 사용 패턴 분석, 프로젝트 범위 축소, 온디맨드 스킬 변환을 위한 Claude Code Marketplace 플러그인입니다.**

`mcp-optimizer`는 아래 네 가지 질문에 답하도록 설계되어 있습니다.

1. 지금 MCP 서버 상태가 정상인가?
2. 실제로 어떤 서버가 토큰을 낭비하고 있는가?
3. MCP는 유지하되 이 프로젝트에 맞게 범위를 줄여야 하는가?
4. 무거운 MCP 서버를 로컬 온디맨드 스킬로 바꿔야 하는가?

이 플러그인은 다음 두 형태를 함께 제공합니다.

- `commands/`의 명시적 플러그인 명령
- `skills/`의 번들된 자동 발견용 Skill

각 `/mcp-optimizer:*` command는 대응하는 번들 Skill로 위임하는 얇은 진입점이고, 실제 워크플로 로직은 Skill 쪽에만 유지됩니다.

## 왜 필요한가

MCP 서버가 Claude Code에 연결되면, **사용 여부와 관계없이 도구 스키마가 매 대화마다 컨텍스트에 로드됩니다**.

| 시나리오 | 토큰 비용 |
|----------|-----------|
| Linear MCP (31개 도구) | 대화당 ~3,000+ 토큰 |
| GitHub MCP (20개+ 도구) | 대화당 ~2,000+ 토큰 |
| MCP 서버 3개 연결 | 대화당 ~6,500+ 토큰 |
| 필요할 때만 쓰는 로컬 skill | 유휴 시 ~0 토큰 |

이 때문에 보통 다음 세 가지 문제가 생깁니다.

- 큰 MCP 스키마가 유휴 상태에서도 토큰을 낭비함
- 고장 난 서버나 중복 서버가 컨텍스트를 오염시킴
- 글로벌 MCP 설정이 특정 프로젝트에는 과도하게 넓음

## 설치

### GitHub에서 설치 (권장)

1. 이 저장소를 마켓플레이스로 추가합니다.

   ```bash
   /plugin marketplace add choam2426/mcp-optimizer
   ```

2. 플러그인을 설치합니다.

   ```bash
   /plugin install mcp-optimizer
   ```

3. 필요하면 Claude Code를 재시작한 뒤 설치를 확인합니다.

   ```bash
   /help
   ```

### 다른 Marketplace에서 설치

`mcp-optimizer`가 포함된 별도 마켓플레이스가 있다면:

```bash
/plugin marketplace add your-org/claude-plugins
/plugin install mcp-optimizer@your-org
```

## 구성 요소 한눈에 보기

| Command | 카테고리 | 용도 | 주요 입력 | 파일 작성 여부 |
|---------|----------|------|-----------|----------------|
| `/mcp-optimizer:mcp-doctor` | 진단 | 서버 상태, 중복 도구, 자격 증명 확인 | `--server`, `--fix` | 없음 |
| `/mcp-optimizer:mcp-audit` | 분석 | 실제 세션 기준 토큰 낭비 측정 | `--scope` | 없음 |
| `/mcp-optimizer:mcp-optimize` | 최적화 | 더 작은 프로젝트 로컬 `.mcp.json` 생성 | `--dry-run`, `--min-sessions` | 확인 후 작성 |
| `/mcp-optimizer:mcp-to-skills` | 변환 | MCP 서버를 로컬 온디맨드 스킬로 변환 | `<server-command>` | `.claude/skills/...` 생성 |

## 추천 사용 흐름

1. 먼저 진단부터 시작합니다.

   ```bash
   /mcp-optimizer:mcp-doctor
   ```

2. 서버 상태가 정상이면 실제 낭비를 측정합니다.

   ```bash
   /mcp-optimizer:mcp-audit
   ```

3. 목적에 맞는 실행 경로를 선택합니다.

   - MCP는 유지하되 이 프로젝트에서만 범위를 줄이려면:

     ```bash
     /mcp-optimizer:mcp-optimize
     ```

   - 무거운 서버를 온디맨드 로컬 스킬로 바꾸려면:

     ```bash
     /mcp-optimizer:mcp-to-skills npx @linear/mcp-server
     ```

핵심 구분은 다음과 같습니다.

- `mcp-doctor`는 **최적화 명령이 아니라 진단 명령**입니다.
- `mcp-audit`는 **낭비 원인을 분석하는 명령**입니다.
- `mcp-optimize`와 `mcp-to-skills`가 **실제 최적화 실행 경로**입니다.

## Command Reference

### Diagnostics / 진단: `/mcp-optimizer:mcp-doctor`

`mcp-doctor`는 무엇을 바꾸기 전에 MCP 서버 상태를 먼저 검사할 때 사용합니다.

하는 일:

- 설정된 MCP 서버 연결 점검
- 응답 시간 측정
- 서버 간 중복 도구 이름 탐지
- 누락되었거나 의심스러운 자격 증명 확인
- 구체적인 조치 방향 제안

호출 형식:

```bash
/mcp-optimizer:mcp-doctor [--server <name>] [--fix]
```

인자:

| 인자 | 의미 | 기본값 |
|------|------|--------|
| `--server <name>` | 특정 MCP 서버 하나만 검사 | 설정된 모든 서버 검사 |
| `--fix` | 최종 리포트에 구체적인 수정 명령이나 후속 조치 포함 | 꺼짐 |

기본 동작:

- 읽기 전용 health check로 동작합니다.
- 설정 파일을 수정하지 않습니다.
- `--fix`를 써도 자동 수정은 하지 않고, 필요한 명령이나 후속 조치만 제안합니다.

기대 결과:

- 서버별 상태 리포트
- 응답 시간
- 중복 도구 정보
- 누락된 자격 증명 경고
- 이후 보통 `/mcp-optimizer:mcp-audit`로 이어지는 다음 단계 제안

예시:

```bash
/mcp-optimizer:mcp-doctor
/mcp-optimizer:mcp-doctor --server github
/mcp-optimizer:mcp-doctor --fix
```

### Analysis / 분석: `/mcp-optimizer:mcp-audit`

`mcp-audit`는 무엇을 유지하고, 줄이고, 변환할지 결정하기 전에 실제 토큰 낭비를 근거 기반으로 확인할 때 사용합니다.

하는 일:

- Claude Code 세션 기록 분석
- 서버별 스키마 오버헤드 추정
- 사용된 도구와 한 번도 쓰지 않은 도구 비교
- 최적화 우선순위 계산
- 고비용 서버에 대한 변환 명령 제안

호출 형식:

```bash
/mcp-optimizer:mcp-audit [--scope project|all]
```

인자:

| 인자 | 의미 | 기본값 |
|------|------|--------|
| `--scope project` | 현재 프로젝트 세션만 분석 | 예 |
| `--scope all` | Claude가 볼 수 있는 전체 프로젝트 세션 분석 | 아니오 |

기본 동작:

- scope를 주지 않으면 `project`가 기본값입니다.
- 세션 기록만 읽고 분석하며, 설정이나 generated skill을 수정하지 않습니다.

기대 결과:

- MCP 서버별 토큰 낭비 순위
- 전체 추정 낭비량
- 사용 비율과 미사용 도구 비율
- `/mcp-optimizer:mcp-optimize`, `/mcp-optimizer:mcp-to-skills` 추천

예시:

```bash
/mcp-optimizer:mcp-audit
/mcp-optimizer:mcp-audit --scope project
/mcp-optimizer:mcp-audit --scope all
```

### Optimization / 최적화: `/mcp-optimizer:mcp-optimize`

`mcp-optimize`는 MCP 자체는 계속 쓰고 싶지만, 모든 글로벌 서버를 이 프로젝트에 로드하고 싶지는 않을 때 사용합니다.

하는 일:

- 현재 프로젝트에 실제로 필요한 서버를 추정
- 더 작은 프로젝트 로컬 `.mcp.json` 제안
- 세션당 절감량 추정
- 사용자 확인 후에만 파일 작성

호출 형식:

```bash
/mcp-optimizer:mcp-optimize [--dry-run] [--min-sessions <N>]
```

인자:

| 인자 | 의미 | 기본값 |
|------|------|--------|
| `--dry-run` | `.mcp.json`을 쓰지 않고 계획만 표시 | 안전한 계획 우선 동작 |
| `--min-sessions <N>` | 더 강한 추천을 내리기 위한 최소 세션 수 | `5` |

기본 동작:

- 항상 계획을 먼저 보여주는 흐름으로 이해하면 됩니다.
- 제안된 `.mcp.json`을 먼저 보여준 뒤 확인을 받습니다.
- 프로젝트 로컬 `.mcp.json`만 다룹니다.
- `~/.claude.json` 같은 글로벌 설정은 수정하지 않습니다.

기대 결과:

- 서버별 keep/remove 제안
- 세션당 예상 절감량
- 전체 제안 `.mcp.json`
- 실제 쓰기 전 확인 단계

예시:

```bash
/mcp-optimizer:mcp-optimize
/mcp-optimizer:mcp-optimize --dry-run
/mcp-optimizer:mcp-optimize --min-sessions 10
```

### Conversion / 변환: `/mcp-optimizer:mcp-to-skills`

`mcp-to-skills`는 서버 도구는 많지만 실제로는 일부만 필요해서, 그 일부를 필요할 때만 쓰는 로컬 스킬로 바꾸고 싶을 때 사용합니다.

하는 일:

- 대상 MCP 서버 스키마 검사
- tool schema 읽기
- 도구별 로컬 Claude Code skill 생성
- 명확한 이유가 없으면 proxy mode를 기본으로 선택

호출 형식:

```bash
/mcp-optimizer:mcp-to-skills <server-command>
```

인자:

| 인자 | 의미 | 필수 여부 |
|------|------|-----------|
| `<server-command>` | 검사하고 변환할 MCP 서버 명령. 예: `npx @linear/mcp-server` | 필수 |

기본 동작:

- 실제 MCP 서버 명령을 반드시 받아야 합니다.
- 생성 결과는 `.claude/skills/` 아래에 기록됩니다.
- 기본적으로 proxy mode를 우선합니다.

기대 결과:

- 감지된 서비스 이름
- 생성된 skill 디렉터리 목록
- 도구별 설명
- 생성된 skill을 트리거할 자연어 예시

예시:

```bash
/mcp-optimizer:mcp-to-skills npx @linear/mcp-server
/mcp-optimizer:mcp-to-skills uvx mcp-server-gitlab
```

## Command와 Skill의 차이

이 플러그인은 같은 워크플로를 두 형태로 노출합니다.

- `commands/`: 사용자가 직접 실행하는 `/mcp-optimizer:mcp-audit` 같은 명령
- `skills/`: Claude가 자연어 요청에서 자동으로 발견할 수 있는 번들 Skill

이 저장소 기준으로:

- command는 명시적 공개 진입점입니다.
- matching Skill이 실제 canonical workflow입니다.
- command는 동일한 지시를 중복하지 않고 대응 Skill로 위임합니다.

즉 다음 두 방식 모두 가능합니다.

- command를 직접 호출
- 자연어로 요청해서 Claude가 번들 Skill을 자동 발견하도록 사용

## 생성되는 로컬 Skill

`/mcp-optimizer:mcp-to-skills`는 `.claude/skills/` 아래에 로컬 skill을 생성합니다.

중요한 점:

- 생성된 로컬 skill은 `/mcp-optimizer:*` 네임스페이스를 쓰지 않습니다.
- 플러그인에 내장된 command와는 별개의 로컬 skill입니다.
- 사용자가 해당 작업을 자연어로 요청하면 Claude가 자동으로 발견해 활용하는 형태를 기대하면 됩니다.

변환 후 요청 예시:

```text
Engineering 팀의 open Linear 이슈를 보여줘
```

## 예시 시나리오

| 상황 | 시작 command | 이유 |
|------|--------------|------|
| "어떤 MCP 서버가 깨졌는지 모르겠다" | `/mcp-optimizer:mcp-doctor` | 최적화 전에 상태를 먼저 진단 |
| "토큰 낭비가 어디서 생기는지 알고 싶다" | `/mcp-optimizer:mcp-audit` | 실제 사용 기록 기준으로 낭비 측정 |
| "이 프로젝트에서는 글로벌 MCP를 다 로드하고 싶지 않다" | `/mcp-optimizer:mcp-optimize` | MCP는 유지하되 범위만 축소 |
| "이 서버는 너무 무겁지만 일부 기능은 계속 쓰고 싶다" | `/mcp-optimizer:mcp-to-skills` | 도구를 로컬 온디맨드 skill로 변환 |

## 요구 사항 및 참고

- Python 3.10+
- Claude Code 설치 및 실행 환경
- `mcp-doctor`, `mcp-to-skills` 사용 시 필요한 MCP 서버 환경 변수는 이미 준비되어 있어야 함
- `mcp-audit`는 사용 가능한 Claude Code 세션 기록이 있어야 함
- `mcp-optimize`는 프로젝트 로컬 `.mcp.json`만 작성함

## 라이선스

[MIT](LICENSE)
