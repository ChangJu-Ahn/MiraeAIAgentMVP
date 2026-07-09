from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl
from chainlit.context import local_steps
from chainlit.input_widget import Select, Switch

from agent.followups import suggest_followups
from agent.observability import collect_trace_json, reset_trace, setup_observability
from agent.orchestrator import start_stream
from agent.reflection import augmented_question, critique
from agent.translate import detect_lang, needs_translation, translate
from agent.visuals import ChartVisual, ImageVisual, TableVisual
from app.formatting import cited_sources, dedup_sources, format_citations, format_debug
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from ingest.figures import render_page_png

setup_observability()


# 헤더의 "원본자료" 링크가 여는 페이지 — 매 요청마다 신선한 SAS 링크 목록 서빙.
# Chainlit의 SPA catch-all보다 먼저 매칭되도록 라우트를 맨 앞에 삽입한다.
try:
    import html as _html

    from chainlit.server import app as _fastapi_app
    from fastapi.responses import HTMLResponse

    from app.source_docs import source_doc_links

    async def _source_docs_page() -> HTMLResponse:
        links = source_doc_links()
        rows = "".join(
            f'<li><a href="{_html.escape(url, quote=True)}" target="_blank" rel="noopener">{_html.escape(label)}</a></li>'
            for label, url in links
        )
        page = (
            "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>원본자료</title><style>"
            "body{font-family:system-ui,-apple-system,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#1f2937}"
            "h1{font-size:1.25rem} p{color:#4b5563} ul{line-height:2} a{color:#2563eb;text-decoration:none} a:hover{text-decoration:underline}"
            "</style></head><body>"
            "<h1>📎 원본자료 (데이터소스)</h1>"
            "<p>기금운용평가 원본 PDF입니다. 클릭하면 새 탭에서 열립니다.</p>"
            f"<ul>{rows or '<li>(자료를 불러올 수 없습니다)</li>'}</ul>"
            "</body></html>"
        )
        return HTMLResponse(page)

    _fastapi_app.add_api_route("/source-docs", _source_docs_page, methods=["GET"])
    _fastapi_app.router.routes.insert(0, _fastapi_app.router.routes.pop())
