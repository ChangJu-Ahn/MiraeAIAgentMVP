#!/usr/bin/env bash
set -euo pipefail

SUB="347e0df7-94e9-4feb-b42d-57d7e49566f2"
LOCATION="${LOCATION:-koreacentral}"
CHAT_MODEL="${CHAT_MODEL:-gpt-4o}"
EMBED_MODEL="${EMBED_MODEL:-text-embedding-3-large}"

az account set --subscription "$SUB"
echo "== Region: $LOCATION =="

echo "-- AI Search SKUs (need basic+) --"
az search service list-sku-mapping 2>/dev/null || true
az provider show --namespace Microsoft.Search \
  --query "resourceTypes[?resourceType=='searchServices'].locations" -o tsv \
  | tr ',' '\n' | grep -i "korea" || echo "WARN: Search may not list koreacentral"

echo "-- Cognitive Services (Document Intelligence 'FormRecognizer') --"
az cognitiveservices account list-skus --location "$LOCATION" --kind FormRecognizer \
  -o table 2>/dev/null || echo "WARN: FormRecognizer SKU query failed for $LOCATION"

echo "-- Foundry (AIServices) chat/embedding model availability --"
az cognitiveservices model list --location "$LOCATION" \
  --query "[?contains(model.name, '${CHAT_MODEL}') || contains(model.name, '${EMBED_MODEL}')].{name:model.name, version:model.version, sku:model.skus[0].name}" \
  -o table 2>/dev/null || echo "WARN: model list failed; check portal"

echo ""
echo "위 목록에 $CHAT_MODEL, $EMBED_MODEL 이 없으면 LOCATION 또는 모델명을 조정하세요."
