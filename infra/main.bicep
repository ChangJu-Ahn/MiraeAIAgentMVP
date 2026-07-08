targetScope = 'resourceGroup'

param location string = resourceGroup().location
@description('현재 개발자 objectId (az ad signed-in-user)')
param developerObjectId string
@description('리소스 이름 접미사(전역 유니크)')
param suffix string = uniqueString(resourceGroup().id)

param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-11-20'
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'

@description('ACA 컨테이너 이미지 (초기 배포는 placeholder, 이후 실이미지로 갱신)')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Container App 배포 여부 (1단계=false로 인프라만, 이미지 빌드 후 2단계=true)')
param deployApp bool = false

module search 'modules/search.bicep' = {
  name: 'search'
  params: {
    name: 'srch-mirae-${suffix}'
    location: location
    sku: 'basic'
  }
}

module di 'modules/docintelligence.bicep' = {
  name: 'docintelligence'
  params: {
    name: 'di-mirae-${suffix}'
    location: location
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    name: 'aif-mirae-${suffix}'
    location: location
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    developerObjectId: developerObjectId
    searchPrincipalId: search.outputs.searchPrincipalId
    searchName: search.outputs.searchName
    docIntelligenceName: di.outputs.docIntelligenceName
    foundryName: foundry.outputs.foundryName
  }
}

module observability 'modules/observability.bicep' = {
  name: 'observability'
  params: {
    name: 'mirae-${suffix}'
    location: location
  }
}

output docIntelligenceEndpoint string = di.outputs.docIntelligenceEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output foundryProjectEndpoint string = foundry.outputs.foundryProjectEndpoint
output chatDeploymentName string = foundry.outputs.chatDeploymentName
output embeddingDeploymentName string = foundry.outputs.embeddingDeploymentName
output reasoningDeploymentName string = foundry.outputs.reasoningDeploymentName
output appInsightsConnectionString string = observability.outputs.appInsightsConnectionString

// ── ACA 앱 배포용 리소스 ──────────────────────────────────────────────
module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    name: 'id-mirae-${suffix}'
    location: location
  }
}

module acr 'modules/acr.bicep' = {
  name: 'acr'
  params: {
    name: 'acrmirae${suffix}'
    location: location
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    name: 'stmirae${suffix}'
    location: location
  }
}

module containerenv 'modules/containerenv.bicep' = {
  name: 'containerenv'
  params: {
    name: 'cae-mirae-${suffix}'
    location: location
    logAnalyticsName: observability.outputs.logAnalyticsName
  }
}

module containerapp 'modules/containerapp.bicep' = if (deployApp) {
  name: 'containerapp'
  params: {
    name: 'ca-mirae-${suffix}'
    location: location
    environmentId: containerenv.outputs.id
    acrLoginServer: acr.outputs.loginServer
    uamiId: identity.outputs.id
    image: containerImage
    envVars: [
      { name: 'SEARCH_ENDPOINT', value: search.outputs.searchEndpoint }
      { name: 'SEARCH_INDEX_NARRATIVE', value: 'narrative-index' }
      { name: 'SEARCH_INDEX_TABLE', value: 'table-index' }
      { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundry.outputs.foundryProjectEndpoint }
      { name: 'FOUNDRY_CHAT_DEPLOYMENT', value: foundry.outputs.reasoningDeploymentName }
      { name: 'FOUNDRY_VISION_DEPLOYMENT', value: foundry.outputs.chatDeploymentName }
      { name: 'FOUNDRY_EVAL_DEPLOYMENT', value: foundry.outputs.chatDeploymentName }
      { name: 'FOUNDRY_EMBEDDING_DEPLOYMENT', value: foundry.outputs.embeddingDeploymentName }
      { name: 'FOUNDRY_API_VERSION', value: '2024-10-21' }
      { name: 'APPINSIGHTS_CONNECTION_STRING', value: observability.outputs.appInsightsConnectionString }
      { name: 'AZURE_CLIENT_ID', value: identity.outputs.clientId }
      { name: 'STORAGE_ACCOUNT_NAME', value: storage.outputs.accountName }
      { name: 'SOURCE_DOCS_CONTAINER', value: storage.outputs.containerName }
    ]
  }
}

module apprbac 'modules/apprbac.bicep' = {
  name: 'apprbac'
  params: {
    uamiPrincipalId: identity.outputs.principalId
    developerObjectId: developerObjectId
    searchName: search.outputs.searchName
    foundryName: foundry.outputs.foundryName
    acrName: acr.outputs.name
    storageAccountName: storage.outputs.accountName
  }
}

output acrLoginServer string = acr.outputs.loginServer
output acrName string = acr.outputs.name
output storageAccountName string = storage.outputs.accountName
output sourceDocsContainer string = storage.outputs.containerName
output blobEndpoint string = storage.outputs.blobEndpoint
output containerAppName string = deployApp ? containerapp.outputs.name : ''
output containerAppFqdn string = deployApp ? containerapp.outputs.fqdn : ''
output uamiClientId string = identity.outputs.clientId
