from __future__ import annotations

import argparse

from ingest.chunker import chunk_document
from ingest.embedder import embed_texts
from ingest.figures import build_figure_chunks
from ingest.indexer import ensure_indexes, reset_indexes, upload_chunks
from ingest.parser import analyze_pdf


def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool, figures: bool = True,
        reset: bool = False, year: int | None = None, doc_type: str | None = None,
        fund_scale: str | None = None) -> int:
    reset_indexes() if reset else ensure_indexes()
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc, year=year, doc_type=doc_type, fund_scale_default=fund_scale)
    if figures:
        chunks += build_figure_chunks(doc, pdf, year=year, doc_type=doc_type, fund_scale_default=fund_scale)
    vectors = embed_texts([c.content for c in chunks])
    for c, v in zip(chunks, vectors):
        c.content_vector = v
    total = upload_chunks(chunks)
    n_table = sum(1 for c in chunks if c.chunk_type == "table")
    n_fig = sum(1 for c in chunks if c.chunk_type == "figure")
    print(
        f"doc_id={doc_id} chunks={total} "
        f"(narrative={total - n_table - n_fig}, table={n_table}, figure={n_fig})"
    )
    return total


def run_corpus(reset: bool = False, use_cache: bool = True, figures: bool = True) -> int:
    from ingest.corpus import CORPUS
    total = 0
    for i, d in enumerate(CORPUS):
        total += run(d.pdf, d.doc_id, None, use_cache, figures,
                     reset=(reset and i == 0),
                     year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale)
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
    args = ap.parse_args()

    if args.all:
        run_corpus(reset=args.reset, use_cache=not args.no_cache, figures=not args.no_figures)
        return
    if not args.doc_id:
        ap.error("--all 또는 --doc-id 중 하나가 필요합니다")
    d = get_doc(args.doc_id)
    if d is None:
        ap.error(f"레지스트리에 없는 doc_id: {args.doc_id}")
    run(d.pdf, d.doc_id, args.pages, use_cache=not args.no_cache, figures=not args.no_figures,
        reset=args.reset, year=d.year, doc_type=d.doc_type, fund_scale=d.fund_scale)


if __name__ == "__main__":
    main()
