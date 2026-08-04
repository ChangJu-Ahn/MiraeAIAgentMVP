# Blob → Azure Function → AI Search Ingestion Demo Design

## Context

The team wants a small, self-contained demo that shows the classic
"event-driven ingestion" pattern on Azure: drop a PDF into Blob Storage, an
Azure Function fires automatically, and the extracted text lands in an Azure AI
Search index — with **no embeddings**, just static text chunking.

This is intentionally separate from the main MiraeAIAgentMVP application. It
must **not** modify `infra/main.bicep`, the Container App, or the existing
ingestion pipeline under `ingest/`. It reuses two existing Azure resources and
adds one new compute resource plus two lightweight child objects.

The existing environment (RG `rg-mirae-ai-agent-poc`, `koreacentral`) already
has:

- An Azure AI Search service (`srch-mirae-<suffix>`) created by `main.bicep`
  with `disableLocalAuth: true` (Entra ID / RBAC only, no API keys).
- A previously deployed Storage account that still exists in Azure but is no
  longer referenced by Bicep or code.

## Goals

- Upload a PDF to a blob container → Function runs automatically within seconds.
- Function statically chunks the extracted text and uploads documents to a new
  AI Search index. No embedding / vector generation.
- Deployable end-to-end from a single script; independently removable.

## Non-Goals

- No embeddings, vectors, or semantic ranking.
- No changes to `main.bicep`, the Container App, or existing indexes.
- No high-fidelity PDF parsing (no Document Intelligence). A lightweight text
  extraction is sufficient for the demo.
- Not production-hardened (no DLQ, no private networking, no alerting).

## Requirements

1. Reuse the **existing** Storage account; add only a **new container** `pdfs`.
2. Reuse the **existing** AI Search service; add only a **new index**
   `demo-blob-index`.
3. Trigger via **Event Grid**: Storage `BlobCreated` event delivered directly
   to the Function (Event Grid subscription with `--endpoint-type azurefunction`).
4. Function runtime: **Python 3.12**, Linux, Consumption (Y1) plan, v2
   programming model, **system-assigned managed identity**.
5. All data-plane access via **managed identity + RBAC** (the Search service
   forbids key auth).
6. Text extraction inside the Function using **pypdf** (no external service).
7. Static chunking: fixed **1000-character** chunks (configurable).
8. Idempotent: re-uploading the same PDF overwrites the same documents.

## Architecture

```
PDF upload ──► Storage (existing)          AI Search (existing)
              └─ container: pdfs               └─ index: demo-blob-index
                     │  BlobCreated                     ▲
                     ▼                                   │ upload_documents (MI)
              Event Grid subscription ──► Azure Function (new, Python)
              (endpoint-type=azurefunction)   1. parse event → blob URL
                                              2. download blob (MI)
                                              3. pypdf extract text
                                              4. static 1000-char chunk
                                              5. ensure index + upload docs
```

The Event Grid subscription and its auto-created system topic are lightweight,
free-tier routing objects — not an Azure subscription, not a compute resource.

## Components

### 1. New blob container (existing Storage account)

Referenced in Bicep as an `existing` storage account; a single
`blobServices/default/containers/pdfs` child resource is added. The Function's
runtime storage (`AzureWebJobsStorage`) reuses this same account.

- Primary runtime auth: connection string (simplest, most reliable for a demo).
- Contingency: if the account has `allowSharedKeyAccess = false`, the deploy
  script switches `AzureWebJobsStorage` to identity-based
  (`AzureWebJobsStorage__accountName` + the identity roles below). The deploy
  script checks this at deploy time.

### 2. New AI Search index — `demo-blob-index`

No vector field, no semantic config. Schema:

| field         | type            | attributes                         |
| ------------- | --------------- | ---------------------------------- |
| `id`          | Edm.String      | key                                |
| `content`     | Edm.String      | searchable, analyzer `ko.lucene`   |
| `source_file` | Edm.String      | filterable, facetable              |
| `chunk_index` | Edm.Int32       | filterable, sortable               |
| `page`        | Edm.Int32       | filterable (source page number)    |
| `uploaded_at` | Edm.DateTimeOffset | filterable, sortable            |

The Function ensures the index via `create_or_update_index` on invocation
(idempotent, self-contained).

### 3. Azure Function — `functions/blob_to_search/`

Isolated Python project with its own `requirements.txt` (does NOT pull in
chainlit / agent-framework, keeping the deployment package small).

Files:

- `function_app.py` — v2 model app with a single `@app.event_grid_trigger`.
- `chunking.py` — pure `chunk_text(text, size) -> list[str]` (unit-testable, no
  Azure imports).
- `requirements.txt` — `azure-functions`, `azure-identity`,
  `azure-search-documents`, `azure-storage-blob`, `pypdf`.
- `host.json`, `.funcignore`.

Handler flow:

1. Parse the Event Grid event; read `data.url` (blob URL) and container/blob
   name from the event subject. Skip if the blob is not under `pdfs/` or does
   not end in `.pdf`.
2. Download blob bytes with `BlobClient(account_url, container, blob,
   credential=DefaultAzureCredential())`.
3. Extract text **per page** with `pypdf.PdfReader`.
4. `chunk_text` each page's text into fixed 1000-char chunks; every chunk keeps
   its exact source `page` number and a document-global `chunk_index`.
5. Ensure the index exists, then `SearchClient.upload_documents` in batches.

Document id is deterministic: `f"{sanitize(source_file)}-{chunk_index}"`
(sanitized to the Search key charset: letters, digits, `_`, `-`, `=`). Using
`merge_or_upload` semantics makes re-delivery / re-upload idempotent.

