from ingest.models import Chunk, ParsedDoc, ParsedParagraph, ParsedTable


def test_parsed_doc_holds_elements():
    doc = ParsedDoc(
        doc_id="d1",
        paragraphs=[ParsedParagraph(role="title", content="T", page=1)],
        tables=[ParsedTable(markdown="| a |\n|---|", page=2, caption="cap")],
    )
    assert doc.paragraphs[0].role == "title"
    assert doc.tables[0].page == 2


def test_chunk_defaults():
    c = Chunk(
        id="d1-0",
        doc_id="d1",
        content="body",
        chunk_type="narrative",
        section_path="Ⅱ > 1 > 가",
        page_printed=24,
        page_physical=40,
    )
    assert c.page_printed == 24
    assert c.content_vector is None
