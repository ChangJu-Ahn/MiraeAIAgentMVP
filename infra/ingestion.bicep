targetScope = 'resourceGroup'

param location string = resourceGroup().location
@description('기존 스토리지 계정 이름 (pdfs 컨테이너 추가 + Function 런타임)')
param existingStorageAccountName string
@description('기존 AI Search 서비스 이름')
param existingSearchName string
@description('기존 Application Insights 이름 (Function 관측/디버깅)')
param existingAppInsightsName string
param existingDocIntelligenceName string
param existingFoundryName string
param foundryProjectEndpoint string
param namePrefix string = 'blobsearch'
param suffix string = uniqueString(resourceGroup().id)
param uploadContainer string = 'pdfs'
param assetsContainer string = 'document-assets'
@description('Use private Blob networking for the existing restricted-storage deployment.')
param privateStorage bool = true
param prebuiltDeployment bool = false
param pauseProcessing bool = false
@allowed(['identity', 'keys'])
param authMode string = 'identity'
param resourceTags object = {}

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: existingStorageAccountName
}
resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: sa
  name: 'default'
}
resource pdfs 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: uploadContainer
  properties: {
    publicAccess: 'None'
  }
}
resource assets 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: assetsContainer
  properties: {
    publicAccess: 'None'
  }
}
resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: existingDocIntelligenceName
}
resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: existingSearchName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: existingFoundryName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: existingAppInsightsName
}

module net 'modules/ingestion-network.bicep' = if (privateStorage) {
  name: 'blobdemo-net'
  params: {
    location: location
    vnetName: 'vnet-${namePrefix}-${suffix}'
    storageAccountName: existingStorageAccountName
  }
}

module fn 'modules/ingestion-function.bicep' = {
  name: 'blobdemo-func'
  params: {
    name: '${namePrefix}-${suffix}'
    location: location
    storageAccountName: existingStorageAccountName
    searchEndpoint: 'https://${existingSearchName}.search.windows.net'
    funcSubnetId: net.?outputs.funcSubnetId ?? ''
    appInsightsConnectionString: appInsights.properties.ConnectionString
    docIntelligenceEndpoint: di.properties.endpoint
    foundryProjectEndpoint: foundryProjectEndpoint
    assetsContainer: assetsContainer
    uploadContainer: uploadContainer
    prebuiltDeployment: prebuiltDeployment
    pauseProcessing: pauseProcessing
    authMode: authMode
    resourceTags: resourceTags
    searchApiKey: authMode == 'keys' ? searchService.listAdminKeys().primaryKey : ''
    docIntelligenceApiKey: authMode == 'keys' ? di.listKeys().key1 : ''
    foundryApiKey: authMode == 'keys' ? foundry.listKeys().key1 : ''
    storageConnectionString: authMode == 'keys'
      ? 'DefaultEndpointsProtocol=https;AccountName=${sa.name};AccountKey=${sa.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
      : ''
  }
}

module rbac 'modules/ingestion-rbac.bicep' = if (authMode == 'identity') {
  name: 'blobdemo-rbac'
  params: {
    functionPrincipalId: fn.outputs.principalId
    storageAccountName: existingStorageAccountName
    searchName: existingSearchName
    docIntelligenceName: existingDocIntelligenceName
    foundryName: existingFoundryName
  }
}

output functionAppName string = fn.outputs.name
output functionAppId string = fn.outputs.id
output functionHostName string = fn.outputs.defaultHostName
output uploadUrl string = 'https://${fn.outputs.defaultHostName}/api/upload'
output apiEndpoint string = 'https://${fn.outputs.defaultHostName}'
output functionPrincipalId string = fn.outputs.principalId
