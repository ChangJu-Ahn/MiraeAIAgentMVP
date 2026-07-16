from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chainlit as cl
from chainlit.context import local_steps
from chainlit.input_widget import Select, Switch
from chainlit.server import app as chainlit_app

from agent.observability import collect_trace_json, reset_trace, setup_observability
from agent.orchestrator import new_session, start_stream
from agent.reflection import augmented_question, critique
from agent.tools import TraceRecorder
from agent.visuals import ChartVisual, ImageVisual, TableVisual, VisualRecorder
from app.formatting import cited_sources, dedup_sources, format_citations, format_debug
from app.source_docs import source_document_response, source_docs_page
from app.visual_bind import chart_to_figure, table_to_dataframe
from config.settings import get_settings
from eval.live import (
    evaluate_existing_answer,
    find_reference_answer,
    format_live_evaluation,
)
from ingest.figures import render_page_png

setup_observability()

_DEBUG_HISTORY_LIMIT = 10
_EVALUATION_HISTORY_LIMIT = 10
_EVALUATION_TASKS: set[asyncio.Task[None]] = set()


def _register_source_document_routes() -> None:
    route_specs = (
        ("/source-docs/{doc_id}", source_document_response, "source-document"),
        ("/source-docs", source_docs_page, "source-documents"),
    )
    for path, endpoint, name in route_specs:
        if any(getattr(route, "path", None) == path for route in chainlit_app.router.routes):
            continue
        chainlit_app.add_api_route(
            path,
            endpoint,
            methods=["GET"],
            name=name,
            include_in_schema=False,
        )
        chainlit_app.router.routes.insert(0, chainlit_app.router.routes.pop())


_register_source_document_routes()


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("debug", False)
    cl.user_session.set("effort", "medium")
    cl.user_session.set("reflection", False)
    cl.user_session.set("answer_evaluation", False)
    cl.user_session.set("agent_session", new_session())
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
            Switch(
                id="answer_evaluation",
                label="답변 평가 (답변 완료 후 백그라운드 품질 평가)",
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
            "**MVP 안내**\n"
            "본 서비스는 기능과 사용자 경험 검증을 위한 PoC/MVP이며, "
            "Production 운영용 서비스가 아닙니다. 중요한 판단에는 답변의 "
            "출처와 원본 문서를 함께 확인해 주세요.\n\n"
            "안녕하세요. 기금운용평가보고서에 대해 질문해 주세요.\n\n"
            "우측 상단 **⚙️ 설정**에서 디버그 모드·자가 점검·답변 평가·"
            "추론 강도를 조정할 수 있습니다."
        )
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    debug = bool(settings.get("debug", False))
    cl.user_session.set("debug", debug)
    cl.user_session.set("effort", settings.get("effort", "medium"))
    cl.user_session.set("reflection", bool(settings.get("reflection", False)))
    cl.user_session.set(
        "answer_evaluation", bool(settings.get("answer_evaluation", False))
    )
    if not debug:
        await cl.ElementSidebar.set_elements([])


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
                            path=tmp.name,
                            name=v.title,
                            display="inline",
                            mime="image/png",
                            size="large",
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


