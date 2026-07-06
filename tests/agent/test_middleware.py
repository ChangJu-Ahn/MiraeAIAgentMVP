import asyncio


def test_process_recorder_basic():
    from agent.middleware import ProcessEvent, ProcessRecorder

    rec = ProcessRecorder()
    rec.events.append(ProcessEvent(kind="plan", title="계획", detail="x"))
    assert rec.events[0].kind == "plan"
    rec.reset()
    assert rec.events == []


def test_tool_middleware_records_tool_event():
    from agent.middleware import ProcessRecorder, ToolProcessMiddleware

    rec = ProcessRecorder()
    mw = ToolProcessMiddleware(rec)

    class _Fn:
        name = "search_narrative"

    class _Ctx:
        function = _Fn()
        arguments = {"query": "탁월"}
        result = "결과 텍스트"

    async def call_next():
        return None

    asyncio.run(mw.process(_Ctx(), call_next))
    assert rec.events and rec.events[-1].kind == "tool"
    assert rec.events[-1].title == "search_narrative"
    assert "탁월" in rec.events[-1].detail


def test_stringify_handles_content_types():
    from agent.middleware import _stringify

    class _C:
        def __init__(self, text):
            self.text = text

    assert _stringify(None) == ""
    assert _stringify("plain") == "plain"
    assert _stringify(_C("x")) == "x"
    assert _stringify([_C("a"), _C("b")]) == "a b"
