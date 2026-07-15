"""Authoritative fund catalog extracted from the TOC of annual evaluation reports.

Produces ``FundCatalogEntry`` records by parsing the ``Ⅲ. 기금별 자산운용평가 결과``
section of a ``ParsedDoc``.  Each entry captures the fund's toc_order, canonical
name, ministry, printed page range, and physical page pointers.
"""
from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, Field

from ingest.models import Chunk, ParsedDoc

# ── OCR alias repair table ────────────────────────────────────────────────────

_OCR_ALIASES: Final[dict[str, str]] = {
    # "장력" is a consistent OCR mis-read of "장려" in all scanned reports.
    "농어가목돈마련저축장력기금": "농어가목돈마련저축장려기금",
    # The 2021 aggregate grade table drops the final consonant in "마련".
    "농어가목돈마려저축장려기금": "농어가목돈마련저축장려기금",
}

# ── compiled patterns ─────────────────────────────────────────────────────────

_TOC_SECTION_RE: Final = re.compile(r"Ⅲ\s*[\. ]+.+기금별\s*자산운용평가.*결과")
_MINISTRY_RE: Final = re.compile(r"^【(.+)】$")
# Inline: "18. 무역보험기금 153"
_ENTRY_INLINE_RE: Final = re.compile(r"^(\d+)\.\s+(.+?)\s+(\d+)$")
# Split start: "18. 무역보험기금"  (page follows in next paragraph)
_ENTRY_NAME_RE: Final = re.compile(r"^(\d+)\.\s+(.+)$")
# pageNumber paragraph body: "- 42 -"
_PAGE_NUMBER_RE: Final = re.compile(r"^-\s*(\d+)\s*-$")
# Pure integer content (may appear as the continuation page in split entries)
_DIGITS_RE: Final = re.compile(r"^\d+$")

# Content marker that terminates the TOC region (first body chapter heading).
_BODY_STARTS_RE: Final = re.compile(r"Ⅰ\.?\s*.*기금운용평가.*개요")


# ── public models ─────────────────────────────────────────────────────────────


class FundCatalogEntry(BaseModel):
    id: str
    """``{doc_id}/{toc_order:03d}``"""
    fund_id: str
    """Stable normalised fund name used as a cross-document key."""
    year: int
    doc_id: str
    toc_order: int
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    ministry: str
    fund_scale: str | None = None
    start_page_printed: int
    end_page_printed: int
    start_page_physical: int | None = None
    end_page_physical: int | None = None
    source_page_physical: int
    """Physical page of the TOC paragraph that introduced this entry."""


class CatalogValidationError(ValueError):
    """Raised when the extracted TOC does not satisfy structural invariants."""


# ── public helpers ────────────────────────────────────────────────────────────


def normalize_fund_name(name: str) -> str:
    """Strip surrounding whitespace and repair known OCR aliases."""
    stripped = name.strip()
    return _OCR_ALIASES.get(stripped, stripped)


def fund_id_for(name: str) -> str:
    """Return the stable cross-document identifier for *name*.

    Parenthesised account names are intentionally preserved so that funds
    sharing a base name but belonging to different sub-accounts remain
    distinct (e.g. 국민체육진흥기금(국민체육진흥계정) vs
    국민체육진흥기금(사행산업중독예방치유계정)).
    """
    return normalize_fund_name(name)


# ── internal helpers ──────────────────────────────────────────────────────────


def _build_page_map(doc: ParsedDoc) -> dict[int, int]:
    """Return ``{printed_page: physical_page}`` from *pageNumber* paragraphs."""
    result: dict[int, int] = {}
    for para in doc.paragraphs:
        if para.role == "pageNumber":
            m = _PAGE_NUMBER_RE.match(para.content.strip())
            if m:
                result[int(m.group(1))] = para.page
    return result


def _max_printed_page(doc: ParsedDoc) -> int:
    """Return the highest numeric printed page found in *pageNumber* paragraphs."""
    max_p = 0
    for para in doc.paragraphs:
        if para.role == "pageNumber":
            m = _PAGE_NUMBER_RE.match(para.content.strip())
            if m:
                n = int(m.group(1))
                if n > max_p:
                    max_p = n
    return max_p


# ── main extractor ────────────────────────────────────────────────────────────


