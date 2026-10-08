#!/usr/bin/env bash
set -euo pipefail

# Explicit targets only. This script does not reset any Search data.
: "${SUB:?Set SUB to the intended subscription ID}"
: "${RG:?Set RG to the existing resource group}"
: "${UPLOAD_STORAGE_ACCOUNT:?Set UPLOAD_STORAGE_ACCOUNT}"
: "${SEARCH_SERVICE_NAME:?Set SEARCH_SERVICE_NAME}"
: "${DOC_INTELLIGENCE_NAME:?Set DOC_INTELLIGENCE_NAME}"
: "${FOUNDRY_NAME:?Set FOUNDRY_NAME}"
: "${FOUNDRY_PROJECT_ENDPOINT:?Set FOUNDRY_PROJECT_ENDPOINT}"
: "${APP_INSIGHTS_NAME:?Set APP_INSIGHTS_NAME}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCATION="${LOCATION:-koreacentral}"
az account set --subscription "$SUB"
az provider register --namespace Microsoft.EventGrid --wait -o none
az deployment group create -g "$RG" -n blob-ingestion \
  --template-file "$ROOT/infra/ingestion.bicep" \
  --parameters location="$LOCATION" \
    existingStorageAccountName="$UPLOAD_STORAGE_ACCOUNT" \
    existingSearchName="$SEARCH_SERVICE_NAME" \
    existingDocIntelligenceName="$DOC_INTELLIGENCE_NAME" \
    existingFoundryName="$FOUNDRY_NAME" \
    foundryProjectEndpoint="$FOUNDRY_PROJECT_ENDPOINT" \
    existingAppInsightsName="$APP_INSIGHTS_NAME" -o none

FUNC_NAME="$(az deployment group show -g "$RG" -n blob-ingestion --query properties.outputs.functionAppName.value -o tsv)"
FUNC_ID="$(az deployment group show -g "$RG" -n blob-ingestion --query properties.outputs.functionAppId.value -o tsv)"
API="$(az deployment group show -g "$RG" -n blob-ingestion --query properties.outputs.apiEndpoint.value -o tsv)"
PACKAGE="$(mktemp -t mirae-ingest)"
trap 'rm -f -- "$PACKAGE"' EXIT
python3 - "$ROOT" "$PACKAGE" <<'PY'
from pathlib import Path
import sys
from zipfile import ZipFile

root, destination = Path(sys.argv[1]), sys.argv[2]
with ZipFile(destination, "w") as archive:
    for filename in ("function_app.py", "host.json", "requirements.txt"):
        archive.write(root / "functions" / "ingestion" / filename, filename)
    for package in ("ingest", "config"):
        for source in sorted((root / package).glob("*.py")):
            archive.write(source, str(source.relative_to(root)))
PY
az functionapp deployment source config-zip -g "$RG" -n "$FUNC_NAME" \
  --src "$PACKAGE" --build-remote true -o none

STORAGE_ID="$(az storage account show -g "$RG" -n "$UPLOAD_STORAGE_ACCOUNT" --query id -o tsv)"
# Reuse the legacy subscription name: update it rather than creating a second consumer.
az eventgrid event-subscription create \
  --name blob-to-search-demo --source-resource-id "$STORAGE_ID" \
  --endpoint-type azurefunction --endpoint "$FUNC_ID/functions/index" \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with "/blobServices/default/containers/pdfs/" -o none

if [[ -n "${CONTAINER_APP_NAME:-}" ]]; then
  az containerapp update -g "$RG" -n "$CONTAINER_APP_NAME" \
    --set-env-vars "INGEST_API_ENDPOINT=$API" "SEARCH_INDEX_FIGURE=figure-index" -o none
fi
curl --fail --silent --show-error --retry 6 --retry-all-errors --retry-delay 10 \
  "$API/api/documents"
printf '\nUpload: %s/api/upload\nSet INGEST_API_ENDPOINT=%s in the updated chatbot.\n' "$API" "$API"
printf 'Search data has NOT been reset. Use python -m ingest.reset with the confirmed endpoint.\n'
