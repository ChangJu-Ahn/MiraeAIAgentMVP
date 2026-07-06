#!/usr/bin/env bash
set -euo pipefail

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
RG="rg-mirae-ai-agent-poc"
LOCATION="${LOCATION:-koreacentral}"

az account set --subscription "$SUB"

echo "== 리소스 그룹 생성 =="
az group create --name "$RG" --location "$LOCATION" -o none

echo "== 개발자 objectId 조회 =="
export DEVELOPER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
echo "objectId=$DEVELOPER_OBJECT_ID"

echo "== what-if (변경 미리보기) =="
az deployment group what-if \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters location="$LOCATION" developerObjectId="$DEVELOPER_OBJECT_ID" || true

echo "== 배포 =="
az deployment group create \
  --resource-group "$RG" \
  --name mirae-p1 \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters location="$LOCATION" developerObjectId="$DEVELOPER_OBJECT_ID" \
  -o none

echo "== outputs → .env =="
OUT="$(az deployment group show --resource-group "$RG" --name mirae-p1 --query properties.outputs -o json)"
di=$(echo "$OUT"    | python3 -c "import sys,json;print(json.load(sys.stdin)['docIntelligenceEndpoint']['value'])")
srch=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['searchEndpoint']['value'])")
proj=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['foundryProjectEndpoint']['value'])")
chat=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['chatDeploymentName']['value'])")
embed=$(echo "$OUT" | python3 -c "import sys,json;print(json.load(sys.stdin)['embeddingDeploymentName']['value'])")
appi=$(echo "$OUT"  | python3 -c "import sys,json;print(json.load(sys.stdin)['appInsightsConnectionString']['value'])")

cat > .env <<EOF
DOC_INTELLIGENCE_ENDPOINT=$di
SEARCH_ENDPOINT=$srch
SEARCH_INDEX_NARRATIVE=narrative-index
SEARCH_INDEX_TABLE=table-index
FOUNDRY_PROJECT_ENDPOINT=$proj
FOUNDRY_CHAT_DEPLOYMENT=$chat
FOUNDRY_EMBEDDING_DEPLOYMENT=$embed
FOUNDRY_API_VERSION=2024-10-21
APPINSIGHTS_CONNECTION_STRING=$appi
EOF

echo "== .env 생성 완료 =="
cat .env
