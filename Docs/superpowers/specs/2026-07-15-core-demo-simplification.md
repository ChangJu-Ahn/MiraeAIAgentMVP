# Core Demo Simplification

## Goal

Make the PoC easy to read from the user question to the grounded answer while preserving the behavior that proves the product: deterministic retrieval, citations, visual evidence, ingestion validation, evaluation, and Azure observability.

## Selected Scope

Use a single-pass core demo:

1. Chainlit creates one Agent Framework session per chat.
2. Each message runs the Foundry agent once and streams only the final answer.
3. Search tools record sources and deterministic evidence as they do today.
4. Chainlit renders requested tables, charts, source-page images, and cited sources.
5. Application Insights receives Agent Framework traces when configured.

The following optional processes are removed:

- reflection and second-round answer generation
- generated follow-up questions and action callbacks
- reasoning-summary translation
- reasoning/tool-call progress UI
- debug sidebar, raw in-memory OpenTelemetry traces, and debug settings
- runtime Blob listing, user-delegation SAS generation, and the `/source-docs` page
- the Storage account and Storage RBAC that existed only for that page

The following integrity-critical behavior is explicitly retained:

- narrative, table, catalog, and fact indexes
- corpus-manifest guards and missing-source refusal
- annual-summary grade authority and evaluated-population scoping
- deterministic ranking, distribution, year comparison, grade change, and intersection operations
- source/evidence recording used by citations and evaluation
- ingestion completeness validation and the five-judge evaluation artifact
- tables, charts, and local source-page rendering

## Code Shape

`app/chat.py` owns only four steps: initialize a session, stream answer text, bind visuals, and render citations. It has no secondary model calls, settings callbacks, custom FastAPI route, debug store, or action callbacks.

`agent/orchestrator.py` keeps the sync, async, and streaming entry points. Reasoning options are one static default rather than a user-configurable branch.

`agent/observability.py` configures the Azure Monitor trace exporter only when `APPINSIGHTS_CONNECTION_STRING` is set. It no longer keeps process-local spans for a UI feature.

The structured search, ingestion, and evaluation implementations remain in place. Confirmed unused imports, variables, and stale test setup are removed without redesigning those modules.

## Infrastructure

Container Apps, managed identity, ACR, AI Search, Document Intelligence, Foundry, and Application Insights remain. Blob Storage is removed because no retained runtime or ingestion path consumes it. The container continues to copy source PDFs so `show_source_page` can render evidence locally.

## Acceptance Criteria

- A chat message produces one agent run and streams its final text.
- Multi-turn session continuity remains.
- Cited sources and requested visuals still render.
- CLI queries and evaluation continue to use the same orchestrator and evidence recorders.
- No production import or configuration points to the removed optional modules or Blob source-doc feature.
- Python tests pass, Pylance reports no errors, the lockfile is current, and `infra/main.bicep` builds.

## Non-Goals

- Redesigning deterministic analytics or ingestion schemas
- Changing the four-index retrieval contract
- Rewriting the Agent Framework integration
- Removing evaluation to reduce line count
- Adding replacement abstractions for deleted features