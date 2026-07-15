import asyncio
from types import SimpleNamespace


def test_chat_start_sends_debug_and_reasoning_settings(monkeypatch):
    from app import chat

    agent_session = object()
    stored = {}
    settings_inputs = []

    class FakeSendable:
        def __init__(self, content=""):
            self.content = content

        async def send(self):
            return self

    class FakeChatSettings(FakeSendable):
        def __init__(self, inputs):
            super().__init__()
            settings_inputs.extend(inputs)

    monkeypatch.setattr(chat, "new_session", lambda: agent_session)
    monkeypatch.setattr(chat.cl.user_session, "set", stored.__setitem__)
    monkeypatch.setattr(chat.cl, "ChatSettings", FakeChatSettings)
    monkeypatch.setattr(chat.cl, "Message", FakeSendable)

    asyncio.run(chat.on_chat_start())

    assert stored == {
        "debug": False,
        "effort": "medium",
        "reflection": False,
        "agent_session": agent_session,
    }
    assert [widget.id for widget in settings_inputs] == [
        "debug",
        "reflection",
        "effort",
    ]


def test_settings_update_persists_values_and_closes_disabled_debug(monkeypatch):
    from app import chat

    stored = {}
    sidebar_updates = []

    async def set_elements(elements):
        sidebar_updates.append(elements)

    monkeypatch.setattr(chat.cl.user_session, "set", stored.__setitem__)
    monkeypatch.setattr(chat.cl.ElementSidebar, "set_elements", set_elements)

    asyncio.run(
        chat.on_settings_update(
            {"debug": False, "effort": "high", "reflection": True}
        )
    )

    assert stored == {"debug": False, "effort": "high", "reflection": True}
    assert sidebar_updates == [[]]


def test_stream_answer_runs_one_agent_stream_and_returns_recorders(monkeypatch):
    from app import chat

    session = object()
    trace = object()
    visual = object()
    calls = []
    messages = []

    async def updates():
        yield SimpleNamespace(
            contents=[
                SimpleNamespace(type="text_reasoning", text="내부 추론"),
                SimpleNamespace(type="text", text="첫 "),
            ]
        )
        yield SimpleNamespace(
            contents=[SimpleNamespace(type="text", text="답변")]
        )

    def fake_start_stream(question, effort="medium", *, session=None):
        calls.append((question, effort, session))
        return updates(), trace, visual

    class FakeMessage:
        def __init__(self, content):
            self.content = content
            self.tokens = []
            self.updated = False
            messages.append(self)

        async def stream_token(self, token):
            self.tokens.append(token)

        async def update(self):
            self.updated = True

    class FakeStep:
        def __init__(self, name, type, parent_id=None):
            self.id = "reasoning-step"
            self.name = name
            self.output = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def stream_token(self, token):
            return None

        async def update(self):
            return self

    monkeypatch.setattr(chat, "start_stream", fake_start_stream)
    monkeypatch.setattr(chat.cl, "Message", FakeMessage)
    monkeypatch.setattr(chat.cl, "Step", FakeStep)
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        {"agent_session": session, "effort": "high"}.get,
    )

    first = asyncio.run(chat._stream_answer("질문"))
    second = asyncio.run(chat._stream_answer("후속 질문"))

    assert calls == [
        ("질문", "high", session),
        ("후속 질문", "high", session),
    ]
    assert first == ("첫 답변", trace, visual)
    assert second == ("첫 답변", trace, visual)
    assert messages[0].tokens == ["첫 ", "답변"]
    assert all(message.updated for message in messages)