async def _stream_answer(
    question: str,
) -> tuple[str, TraceRecorder, VisualRecorder]:
    session = cl.user_session.get("agent_session")
    effort = cl.user_session.get("effort") or "medium"
    stream, trace, visual = start_stream(question, effort, session=session)
    answer_message = cl.Message(content="")
    tool_calls: dict[str, dict] = {}
    any_process = False
    answer_text = ""
    round_started = perf_counter()

    async with cl.Step(name="생각 중", type="reasoning") as reasoning_step:
        pending_reasoning = ""
        pending_reasoning_id: str | None = None

        async def flush_reasoning() -> None:
            nonlocal pending_reasoning, pending_reasoning_id, any_process
            segment = pending_reasoning.strip()
            pending_reasoning = ""
            pending_reasoning_id = None
            if not segment:
                return
            any_process = True
            await reasoning_step.stream_token(f"\n{segment}\n")

        async def flush_tool_steps() -> None:
            nonlocal any_process
            for info in tool_calls.values():
                if info["step"] is not None or not info["name"]:
                    continue
                display = info["args"] or "(입력 없음)"
                try:
                    args = json.loads(info["args"])
                    query = args.get("query", "")
                    filters = {
                        key: args[key]
                        for key in ("year", "doc_type", "fund_name", "fund_scale")
                        if args.get(key) not in (None, "")
                    }
                    parts = [f'질의: "{query}"'] if query else []
                    parts.append(
                        "필터: "
                        + (
                            ", ".join(f"{key}={value}" for key, value in filters.items())
                            if filters
                            else "없음"
                        )
                    )
                    display = "\n".join(parts) or display
                except (ValueError, TypeError):
                    pass

                step = cl.Step(
                    name=f"🔧 {info['name']}",
                    type="tool",
                    parent_id=reasoning_step.id,
                )
                step.input = display
                await step.send()
                stack = local_steps.get() or []
                if stack and stack[-1] is step:
                    local_steps.set(stack[:-1])
                info["step"] = step
                any_process = True

        stream_iterator = aiter(stream)
        while True:
            try:
                update = await anext(stream_iterator)
            except StopAsyncIteration:
                break
            except Exception:  # noqa: BLE001
                cl.logger.exception("agent stream failed")
                error_marker = "\n\n`E_STREAM`\n"
                answer_text += error_marker
                await answer_message.stream_token(error_marker)
                break

            for content in getattr(update, "contents", []):
                content_type = getattr(content, "type", None)

                if content_type == "text_reasoning":
                    token = getattr(content, "text", "") or ""
                    if not token:
                        continue
                    await flush_tool_steps()
                    content_id = getattr(content, "id", None)
                    if (
                        pending_reasoning_id is not None
                        and content_id != pending_reasoning_id
                    ):
                        await flush_reasoning()
                    pending_reasoning_id = content_id
                    pending_reasoning += token
                    continue

                await flush_reasoning()

                if content_type == "function_call":
                    call_id = getattr(content, "call_id", None) or "?"
                    info = tool_calls.setdefault(
                        call_id,
                        {"name": None, "args": "", "step": None, "started": None},
                    )
                    if info["started"] is None:
                        info["started"] = perf_counter()
                    if getattr(content, "name", None):
                        info["name"] = content.name
                    arguments = getattr(content, "arguments", None)
                    if arguments:
                        info["args"] += (
                            arguments
                            if isinstance(arguments, str)
                            else json.dumps(arguments, ensure_ascii=False)
                        )

                elif content_type == "function_result":
                    await flush_tool_steps()
                    call_id = getattr(content, "call_id", None) or "?"
                    info = tool_calls.get(call_id)
                    result = str(getattr(content, "result", "") or "")
                    if info and info["step"] is not None:
                        if info["started"] is not None:
                            elapsed = perf_counter() - info["started"]
                            info["step"].name = f"🔧 {info['name']} ({elapsed:.1f}s)"
                        if result:
                            info["step"].output = result
                        await info["step"].update()

                elif content_type == "text":
                    await flush_tool_steps()
                    token = getattr(content, "text", "") or ""
                    if token:
                        answer_text += token
                        await answer_message.stream_token(token)

        await flush_reasoning()
        await flush_tool_steps()
        elapsed_total = perf_counter() - round_started
        reasoning_step.name = f"생각 중 (총 {elapsed_total:.1f}s)"
        if not any_process:
            reasoning_step.output = "(이 라운드에서는 별도 사고 과정이 관측되지 않았습니다.)"
        await reasoning_step.update()

    await answer_message.update()
    return answer_text, trace, visual


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await answer_and_render(message.content)


