import json
from pathlib import Path

from ingest.models import ParsedDoc, ParsedFigure
from ingest.parser import _result_to_parsed


def test_parsed_figure_model():
    f = ParsedFigure(page=1, polygon=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0], offset=10)
    assert f.page == 1 and len(f.polygon) == 8 and f.caption is None


def test_parser_captures_figures_from_cache():
    cache = Path(".ingest_cache/gicheum-2025-asset.json")
    if not cache.exists():
        import pytest

        pytest.skip("DI cache not present")
    data = json.loads(cache.read_text(encoding="utf-8"))
    doc = _result_to_parsed("gicheum-2025-asset", data)
    assert isinstance(doc, ParsedDoc)
    assert len(doc.figures) >= 1
    assert all(len(fig.polygon) >= 8 for fig in doc.figures)
    assert all(fig.page >= 1 for fig in doc.figures)


def test_render_and_describe_first_figure():
    import pytest

    from config.settings import get_settings
    from ingest.figures import describe_figure, render_figure_png
    from ingest.parser import analyze_pdf

    s = get_settings()
    doc = analyze_pdf(s.source_pdf_path, "gicheum-2025-asset", use_cache=True)
    if not doc.figures:
        pytest.skip("no figures")
    fig = doc.figures[0]
    png = render_figure_png(s.source_pdf_path, fig.page, fig.polygon)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    desc = describe_figure(png)
    assert desc and len(desc) > 10


def test_build_figure_chunks_subset():
    import pytest

    from config.settings import get_settings
    from ingest.figures import build_figure_chunks
    from ingest.parser import analyze_pdf

    s = get_settings()
    doc = analyze_pdf(s.source_pdf_path, "gicheum-2025-asset", use_cache=True)
    if not doc.figures:
        pytest.skip("no figures")
    doc.figures = doc.figures[:2]
    chunks = build_figure_chunks(doc, s.source_pdf_path)
    assert len(chunks) == 2
    assert all(c.chunk_type == "figure" for c in chunks)
    assert all(c.id.startswith("gicheum-2025-asset-fig-") for c in chunks)
    assert all("[그림]" in c.content for c in chunks)
