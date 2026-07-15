"""Tests for ingest.run – structured ingest orchestration and validate-only mode.

TDD RED: written before implementation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from ingest.catalog import CatalogCoverage, CatalogValidationError, FundCatalogEntry
from ingest.facts import EvaluationFact
from ingest.models import Chunk, ParsedDoc


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(
    idx: int = 0,
    doc_id: str = "report-2025",
    chunk_type: str = "narrative",
    fund_id: str | None = None,
    page_physical: int = 10,
) -> Chunk:
    return Chunk(
        id=f"{doc_id}/chunk-{idx}",
        doc_id=doc_id,
        content=f"content-{idx}",
        chunk_type=chunk_type,
        section_path="A > B",
        page_physical=page_physical,
        fund_id=fund_id,
    )


def _make_catalog_entry(
    order: int = 1,
    name: str = "국민연금기금",
    ministry: str = "보건복지부",
    doc_id: str = "report-2025",
    year: int = 2025,
) -> FundCatalogEntry:
    return FundCatalogEntry(
        id=f"{doc_id}/{order:03d}",
        fund_id=name,
        year=year,
        doc_id=doc_id,
        toc_order=order,
        canonical_name=name,
        ministry=ministry,
        start_page_printed=10,
        end_page_printed=20,
        source_page_physical=1,
    )


def _make_fact(
    fund_id: str = "국민연금기금",
    metric_code: str = "asset_management_performance",
    doc_id: str = "report-2025",
    year: int = 2025,
) -> EvaluationFact:
    return EvaluationFact(
        id=f"{doc_id}/{fund_id}/{metric_code}",
        fund_id=fund_id,
        fund_name=fund_id,
        doc_id=doc_id,
        year=year,
        ministry="보건복지부",
        fact_type="score",
        metric_code=metric_code,
        metric_name="자산운용 성과",
        score=85.0,
        max_score=100.0,
        source_chunk_id=f"{doc_id}/chunk-0",
        source_page_physical=10,
        source_section_path="A > B",
        source_text="자산운용 성과 | 100 | 85 | | 우수",
    )


def _make_overall_fact(
    fund_id: str,
    doc_id: str = "report-2025",
    year: int = 2025,
) -> EvaluationFact:
    return EvaluationFact(
        id=f"{doc_id}/{fund_id}/overall_grade",
        fund_id=fund_id,
        fund_name=fund_id,
        doc_id=doc_id,
        year=year,
        ministry="보건복지부",
        fact_type="grade",
        metric_code="overall_grade",
        metric_name="종합등급",
        grade="우수",
        grade_rank=4,
        source_scope="annual_summary",
        population_scope="evaluated",
        source_chunk_id=f"{doc_id}/summary",
        source_page_physical=5,
        source_section_path="참고 7 기금 유형별 평가결과",
        source_text="| 사회보험성 | 우수 | 기금 |",
    )


def _parsed_doc(doc_id: str = "report-2025") -> ParsedDoc:
    return ParsedDoc(doc_id=doc_id, paragraphs=[], tables=[])


def _azure_bomb(name: str):
    """Return a callable that raises AssertionError if invoked."""
    def _bomb(*a, **kw):
        raise AssertionError(f"{name} must not be called")
    return _bomb


# ── patch targets ─────────────────────────────────────────────────────────────

_RUN = "ingest.run"

_AZURE_FAKES = (
    "embed_texts", "ensure_indexes", "reset_indexes",
    "ensure_structured_indexes", "upload_chunks",
    "replace_catalog", "replace_facts",
)


def _block_all_azure(monkeypatch):
    """Install AssertionError-throwing fakes for ALL remote operations."""
    for fn in _AZURE_FAKES:
        monkeypatch.setattr(f"{_RUN}.{fn}", _azure_bomb(fn))
    monkeypatch.setattr(f"{_RUN}.build_figure_chunks", _azure_bomb("build_figure_chunks"))
    monkeypatch.setattr(f"{_RUN}.SearchClient", _azure_bomb("SearchClient"))
    monkeypatch.setattr(f"{_RUN}.DefaultAzureCredential", _azure_bomb("DefaultAzureCredential"))
    monkeypatch.setattr(f"{_RUN}.get_settings", _azure_bomb("get_settings"))


# ── Report ingest: operation order ────────────────────────────────────────────


class TestReportIngestOrder:
    """Report ingest must follow: analyze -> chunk -> catalog -> annotate -> facts
    -> validate -> figures -> re-annotate -> embed -> ensure -> upload -> replace."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.call_log: list[str] = []
        self.fact_catalog = None

        chunks = [_make_chunk(i, fund_id="국민연금기금") for i in range(3)]
        catalog = [_make_catalog_entry()]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        facts = [_make_fact()]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: (self.call_log.append("analyze"), _parsed_doc())[1])
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: (self.call_log.append("chunk"), chunks)[1])
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", lambda *a, **kw: (self.call_log.append("figures"), [_make_chunk(99, chunk_type="figure", fund_id=None)])[1])
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: (self.call_log.append("catalog"), catalog)[1])
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: (self.call_log.append("annotate"), coverage)[1])
        def _extract_facts(*args, **kwargs):
            self.call_log.append("facts")
            self.fact_catalog = kwargs.get("catalog")
            return facts

        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", _extract_facts)
        monkeypatch.setattr(f"{_RUN}.embed_texts", lambda *a, **kw: (self.call_log.append("embed"), [[0.1] * 1536] * len(a[0]))[1])
        monkeypatch.setattr(f"{_RUN}.ensure_indexes", lambda *a, **kw: self.call_log.append("ensure_indexes"))
        monkeypatch.setattr(f"{_RUN}.reset_indexes", lambda *a, **kw: self.call_log.append("reset_indexes"))
        monkeypatch.setattr(f"{_RUN}.ensure_structured_indexes", lambda *a, **kw: self.call_log.append("ensure_structured"))
        monkeypatch.setattr(f"{_RUN}.upload_chunks", lambda *a, **kw: (self.call_log.append("upload"), len(a[0]))[1])
        monkeypatch.setattr(f"{_RUN}.replace_catalog", lambda *a, **kw: self.call_log.append("replace_catalog"))
        monkeypatch.setattr(f"{_RUN}.replace_facts", lambda *a, **kw: self.call_log.append("replace_facts"))
        monkeypatch.setattr(f"{_RUN}.SearchClient", lambda *a, **kw: (self.call_log.append(f"SearchClient({kw.get('index_name', '')})"), MagicMock())[1])
        monkeypatch.setattr(f"{_RUN}.DefaultAzureCredential", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(f"{_RUN}.get_settings", lambda: MagicMock(
            search_endpoint="https://x.search.windows.net",
            search_index_catalog="fund-catalog-index",
            search_index_facts="evaluation-facts-index",
        ))

    def test_report_normal_order(self):
        """Pure validation before figure build, final annotation before embed."""
        from ingest.run import run
        run("f.pdf", "report-2025", None, True, figures=True,
            year=2025, doc_type="report")

        # Pure extraction before any Azure
        assert self.call_log.index("analyze") < self.call_log.index("chunk")
        assert self.call_log.index("chunk") < self.call_log.index("catalog")
        assert self.call_log.index("catalog") < self.call_log.index("annotate")
        assert self.call_log.index("annotate") < self.call_log.index("facts")

        # Figures built AFTER facts (validation), then re-annotated
        assert self.call_log.index("facts") < self.call_log.index("figures")
        annotate_indices = [i for i, x in enumerate(self.call_log) if x == "annotate"]
        assert len(annotate_indices) == 2, "must annotate twice: base + combined"
        assert annotate_indices[1] > self.call_log.index("figures")

        # Azure writes after figures+re-annotate
        assert self.call_log.index("figures") < self.call_log.index("embed")
        assert self.call_log.index("embed") < self.call_log.index("ensure_indexes")
        assert self.call_log.index("ensure_indexes") < self.call_log.index("ensure_structured")
        assert self.call_log.index("ensure_structured") < self.call_log.index("upload")
        assert self.call_log.index("upload") < self.call_log.index("replace_catalog")
        assert self.call_log.index("replace_catalog") < self.call_log.index("replace_facts")

    def test_report_passes_catalog_to_fact_extractor(self):
        from ingest.run import run

        run("f.pdf", "report-2025", None, True, figures=False,
            year=2025, doc_type="report")

        assert self.fact_catalog is not None
        assert [entry.fund_id for entry in self.fact_catalog] == ["국민연금기금"]

    def test_report_no_ensure_before_validation(self):
        """ensure_indexes / ensure_structured / SearchClient must not appear
        before all pure extraction steps complete."""
        from ingest.run import run
        run("f.pdf", "report-2025", None, True, figures=True,
            year=2025, doc_type="report")

        facts_idx = self.call_log.index("facts")
        for blocked in ("ensure_indexes", "ensure_structured", "embed", "upload",
                        "replace_catalog", "replace_facts"):
            if blocked in self.call_log:
                assert self.call_log.index(blocked) > facts_idx, \
                    f"{blocked} must not appear before facts extraction"

        # SearchClient must not be constructed before facts
        for i, entry in enumerate(self.call_log):
            if entry.startswith("SearchClient"):
                assert i > facts_idx

    def test_report_reset_after_validation(self):
        """reset=True must reset evidence indexes only after validation passes."""
        from ingest.run import run
        run("f.pdf", "report-2025", None, True, figures=True,
            reset=True, year=2025, doc_type="report")

        assert "reset_indexes" in self.call_log
        assert self.call_log.index("reset_indexes") > self.call_log.index("facts")

    def test_search_client_index_names(self):
        """SearchClient must be constructed with correct index names."""
        from ingest.run import run
        run("f.pdf", "report-2025", None, True, figures=True,
            year=2025, doc_type="report")

        sc_calls = [e for e in self.call_log if e.startswith("SearchClient")]
        index_names = {e.split("(")[1].rstrip(")") for e in sc_calls}
        assert "fund-catalog-index" in index_names
        assert "evaluation-facts-index" in index_names


# ── Report validate-only ──────────────────────────────────────────────────────


class TestReportValidateOnly:
    """validate_only=True must do all extraction but zero Azure/Vision calls."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.call_log: list[str] = []

        chunks = [_make_chunk(i, fund_id="국민연금기금") for i in range(4)]
        catalog = [_make_catalog_entry()]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        facts = [_make_fact()]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: (self.call_log.append("analyze"), _parsed_doc())[1])
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: (self.call_log.append("chunk"), chunks)[1])
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: (self.call_log.append("catalog"), catalog)[1])
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: (self.call_log.append("annotate"), coverage)[1])
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: (self.call_log.append("facts"), facts)[1])

        # ALL remote operations must throw if called (I1)
        _block_all_azure(monkeypatch)

    def test_validate_only_returns_chunk_count(self):
        from ingest.run import run
        result = run("f.pdf", "report-2025", None, True, figures=True,
                     year=2025, doc_type="report", validate_only=True)
        assert result == 4  # annotated chunk count

    def test_validate_only_performs_extraction(self):
        from ingest.run import run
        run("f.pdf", "report-2025", None, True, figures=True,
                     year=2025, doc_type="report", validate_only=True)
        for step in ("analyze", "chunk", "catalog", "annotate", "facts"):
            assert step in self.call_log, f"{step} must be called in validate_only"

    def test_validate_only_with_figures_never_calls_build_figure_chunks(self):
        """C1: validate_only=True must make zero Vision calls even with figures=True."""
        from ingest.run import run
        # build_figure_chunks is an AssertionError bomb from _block_all_azure
        result = run("f.pdf", "report-2025", None, True, figures=True,
                     year=2025, doc_type="report", validate_only=True)
        assert result == 4
        assert "figures" not in self.call_log


# ── Validation failure stops ingest ───────────────────────────────────────────


class TestValidationFailureStopsIngest:
    """If catalog/annotation/fact completeness fails, no Azure work occurs."""

    def test_missing_funds_stops_ingest(self, monkeypatch):
        chunks = [_make_chunk(0)]
        catalog = [_make_catalog_entry(), _make_catalog_entry(order=2, name="사학연금기금")]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=2, annotated_fund_count=1,
            missing_fund_ids=["사학연금기금"],
        )

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: [_make_fact()])

        # I1: ALL remote fakes throw AssertionError
        _block_all_azure(monkeypatch)

        from ingest.run import run
        with pytest.raises(ValueError, match="missing_fund_ids"):
            run("f.pdf", "report-2025", None, True, year=2025, doc_type="report")

    def test_missing_perf_fact_stops_ingest(self, monkeypatch):
        """Every catalog fund must have exactly one asset_management_performance fact."""
        chunks = [_make_chunk(0, fund_id="국민연금기금")]
        catalog = [_make_catalog_entry()]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        # No facts at all -> missing asset_management_performance
        facts: list[EvaluationFact] = []

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts)

        # I1: ALL remote fakes throw AssertionError
        _block_all_azure(monkeypatch)

        from ingest.run import run
        with pytest.raises(ValueError, match="asset_management_performance count != 1"):
            run("f.pdf", "report-2025", None, True, year=2025, doc_type="report")

    def test_duplicate_amp_stops_before_remote(self, monkeypatch):
        """C2: >1 AMP fact for one fund stops before any remote operation."""
        chunks = [_make_chunk(0, fund_id="국민연금기금")]
        catalog = [_make_catalog_entry()]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        # Two AMP facts for same fund
        facts = [_make_fact(), _make_fact()]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts)

        # ALL remote fakes throw
        _block_all_azure(monkeypatch)

        from ingest.run import run
        with pytest.raises(ValueError, match="asset_management_performance count != 1"):
            run("f.pdf", "report-2025", None, True, year=2025, doc_type="report")

    def test_external_fact_fund_id_stops_before_remote(self, monkeypatch):
        """C3: fact with fund_id absent from catalog raises before remote ops."""
        chunks = [_make_chunk(0, fund_id="국민연금기금")]
        catalog = [_make_catalog_entry()]  # only 국민연금기금
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        # Fact references a fund not in catalog
        external_fact = _make_fact(fund_id="외부기금")
        facts = [_make_fact(), external_fact]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts)

        # ALL remote fakes throw
        _block_all_azure(monkeypatch)

        from ingest.run import run
        with pytest.raises(ValueError, match="external_fact_fund_ids"):
            run("f.pdf", "report-2025", None, True, year=2025, doc_type="report")

    def test_wrong_annual_evaluated_population_stops_before_remote(
        self, monkeypatch
    ):
        chunks = [
            _make_chunk(0, fund_id="국민연금기금"),
            _make_chunk(1, fund_id="사립학교교직원연금기금"),
        ]
        catalog = [
            _make_catalog_entry(name="국민연금기금"),
            _make_catalog_entry(order=2, name="사립학교교직원연금기금"),
        ]
        coverage = CatalogCoverage(
            chunks=chunks,
            population_count=2,
            annotated_fund_count=2,
            missing_fund_ids=[],
        )
        facts = [
            _make_fact(fund_id="국민연금기금"),
            _make_fact(fund_id="사립학교교직원연금기금"),
            _make_overall_fact("국민연금기금"),
        ]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(
            f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts
        )
        _block_all_azure(monkeypatch)

        from ingest.run import run

        with pytest.raises(ValueError, match="overall_grade evaluated population"):
            run(
                "f.pdf",
                "report-2025",
                None,
                True,
                year=2025,
                doc_type="report",
                expected_overall_grade_count=1,
                expected_overall_grade_excluded_fund_ids=("국민연금기금",),
            )


def test_corpus_declares_exact_annual_evaluated_populations():
    from ingest.corpus import CORPUS

    reports = {doc.doc_id: doc for doc in CORPUS if doc.doc_type == "report"}

    assert {
        doc_id: (
            doc.expected_overall_grade_count,
            doc.expected_overall_grade_excluded_fund_ids,
        )
        for doc_id, doc in reports.items()
    } == {
        "report-2021": (32, ("국민연금기금",)),
        "report-2022": (30, ("국민연금기금",)),
        "report-2025": (24, ("국민연금기금",)),
    }


# ── Guideline ingest ──────────────────────────────────────────────────────────


class TestGuidelineIngest:
    """Guidelines skip catalog/annotate/facts and never create structured indexes."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.call_log: list[str] = []
        chunks = [_make_chunk(i) for i in range(2)]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: (self.call_log.append("analyze"), _parsed_doc())[1])
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: (self.call_log.append("chunk"), chunks)[1])
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", lambda *a, **kw: (self.call_log.append("figures"), [])[1])
        monkeypatch.setattr(f"{_RUN}.embed_texts", lambda *a, **kw: (self.call_log.append("embed"), [[0.1] * 1536] * 2)[1])
        monkeypatch.setattr(f"{_RUN}.ensure_indexes", lambda *a, **kw: self.call_log.append("ensure_indexes"))
        monkeypatch.setattr(f"{_RUN}.reset_indexes", lambda *a, **kw: self.call_log.append("reset_indexes"))
        monkeypatch.setattr(f"{_RUN}.upload_chunks", lambda *a, **kw: (self.call_log.append("upload"), len(a[0]))[1])

        # These must never be called for guidelines
        for fn in ("extract_fund_catalog", "annotate_chunks",
                    "extract_evaluation_facts", "ensure_structured_indexes",
                    "replace_catalog", "replace_facts"):
            monkeypatch.setattr(f"{_RUN}.{fn}", _azure_bomb(fn))
        monkeypatch.setattr(f"{_RUN}.SearchClient", _azure_bomb("SearchClient"))
        monkeypatch.setattr(f"{_RUN}.DefaultAzureCredential", _azure_bomb("DefaultAzureCredential"))

    def test_guideline_normal_ingest(self):
        from ingest.run import run
        result = run("f.pdf", "guideline-2021-dh", None, True,
                     year=2021, doc_type="guideline")
        assert result == 2
        assert "ensure_indexes" in self.call_log
        assert "embed" in self.call_log
        assert "upload" in self.call_log

    def test_guideline_validate_only(self, monkeypatch):
        """Guideline validate_only parses/chunks but skips all Azure and Vision."""
        # Override embed/ensure/upload/figures to fail too
        for fn in ("embed_texts", "ensure_indexes", "reset_indexes", "upload_chunks"):
            monkeypatch.setattr(f"{_RUN}.{fn}", _azure_bomb(fn))
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", _azure_bomb("build_figure_chunks"))

        from ingest.run import run
        result = run("f.pdf", "guideline-2021-dh", None, True,
                     year=2021, doc_type="guideline", validate_only=True)
        assert result == 2
        assert "analyze" in self.call_log
        assert "chunk" in self.call_log

    def test_guideline_validate_only_output(self, monkeypatch, capsys):
        """Guideline validate-only output includes VALIDATE-ONLY and no figure count claim."""
        for fn in ("embed_texts", "ensure_indexes", "reset_indexes", "upload_chunks"):
            monkeypatch.setattr(f"{_RUN}.{fn}", _azure_bomb(fn))
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", _azure_bomb("build_figure_chunks"))

        from ingest.run import run
        run("f.pdf", "guideline-2021-dh", None, True, figures=True,
            year=2021, doc_type="guideline", validate_only=True)

        out = capsys.readouterr().out
        assert "VALIDATE-ONLY" in out
        assert "figure=0" in out  # no figures built in validate-only


