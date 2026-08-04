#!/usr/bin/env bash
set -euo pipefail

# 이 스크립트는 위치에 상관없이 실행되도록 자기 폴더 기준으로 경로를 계산한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_ROOT="$(dirname "$SCRIPT_DIR")"

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
RG="rg-mirae-ai-agent-poc"
LOCATION="${LOCATION:-koreacentral}"
FUNC_DIR="$DEMO_ROOT/function"

command -v func >/dev/null 2>&1 || {
  echo "Azure Functions Core Tools(func)가 필요합니다: npm i -g azure-functions-core-tools@4" >&2
  exit 1
}

az account set --subscription "$SUB"
az provider register --namespace Microsoft.EventGrid -o none || true

echo "== 기존 리소스 확인 =="
if [[ -z "${UPLOAD_STORAGE_ACCOUNT:-}" ]]; then
  ACCTS="$(az storage account list -g "$RG" --query "[].name" -o tsv)"
  COUNT="$(printf '%s\n' "$ACCTS" | grep -c . || true)"
  if [[ "$COUNT" != "1" ]]; then
    echo "스토리지 계정이 $COUNT개입니다. UPLOAD_STORAGE_ACCOUNT로 지정하세요:" >&2
    printf '%s\n' "$ACCTS" >&2
    exit 1
  fi
  UPLOAD_STORAGE_ACCOUNT="$(printf '%s\n' "$ACCTS" | head -1)"
fi
export UPLOAD_STORAGE_ACCOUNT
if [[ -z "${SEARCH_SERVICE_NAME:-}" ]]; then
  SEARCH_SERVICE_NAME="$(az search service list -g "$RG" --query "[0].name" -o tsv)"
fi
export SEARCH_SERVICE_NAME
if [[ -z "${APP_INSIGHTS_NAME:-}" ]]; then
  APP_INSIGHTS_NAME="$(az resource list -g "$RG" --resource-type Microsoft.Insights/components --query "[0].name" -o tsv)"
fi
export APP_INSIGHTS_NAME
echo "storage=$UPLOAD_STORAGE_ACCOUNT  search=$SEARCH_SERVICE_NAME  appinsights=$APP_INSIGHTS_NAME"

# 이 데모는 공유키(shared key) 없이 관리 ID(RBAC)만으로 동작한다.
# 스토리지가 allowSharedKeyAccess=false + publicNetworkAccess=Disabled(정책 강제)라
# Dedicated(App Service) 플랜을 쓴다: 코드는 플랫폼 관리 wwwroot에 배포(사용자 스토리지 미접근)되고
# 런타임 스토리지 접근만 VNet 통합 + 프라이빗 엔드포인트로 처리한다.

echo "== Bicep 배포 =="
az deployment group create \
  --resource-group "$RG" \
  --name blob-demo \
  --template-file "$DEMO_ROOT/infra/blob-demo.bicep" \
  --parameters "$DEMO_ROOT/infra/blob-demo.bicepparam" \
  --parameters location="$LOCATION" \
  -o none

FUNC_NAME="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.functionAppName.value -o tsv)"
FUNC_ID="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.functionAppId.value -o tsv)"
UPLOAD_URL="$(az deployment group show -g "$RG" -n blob-demo --query properties.outputs.uploadUrl.value -o tsv)"
echo "function=$FUNC_NAME"

echo "== 함수 코드 배포 (Linux 원격 빌드; wwwroot 배포) =="
# Dedicated 플랜은 코드를 플랫폼 관리 wwwroot에 배포하므로 사용자 스토리지에 접근하지 않는다.
# SCM_DO_BUILD_DURING_DEPLOYMENT=true 로 Oryx 원격 빌드(pip install)가 수행된다.
sleep 30
PUBLISH_OK=0
for attempt in 1 2 3 4 5 6; do
  if ( cd "$FUNC_DIR" && func azure functionapp publish "$FUNC_NAME" --python --build remote ); then
    PUBLISH_OK=1
    break
  fi
  echo "publish 실패 — 대기 후 재시도 ($attempt/6)..." >&2
  sleep 30
done
if [[ "$PUBLISH_OK" != "1" ]]; then
  echo "함수 코드 배포에 실패했습니다." >&2
  exit 1
fi

echo "== Event Grid 구독 생성 =="
STORAGE_ID="$(az storage account show -g "$RG" -n "$UPLOAD_STORAGE_ACCOUNT" --query id -o tsv)"
az eventgrid event-subscription create \
  --name blob-to-search-demo \
  --source-resource-id "$STORAGE_ID" \
  --endpoint-type azurefunction \
  --endpoint "$FUNC_ID/functions/index" \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with "/blobServices/default/containers/pdfs/" \
  -o none

echo ""
echo "== 완료 =="
echo "업로드 페이지: $UPLOAD_URL"
echo "CLI 업로드 예: az storage blob upload --account-name $UPLOAD_STORAGE_ACCOUNT --container pdfs --auth-mode login -f <sample.pdf> -n <sample.pdf>"
echo "인덱스 확인:  SEARCH_ENDPOINT=https://$SEARCH_SERVICE_NAME.search.windows.net uv run python \"$DEMO_ROOT/scripts/verify_blob_demo.py\""
