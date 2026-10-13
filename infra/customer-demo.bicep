targetScope = 'resourceGroup'

param location string = resourceGroup().location
param modelLocation string = location
param developerObjectId string = ''
@allowed(['keys', 'identity'])
param authMode string = 'keys'
param resourceTags object = {}
@allowed(['User', 'ServicePrincipal'])
param developerPrincipalType string = 'User'
param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-11-20'
@minValue(1)
param chatCapacity int = 10
param reasoningModelName string = 'gpt-5.4-mini'
param reasoningModelVersion string = '2026-03-17'
@minValue(1)
param reasoningCapacity int = 10
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
@minValue(1)
param embeddingCapacity int = 50

var suffix = uniqueString(resourceGroup().id)

module base 'main.bicep' = {
  name: 'customer-services'
  params: {
    location: location
    modelLocation: modelLocation
    suffix: suffix
    developerObjectId: developerObjectId
    developerPrincipalType: developerPrincipalType
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatCapacity: chatCapacity
    reasoningModelName: reasoningModelName
    reasoningModelVersion: reasoningModelVersion
    reasoningCapacity: reasoningCapacity
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingCapacity: embeddingCapacity
    deployApp: false
    useManagedIdentity: authMode == 'identity'
    resourceTags: resourceTags
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stmirae${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  tags: resourceTags
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: authMode == 'keys'
    publicNetworkAccess: 'Enabled'
  }
}

resource operatorStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (authMode == 'identity') {
  scope: storage
  name: guid(storage.id, developerObjectId, 'Storage Blob Data Contributor')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: developerObjectId
    principalType: developerPrincipalType
  }
}

module ingestion 'ingestion.bicep' = {
  name: 'customer-ingestion'
  params: {
    location: location
    suffix: suffix
    existingStorageAccountName: storage.name
    existingSearchName: base.outputs.searchName
    existingDocIntelligenceName: base.outputs.docIntelligenceName
    existingFoundryName: base.outputs.foundryName
    foundryProjectEndpoint: base.outputs.foundryProjectEndpoint
    existingAppInsightsName: base.outputs.appInsightsName
    privateStorage: false
    prebuiltDeployment: true
    pauseProcessing: true
    authMode: authMode
    resourceTags: resourceTags
  }
}

output storageAccountName string = storage.name
output storageId string = storage.id
output storageEndpoint string = storage.properties.primaryEndpoints.blob
output uploadContainer string = 'pdfs'
output assetsContainer string = 'document-assets'
output functionAppName string = ingestion.outputs.functionAppName
output functionAppId string = ingestion.outputs.functionAppId
output functionPrincipalId string = ingestion.outputs.functionPrincipalId
output apiEndpoint string = ingestion.outputs.apiEndpoint
output uploadUrl string = ingestion.outputs.uploadUrl
output searchEndpoint string = base.outputs.searchEndpoint
output searchName string = base.outputs.searchName
output docIntelligenceEndpoint string = base.outputs.docIntelligenceEndpoint
output foundryProjectEndpoint string = base.outputs.foundryProjectEndpoint
output chatDeploymentName string = base.outputs.chatDeploymentName
output reasoningDeploymentName string = base.outputs.reasoningDeploymentName
output embeddingDeploymentName string = base.outputs.embeddingDeploymentName
output acrName string = base.outputs.acrName
output acrLoginServer string = base.outputs.acrLoginServer
output uamiId string = base.outputs.uamiId
output uamiClientId string = base.outputs.uamiClientId
output uamiPrincipalId string = base.outputs.uamiPrincipalId
output containerEnvironmentId string = base.outputs.containerEnvironmentId
output containerAppName string = 'ca-mirae-${suffix}'
output appInsightsConnectionString string = base.outputs.appInsightsConnectionString
output foundryName string = base.outputs.foundryName
output authenticationMode string = authMode
output resourceTags object = resourceTags
