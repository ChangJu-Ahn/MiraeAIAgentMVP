# P8: 관측성 (Azure Application Insights + OpenTelemetry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bicep으로 Application Insights(+Log Analytics)를 프로비저닝하고, Microsoft Agent Framework 내장 관측성으로 에이전트 실행과 **툴 콜(입력=근거, 출력=답변)**을 OpenTelemetry gen_ai 스팬으로 Azure Application Insights에 기록한다. 민감 데이터 텔레메트리를 켜서 프롬프트·검색 근거·답변까지 트레이스에 남긴다.

**Architecture:** `infra/modules/observability.bicep`가 Log Analytics 워크스페이스와 워크스페이스 기반 Application Insights를 만들고 연결 문자열을 출력한다. `deploy.sh`가 이를 `.env`(APPINSIGHTS_CONNECTION_STRING)에 기록한다. `agent/observability.py`의 `setup_observability()`가 Azure Monitor OTel exporter(trace/log/metric)로 `configure_otel_providers(...)` + `enable_instrumentation(enable_sensitive_data=True)`를 1회 구성한다. 각 진입점(Chainlit 앱, CLI들)이 시작 시 이를 호출하면 Agent Framework가 자동 계측한 스팬이 App Insights로 흐른다.

**Tech Stack:** Bicep, Azure CLI, Python 3.12(uv), agent-framework(observability: configure_otel_providers/enable_instrumentation), azure-monitor-opentelemetry-exporter, config.settings, pytest.

## Global Constraints

- 관측성 백엔드는 **Azure Application Insights**(OpenTelemetry). 계측은 **Microsoft Agent Framework 내장** 사용. (스펙 §7, 사용자 지시)
- **툴 콜의 입력(근거)·출력(답변)·프롬프트가 트레이스에 기록**되어야 함 → `enable_sensitive_data=True`. (사용자 지시)
- 연결 문자열은 `settings.appinsights_connection_string`(.env, gitignore). 값이 없으면 관측성은 no-op(로컬/미설정 안전).
- Bicep은 P1 패턴(전용 RG, 기존 모듈 구조) 준수. 재배포로 App Insights 추가.
- 관측성 설정은 프로세스당 1회(중복 구성 방지 가드).
- 실제 배포/실제 트레이스 흐름 검증 허용.
- 모든 커밋 끝에 트레일러:
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`

## 확정된 API (검증됨)
- `from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter, AzureMonitorLogExporter, AzureMonitorMetricExporter` — `connection_string=` 인자로 생성(검증됨).
- `from agent_framework.observability import configure_otel_providers, enable_instrumentation`.
  - `configure_otel_providers(exporters=[...], enable_sensitive_data=True)`
  - `enable_instrumentation(enable_sensitive_data=True)`
- azure-monitor-opentelemetry-exporter 설치됨(1.0.0b55).

---

## File Structure

- `infra/modules/observability.bicep` (신규) — Log Analytics + Application Insights
- `infra/main.bicep` (수정) — observability 모듈 호출 + output
- `scripts/deploy.sh` (수정) — APPINSIGHTS_CONNECTION_STRING → .env
- `config/settings.py` (수정) — `appinsights_connection_string`
- `.env.example` (수정)
- `agent/observability.py` (신규) — `setup_observability()`
- `app/chat.py`, `ingest/run.py`, `agent/ask.py`, `eval/run_eval.py` (수정) — 진입점에서 setup 호출
- `tests/agent/test_observability.py` (신규) — no-op/guard 단위 테스트
- `README.md` (수정)

---

## Task 1: Bicep Application Insights + 재배포

**Files:**
- Create: `infra/modules/observability.bicep`
- Modify: `infra/main.bicep`, `scripts/deploy.sh`, `config/settings.py`, `.env.example`

**Interfaces:**
- Produces: `observability.bicep` outputs `appInsightsConnectionString string`, `appInsightsName string`. `main.bicep` output `appInsightsConnectionString`. `.env`에 `APPINSIGHTS_CONNECTION_STRING`. `Settings.appinsights_connection_string: str = ""`.

- [ ] **Step 1: observability.bicep 작성**

Create `infra/modules/observability.bicep`:
```bicep
@description('Log Analytics/App Insights 이름 접미사')
param name string
param location string

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${name}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
  }
}