# ── Vector length mismatch ────────────────────────────────────────────────────


class TestVectorLengthMismatch:
    """embed_texts returning wrong number of vectors must fail visibly."""

    def test_vector_count_mismatch(self, monkeypatch):
        chunks = [_make_chunk(i) for i in range(3)]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", lambda *a, **kw: [])
        # Return 2 vectors for 3 chunks
        monkeypatch.setattr(f"{_RUN}.embed_texts", lambda *a, **kw: [[0.1]] * 2)
        monkeypatch.setattr(f"{_RUN}.ensure_indexes", lambda *a, **kw: None)
        monkeypatch.setattr(f"{_RUN}.upload_chunks", lambda *a, **kw: 0)

        from ingest.run import run
        with pytest.raises(ValueError, match="vector count.*mismatch"):
            run("f.pdf", "guideline-2021-dh", None, True,
                year=2021, doc_type="guideline")


# ── Summary output ────────────────────────────────────────────────────────────


class TestSummaryOutput:
    """Print line must contain required fields."""

    def test_report_summary(self, monkeypatch, capsys):
        chunks = [_make_chunk(i, fund_id="국민연금기금") for i in range(3)]
        figure = _make_chunk(99, chunk_type="figure", fund_id=None)
        catalog = [_make_catalog_entry()]
        facts = [_make_fact()]
        uploaded: list[Chunk] = []

        def annotate(input_chunks, _catalog):
            return CatalogCoverage(
                chunks=list(input_chunks), population_count=1,
                annotated_fund_count=1, missing_fund_ids=[],
            )

        def upload(input_chunks):
            uploaded.extend(input_chunks)
            return len(input_chunks)

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.build_figure_chunks", lambda *a, **kw: [figure])
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", annotate)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts)
        monkeypatch.setattr(f"{_RUN}.embed_texts", lambda *a, **kw: [[0.1] * 1536] * len(a[0]))
        monkeypatch.setattr(f"{_RUN}.ensure_indexes", lambda *a, **kw: None)
        monkeypatch.setattr(f"{_RUN}.ensure_structured_indexes", lambda *a, **kw: None)
        monkeypatch.setattr(f"{_RUN}.upload_chunks", upload)
        monkeypatch.setattr(f"{_RUN}.replace_catalog", lambda *a, **kw: None)
        monkeypatch.setattr(f"{_RUN}.replace_facts", lambda *a, **kw: None)
        monkeypatch.setattr(f"{_RUN}.SearchClient", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(f"{_RUN}.DefaultAzureCredential", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(f"{_RUN}.get_settings", lambda: MagicMock(
            search_endpoint="https://x.search.windows.net",
            search_index_catalog="fund-catalog-index",
            search_index_facts="evaluation-facts-index",
        ))

        from ingest.run import run
        result = run("f.pdf", "report-2025", None, True, year=2025, doc_type="report")

        out = capsys.readouterr().out
        assert result == 4
        assert len(uploaded) == 4
        assert any(chunk.chunk_type == "figure" for chunk in uploaded)
        assert "doc_id=report-2025" in out
        assert "chunks=4" in out
        assert "figure=1" in out
        assert "catalog=1" in out
        assert "annotated=1" in out
        assert "facts=1" in out
        assert "asset_management_performance=1" in out
        assert "missing_facts=0" in out

    def test_validate_only_marker(self, monkeypatch, capsys):
        chunks = [_make_chunk(0, fund_id="국민연금기금")]
        catalog = [_make_catalog_entry()]
        coverage = CatalogCoverage(
            chunks=chunks, population_count=1, annotated_fund_count=1,
            missing_fund_ids=[],
        )
        facts = [_make_fact()]

        monkeypatch.setattr(f"{_RUN}.analyze_pdf", lambda *a, **kw: _parsed_doc())
        monkeypatch.setattr(f"{_RUN}.chunk_document", lambda *a, **kw: chunks)
        monkeypatch.setattr(f"{_RUN}.extract_fund_catalog", lambda *a, **kw: catalog)
        monkeypatch.setattr(f"{_RUN}.annotate_chunks", lambda *a, **kw: coverage)
        monkeypatch.setattr(f"{_RUN}.extract_evaluation_facts", lambda *a, **kw: facts)
        _block_all_azure(monkeypatch)

        from ingest.run import run
        run("f.pdf", "report-2025", None, True, year=2025, doc_type="report",
            validate_only=True)

        out = capsys.readouterr().out
        assert "VALIDATE-ONLY" in out


# ── CLI flag propagation ──────────────────────────────────────────────────────


class TestCLI:
    """--validate-only must propagate to run and run_corpus."""

    def test_all_validate_only_propagates(self):
        """I3: --all --validate-only propagates validate_only=True exactly."""
        import sys
        from ingest.run import main
        with patch.object(sys, "argv", ["prog", "--all", "--validate-only"]):
            with patch(f"{_RUN}.run_corpus") as mock_rc:
                with patch("agent.observability.setup_observability"):
                    main()
            mock_rc.assert_called_once()
            _, kwargs = mock_rc.call_args
            assert kwargs["validate_only"] is True

    def test_doc_id_validate_only_propagates(self):
        """I2: --doc-id report-2025 --validate-only propagates correctly."""
        import sys
        from ingest.run import main
        fake_doc = MagicMock(
            pdf="f.pdf", doc_id="report-2025", year=2025,
            doc_type="report", fund_scale=None,
        )
        with patch.object(sys, "argv", ["prog", "--doc-id", "report-2025", "--validate-only"]):
            with patch("ingest.corpus.get_doc", return_value=fake_doc):
                with patch(f"{_RUN}.run") as mock_run:
                    with patch("agent.observability.setup_observability"):
                        main()
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs["validate_only"] is True
            assert mock_run.call_args[0][1] == "report-2025"

    def test_run_corpus_propagates_validate_only(self, monkeypatch):
        """run_corpus must pass validate_only to each run() call."""
        calls: list[dict] = []

        def fake_run(*args, **kwargs):
            calls.append(kwargs)
            return 0

        monkeypatch.setattr(f"{_RUN}.run", fake_run)

        from ingest.run import run_corpus
        run_corpus(validate_only=True)

        assert len(calls) == 5  # CORPUS has 5 docs
        for kw in calls:
            assert kw.get("validate_only") is True
