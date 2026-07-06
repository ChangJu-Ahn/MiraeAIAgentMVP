from __future__ import annotations

import argparse

from ingest.chunker import chunk_document
from ingest.embedder import embed_texts
from ingest.indexer import ensure_indexes, upload_chunks
from ingest.parser import analyze_pdf


def run(pdf: str, doc_id: str, pages: str | None, use_cache: bool) -> int:
    ensure_indexes()
    doc = analyze_pdf(pdf, doc_id, pages=pages, use_cache=use_cache)
    chunks = chunk_document(doc)
    vectors = embed_texts([c.content for c in chunks])
    for c, v in zip(chunks, vectors):
        c.content_vector = v
    total = upload_chunks(chunks)
    n_table = sum(1 for c in chunks if c.chunk_type == "table")
    print(f"doc_id={doc_id} chunks={total} (narrative={total - n_table}, table={n_table})")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest a PDF into Azure AI Search")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--pages", default=None, help="e.g. '1-100' (DI page range)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    run(args.pdf, args.doc_id, args.pages, use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