output appInsightsName string = appi.name
output appInsightsConnectionString string = appi.properties.ConnectionString
```

- [ ] **Step 2: 문법 검증**

Run: `az bicep build --file infra/modules/observability.bicep --stdout > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: main.bicep 통합**

Edit `infra/main.bicep` — add module + output:
```bicep
module observability 'modules/observability.bicep' = {
  name: 'observability'
  params: {
    name: 'mirae-${suffix}'
    location: location
  }
}
```
And add output:
```bicep
output appInsightsConnectionString string = observability.outputs.appInsightsConnectionString
```

Run: `az bicep build --file infra/main.bicep --stdout > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 4: settings + .env.example**

Edit `config/settings.py` — add field:
```python
    appinsights_connection_string: str = ""
```
Edit `.env.example` — add:
```
# Azure Application Insights (OpenTelemetry)
APPINSIGHTS_CONNECTION_STRING=
```

- [ ] **Step 5: deploy.sh — .env에 연결 문자열 기록**

Edit `scripts/deploy.sh` — after existing output parsing, add:
```bash
appi=$(echo "$OUT" | python3 -c "import sys,json;print(json.load(sys.stdin)['appInsightsConnectionString']['value'])")
```
And append to the `.env` heredoc:
```
APPINSIGHTS_CONNECTION_STRING=$appi
```

- [ ] **Step 6: 재배포**

Run:
```bash
bash scripts/deploy.sh
```
Expected: 배포 성공(App Insights + LAW 추가), `.env`에 `APPINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...` 기록. (실 Azure)

- [ ] **Step 7: 확인 + Commit**

Run: `grep -q "APPINSIGHTS_CONNECTION_STRING=InstrumentationKey" .env && echo OK`
Expected: `OK`

```bash
git add infra/modules/observability.bicep infra/main.bicep scripts/deploy.sh config/settings.py .env.example
git commit -m "feat(infra): provision Application Insights + Log Analytics via bicep

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: 관측성 설정 + 진입점 연결 + 트레이스 검증

**Files:**
- Create: `agent/observability.py`, `tests/agent/test_observability.py`
- Modify: `app/chat.py`, `ingest/run.py`, `agent/ask.py`, `eval/run_eval.py`, `README.md`

**Interfaces:**
- Produces:
  - `setup_observability() -> bool` — 연결 문자열이 있으면 Azure Monitor exporter로 OTel 구성 + Agent Framework 계측(민감 데이터 포함) 후 True, 없으면 no-op False. 프로세스당 1회(모듈 플래그 가드).

- [ ] **Step 1: 실패하는 단위 테스트 작성**

Create `tests/agent/test_observability.py`:
```python
import agent.observability as obs


def test_setup_observability_noop_without_connection(monkeypatch):
    # 연결 문자열이 없으면 no-op(False), 예외 없음
    monkeypatch.setattr(obs, "_configured", False, raising=False)
    monkeypatch.delenv("APPINSIGHTS_CONNECTION_STRING", raising=False)
    from config.settings import Settings

    monkeypatch.setattr(obs, "get_settings", lambda: Settings(_env_file=None))
    assert obs.setup_observability() is False


def test_setup_observability_idempotent_guard(monkeypatch):
    monkeypatch.setattr(obs, "_configured", True, raising=False)
    # 이미 구성되었으면 재구성 없이 True 반환
    assert obs.setup_observability() is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/agent/test_observability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.observability'`

- [ ] **Step 3: observability.py 구현**

Create `agent/observability.py`:
```python
from __future__ import annotations

from config.settings import get_settings

_configured = False


def setup_observability() -> bool:
    """Wire Azure Application Insights (OpenTelemetry) once per process.

    Records agent runs and tool calls (inputs=grounds, outputs=answers) as
    gen_ai spans when APPINSIGHTS_CONNECTION_STRING is set. No-op otherwise.
    """
    global _configured
    if _configured:
        return True
    conn = get_settings().appinsights_connection_string
    if not conn:
        return False

    from agent_framework.observability import configure_otel_providers, enable_instrumentation
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorLogExporter,
        AzureMonitorMetricExporter,
        AzureMonitorTraceExporter,
    )

    configure_otel_providers(
        exporters=[
            AzureMonitorTraceExporter(connection_string=conn),
            AzureMonitorLogExporter(connection_string=conn),
            AzureMonitorMetricExporter(connection_string=conn),
        ],
        enable_sensitive_data=True,
    )
    enable_instrumentation(enable_sensitive_data=True)
    _configured = True
    return True
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/agent/test_observability.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 진입점 연결**

Edit `app/chat.py` — after imports, call once at import (guarded):
```python
from agent.observability import setup_observability

