from agent.tools import TraceRecorder, make_search_tools


def test_search_narrative_returns_citations_and_records():
    rec = TraceRecorder()
    search_narrative, _search_tables = make_search_tools(rec)
    out = search_narrative("탁월 등급의 의미")
    assert "[출처 1]" in out
    assert rec.steps and rec.steps[0].tool == "search_narrative"
    assert rec.sources and rec.sources[0].section_path is not None


def test_search_tables_records_table_tool():
    rec = TraceRecorder()
    _n, search_tables = make_search_tools(rec)
    out = search_tables("등급 내용 표")
    assert "[출처" in out
    assert rec.steps[-1].tool == "search_tables"