except Exception:  # noqa: BLE001 - 라우트 등록 실패는 앱 기동을 막지 않음
    pass


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("debug", False)
    cl.user_session.set("effort", "medium")
    cl.user_session.set("reflection", False)
    # 헤더(우측 상단)에 디버그 토글 + 추론 강도 선택 표시 (config.toml chat_settings_location="sidebar")
    await cl.ChatSettings(
        [
            Switch(
                id="debug",
                label="🐞 디버그 모드 (전체 트레이스 · 검색 결과 · 스코어 · OTel raw)",
                initial=False,
            ),
            Switch(
                id="reflection",
                label="🔍 자가 점검·보완 (답변이 부족하면 다시 조회, 느려짐)",
                initial=False,
            ),
            Select(
                id="effort",
                label="🧠 추론 강도 (낮을수록 빠르고, 높을수록 깊게 사고)",
                values=["low", "medium", "high"],
                initial_index=1,
            ),
        ]
    ).send()
    await cl.Message(
        content=(
            "안녕하세요! 기금운용평가보고서 기반 AI 어시스턴트입니다. 질문을 입력해 주세요.\n\n"
            "우측 상단 **⚙️ 설정**에서 디버그 모드·**자가 점검**·**추론 강도(low/medium/high)**, "
            "우측 상단 **원본자료**에서 데이터소스 원본 PDF를 열람할 수 있습니다."
        )
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    debug = bool(settings.get("debug", False))
    cl.user_session.set("debug", debug)
    cl.user_session.set("effort", settings.get("effort", "medium"))
    cl.user_session.set("reflection", bool(settings.get("reflection", False)))
    if not debug:
        await cl.ElementSidebar.set_elements([])  # 디버그 끄면 우측 패널 비움


def _visual_elements(visuals: list) -> list:
    elements: list = []
    for v in visuals:
        if isinstance(v, TableVisual):
            elements.append(
                cl.Dataframe(data=table_to_dataframe(v), name=v.title, display="inline")
            )
        elif isinstance(v, ChartVisual):
            elements.append(
                cl.Plotly(figure=chart_to_figure(v), name=v.title, display="inline")
            )
        elif isinstance(v, ImageVisual):
            if v.path.startswith("__page__:"):
                try:
                    page = int(v.path.split(":", 1)[1])
                    pdf = _resolve_source_pdf(get_settings().source_pdf_path)
                    if not pdf:
                        continue
                    png = render_page_png(pdf, page)
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                    tmp.write(png)
                    tmp.close()
                    elements.append(
                        cl.Image(
                            path=tmp.name, name=v.title, display="inline", mime="image/png", size="large"
                        )
                    )
                except Exception:  # noqa: BLE001 - 원문 페이지 렌더 실패는 건너뜀
                    continue
            else:
                elements.append(cl.Image(path=v.path, name=v.title, display="inline", size="large"))
    return elements


def _resolve_source_pdf(configured: str) -> str | None:
    """원문 PDF 경로를 견고하게 해석. 정확 경로가 없으면 docs/에서 2025 보고서를 찾는다.

    (대소문자·유니코드 정규화 차이로 정확 경로가 안 맞을 수 있어 목록 조회로 보완)
    """
    import os
    import unicodedata

    if os.path.exists(configured):
        return configured
    for d in ("docs", "Docs"):
        if os.path.isdir(d):
            for f in os.listdir(d):
                nf = unicodedata.normalize("NFC", f)
                if f.lower().endswith(".pdf") and "2025" in nf and "보고서" in nf:
                    return os.path.join(d, f)
    return None


async def _run_round(question: str) -> tuple[str, object, object]:
    """스트리밍으로 한 라운드를 실행. (answer_text, trace, visual) 반환.

    2단계 접이식 구조로 진행 과정을 보여준다.
      - 부모 "생각 중" 스텝: 모델의 추론 요약(reasoning summary)을 흐름대로 누적.
      - 자식 도구 스텝: 각 도구 호출을 call_id별 독립 스텝으로 열어 입력(검색어)과
        출력(검색 결과 전문)을 각각 접었다 펼 수 있게 한다.
    모델의 추론 요약은 영어로 생성되는 경우가 많으므로, 질문 언어와 다르면 세그먼트
    단위로 번역하여 표시한다(도구 입력/결과는 이미 질문 언어이므로 그대로 표시).
    """
    stream, trace, visual = start_stream(question, cl.user_session.get("effort") or "medium")
    answer_msg = cl.Message(content="")

    target_lang = detect_lang(question)
    tool_calls: dict[str, dict] = {}  # call_id -> {"name", "args", "step", "t0"}
    any_process = False
    answer_text = ""
    round_t0 = perf_counter()

    async with cl.Step(name="생각 중", type="reasoning") as think:
        pending_reasoning = ""  # 완성 대기 중인 추론 세그먼트
        pending_id: str | None = None

        async def flush_reasoning() -> None:
            nonlocal pending_reasoning, pending_id, any_process
            seg = pending_reasoning.strip()
            pending_reasoning, pending_id = "", None
            if not seg:
                return
            if needs_translation(seg, target_lang):
                seg = await translate(seg, target_lang)
            any_process = True
            await think.stream_token(f"\n{seg}\n")

        async def flush_tool_steps() -> None:
            """arguments 델타가 모두 모인 도구 호출을 '생각 중'의 자식 스텝으로 연다.

            각 도구는 call_id별 독립 스텝이므로, 병렬 호출/결과가 뒤섞여 도착해도
            입력·출력이 엇갈리지 않고 각자의 접이식 스텝에 정확히 담긴다.
            """
            nonlocal any_process
            for info in tool_calls.values():
                if info["step"] is not None or not info["name"]:
                    continue
                display = info["args"] or "(입력 없음)"
                try:
                    args = json.loads(info["args"])
                    query = args.get("query", "")
                    filters = {
                        k: args[k]
                        for k in ("year", "doc_type", "fund_name", "fund_scale")
                        if args.get(k) not in (None, "")
                    }
                    parts = [f'질의: "{query}"'] if query else []
                    parts.append(
                        "필터: " + ", ".join(f"{k}={v}" for k, v in filters.items())
                        if filters
                        else "필터: 없음"
                    )
                    display = "\n".join(parts) or display
                except (ValueError, TypeError):
                    pass
                step = cl.Step(name=f"🔧 {info['name']}", type="tool", parent_id=think.id)
                step.input = display
                await step.send()
                # send()가 자신을 스텝 스택에 push하므로 형제 오염을 막기 위해 제거
                stack = local_steps.get() or []
                if stack and stack[-1] is step:
                    local_steps.set(stack[:-1])
                info["step"] = step
                any_process = True

        async for update in stream:
            for content in update.contents:
                ctype = getattr(content, "type", None)

                if ctype == "text_reasoning":
                    token = getattr(content, "text", "") or ""
                    if not token:
                        continue
                    await flush_tool_steps()  # 앞선 도구 호출 확정
                    cid = getattr(content, "id", None)
                    if pending_id is not None and cid != pending_id:
                        await flush_reasoning()
                    pending_id = cid
                    pending_reasoning += token
                    continue

                # 추론 외 이벤트가 오면, 진행 중 추론 세그먼트를 먼저 확정해 순서를 유지
                await flush_reasoning()

                if ctype == "function_call":
                    cid = getattr(content, "call_id", None) or "?"
                    info = tool_calls.setdefault(cid, {"name": None, "args": "", "step": None})
                    if info.get("t0") is None:
                        info["t0"] = perf_counter()  # 도구 실행 시작 근사치(첫 호출 델타 시점)
                    if getattr(content, "name", None):
                        info["name"] = content.name
                    args = getattr(content, "arguments", None)
                    if args:
                        info["args"] += args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)

                elif ctype == "function_result":
                    await flush_tool_steps()  # 결과에 앞서 호출 스텝 확정
                    cid = getattr(content, "call_id", None) or "?"
                    info = tool_calls.get(cid)
                    result = str(getattr(content, "result", "") or "")
                    if info and info["step"] is not None:
                        if info.get("t0") is not None:
                            elapsed = perf_counter() - info["t0"]
                            info["step"].name = f"🔧 {info['name']} ({elapsed:.1f}s)"
                        if result:
                            info["step"].output = result
                        await info["step"].update()

                elif ctype == "text":
                    await flush_tool_steps()
                    token = getattr(content, "text", "") or ""
                    if token:
                        answer_text += token
                        await answer_msg.stream_token(token)

        await flush_reasoning()
        await flush_tool_steps()
        elapsed_total = perf_counter() - round_t0
        think.name = f"생각 중 (총 {elapsed_total:.1f}s)"
        await think.update()
        if not any_process:
            think.output = "(이 라운드에서는 별도 사고 과정이 관측되지 않았습니다.)"

    await answer_msg.update()
    return answer_text, trace, visual


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await answer_and_render(message.content)


