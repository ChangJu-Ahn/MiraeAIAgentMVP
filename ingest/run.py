from __future__ import annotations

import argparse
from collections import Counter

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from config.settings import get_settings
from ingest.catalog import (
    CatalogCoverage,
    FundCatalogEntry,
    annotate_chunks,
    extract_fund_catalog,
)
from ingest.chunker import chunk_document
from ingest.embedder import embed_texts
from ingest.facts import EvaluationFact, extract_evaluation_facts
from ingest.figures import build_figure_chunks
from ingest.indexer import ensure_indexes, reset_indexes, upload_chunks
from ingest.parser import analyze_pdf
from ingest.structured_indexer import (
    ensure_structured_indexes,
    replace_catalog,
    replace_facts,
)


def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool, figures: bool = True,
        reset: bool = False, year: int | None = None, doc_type: str | None = None,
    fund_scale: str | None = None, validate_only: bool = False,
    expected_overall_grade_count: int | None = None,
    expected_overall_grade_excluded_fund_ids: tuple[str, ...] = ()) -> int:
    is_report = doc_type == "report"

    # ── Phase 1: pure extraction (no Azure, no Vision) ────────────────────────
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc, year=year, doc_type=doc_type, fund_scale_default=fund_scale)

    catalog: list[FundCatalogEntry] = []
    coverage: CatalogCoverage | None = None
    facts: list[EvaluationFact] = []

    if is_report:
        catalog = extract_fund_catalog(doc, year=year or 0, doc_id=doc_id)
        coverage = annotate_chunks(chunks, catalog)
        chunks = coverage.chunks
        facts = extract_evaluation_facts(chunks, catalog=catalog)

        # ── Completeness validation ───────────────────────────────────────────
        if coverage.missing_fund_ids:
            raise ValueError(
                f"missing_fund_ids for {doc_id}: {coverage.missing_fund_ids}"
            )

        catalog_fund_ids = {e.fund_id for e in catalog}

        # C3: reject facts whose fund_id is absent from the catalog
        external_facts = [f for f in facts if f.fund_id not in catalog_fund_ids]
        if external_facts:
            external_detail = sorted(
                set((f.fund_id, f.id) for f in external_facts)
            )
            raise ValueError(
                f"external_fact_fund_ids for {doc_id}: {external_detail}"
            )

        # C2: exactly one asset_management_performance fact per catalog fund
        amp_counter: Counter[str] = Counter(
            f.fund_id for f in facts
            if f.metric_code == "asset_management_performance"
        )
        amp_violations: list[str] = []
        for entry in sorted(catalog, key=lambda e: e.fund_id):
            count = amp_counter.get(entry.fund_id, 0)
            if count != 1:
                amp_violations.append(
                    f"{entry.canonical_name}(fund_id={entry.fund_id}, count={count})"
                )
        if amp_violations:
            raise ValueError(
                f"asset_management_performance count != 1 for {doc_id}: "
                f"{amp_violations}"
            )

        overall_grade_fund_ids = {
            fact.fund_id for fact in facts if fact.metric_code == "overall_grade"
        }
        if expected_overall_grade_count is not None:
            actual_excluded_fund_ids = catalog_fund_ids - overall_grade_fund_ids
            expected_excluded_fund_ids = set(
                expected_overall_grade_excluded_fund_ids
            )
            if (
                len(overall_grade_fund_ids) != expected_overall_grade_count
                or actual_excluded_fund_ids != expected_excluded_fund_ids
            ):
                raise ValueError(
                    f"overall_grade evaluated population mismatch for {doc_id}: "
                    f"expected_count={expected_overall_grade_count}, "
                    f"actual_count={len(overall_grade_fund_ids)}, "
                    f"expected_excluded={sorted(expected_excluded_fund_ids)}, "
                    f"actual_excluded={sorted(actual_excluded_fund_ids)}"
                )

        # ── Post-validation figure build (Vision calls happen here) ───────────
        if figures and not validate_only:
            fig_chunks = build_figure_chunks(
                doc, pdf, year=year, doc_type=doc_type, fund_scale_default=fund_scale
            )
            if fig_chunks:
                chunks = chunks + fig_chunks
                # Re-annotate combined so figures get authoritative identity
                coverage = annotate_chunks(chunks, catalog)
                chunks = coverage.chunks

        n_perf = sum(amp_counter.values())
        n_table = sum(1 for c in chunks if c.chunk_type == "table")
        n_fig = sum(1 for c in chunks if c.chunk_type == "figure")
        n_total = len(chunks)
        vo_marker = " [VALIDATE-ONLY]" if validate_only else ""
        print(
            f"doc_id={doc_id} chunks={n_total} "
            f"(narrative={n_total - n_table - n_fig}, table={n_table}, figure={n_fig}) "
            f"catalog={len(catalog)} annotated={coverage.annotated_fund_count} "
            f"facts={len(facts)} asset_management_performance={n_perf} "
            f"overall_grade={len(overall_grade_fund_ids)} "
            f"missing_facts=0{vo_marker}"
        )

        if validate_only:
            return len(chunks)

    else:
        # Guideline path — figures only in real ingest
        if figures and not validate_only:
            chunks += build_figure_chunks(
                doc, pdf, year=year, doc_type=doc_type, fund_scale_default=fund_scale
            )
        n_table = sum(1 for c in chunks if c.chunk_type == "table")
        n_fig = sum(1 for c in chunks if c.chunk_type == "figure")
        n_total = len(chunks)
        vo_marker = " [VALIDATE-ONLY]" if validate_only else ""
        print(
            f"doc_id={doc_id} chunks={n_total} "
            f"(narrative={n_total - n_table - n_fig}, table={n_table}, "
            f"figure={n_fig}){vo_marker}"
        )
        if validate_only:
            return len(chunks)

    # ── Phase 2: embedding + Azure writes ─────────────────────────────────────
    vectors = embed_texts([c.content for c in chunks])
    if len(vectors) != len(chunks):
        raise ValueError(
            f"vector count mismatch: {len(vectors)} vectors for {len(chunks)} chunks"
        )
    for c, v in zip(chunks, vectors):
        c.content_vector = v

    if reset:
        reset_indexes()
    else:
        ensure_indexes()

    if is_report:
        ensure_structured_indexes()

    total = upload_chunks(chunks)

    if is_report:
        s = get_settings()
        cred = DefaultAzureCredential()
        cat_client = SearchClient(
            endpoint=s.search_endpoint,
            index_name=s.search_index_catalog,
            credential=cred,
        )
        facts_client = SearchClient(
            endpoint=s.search_endpoint,
            index_name=s.search_index_facts,
            credential=cred,
        )
        replace_catalog(doc_id, catalog, cat_client)
        replace_facts(doc_id, facts, facts_client)

    return total


