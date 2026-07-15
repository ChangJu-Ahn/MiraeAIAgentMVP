import asyncio
from types import SimpleNamespace


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

    def fake_start_stream(question, *, session=None):
        calls.append((question, session))
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

    monkeypatch.setattr(chat, "start_stream", fake_start_stream)
    monkeypatch.setattr(chat.cl, "Message", FakeMessage)
    monkeypatch.setattr(
        chat.cl.user_session,
        "get",
        lambda key: session if key == "agent_session" else None,
    )

    first = asyncio.run(chat._stream_answer("질문"))
    second = asyncio.run(chat._stream_answer("후속 질문"))

    assert calls == [("질문", session), ("후속 질문", session)]
    assert first == ("첫 답변", trace, visual)
    assert second == ("첫 답변", trace, visual)
    assert messages[0].tokens == ["첫 ", "답변"]
    assert all(message.updated for message in messages)


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
