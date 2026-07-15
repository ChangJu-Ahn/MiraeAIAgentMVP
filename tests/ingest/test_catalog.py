from __future__ import annotations

from pathlib import Path

import pytest

from ingest.catalog import (
    CatalogCoverage,
    CatalogValidationError,
    FundCatalogEntry,
    annotate_chunks,
    extract_fund_catalog,
    fund_id_for,
    normalize_fund_name,
)
from ingest.models import Chunk, ParsedDoc, ParsedParagraph

CACHE_DIR = Path(".ingest_cache")


# ── helpers ───────────────────────────────────────────────────────────────────


def _para(
    content: str,
    *,
    page: int = 3,
    role: str | None = None,
    offset: int = 0,
) -> ParsedParagraph:
    return ParsedParagraph(role=role, content=content, page=page, offset=offset)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _mixed_toc_doc() -> ParsedDoc:
    """
    Three fund entries:
      1. 기금A 49          (inline, 재정경제부)
      2. 국민체육진흥기금(국민체육진흥계정) / 137  (split, parenthesised name)
      3. 기금B / 393       (split, 금융위원회)
    """
    paras = [
        # TOC section heading
        _para("Ⅲ. 2025회계연도 기금별 자산운용평가 결과 45", role="sectionHeading"),
        # Ministry 1
        _para("【재정경제부】", role="sectionHeading"),
        # Entry 1: inline (number + name + page in one paragraph)
        _para("1. 기금A 49"),
        # Entry 2: split – name and page are separate paragraphs
        _para("2. 국민체육진흥기금(국민체육진흥계정)"),
        _para("137"),
        # Ministry 2
        _para("【금융위원회】"),
        # Entry 3: split
        _para("3. 기금B"),
        _para("393"),
        # Body start marker – physical page 7 signals end of TOC region
        _para(
            "Ⅰ. 2025회계연도 기금운용평가 자산운용부문 개요",
            page=7,
            role="title",
        ),
        # pageNumber paragraph: physical page 7 = printed page 1
        _para("- 1 -", page=7, role="pageNumber"),
    ]
    return ParsedDoc(doc_id="report-2025", paragraphs=paras, tables=[], figures=[])


def _toc_with_orders(*orders: int) -> ParsedDoc:
    """Minimal TOC doc with the given toc ordinal numbers."""
    paras: list[ParsedParagraph] = [
        _para("Ⅲ. 2025회계연도 기금별 자산운용평가 결과 45", role="sectionHeading"),
        _para("【재정경제부】", role="sectionHeading"),
    ]
    for n in orders:
        paras.append(_para(f"{n}. 기금{n} {100 + n}"))
    paras.append(
        _para(
            "Ⅰ. 2025회계연도 기금운용평가 자산운용부문 개요",
            page=7,
            role="title",
        )
    )
    paras.append(_para("- 1 -", page=7, role="pageNumber"))
    return ParsedDoc(doc_id="report-2025", paragraphs=paras, tables=[], figures=[])


# ── unit tests: TOC shape parsing ────────────────────────────────────────────


def test_extract_catalog_handles_inline_and_split_toc_entries():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    assert [item.toc_order for item in catalog] == [1, 2, 3]
    assert catalog[1].canonical_name == "국민체육진흥기금(국민체육진흥계정)"
    assert catalog[2].ministry == "금융위원회"
    assert catalog[2].start_page_printed == 393


def test_ministry_carries_forward_to_next_entry():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    assert catalog[0].ministry == "재정경제부"
    assert catalog[1].ministry == "재정경제부"  # no ministry heading between entry 1 and 2


def test_end_pages_are_contiguous():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    # Each fund ends one page before the next fund starts
    assert catalog[0].end_page_printed == 136   # next start 137 − 1
    assert catalog[1].end_page_printed == 392   # next start 393 − 1


def test_fund_id_preserves_parenthesized_account():
    assert "국민체육진흥계정" in fund_id_for("국민체육진흥기금(국민체육진흥계정)")


def test_entry_id_format():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    assert catalog[0].id == "report-2025/001"
    assert catalog[2].id == "report-2025/003"


def test_year_and_doc_id_on_entries():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    assert all(e.year == 2025 for e in catalog)
    assert all(e.doc_id == "report-2025" for e in catalog)


def test_source_page_physical_is_toc_page():
    catalog = extract_fund_catalog(_mixed_toc_doc(), year=2025, doc_id="report-2025")
    # All TOC entries are on physical page 3 in the fixture
    assert all(e.source_page_physical == 3 for e in catalog)


# ── unit tests: validation ────────────────────────────────────────────────────


def test_catalog_rejects_non_contiguous_ordinals():
    with pytest.raises(CatalogValidationError, match="contiguous"):
        extract_fund_catalog(_toc_with_orders(1, 3), year=2025, doc_id="report-2025")


def test_catalog_rejects_duplicate_ordinals():
    with pytest.raises(CatalogValidationError):
        extract_fund_catalog(_toc_with_orders(1, 1, 2), year=2025, doc_id="report-2025")


