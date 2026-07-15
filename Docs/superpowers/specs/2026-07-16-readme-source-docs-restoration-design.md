# Readme and Source Documents Restoration Design

## Context

The core-demo simplification commit removed the `원본자료` header link and its
Storage-backed `/source-docs` route. The later evaluation experience added only
the `Evaluation` link, so users can no longer open the five source PDFs.

The repository README is the developer and operator reference. Chainlit's
`chainlit.md` is the user-facing Readme panel and should contain the verified
product overview without internal deployment commands or index schemas.

## Requirements

- Keep the existing `Evaluation` header link.
- Restore a `원본자료` header link that opens `/source-docs` in a new tab.
- List all five PDFs registered in `ingest.corpus.CORPUS` and open the actual
  PDF bytes in the browser, not screenshots or extracted text.
- Use stable manifest document IDs in URLs and never accept filesystem paths
  from the request.
- Work identically in local development and Azure Container Apps.
- Keep raw evaluation reports out of the container image.
- Expand the Chainlit Readme with verified, user-relevant content from the main
  README while preserving the main README as the full engineering reference.

## Chosen Design

Add `app/source_docs.py` as the owner of the source-document catalog, Unicode-
safe local path resolution, HTML index response, and inline PDF response. The
module resolves only entries from `CORPUS`, maps each entry to the existing
lowercase `docs/` directory, and returns HTTP 404 for unknown or missing IDs.

Register `/source-docs` and `/source-docs/{doc_id}` on Chainlit's FastAPI app
before the SPA catch-all. The list page links to stable ASCII document IDs;
`FileResponse` streams each matched file as `application/pdf` with inline
content disposition and supports the framework's normal file and range
handling.

The Container App already contains `docs/`, so this design introduces no
Storage account, SAS token, credential, RBAC, or package dependency. It also
avoids duplicating large PDFs under `public/`.

## Alternatives Considered

1. Restore the former private Blob and user-delegation SAS implementation.
   This preserves the old backend but reverses the deliberate Storage removal
   and adds runtime identity, RBAC, environment, and SDK dependencies.
2. Copy PDFs into `public/`. This is simple in the image but duplicates source
   assets and does not behave the same in a local checkout.

## User-Facing Readme

`chainlit.md` will describe the supported source set, evidence-first behavior,
high-level five-stage flow, deterministic analysis, visual outputs, settings,
evaluation dashboard, and limitations. It will not reproduce developer setup,
deployment, RBAC, or detailed index-field documentation.

The main README will correct two potentially misleading phrases: optional
reflection can cause a second agent run, and the five evaluation criteria use
one configured judge deployment rather than five judge models.

## Failure Handling and Security

- Unknown document IDs and missing files return 404 without exposing paths.
- The list contains only existing PDF entries from the manifest.
- HTML labels and links are escaped before rendering.
- The source route has no additional authentication because the current PoC
  endpoint and the requested source-document experience are public.

## Verification

- Contract tests for both header links and the expanded Readme.
- Unit tests for five manifest entries, Unicode-safe path resolution, escaped
  HTML, inline PDF response, and unknown-ID 404 behavior.
- Route-order test proving both endpoints precede Chainlit's SPA catch-all.
- Docker-context contract proving `docs/` remains included and reports remain
  excluded.
- Full pytest, lock, diff, diagnostics, Bicep/ARM preflight, local HTTP/browser
  checks, Azure deployment, production HTTP/browser checks, and log review.