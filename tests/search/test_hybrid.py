from config.settings import get_settings
from search.hybrid import hybrid_search


def test_hybrid_search_narrative_returns_relevant_hit():
    s = get_settings()
    hits = hybrid_search(s.search_index_narrative, "탁월 등급의 의미", top=5)
    assert hits, "expected at least one hit"
    assert any("탁월" in h.content for h in hits)
    assert all(h.score >= 0 for h in hits)


def test_hybrid_search_table_index():
    s = get_settings()
    hits = hybrid_search(s.search_index_table, "등급 내용 표", top=5)
    assert hits
    assert hits[0].chunk_type == "table"


def test_hybrid_search_accepts_odata_filter():
    s = get_settings()
    # 존재하지 않는 연도로 필터 → 0건(필터가 실제 적용됨을 확인)
    hits = hybrid_search(s.search_index_narrative, "평가", top=5, odata_filter="year eq 1900")
    assert hits == []
