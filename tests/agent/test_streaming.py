import asyncio


def test_start_stream_streams_text_and_records_steps():
    from agent.orchestrator import start_stream

    async def run():
        stream, trace, _visual = start_stream("자산운용 평가의 목적은?")
        chunks = 0
        text = ""
        async for update in stream:
            if update.text:
                chunks += 1
                text += update.text
        return chunks, text, trace

    chunks, text, trace = asyncio.run(run())
    assert chunks >= 2, "expected incremental token deltas (streaming)"
    assert text.strip()
    assert trace.steps, "expected at least one tool-call step recorded during stream"
