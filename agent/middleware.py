from __future__ import annotations

from agent_framework import ChatMiddleware, FunctionMiddleware
from pydantic import BaseModel


class ProcessEvent(BaseModel):
    kind: str  # "plan" | "tool"
    title: str
    detail: str


class ProcessRecorder(BaseModel):
    events: list[ProcessEvent] = []

    def reset(self) -> None:
        self.events.clear()


class ToolProcessMiddleware(FunctionMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        name = getattr(getattr(context, "function", None), "name", "tool")
        args = getattr(context, "arguments", None)
        await call_next()
        result = getattr(context, "result", "")
        result_str = str(result)
        if len(result_str) > 200:
            result_str = result_str[:200] + "…"
        self._recorder.events.append(
            ProcessEvent(kind="tool", title=str(name), detail=f"{args} → {result_str}")
        )


class PlanningChatMiddleware(ChatMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        await call_next()
        result = getattr(context, "result", None)
        # 스트림은 소비하지 않는다. 텍스트를 안전히 읽을 수 있을 때만 계획 이벤트 기록.
        text = getattr(result, "text", None) if result is not None else None
        if isinstance(text, str) and text.strip():
            snippet = text.strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            self._recorder.events.append(
                ProcessEvent(kind="plan", title="계획/사고", detail=snippet)
            )