@cl.action_callback("ask_followup")
async def ask_followup(action: cl.Action) -> None:
    q = action.payload.get("q", "")
    await action.remove()  # 클릭한 제안 버튼 정리
    if not q:
        return
    await cl.Message(content=q, type="user_message").send()  # 사용자가 물은 것처럼 표시
    await answer_and_render(q)


async def answer_and_render(question_input: str) -> None:
    """한 질문에 대해 라운드 실행 → 답변·시각물·근거·디버그·후속질문까지 렌더링.

    on_message와 후속 질문 버튼(ask_followup) 양쪽에서 재사용한다.
    """
    reflection_on = bool(cl.user_session.get("reflection"))
    max_rounds = 2 if reflection_on else 1
    original_question = question_input
    question = question_input
    answer_text, trace, visual = "", None, None
    rounds: list[tuple[str, list, list]] = []  # 디버그용 라운드별 (질의, 트레이스, 검색결과)
    reset_trace()  # 이번 턴의 OpenTelemetry 스팬만 모으도록 캡처 버퍼 초기화

    for rnd in range(1, max_rounds + 1):
        answer_text, trace, visual = await _run_round(question)
        rounds.append((question, trace.steps, trace.sources))
        if rnd == max_rounds:
            break
        # 자가 점검(설정 ON일 때만): 답변이 충분한가? (점검 실패 시 안전하게 통과 처리)
        try:
            verdict = await critique(original_question, answer_text, trace.sources)
        except Exception as exc:  # noqa: BLE001
            cl.logger.warning(f"reflection critique failed: {exc}; treating as sufficient")
            break
        if verdict.sufficient:
            break
        async with cl.Step(name="🔍 자가 점검: 보완 필요", type="reflection") as s:
            s.output = f"부족한 부분: {verdict.missing}\n→ 보완 질의로 다시 조회합니다."
        question = augmented_question(original_question, verdict.missing)

    # 시각물 바인딩 (표/차트/원문 이미지) — 최종 라운드
    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    # 근거 출처 카드 — 답변이 실제 인용한 [출처 N]을 우선 표시.
    # 모델이 인용 형식을 누락한 경우, 이번 답변 생성에 검색된 자료를 참고 자료로 표시.
    used = cited_sources(answer_text, trace.sources)
    if used:
        citations = format_citations(used, heading="근거")
    else:
        citations = format_citations(dedup_sources(trace.sources), heading="참고한 자료")
    if citations:
        await cl.Message(content=citations).send()

    # 관련 후속 질문 — 클릭하면 바로 이어서 질문할 수 있는 버튼 바
    followups = await suggest_followups(original_question, answer_text)
    if followups:
        actions = [
            cl.Action(name="ask_followup", payload={"q": q}, label=q, tooltip="이 질문으로 이어서 물어보기")
            for q in followups
        ]
        await cl.Message(content="💡 **이어서 물어보기**", actions=actions).send()

    # 디버그 모드: 우측 사이드바에 전체 트레이스 + AI Search 결과·스코어 + 최종 인용 표시.
    # 다른 메시지 렌더에 밀리지 않도록 이 턴의 '마지막'에 열어 최종 상태로 남긴다.
    if cl.user_session.get("debug"):
        raw_trace = collect_trace_json()  # OpenTelemetry 표준 raw 트레이스
        debug_md = format_debug(rounds, used, raw_trace=raw_trace)
        await cl.ElementSidebar.set_title("🐞 디버그 트레이스 (우측 패널 토글로 접기/펼치기)")
        await cl.ElementSidebar.set_elements(
            [cl.Text(content=debug_md, name="debug-trace")]
        )