def extract_fund_catalog(
    doc: ParsedDoc, *, year: int, doc_id: str
) -> list[FundCatalogEntry]:
    """Parse the TOC of *doc* and return one ``FundCatalogEntry`` per fund.

    The TOC region is delimited by:
    - **Start**: the first ``Ⅲ.*기금별 자산운용평가.*결과`` paragraph.
    - **End**:   the first paragraph matching ``Ⅰ.*기금운용평가.*개요`` (body start).

    Within that region the parser handles:
    - Ministry headings ``【...】`` (any role, including ``None``).
    - Inline entries ``N. 기금명 PAGE``.
    - Split entries ``N. 기금명`` followed immediately by a pure-digit paragraph.
    """
    page_map = _build_page_map(doc)
    max_printed = _max_printed_page(doc)

    in_toc = False
    current_ministry = ""
    # raw list of (toc_order, canonical_name, ministry, start_printed, source_page)
    raw: list[tuple[int, str, str, int, int]] = []
    # pending split entry awaiting its page number paragraph
    pending: tuple[int, str, str, int] | None = None  # (order, name, ministry, src_page)

    for para in doc.paragraphs:
        content = para.content.strip()

        # ── TOC region boundary ───────────────────────────────────────────────

        if not in_toc:
            if _TOC_SECTION_RE.search(content):
                in_toc = True
            continue  # always skip paragraphs before the Ⅲ heading

        if _BODY_STARTS_RE.search(content):
            break  # left the TOC region; remaining paragraphs are body text

        # ── ministry heading ──────────────────────────────────────────────────

        m = _MINISTRY_RE.match(content)
        if m:
            current_ministry = m.group(1).strip()
            continue

        # ── pending split entry: consume the page paragraph ───────────────────

        if pending is not None:
            if _DIGITS_RE.match(content):
                order, name, ministry, src_page = pending
                raw.append((order, name, ministry, int(content), src_page))
                pending = None
                continue
            # Not a digit paragraph: the pending entry never received a page.
            # Fall through to see if this line starts a new entry (which would
            # mean the previous entry was malformed).  Raise for safety.
            raise CatalogValidationError(
                f"TOC entry '{pending[1]}' (order {pending[0]}) has no page number; "
                f"next paragraph was {content!r}"
            )

        # ── inline entry: "N. 기금명 PAGE" ────────────────────────────────────

        m = _ENTRY_INLINE_RE.match(content)
        if m:
            order = int(m.group(1))
            name = normalize_fund_name(m.group(2).strip())
            raw.append((order, name, current_ministry, int(m.group(3)), para.page))
            continue

        # ── split-entry start: "N. 기금명" ────────────────────────────────────

        m = _ENTRY_NAME_RE.match(content)
        if m:
            order = int(m.group(1))
            name = normalize_fund_name(m.group(2).strip())
            pending = (order, name, current_ministry, para.page)
            continue

        # Any other paragraph (pageNumber front-matter, sub-headers, etc.) is
        # silently ignored within the TOC region.

    # A pending entry that was never resolved is a parse error.
    if pending is not None:
        raise CatalogValidationError(
            f"TOC entry '{pending[1]}' (order {pending[0]}) has no page number "
            f"(reached end of TOC region)"
        )

    if not raw:
        raise CatalogValidationError(
            f"No fund entries found in TOC of {doc_id!r}"
        )

    # ── structural validation ─────────────────────────────────────────────────

    raw.sort(key=lambda t: t[0])
    orders = [t[0] for t in raw]

    if len(orders) != len(set(orders)):
        raise CatalogValidationError(
            f"Duplicate TOC ordinals in {doc_id!r}: {orders}"
        )

    if orders[0] != 1:
        raise CatalogValidationError(
            f"TOC ordinals must start at 1 in {doc_id!r}; got first ordinal {orders[0]}"
        )

    expected = list(range(1, len(orders) + 1))
    if orders != expected:
        raise CatalogValidationError(
            f"TOC ordinals are not contiguous in {doc_id!r}: "
            f"got {orders}, expected {expected}"
        )

    # ── assemble FundCatalogEntry records ─────────────────────────────────────

    result: list[FundCatalogEntry] = []
    for i, (order, name, ministry, start_printed, src_page) in enumerate(raw):
        end_printed = raw[i + 1][3] - 1 if i + 1 < len(raw) else max_printed

        result.append(
            FundCatalogEntry(
                id=f"{doc_id}/{order:03d}",
                fund_id=fund_id_for(name),
                year=year,
                doc_id=doc_id,
                toc_order=order,
                canonical_name=name,
                aliases=sorted(
                    alias
                    for alias, canonical in _OCR_ALIASES.items()
                    if canonical == name
                ),
                ministry=ministry,
                start_page_printed=start_printed,
                end_page_printed=end_printed,
                start_page_physical=page_map.get(start_printed),
                end_page_physical=page_map.get(end_printed),
                source_page_physical=src_page,
            )
        )

    return result


# ── catalog coverage annotation ───────────────────────────────────────────────


class CatalogCoverage(BaseModel):
    chunks: list[Chunk]
    population_count: int
    annotated_fund_count: int
    missing_fund_ids: list[str]


def annotate_chunks(
    chunks: list[Chunk],
    catalog: list[FundCatalogEntry],
) -> CatalogCoverage:
    """Annotate *chunks* with authoritative fund identity from *catalog*.

    Physical page ranges are used first; printed page ranges serve as fallback
    when ``start_page_physical`` is None.  Overview chunks (before all fund
    ranges) remain unassigned.  Any catalog fund whose page range contains no
    chunks is reported in ``missing_fund_ids``.
    """
    fund_hit: set[str] = set()
    annotated: list[Chunk] = []

    for chunk in chunks:
        matched: FundCatalogEntry | None = None

        for entry in catalog:
            # Primary: physical page range
            if (
                entry.start_page_physical is not None
                and entry.end_page_physical is not None
            ):
                if entry.start_page_physical <= chunk.page_physical <= entry.end_page_physical:
                    matched = entry
                    break
            else:
                # Fallback: printed page range
                if chunk.page_printed is not None and (
                    entry.start_page_printed <= chunk.page_printed <= entry.end_page_printed
                ):
                    matched = entry
                    break

        if matched is not None:
            chunk = chunk.model_copy(update={
                "fund_id": matched.fund_id,
                "ministry": matched.ministry,
                "fund_name": matched.canonical_name,
            })
            fund_hit.add(matched.fund_id)

        annotated.append(chunk)

    all_fund_ids = {e.fund_id for e in catalog}
    missing = sorted(all_fund_ids - fund_hit)

    return CatalogCoverage(
        chunks=annotated,
        population_count=len(catalog),
        annotated_fund_count=len(fund_hit),
        missing_fund_ids=missing,
    )
