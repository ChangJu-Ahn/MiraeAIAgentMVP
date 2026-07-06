from config.settings import get_settings
from search.hybrid import hybrid_search


def test_hybrid_search_narrative_returns_relevant_hit():
    s = get_settings()
    hits = hybrid_search(s.search_index_narrative, "탁월 등급의 의미", top=5)
    assert hits, "expected at least one hit"
    assert any("탁월" in h.content for h in hits)


def test_hybrid_search_table_index():
    s = get_settings()
    hits = hybrid_search(s.search_index_table, "등급 내용 표", top=5)
    assert hits
    assert hits[0].chunk_type == "table"