async def answer_and_render(question_input: str) -> None:
    reflection_enabled = bool(cl.user_session.get("reflection"))
    max_rounds = 2 if reflection_enabled else 1
    original_question = question_input
    question = question_input
    answer_text = ""
    trace: TraceRecorder | None = None
    visual: VisualRecorder | None = None
    rounds: list[tuple[str, list, list]] = []
    reset_trace()

    for round_number in range(1, max_rounds + 1):
        answer_text, trace, visual = await _stream_answer(question)
        rounds.append((question, trace.steps, trace.sources))
        if round_number == max_rounds:
            break
        try:
            verdict = await critique(original_question, answer_text, trace.sources)
        except Exception as exc:  # noqa: BLE001
            cl.logger.warning(
                f"reflection critique failed: {exc}; treating as sufficient"
            )
            break
        if verdict.sufficient:
            break
        async with cl.Step(
            name="🔍 자가 점검: 보완 필요",
            type="reflection",
        ) as reflection_step:
            reflection_step.output = (
                f"부족한 부분: {verdict.missing}\n"
                "→ 보완 질의로 다시 조회합니다."
            )
        question = augmented_question(original_question, verdict.missing)

    if trace is None or visual is None:
        return

    elements = _visual_elements(visual.items)
    if elements:
        await cl.Message(content="📊 시각화", elements=elements).send()

    used = cited_sources(answer_text, trace.sources)
    sources = used or dedup_sources(trace.sources)
    heading = "근거" if used else "참고한 자료"
    citations = format_citations(sources, heading=heading)
    if citations:
        await cl.Message(content=citations).send()

    if cl.user_session.get("debug"):
        debug_markdown = format_debug(
            rounds,
            used,
            raw_trace=collect_trace_json(),
        )
        debug_store = dict(cl.user_session.get("debug_store") or {})
        debug_id = uuid.uuid4().hex
        debug_store[debug_id] = debug_markdown
        while len(debug_store) > _DEBUG_HISTORY_LIMIT:
            debug_store.pop(next(iter(debug_store)))
        cl.user_session.set("debug_store", debug_store)
        await cl.ElementSidebar.set_title("🐞 디버그 트레이스")
        await cl.ElementSidebar.set_elements(
            [cl.Text(content=debug_markdown, name="debug-trace")]
        )
        await cl.Message(
            content="",
            actions=[
                cl.Action(
                    name="show_debug",
                    payload={"id": debug_id},
                    label="🐞 디버그 보기",
                    tooltip="이 답변의 트레이스를 우측 패널에서 다시 엽니다",
                )
            ],
        ).send()

    if cl.user_session.get("answer_evaluation"):
        await _schedule_answer_evaluation(original_question, answer_text, trace)


async def _run_answer_evaluation(
    question: str,
    answer: str,
    trace: TraceRecorder,
    status_message: cl.Message,
) -> None:
    try:
        ground_truth = find_reference_answer(question)
        result = await cl.make_async(evaluate_existing_answer)(
            question=question,
            answer=answer,
            sources=trace.sources,
            evidence=trace.evidence,
            ground_truth=ground_truth,
        )
        evaluation_markdown = format_live_evaluation(result)
        evaluation_store = dict(cl.user_session.get("evaluation_store") or {})
        evaluation_id = uuid.uuid4().hex
        evaluation_store[evaluation_id] = evaluation_markdown
        while len(evaluation_store) > _EVALUATION_HISTORY_LIMIT:
            evaluation_store.pop(next(iter(evaluation_store)))
        cl.user_session.set("evaluation_store", evaluation_store)

        status_message.content = "답변 평가 완료"
        status_message.actions = [
            cl.Action(
                name="show_evaluation",
                payload={"id": evaluation_id},
                label="답변 평가 보기",
                tooltip="이 답변의 품질 평가 결과를 우측 패널에서 엽니다",
            )
        ]
    except Exception:  # noqa: BLE001 - 평가 실패는 기존 답변과 격리
        cl.logger.exception("live answer evaluation failed")
        status_message.content = "답변 평가 실패"
        status_message.actions = []
    await status_message.update()


async def _schedule_answer_evaluation(
    question: str,
    answer: str,
    trace: TraceRecorder,
) -> None:
    status_message = cl.Message(content="답변 평가 중")
    await status_message.send()
    task = asyncio.create_task(
        _run_answer_evaluation(question, answer, trace, status_message)
    )
    _EVALUATION_TASKS.add(task)
    task.add_done_callback(_EVALUATION_TASKS.discard)


@cl.action_callback("show_debug")
async def show_debug(action: cl.Action) -> None:
    debug_store = cl.user_session.get("debug_store") or {}
    debug_markdown = debug_store.get(action.payload.get("id", ""))
    if not debug_markdown:
        return
    await cl.ElementSidebar.set_title("🐞 디버그 트레이스")
    await cl.ElementSidebar.set_elements(
        [cl.Text(content=debug_markdown, name="debug-trace")]
    )


@cl.action_callback("show_evaluation")
async def show_evaluation(action: cl.Action) -> None:
    evaluation_store = cl.user_session.get("evaluation_store") or {}
    evaluation_markdown = evaluation_store.get(action.payload.get("id", ""))
    if not evaluation_markdown:
        return
    await cl.ElementSidebar.set_title("답변 평가")
    await cl.ElementSidebar.set_elements(
        [cl.Text(content=evaluation_markdown, name="answer-evaluation")]
    )
