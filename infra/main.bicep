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