def run_corpus(reset: bool = False, use_cache: bool = True, figures: bool = True,
               validate_only: bool = False) -> int:
    from ingest.corpus import CORPUS
    total = 0
    for i, d in enumerate(CORPUS):
        total += run(d.pdf, d.doc_id, None, use_cache, figures,
                     reset=(reset and i == 0),
                     year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale,
                     validate_only=validate_only,
                     expected_overall_grade_count=d.expected_overall_grade_count,
                     expected_overall_grade_excluded_fund_ids=(
                         d.expected_overall_grade_excluded_fund_ids
                     ))
    return total


def main() -> None:
    from agent.observability import setup_observability
    from ingest.corpus import get_doc

    setup_observability()
    ap = argparse.ArgumentParser(description="Ingest fund-evaluation PDFs into Azure AI Search")
    ap.add_argument("--all", action="store_true", help="레지스트리 전체 인제스트")
    ap.add_argument("--doc-id", help="레지스트리의 특정 문서만 인제스트")
    ap.add_argument("--pages", default=None, help="예: '1-100' (DI 페이지 범위)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-figures", action="store_true", help="그림 설명 인덱싱 비활성")
    ap.add_argument("--reset", action="store_true", help="인덱스 삭제 후 재생성(스키마 반영)")
    ap.add_argument("--validate-only", action="store_true",
                    help="추출·검증만 수행; 임베딩/Azure Search 쓰기 없음")
    args = ap.parse_args()

    if args.all:
        run_corpus(reset=args.reset, use_cache=not args.no_cache,
                   figures=not args.no_figures, validate_only=args.validate_only)
        return
    if not args.doc_id:
        ap.error("--all 또는 --doc-id 중 하나가 필요합니다")
    d = get_doc(args.doc_id)
    if d is None:
        ap.error(f"레지스트리에 없는 doc_id: {args.doc_id}")
    run(d.pdf, d.doc_id, args.pages, use_cache=not args.no_cache, figures=not args.no_figures,
        reset=args.reset, year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale,
        validate_only=args.validate_only,
        expected_overall_grade_count=d.expected_overall_grade_count,
        expected_overall_grade_excluded_fund_ids=(
            d.expected_overall_grade_excluded_fund_ids
        ))


if __name__ == "__main__":
    main()
