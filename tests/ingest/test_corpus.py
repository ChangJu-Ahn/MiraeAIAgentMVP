import os
from ingest.corpus import CORPUS, get_doc


def test_corpus_entries_valid():
    assert len(CORPUS) == 5
    ids = [d.doc_id for d in CORPUS]
    assert len(set(ids)) == 5  # doc_id 유일
    for d in CORPUS:
        assert d.doc_type in ("report", "guideline")
        assert 2000 <= d.year <= 2100
        assert os.path.exists(d.pdf), f"missing pdf: {d.pdf}"


def test_get_doc_lookup():
    assert get_doc("report-2025").year == 2025
    assert get_doc("nope") is None