def test_stream_answer_renders_reasoning_tool_steps_and_timing(monkeypatch):
    from app import chat

    session = object()
    trace = object()
    visual = object()
    steps = []

    async def updates():
        yield SimpleNamespace(
            contents=[
                SimpleNamespace(
                    type="text_reasoning",
                    id="reason-1",
                    text="근거를 찾습니다.",
                )
            ]
        )
        yield SimpleNamespace(
            contents=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call-1",
                    name="search_narrative",
                    arguments='{"query":"평가 목적","year":2022}',
                )
            ]
        )
        yield SimpleNamespace(
            contents=[
                SimpleNamespace(
                    type="function_result",
                    call_id="call-1",
                    result="검색 결과 2건",
                )
            ]
        )
        yield SimpleNamespace(
            contents=[SimpleNamespace(type="text", text="최종 답변")]
        )

    def fake_start_stream(question, effort="medium", *, session=None):
        return updates(), trace, visual

    class FakeMessage:
        def __init__(self, content):
            self.tokens = []

        async def stream_token(self, token):
            self.tokens.append(token)

        async def update(self):
            return None

    class FakeStep:
        def __init__(self, name, type, parent_id=None):
            self.id = f"step-{len(steps) + 1}"
            self.name = name
            self.type = type
            self.parent_id = parent_id
            self.input = None
            self.output = None
            self.tokens = []
            steps.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def stream_token(self, token):
            self.tokens.append(token)

        async def send(self):
            return self

        async def update(self):
            return self

    clock = iter([10.0, 11.0, 13.5, 15.0])
    monkeypatch.setattr(chat, "start_stream", fake_start_stream)
    monkeypatch.setattr(chat.cl, "Message", FakeMessage)
    monkeypatch.setattr(chat.cl, "Step", FakeStep)
    monkeypatch.setattr(chat, "perf_counter", lambda: next(clock), raising=False)
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        {"agent_session": session, "effort": "medium"}.get,
    )

    answer, returned_trace, returned_visual = asyncio.run(
        chat._stream_answer("질문")
    )

    assert (answer, returned_trace, returned_visual) == (
        "최종 답변",
        trace,
        visual,
    )
    assert len(steps) == 2
    reasoning_step, tool_step = steps
    assert reasoning_step.name == "생각 중 (총 5.0s)"
    assert reasoning_step.tokens == ["\n근거를 찾습니다.\n"]
    assert tool_step.name == "🔧 search_narrative (2.5s)"
    assert tool_step.parent_id == reasoning_step.id
    assert tool_step.input == '질의: "평가 목적"\n필터: year=2022'
    assert tool_step.output == "검색 결과 2건"


def test_stream_answer_streams_reasoning_without_translation(monkeypatch):
    from app import chat

    reasoning_tokens = []

    async def updates():
        yield SimpleNamespace(
            contents=[
                SimpleNamespace(
                    type="text_reasoning",
                    id="reason-1",
                    text="Searching for evidence.",
                ),
                SimpleNamespace(type="text", text="답변"),
            ]
        )

    def fake_start_stream(question, effort="medium", *, session=None):
        return updates(), object(), object()

    class FakeMessage:
        def __init__(self, content):
            return None

        async def stream_token(self, token):
            return None

        async def update(self):
            return None

    class FakeStep:
        def __init__(self, name, type, parent_id=None):
            self.id = "reasoning-step"
            self.name = name
            self.output = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def stream_token(self, token):
            reasoning_tokens.append(token)

        async def update(self):
            return self

    monkeypatch.setattr(chat, "start_stream", fake_start_stream)
    monkeypatch.setattr(chat.cl, "Message", FakeMessage)
    monkeypatch.setattr(chat.cl, "Step", FakeStep)
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        {"agent_session": object(), "effort": "medium"}.get,
    )

    asyncio.run(chat._stream_answer("질문"))

    assert reasoning_tokens == ["\nSearching for evidence.\n"]


def test_answer_and_render_runs_one_reflection_round_when_needed(monkeypatch):
    from app import chat

    trace = SimpleNamespace(steps=[], sources=[])
    visual = SimpleNamespace(items=[])
    stream_questions = []
    critique_calls = []
    reflection_steps = []

    async def fake_stream_answer(question):
        stream_questions.append(question)
        return f"답변 {len(stream_questions)}", trace, visual

    async def fake_critique(question, answer, sources):
        critique_calls.append((question, answer, sources))
        return SimpleNamespace(sufficient=False, missing="추가 근거")

    class FakeStep:
        def __init__(self, name, type, parent_id=None):
            self.name = name
            self.type = type
            self.output = None
            reflection_steps.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(chat, "_stream_answer", fake_stream_answer)
    monkeypatch.setattr(chat, "critique", fake_critique, raising=False)
    monkeypatch.setattr(chat.cl, "Step", FakeStep)
    monkeypatch.setattr(chat, "reset_trace", lambda: None)
    monkeypatch.setattr(chat, "_visual_elements", lambda visuals: [])
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        {"reflection": True, "debug": False}.get,
    )

    asyncio.run(chat.answer_and_render("원 질문"))

    assert stream_questions[0] == "원 질문"
    assert "[보완 지시]" in stream_questions[1]
    assert "추가 근거" in stream_questions[1]
    assert critique_calls == [("원 질문", "답변 1", [])]
    assert reflection_steps[0].name == "🔍 자가 점검: 보완 필요"
    assert "추가 근거" in reflection_steps[0].output