def test_catalog_rejects_ordinals_not_starting_at_one():
    with pytest.raises(CatalogValidationError):
        extract_fund_catalog(_toc_with_orders(2, 3), year=2025, doc_id="report-2025")


# ── unit tests: normalisation ─────────────────────────────────────────────────


def test_normalize_fund_name_repairs_reviewed_ocr_alias():
    assert normalize_fund_name("농어가목돈마련저축장력기금") == "농어가목돈마련저축장려기금"
    assert normalize_fund_name("농어가목돈마려저축장려기금") == "농어가목돈마련저축장려기금"


def test_catalog_preserves_reviewed_ocr_variants_as_aliases():
    doc = ParsedDoc(
        doc_id="report-2021",
        paragraphs=[
            _para("Ⅲ. 2021회계연도 기금별 자산운용평가 결과", role="sectionHeading"),
            _para("【기획재정부】"),
            _para("1. 농어가목돈마련저축장력기금 49"),
            _para("Ⅰ. 2021회계연도 기금운용평가 개요", page=7, role="title"),
            _para("- 1 -", page=7, role="pageNumber"),
        ],
        tables=[],
        figures=[],
    )

    entry = extract_fund_catalog(doc, year=2021, doc_id="report-2021")[0]

    assert entry.canonical_name == "농어가목돈마련저축장려기금"
    assert set(entry.aliases) == {
        "농어가목돈마련저축장력기금",
        "농어가목돈마려저축장려기금",
    }


def test_normalize_fund_name_passthrough_for_clean_name():
    assert normalize_fund_name("국민연금기금") == "국민연금기금"


def test_normalize_fund_name_strips_surrounding_whitespace():
    assert normalize_fund_name("  국민연금기금  ") == "국민연금기금"


# ── regression: TOC termination uses content marker, not physical page ───────


def _early_body_marker_doc() -> ParsedDoc:
    """TOC entries on physical pages 3–5; body marker appears on physical page 5
    (before the old hardcoded threshold of 7).  The extractor must stop at the
    content marker and NOT include the spurious entry on page 6."""
    paras = [
        _para("Ⅲ. 2025회계연도 기금별 자산운용평가 결과", role="sectionHeading", page=2),
        _para("【재정경제부】", page=3),
        _para("1. 기금A 49", page=3),
        _para("2. 기금B 137", page=4),
        # Body chapter starts at physical page 5 (well below old threshold 7)
        _para("Ⅰ. 기금운용평가 개요", page=5, role="title"),
        _para("- 1 -", page=5, role="pageNumber"),
        # This entry is BODY text, must be excluded from catalog
        _para("3. 기금C 999", page=6),
    ]
    return ParsedDoc(doc_id="report-2025", paragraphs=paras, tables=[], figures=[])


def test_toc_terminates_at_content_marker_not_physical_page():
    """Fails with old `para.page >= 7` guard; passes with content-marker guard."""
    catalog = extract_fund_catalog(_early_body_marker_doc(), year=2025, doc_id="report-2025")
    assert len(catalog) == 2
    assert [e.toc_order for e in catalog] == [1, 2]


# ── cache-backed completeness tests ──────────────────────────────────────────


def _load_catalog(doc_id: str, year: int) -> list[FundCatalogEntry]:
    from ingest.corpus import get_doc
    from ingest.parser import analyze_pdf

    corpus_entry = get_doc(doc_id)
    pdf_path = corpus_entry.pdf if corpus_entry is not None else ""
    doc = analyze_pdf(pdf_path, doc_id, use_cache=True)
    return extract_fund_catalog(doc, year=year, doc_id=doc_id)


@pytest.mark.parametrize(
    ("doc_id", "year", "count"),
    [
        ("report-2021", 2021, 33),
        ("report-2022", 2022, 31),
        ("report-2025", 2025, 25),
    ],
)
def test_cached_report_catalog_is_complete(doc_id: str, year: int, count: int) -> None:
    if not CACHE_DIR.exists():
        pytest.skip("no .ingest_cache directory")
    cache_file = CACHE_DIR / f"{doc_id}.json"
    if not cache_file.exists():
        pytest.skip(f"{cache_file} not present")

    catalog = _load_catalog(doc_id, year)

    # Exact count
    assert len(catalog) == count, (
        f"{doc_id}: expected {count} funds, got {len(catalog)}\n"
        + "\n".join(f"  {e.toc_order}. {e.canonical_name}" for e in catalog)
    )

    # Contiguous ordinals 1..count
    orders = [e.toc_order for e in catalog]
    assert orders == list(range(1, count + 1)), (
        f"{doc_id}: non-contiguous orders {orders}"
    )

    # No duplicate IDs
    ids = [e.id for e in catalog]
    assert len(ids) == len(set(ids)), f"{doc_id}: duplicate IDs found: {ids}"

    # No 대상기금 entity
    for e in catalog:
        assert "대상기금" not in e.canonical_name, (
            f"{doc_id}: found '대상기금' entity in {e.canonical_name!r}"
        )

    # Physical pages populated for funds whose printed page was found in page map
    funds_with_physical = [e for e in catalog if e.start_page_physical is not None]
    assert len(funds_with_physical) > 0, (
        f"{doc_id}: no physical page mapping resolved for any fund"
    )


