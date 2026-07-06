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


def _stringify(result: object) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    items = result if isinstance(result, (list, tuple)) else [result]
    parts: list[str] = []
    for it in items:
        text = getattr(it, "text", None)
        if text is None:
            to_dict = getattr(it, "to_dict", None)
            if callable(to_dict):
                try:
                    text = to_dict().get("text")
                except Exception:  # noqa: BLE001
                    text = None
        parts.append(text if isinstance(text, str) else str(it))
    return " ".join(p for p in parts if p)


class ToolProcessMiddleware(FunctionMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        name = getattr(getattr(context, "function", None), "name", "tool")
        args = getattr(context, "arguments", None)
        await call_next()
        result_str = _stringify(getattr(context, "result", ""))
        if len(result_str) > 240:
            result_str = result_str[:240] + "…"
        self._recorder.events.append(
            ProcessEvent(kind="tool", title=str(name), detail=f"입력: {args}\n결과: {result_str}")
        )


class PlanningChatMiddleware(ChatMiddleware):
    def __init__(self, recorder: ProcessRecorder) -> None:
        self._recorder = recorder

    async def process(self, context, call_next) -> None:  # noqa: ANN001
        await call_next()
        result = getattr(context, "result", None)
        # 스트림(ResponseStream 등)은 절대 소비하지 않는다.
        if result is None or hasattr(result, "__aiter__") or hasattr(result, "__iter__") and not isinstance(result, (str, list, tuple)):
            return
        text = getattr(result, "text", None)
        if isinstance(text, str) and text.strip():
            snippet = text.strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            self._recorder.events.append(
                ProcessEvent(kind="plan", title="계획/사고", detail=snippet)
            )