def test_on_message_stores_and_opens_debug_trace(monkeypatch):
    from app import chat

    trace = SimpleNamespace(steps=[], sources=[])
    visual = SimpleNamespace(items=[])
    stored = {}
    sent_messages = []
    sidebar_titles = []
    sidebar_elements = []
    reset_calls = []

    async def fake_stream_answer(question):
        return "최종 답변", trace, visual

    async def set_title(title):
        sidebar_titles.append(title)

    async def set_elements(elements):
        sidebar_elements.append(elements)

    class FakeMessage:
        def __init__(self, content="", actions=None, elements=None):
            self.content = content
            self.actions = actions or []
            self.elements = elements or []

        async def send(self):
            sent_messages.append(self)
            return self

    class FakeAction:
        def __init__(self, name, payload, label, tooltip):
            self.name = name
            self.payload = payload
            self.label = label
            self.tooltip = tooltip

    class FakeText:
        def __init__(self, content, name):
            self.content = content
            self.name = name

    monkeypatch.setattr(chat, "_stream_answer", fake_stream_answer)
    monkeypatch.setattr(chat, "reset_trace", lambda: reset_calls.append(True), raising=False)
    monkeypatch.setattr(
        chat,
        "collect_trace_json",
        lambda: '[{"name": "agent-run"}]',
        raising=False,
    )
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        {"debug": True, "debug_store": {}}.get,
    )
    monkeypatch.setattr(chat.cl.user_session, "set", stored.__setitem__)
    monkeypatch.setattr(chat.cl, "Message", FakeMessage)
    monkeypatch.setattr(chat.cl, "Action", FakeAction)
    monkeypatch.setattr(chat.cl, "Text", FakeText)
    monkeypatch.setattr(chat.cl.ElementSidebar, "set_title", set_title)
    monkeypatch.setattr(chat.cl.ElementSidebar, "set_elements", set_elements)

    asyncio.run(chat.on_message(SimpleNamespace(content="질문")))

    assert reset_calls == [True]
    assert sidebar_titles == ["🐞 디버그 트레이스"]
    assert len(sidebar_elements) == 1
    assert "Raw OpenTelemetry Trace" in sidebar_elements[0][0].content
    debug_store = stored["debug_store"]
    assert len(debug_store) == 1
    assert next(iter(debug_store.values())) == sidebar_elements[0][0].content
    assert sent_messages[-1].actions[0].name == "show_debug"
    assert sent_messages[-1].actions[0].payload["id"] in debug_store


def test_show_debug_action_reopens_stored_trace(monkeypatch):
    from app import chat

    sidebar_titles = []
    sidebar_elements = []

    async def set_title(title):
        sidebar_titles.append(title)

    async def set_elements(elements):
        sidebar_elements.append(elements)

    class FakeText:
        def __init__(self, content, name):
            self.content = content
            self.name = name

    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        lambda key: {"trace-1": "# 저장된 트레이스"} if key == "debug_store" else None,
    )
    monkeypatch.setattr(chat.cl, "Text", FakeText)
    monkeypatch.setattr(chat.cl.ElementSidebar, "set_title", set_title)
    monkeypatch.setattr(chat.cl.ElementSidebar, "set_elements", set_elements)

    asyncio.run(chat.show_debug(SimpleNamespace(payload={"id": "trace-1"})))

    assert sidebar_titles == ["🐞 디버그 트레이스"]
    assert sidebar_elements[0][0].content == "# 저장된 트레이스"


def test_start_stream_streams_text_and_records_steps():
    from agent.orchestrator import start_stream

    async def run():
        stream, trace, visual = start_stream("자산운용 평가의 목적은?")
        chunks = 0
        text = ""
        async for update in stream:
            if update.text:
                chunks += 1
                text += update.text
        return chunks, text, trace, visual

    chunks, text, trace, visual = asyncio.run(run())
    assert chunks >= 2, "expected incremental token deltas (streaming)"
    assert text.strip()
    assert trace.steps, "expected at least one tool-call step recorded during stream"
    assert isinstance(visual.items, list)
