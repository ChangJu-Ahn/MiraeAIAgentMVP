# Core Demo Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the PoC to one readable, source-grounded chat path without weakening retrieval, ingestion, visualization, evaluation, or Azure observability.

**Architecture:** Keep the existing Foundry agent and recorders, but make Chainlit a thin renderer around one streaming run. Delete optional secondary model calls and their UI state, then remove the Blob-only runtime and infrastructure path. Preserve deterministic search and data-integrity code.

**Tech Stack:** Python 3.12, Microsoft Agent Framework, Chainlit, Azure AI Search, Microsoft Foundry, Azure Monitor OpenTelemetry, Bicep, pytest, uv

## Global Constraints

- Preserve all four indexes and the deterministic structured analytics contract.
- Preserve missing-source refusal, annual-summary grade authority, and evaluated-population scoping.
- Preserve citations, evidence, visuals, ingestion validation, and five-judge evaluation.
- Do not add replacement abstractions or commit changes unless the user asks.
- Use failing tests before changing Python behavior; configuration-only deletion is validated by builds and reference searches.

---

### Task 1: Collapse The Chat Path

**Files:**
- Modify: `tests/agent/test_streaming.py`
- Modify: `tests/agent/test_orchestrator.py`
- Modify: `app/chat.py`
- Modify: `agent/orchestrator.py`
- Modify: `app/formatting.py`
- Delete: `agent/followups.py`
- Delete: `agent/reflection.py`
- Delete: `agent/translate.py`
- Delete: `tests/agent/test_followups.py`
- Delete: `tests/agent/test_reflection.py`

**Interfaces:**
- Consumes: `start_stream(question: str, session: AgentSession | None = None)` and existing trace/visual recorders.
- Produces: `_stream_answer(question: str) -> tuple[str, TraceRecorder, VisualRecorder]` plus unchanged citation and visual rendering behavior.

- [x] **Step 1: Replace the streaming test with the single-pass contract**

Assert that `_stream_answer` forwards the current session, streams only `type == "text"` content to one answer message, and returns the recorder objects supplied by `start_stream`.

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/agent/test_streaming.py -q`

Expected: collection or assertion failure because `_stream_answer` and the simplified `start_stream` call do not exist yet.

- [x] **Step 3: Implement the minimal single-pass UI**

Keep only chat start, message handling, `_stream_answer`, `_visual_elements`, `_resolve_source_pdf`, and citation rendering. Remove settings, reflection loops, follow-up actions, debug actions, reasoning translation, tool-progress steps, and the source-doc route.

- [x] **Step 4: Make reasoning configuration static**

Replace effort validation with one `REASONING_OPTIONS = {"reasoning": {"effort": "medium", "summary": "auto"}}` constant and remove the `effort` argument from `build_agent` and `start_stream`.

- [x] **Step 5: Delete the optional modules and dead formatters**

Delete the three secondary-agent modules and their dedicated tests. Keep only `cited_sources`, `dedup_sources`, and `format_citations` in `app/formatting.py`.

- [x] **Step 6: Run the focused tests and verify GREEN**

Run: `uv run pytest tests/agent/test_streaming.py tests/agent/test_orchestrator.py tests/app -q`

Expected: all selected tests pass.

### Task 2: Remove Debug Capture And Blob-Only Infrastructure

**Files:**
- Modify: `tests/agent/test_observability.py`
- Modify: `tests/test_settings.py`
- Modify: `agent/observability.py`
- Modify: `config/settings.py`
- Modify: `.chainlit/config.toml`
- Modify: `infra/main.bicep`
- Modify: `infra/modules/apprbac.bicep`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Delete: `app/source_docs.py`
- Delete: `infra/modules/storage.bicep`

**Interfaces:**
- Consumes: `APPINSIGHTS_CONNECTION_STRING` and managed identity authentication.
- Produces: `setup_observability() -> bool`, returning `False` without a connection string and configuring one Azure Monitor trace exporter otherwise.

- [x] **Step 1: Write the no-configuration observability test**

Assert that `setup_observability()` returns `False` and does not configure providers when the Application Insights connection string is blank.

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/agent/test_observability.py -q`

Expected: failure because the current implementation always creates an in-memory exporter and returns `True`.

- [x] **Step 3: Implement Azure-only trace setup**

Remove in-memory span state, `reset_trace`, and `collect_trace_json`. Configure `AzureMonitorTraceExporter` and Agent Framework instrumentation only when Application Insights is configured.

- [x] **Step 4: Remove the Blob source-doc path**

Delete its module, settings, header link, Storage module, environment variables, outputs, existing-resource declaration, and three Storage role assignments. Keep source PDFs in the container for local page rendering.

- [x] **Step 5: Refresh dependencies and validate the focused slice**

Run: `uv lock`

Run: `uv run pytest tests/agent/test_observability.py tests/test_settings.py -q`

Expected: lockfile refresh succeeds and all selected tests pass.

- [x] **Step 6: Build Bicep**

Run: `az bicep build --file infra/main.bicep --stdout > /dev/null`

Expected: exit code 0 with no diagnostics.

### Task 3: Remove Confirmed Debris And Align Documentation

**Files:**
- Modify: `ingest/parser.py`
- Modify: `search/structured.py`
- Modify: `tests/eval/test_runner.py`
- Modify: `README.md`
- Modify: `chainlit.md`

**Interfaces:**
- Preserves: every public ingestion, search, agent, and evaluation interface retained by the design.
- Removes: one unused import, two unused locals, one stale evaluator monkeypatch, and documentation for deleted behavior.

- [x] **Step 1: Remove only Pylance-confirmed or reference-confirmed debris**

Delete the unused `os` import, `first_year`/`last_year` locals, and obsolete `RetrievalEvaluator` monkeypatch. Do not remove any analytics operation.

- [x] **Step 2: Rewrite current-user documentation**

Describe the four indexes, one-pass streaming UI, citations/visuals, deterministic structured tools, evaluation, and optional Application Insights tracing. Remove reflection, debug, live tool-progress, and source-doc link claims.

- [x] **Step 3: Run complete verification**

Run: `uv run pytest -q`

Run: `uv lock --check`

Run: `git diff --check`

Run Pylance workspace diagnostics and build `infra/main.bicep` once more.

Expected: zero test failures, current lockfile, no whitespace errors, no Pylance errors, and a successful Bicep build.