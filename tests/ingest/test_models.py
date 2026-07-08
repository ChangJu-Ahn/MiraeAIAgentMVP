from ingest.models import Chunk, ParsedDoc, ParsedParagraph, ParsedTable


def test_parsed_doc_holds_elements():
    doc = ParsedDoc(
        doc_id="d1",
        paragraphs=[ParsedParagraph(role="title", content="T", page=1)],
        tables=[ParsedTable(markdown="| a |\n|---|", page=2, caption="cap")],
    )
    assert doc.paragraphs[0].role == "title"
    assert doc.tables[0].page == 2


def test_chunk_metadata_defaults():
    c = Chunk(
        id="d1-0", doc_id="d1", content="body", chunk_type="narrative",
        section_path="A", page_printed=24, page_physical=40,
    )
    assert c.year is None
    assert c.doc_type is None
    assert c.fund_name is None
    assert c.fund_scale is None


def test_chunk_metadata_set():
    c = Chunk(
        id="d1-0", doc_id="d1", content="body", chunk_type="table",
        section_path="A", page_physical=40,
        year=2022, doc_type="report", fund_name="국민연금기금", fund_scale="대규모",
    )
    assert (c.year, c.doc_type, c.fund_name, c.fund_scale) == (2022, "report", "국민연금기금", "대규모")
