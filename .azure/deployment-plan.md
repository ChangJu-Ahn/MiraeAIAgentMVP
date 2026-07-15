# Azure Deployment Plan: MiraeAIAgentMVP

Status: Validated

Recipe: Bicep infrastructure with Azure CLI container deployment

## Goal

Run the public Chainlit PoC on Azure Container Apps with managed identity access to AI Search and Microsoft Foundry.

## Infrastructure

| Resource | Bicep module | Purpose |
|---|---|---|
| Azure AI Search | `search.bicep` | Four retrieval indexes |
| Document Intelligence | `docintelligence.bicep` | PDF layout extraction |
| Microsoft Foundry | `foundry.bicep` | Chat, embedding, vision, and evaluation models |
| Application Insights and Log Analytics | `observability.bicep` | Agent trace and platform logs |
| User-assigned managed identity | `identity.bicep` | Keyless application identity |
| Azure Container Registry | `acr.bicep` | Container images |
| Container Apps environment | `containerenv.bicep` | Runtime environment |
| Container App | `containerapp.bicep` | Public Chainlit endpoint, one replica |
| Role assignments | `rbac.bicep`, `apprbac.bicep` | Search read, Foundry inference, ACR pull |

Blob Storage is not part of the current application. Source-page rendering uses PDFs copied into the container image.

## Runtime

- Image command: `chainlit run app/chat.py --host 0.0.0.0 --port 8000`
- Authentication: `DefaultAzureCredential` selects the user-assigned identity through `AZURE_CLIENT_ID`.
- Required endpoints and deployment names are injected as Container App environment variables.
- `APPINSIGHTS_CONNECTION_STRING` enables Agent Framework trace export.
- Ingestion remains a local operator command; the Container App only queries existing indexes.

## Deployment

1. Validate and deploy `infra/main.bicep`.
2. Build and push the image to ACR.
3. Set `deployApp=true` and the new image reference.
4. Verify the public endpoint, a grounded answer, citations, and requested visuals.

```bash
bash scripts/verify_availability.sh
bash scripts/deploy.sh
uv run python scripts/smoke_test.py
```

## Security

- Azure service access is keyless and limited by RBAC.
- The public Chainlit endpoint has no end-user authentication for this PoC.
- The Application Insights connection string is the only runtime connection string.
- The app is fixed at one replica because the current Chainlit conversation session is process-local.

## Current Deployment

- Resource group: `rg-mirae-ai-agent-poc`
- Region: `koreacentral`
- Container App: `ca-mirae-v4xy5m5d3ltw6`
- Public URL: https://ca-mirae-v4xy5m5d3ltw6.purplesky-16661974.koreacentral.azurecontainerapps.io
- Image: `acrmiraev4xy5m5d3ltw6.azurecr.io/mirae-chat:v10`

The previously deployed Storage account is no longer referenced by code or Bicep. Removing that existing Azure resource is an explicit operational cleanup, not an incremental Bicep deployment side effect.

## Validation Proof

Validated on 2026-07-15 against subscription `347e0df7-94e9-4feb-b42d-57d7e49566f2`, resource group `rg-mirae-ai-agent-poc`, and region `koreacentral`.

- `uv run pytest -q`: 390 passed.
- `uv lock --check` and `git diff --check`: passed.
- Pylance workspace diagnostics: zero errors.
- `az bicep build --file infra/main.bicep --stdout`: passed with Bicep 0.41.2.
- `az deployment group validate ... deployApp=true containerImage=<current-image>`: `Succeeded`.
- `az deployment group what-if ...`: `Succeeded`; 17 deploy, 2 ignore, 5 role-assignment resources unresolved until deployment, and zero deletes.
- Live RBAC: UAMI has `Search Index Data Reader`, `Cognitive Services OpenAI User`, `Cognitive Services User`, and `AcrPull` on the required resources.
- Azure Policy assignments at the target resource-group scope: none.
- `uv run python scripts/smoke_test.py`: AI Search, Document Intelligence, and Foundry passed with keyless authentication.
- Container image context: five non-empty source PDFs are copied by the Dockerfile and are not excluded by `.dockerignore`.
- Azure AI Search inventory: `narrative-index`, `table-index`, `fund-catalog-index`, and `evaluation-facts-index`; all four are referenced by production code, so no index is eligible for deletion.
