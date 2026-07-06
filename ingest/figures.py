from __future__ import annotations

import base64
import io
import os
import subprocess
import tempfile

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from PIL import Image

from config.settings import get_settings
from ingest.chunker import HEADING_ROLES, _heading_depth
from ingest.models import Chunk, ParsedDoc

_SCOPE = "https://cognitiveservices.azure.com/.default"
_PROMPT = (
    "이 그림/차트를 한국어로 2~4문장으로 설명하세요. "
    "제목, 축·범례, 핵심 수치나 추세를 최대한 구체적으로 포함하세요. "
    "그림이 표 형태면 어떤 항목들이 있는지 요약하세요."
)


def render_figure_png(
    pdf_path: str, page: int, polygon: list[float], dpi: int = 150, pad_in: float = 0.1
) -> bytes:
    xs = polygon[0::2]
    ys = polygon[1::2]
    left = max(min(xs) - pad_in, 0.0)
    top = max(min(ys) - pad_in, 0.0)
    right = max(xs) + pad_in
    bottom = max(ys) + pad_in
    with tempfile.TemporaryDirectory() as d:
        prefix = os.path.join(d, "pg")
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", pdf_path, prefix],
            check=True,
            capture_output=True,
        )
        pngs = sorted(f for f in os.listdir(d) if f.endswith(".png"))
        img = Image.open(os.path.join(d, pngs[0]))
        box = (int(left * dpi), int(top * dpi), int(right * dpi), int(bottom * dpi))
        crop = img.crop(box)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()


def describe_figure(png: bytes) -> str:
    s = get_settings()
    base = s.foundry_project_endpoint.split("/api/projects")[0]
    provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
    client = AzureOpenAI(
        azure_endpoint=base, api_version=s.foundry_api_version, azure_ad_token_provider=provider
    )
    b64 = base64.b64encode(png).decode()
    resp = client.chat.completions.create(
        model=s.foundry_vision_deployment,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        max_tokens=400,
    )
    return (resp.choices[0].message.content or "").strip()


def heading_path_at(doc: ParsedDoc, offset: int) -> str:
    stack: list[str] = []
    for p in sorted(doc.paragraphs, key=lambda x: x.offset):
        if p.offset > offset:
            break
        if p.role in HEADING_ROLES:
            if p.role == "title":
                stack = [p.content]
            else:
                depth = _heading_depth(p.content)
                stack = stack[:depth] + [p.content]
    return " > ".join(stack)


def build_figure_chunks(doc: ParsedDoc, pdf_path: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, fig in enumerate(doc.figures):
        try:
            png = render_figure_png(pdf_path, fig.page, fig.polygon)
            desc = describe_figure(png)
        except Exception as exc:  # noqa: BLE001
            desc = f"(그림 설명 생성 실패: {exc})"
        prefix = f"[그림] {fig.caption}\n" if fig.caption else "[그림] "
        chunks.append(
            Chunk(
                id=f"{doc.doc_id}-fig-{i}",
                doc_id=doc.doc_id,
                content=prefix + desc,
                chunk_type="figure",
                section_path=heading_path_at(doc, fig.offset),
                page_physical=fig.page,
                page_printed=None,
            )
        )
    return chunks


def render_page_png(pdf_path: str, page: int, dpi: int = 130) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        prefix = os.path.join(d, "pg")
        subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", pdf_path, prefix],
            check=True,
            capture_output=True,
        )
        pngs = sorted(f for f in os.listdir(d) if f.endswith(".png"))
        img = Image.open(os.path.join(d, pngs[0]))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