App settings: `SEARCH_ENDPOINT`, `SEARCH_INDEX_NAME=demo-blob-index`,
`STORAGE_BLOB_ENDPOINT` (e.g. `https://<acct>.blob.core.windows.net`),
`CHUNK_SIZE=1000`, `FUNCTIONS_WORKER_RUNTIME=python`, `AzureWebJobsStorage`.

### 4. Event Grid subscription

Created by the deploy script after the Function is deployed:

```
az eventgrid event-subscription create \
  --name blob-to-search-demo \
  --source-resource-id <storage-account-id> \
  --endpoint-type azurefunction \
  --endpoint <function-app-id>/functions/<FunctionName> \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with /blobServices/default/containers/pdfs/
```

This is the CLI equivalent of the portal Storage → **Events** → *+ Event
Subscription* flow. It auto-creates a free system topic.

### 5. RBAC (Function system-assigned MI)

Reusing the repo's role-GUID convention (`infra/modules/*rbac.bicep`):

| scope             | role                          | GUID                                   | why                     |
| ----------------- | ----------------------------- | -------------------------------------- | ----------------------- |
| existing Storage  | Storage Blob Data Reader      | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | download PDF bytes      |
| existing Search   | Search Service Contributor    | `7ca78c08-252a-4471-8644-bb5ff32d4ba0` | `create_or_update_index`|
| existing Search   | Search Index Data Contributor | `8ebe5a00-799e-43f5-93ac-243d3dce84a7` | `upload_documents`      |

If identity-based `AzureWebJobsStorage` is required (shared key disabled), also
add Storage Blob Data Owner (`b7e6dc6d-f1e8-4753-8033-0f276bb0955b`) and Storage
Queue Data Contributor (`974c5e8b-45b9-4653-ba55-5f855dd0fb88`) on the Storage
account.

## Infrastructure as Code

New files, none touching `main.bicep`:

- `infra/blob-demo.bicep` (resourceGroup scope). Params: `existingStorageAccountName`,
  `existingSearchName`, `location`, `namePrefix`. Composes: `pdfs` container on
  the existing account, the Function App module, and the RBAC module. Outputs:
  `functionAppName`, `functionAppId`, `storageBlobEndpoint`, `searchEndpoint`.
- `infra/blob-demo.bicepparam`.
- `infra/modules/functionapp.bicep` — Y1 Linux plan + Function App
  (`linuxFxVersion: 'PYTHON|3.12'`), system-assigned identity, app settings,
  Application Insights connection (reuse existing App Insights if available,
  else skip).
- `infra/modules/blobdemorbac.bicep` — the three role assignments above.

## Deployment

`scripts/deploy_blob_demo.sh`:

1. `az account set --subscription 347e0df7-94e9-4feb-b42d-57d7e49566f2`.
2. Discover existing Storage account and Search service names in
   `rg-mirae-ai-agent-poc` (`az storage account list`, `az search service list`),
   overridable via env vars.
3. `az deployment group create` with `infra/blob-demo.bicep` (container +
   Function App + RBAC).
4. Publish Function code: `func azure functionapp publish <name> --python`
   (Azure Functions Core Tools; remote build). Documented zip-deploy fallback:
   `az functionapp deployment source config-zip` with
   `SCM_DO_BUILD_DURING_DEPLOYMENT=true`.
5. Create the Event Grid subscription (command above).
6. Print the test command.

## Testing

- **Unit** (`tests/test_blob_chunking.py`): `chunk_text` boundary cases (empty,
  shorter than size, exact multiple, remainder, unicode). Pure function, no
  Azure — runs in the existing `pytest` suite.
- **Manual E2E**:
  `az storage blob upload --account-name <acct> --container pdfs --auth-mode login -f sample.pdf -n sample.pdf`
  then confirm documents in `demo-blob-index`.
- **Verify helper** (`scripts/verify_blob_demo.py`): query the index document
  count via `SearchClient` + `DefaultAzureCredential`.

## Error Handling

- Non-`.pdf` or non-`pdfs/` blobs: log and return (no-op).
- Text extraction failure / empty text: log a warning and skip; do not raise, so
  Event Grid does not retry a poison blob indefinitely.
- Upload is idempotent (`merge_or_upload` + deterministic ids), so Event Grid's
  at-least-once delivery and any retries are safe.
- Missing index: created on the fly by the Function.

## Alternatives Considered

1. **Event Grid-sourced Blob Trigger** (`source=EventGrid`): least code, but
   wiring the subscription needs the blob extension webhook URL + system key
   post-deploy — extra fragile step. Rejected for deploy simplicity.
2. **Classic polling Blob Trigger**: simplest code, no Event Grid, but polls
   (minutes of latency) and is not truly event-driven — poor for a live demo.
   Rejected.
3. **New dedicated Storage account / new Search service**: cleaner isolation but
   the user explicitly wants to reuse the existing Storage and Search. Rejected.
4. **Document Intelligence for extraction**: higher-quality text but adds an
   external call, cost, and RBAC. Overkill for a static-chunking demo. Rejected
   in favor of pypdf.

## Assumptions

- The existing Storage account in `rg-mirae-ai-agent-poc` still exists and is
  writable; its exact name is resolved at deploy time.
- Consumption (Y1) Linux Python and Event Grid are available in `koreacentral`
  (both are); if Y1 is unavailable, fall back to Flex Consumption or Elastic
  Premium.
- The deploying developer already holds Search Service/Index Contributor on the
  Search service (granted by `main.bicep`'s `rbac.bicep`).