setup_observability()
```
Edit `ingest/run.py`, `agent/ask.py`, `eval/run_eval.py` — at start of each `main()`:
```python
    from agent.observability import setup_observability

    setup_observability()
```

- [ ] **Step 6: 실제 트레이스 흐름 검증**

Run:
```bash
uv run python -c "
from agent.observability import setup_observability
from agent.orchestrator import ask_sync
assert setup_observability() is True, 'expected observability enabled (check .env conn string)'
r = ask_sync('자산운용 평가의 목적은?')
print('answer head:', r.answer[:80])
# 스팬 플러시
from opentelemetry import trace
tp = trace.get_tracer_provider()
if hasattr(tp, 'force_flush'):
    tp.force_flush()
print('OBSERVABILITY OK (spans exported)')
"
```
Expected: 관측성 활성(True), 에이전트 응답, 스팬 export 오류 없음, `OBSERVABILITY OK`. (실 Foundry + App Insights ingestion; 스팬은 수십 초~수 분 뒤 포털에 표시)

- [ ] **Step 7: (선택) App Insights에서 트레이스 조회**

Run (extension 필요시 자동 설치 프롬프트 수락):
```bash
sleep 120
APPID=$(az monitor app-insights component show -g rg-mirae-ai-agent-poc --query "[0].appId" -o tsv 2>/dev/null || true)
if [ -n "$APPID" ]; then
  az monitor app-insights query --app "$APPID" \
    --analytics-query "dependencies | where timestamp > ago(10m) | where name has 'chat' or name has 'execute_tool' or target has 'search' | count" \
    -o table || echo "쿼리 스킵(ingestion 지연 가능)"
fi
```
Expected: gen_ai 관련 dependency 스팬이 1건 이상 집계되면 성공. (ingestion 지연으로 0이면 잠시 후 재시도; Step 6 성공이면 파이프라인은 정상.)

- [ ] **Step 8: README + 회귀**

Edit `README.md` — "평가 (P5)" 아래에 추가:
```markdown
## 관측성 (P8)
`.env`에 `APPINSIGHTS_CONNECTION_STRING`이 있으면 에이전트 실행·툴 콜(근거/답변)이 OpenTelemetry로 Azure Application Insights에 자동 기록됩니다(민감 데이터 포함). 각 진입점(챗봇/CLI)이 시작 시 `setup_observability()`를 호출합니다.
```

Run: `uv run pytest -q -k "not test_orchestrator and not runner_smoke and not render_and_describe and not build_figure_chunks"`
Expected: 순수/관측성 단위 테스트 PASS.

- [ ] **Step 9: Commit**

```bash
git add agent/observability.py tests/agent/test_observability.py app/chat.py ingest/run.py agent/ask.py eval/run_eval.py README.md
git commit -m "feat(obs): wire Agent Framework OTel tracing to Application Insights (sensitive data on)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Self-Review 결과

- **Spec coverage:** App Insights 프로비저닝(Task 1), Agent Framework OTel 계측으로 에이전트·툴 콜(근거/답변) 트레이스(Task 2, enable_sensitive_data), 진입점 전반 연결. 연결 문자열 미설정 시 안전 no-op. 응답시간 등 여타 비기능은 스펙 문서 설명으로 충분(사용자 확정).
- **Placeholder scan:** 코드/명령 구체화. App Insights ingestion 지연은 검증 단계에 명시(스팬 export 성공을 1차 성공 기준으로).
- **Type consistency:** `appinsights_connection_string`(settings) ↔ deploy.sh `APPINSIGHTS_CONNECTION_STRING` ↔ observability.setup 일치. Bicep output 이름(appInsightsConnectionString)이 deploy.sh 파서와 일치.

## 후속
- 트레이스에 커스텀 속성(질문 유형, 인덱스 히트수) 부가; App Insights 대시보드/알림; sampling 조정.
