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
