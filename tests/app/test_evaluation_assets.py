from __future__ import annotations

import tomllib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]

THEME_VARIABLES = {
    "--cp-bg",
    "--cp-bg-elevated",
    "--cp-surface",
    "--cp-surface-soft",
    "--cp-border",
    "--cp-border-strong",
    "--cp-text",
    "--cp-text-muted",
    "--cp-text-soft",
    "--cp-accent",
    "--cp-accent-hover",
    "--cp-accent-soft",
    "--cp-accent-fg",
    "--cp-success",
    "--cp-danger",
    "--cp-warning",
    "--cp-link",
    "--cp-shadow",
    "--cp-overlay",
    "--cp-panel",
    "--cp-panel-strong",
    "--cp-sheen",
    "--cp-highlight",
}


def test_chainlit_registers_official_evaluation_header_link():
    config = tomllib.loads(
        (ROOT / ".chainlit" / "config.toml").read_text(encoding="utf-8")
    )

    assert config["UI"]["header_links"] == [
        {
            "name": "Evaluation",
            "display_name": "Evaluation",
            "icon_url": "/public/evaluation-icon.png",
            "url": "/public/evaluation.html",
            "target": "_blank",
        }
    ]


def test_evaluation_dashboard_has_theme_methodology_and_safe_dom_contract():
    html = (ROOT / "public" / "evaluation.html").read_text(encoding="utf-8")

    first_script = html.index("<script>")
    first_style = html.index("<style>")
    assert first_script < first_style
    assert 'new URLSearchParams(window.location.search).get("scoutTheme")' in html
    assert 'document.documentElement.setAttribute("data-theme", theme)' in html
    for variable in THEME_VARIABLES:
        assert variable in html

    assert 'fetch("./evaluation-data.json")' in html
    assert "textContent" in html
    assert "innerHTML" not in html
    assert 'id="evaluation-search"' in html
    assert 'data-status="all"' in html
    assert 'data-status="pass"' in html
    assert 'data-status="review"' in html
    assert "서로 다른 5개 모델을 의미하지 않습니다" in html
    assert "Groundedness" in html
    assert "Similarity" in html
    assert "@media (max-width: 760px)" in html
    assert "@media (max-width: 480px)" in html


def test_evaluation_icon_is_a_small_transparent_png():
    with Image.open(ROOT / "public" / "evaluation-icon.png") as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (64, 64)


def test_container_includes_dashboard_and_runtime_evaluator_without_raw_reports():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "COPY eval/ eval/" in dockerfile
    assert "COPY public/ public/" in dockerfile
    assert "eval" not in ignored
    assert "reports" in ignored