# ── annotate_chunks tests ─────────────────────────────────────────────────────


def _make_chunk(chunk_id: str, page_physical: int, page_printed: int | None = None) -> Chunk:
    return Chunk(
        id=chunk_id,
        doc_id="report-2025",
        content="text",
        chunk_type="narrative",
        section_path="sec",
        page_physical=page_physical,
        page_printed=page_printed,
    )


def _make_entry(
    fund_id: str,
    start_physical: int,
    end_physical: int,
    start_printed: int = 10,
    end_printed: int = 19,
    ministry: str = "기획재정부",
) -> FundCatalogEntry:
    return FundCatalogEntry(
        id=f"report-2025/001",
        fund_id=fund_id,
        year=2025,
        doc_id="report-2025",
        toc_order=1,
        canonical_name=fund_id,
        ministry=ministry,
        start_page_printed=start_printed,
        end_page_printed=end_printed,
        start_page_physical=start_physical,
        end_page_physical=end_physical,
        source_page_physical=3,
    )


def _two_fund_catalog() -> list[FundCatalogEntry]:
    return [
        FundCatalogEntry(
            id="report-2025/001",
            fund_id="fund-a",
            year=2025,
            doc_id="report-2025",
            toc_order=1,
            canonical_name="기금A",
            ministry="기획재정부",
            start_page_printed=10,
            end_page_printed=15,
            start_page_physical=10,
            end_page_physical=15,
            source_page_physical=3,
        ),
        FundCatalogEntry(
            id="report-2025/002",
            fund_id="fund-b",
            year=2025,
            doc_id="report-2025",
            toc_order=2,
            canonical_name="기금B",
            ministry="금융위원회",
            start_page_printed=20,
            end_page_printed=29,
            start_page_physical=20,
            end_page_physical=29,
            source_page_physical=3,
        ),
    ]


def _chunks_on_pages(*pages: int) -> list[Chunk]:
    return [_make_chunk(f"c{p}", page_physical=p) for p in pages]


def test_annotate_chunks_uses_catalog_page_ranges():
    coverage = annotate_chunks(_chunks_on_pages(10, 11, 20), _two_fund_catalog())
    assert [chunk.fund_id for chunk in coverage.chunks] == ["fund-a", "fund-a", "fund-b"]
    assert coverage.missing_fund_ids == []


def test_overview_chunk_remains_unassigned():
    # Page 5 is before any fund range → overview
    coverage = annotate_chunks(_chunks_on_pages(5), _two_fund_catalog())
    assert coverage.chunks[0].fund_id is None
    assert coverage.chunks[0].ministry is None


def test_annotate_chunks_sets_ministry():
    coverage = annotate_chunks(_chunks_on_pages(10), _two_fund_catalog())
    assert coverage.chunks[0].ministry == "기획재정부"


def test_annotate_chunks_overrides_fund_name():
    chunk = _make_chunk("c10", page_physical=10)
    chunk.fund_name = "heading-derived-name"
    catalog = _two_fund_catalog()
    coverage = annotate_chunks([chunk], catalog)
    assert coverage.chunks[0].fund_name == "기금A"


def test_annotation_rejects_catalog_fund_without_chunks():
    # Only chunks for fund-a; fund-b has no chunks → reported as missing
    coverage = annotate_chunks(_chunks_on_pages(10), _two_fund_catalog())
    assert "fund-b" in coverage.missing_fund_ids


def test_coverage_counts():
    coverage = annotate_chunks(_chunks_on_pages(10, 20), _two_fund_catalog())
    assert coverage.annotated_fund_count == 2
    assert coverage.population_count == 2


def test_annotate_chunks_falls_back_to_printed_pages_when_no_physical():
    """When physical pages are None, printed page range is used as fallback."""
    catalog = [
        FundCatalogEntry(
            id="report-2025/001",
            fund_id="fund-c",
            year=2025,
            doc_id="report-2025",
            toc_order=1,
            canonical_name="기금C",
            ministry="행정부",
            start_page_printed=50,
            end_page_printed=60,
            start_page_physical=None,
            end_page_physical=None,
            source_page_physical=3,
        )
    ]
    chunks = [_make_chunk("cx", page_physical=999, page_printed=55)]
    coverage = annotate_chunks(chunks, catalog)
    assert coverage.chunks[0].fund_id == "fund-c"


def test_annotate_chunks_does_not_mutate_input():
    """annotate_chunks must not mutate caller-supplied Chunk objects."""
    original = _make_chunk("c10", page_physical=10)
    original_fund_id = original.fund_id  # None before annotation
    original_ministry = original.ministry

    coverage = annotate_chunks([original], _two_fund_catalog())

    # Input chunk is unchanged
    assert original.fund_id == original_fund_id
    assert original.ministry == original_ministry

    # Coverage chunk has the authoritative catalog identity
    assert coverage.chunks[0].fund_id == "fund-a"
    assert coverage.chunks[0].ministry == "기획재정부"

    # They are different objects
    assert coverage.chunks[0] is not original
