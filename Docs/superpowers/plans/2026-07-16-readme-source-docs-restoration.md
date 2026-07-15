# Readme and Source Documents Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore browser access to all five RAG source PDFs and replace the minimal Chainlit Readme with verified user-facing project content.

**Architecture:** A focused `app/source_docs.py` module maps stable corpus IDs to the existing local PDFs and returns an HTML catalog or inline `FileResponse`. Chainlit registers those routes ahead of its SPA fallback, while header and Readme configuration remain declarative.

**Tech Stack:** Python 3.12, Chainlit 2.11, FastAPI/Starlette, pytest, Docker, Azure Container Apps

## Global Constraints

- Preserve the existing Evaluation experience and public-data allowlist.
- Serve only PDF entries registered in `ingest.corpus.CORPUS`.
- Do not restore Azure Storage, SAS, secrets, RBAC, or dependencies.
- Do not commit the three untracked raw evaluation reports.
- Use test-first red-green cycles for every behavior change.

---

### Task 1: Header and Readme Contracts

**Files:**
- Modify: `tests/app/test_evaluation_assets.py`
- Modify: `.chainlit/config.toml`
- Modify: `chainlit.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Chainlit `UI.header_links` and built-in `chainlit.md` Readme behavior.
- Produces: `Evaluation` and `원본자료` header entries plus verified user-facing documentation.

- [ ] Add assertions that the two header links target `/public/evaluation.html` and `/source-docs`, and that `chainlit.md` documents source files, behavior, settings, evaluation, and limitations.
- [ ] Run `uv run pytest tests/app/test_evaluation_assets.py -q` and confirm it fails because `원본자료` and the expanded Readme are absent.
- [ ] Add the header entry, replace the minimal Readme, and correct the two misleading evaluation/run phrases in `README.md`.
- [ ] Rerun the focused test and confirm it passes.

### Task 2: Manifest-Backed Source Documents

**Files:**
- Create: `tests/app/test_source_docs.py`
- Create: `app/source_docs.py`

**Interfaces:**
- Consumes: `ingest.corpus.CORPUS` and stable `CorpusDoc.doc_id` values.
- Produces: `source_documents()`, `source_docs_page()`, and `source_document_response(doc_id)`.

- [ ] Write tests requiring five existing manifest documents, normalized filename matching, escaped catalog HTML, inline PDF responses, and 404 for unknown IDs.
- [ ] Run `uv run pytest tests/app/test_source_docs.py -q` and confirm collection fails because `app.source_docs` is absent.
- [ ] Implement the three functions with a frozen source-document view model, NFC filename comparison, manifest-only lookup, `HTMLResponse`, and `FileResponse(content_disposition_type="inline")`.
- [ ] Rerun the focused test and confirm it passes.

### Task 3: Chainlit Route Registration and Image Contract

**Files:**
- Modify: `app/chat.py`
- Modify: `tests/app/test_source_docs.py`
- Verify: `Dockerfile`
- Verify: `.dockerignore`

**Interfaces:**
- Consumes: the three `app.source_docs` functions.
- Produces: GET `/source-docs` and GET `/source-docs/{doc_id}` before the Chainlit SPA route.

- [ ] Add a route-contract test that imports `app.chat`, inspects the Chainlit FastAPI router, and requires both source routes before the SPA fallback.
- [ ] Run the focused test and confirm it fails because the routes are absent.
- [ ] Register both routes at app import and move each new route ahead of the fallback.
- [ ] Add Docker assertions that `COPY docs/ docs/` is present, PDF assets are not ignored, and `reports/` remains ignored.
- [ ] Rerun both focused test files and confirm they pass.

### Task 4: Repository and Local Runtime Verification

**Files:**
- Verify all changed files.

**Interfaces:**
- Produces: a commit-ready, locally verified change set.

- [ ] Run Pylance diagnostics and syntax checks for changed Python files.
- [ ] Run `uv run pytest -q`, `uv lock --check`, and `git diff --check`.
- [ ] Start or reload Chainlit locally and verify `/source-docs` plus all five PDF URLs over HTTP.
- [ ] Verify the Readme, Evaluation, and 원본자료 header entries in desktop and mobile browser layouts.
- [ ] Review the final diff and confirm raw reports remain untracked.

### Task 5: Integration and Azure Deployment

**Files:**
- Update after validation: `.azure/deployment-plan.md`

**Interfaces:**
- Produces: pushed feature commit, merged `main`, new ACR image, healthy Container App revision, and deployment evidence.

- [ ] Run Bicep compilation, ARM validation/what-if, target-port checks, dependency smoke tests, RBAC checks, and record fresh validation proof.
- [ ] Commit only intended files, push the feature branch, merge into `main`, and push `main` without touching raw reports.
- [ ] Build the next immutable ACR image from the pushed merge and deploy it through the validated Bicep recipe.
- [ ] Verify production health, source catalog, all five PDF responses, Readme/header UI, Evaluation regression, logs, and telemetry.
- [ ] Record the deployed revision and image evidence, then push the deployment-plan update.