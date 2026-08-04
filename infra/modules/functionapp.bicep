@description('Function App 이름 (전역 유니크)')
param name string
param location string
@description('Function 런타임 스토리지 겸 업로드 대상 기존 스토리지 계정 이름')
param storageAccountName string
@description('AI Search 엔드포인트 (https://<name>.search.windows.net)')
param searchEndpoint string
param searchIndexName string = 'demo-blob-index'
param uploadContainer string = 'pdfs'
param chunkSize int = 1000
param maxUploadMb int = 50

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var storageKey = sa.listKeys().keys[0].value
var storageConn = 'DefaultEndpointsProtocol=https;AccountName=${sa.name};AccountKey=${storageKey};EndpointSuffix=${environment().suffixes.storage}'
var blobEndpoint = 'https://${sa.name}.blob.${environment().suffixes.storage}'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage', value: storageConn }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageConn }
        { name: 'WEBSITE_CONTENTSHARE', value: toLower(name) }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'SEARCH_INDEX_NAME', value: searchIndexName }
        { name: 'STORAGE_BLOB_ENDPOINT', value: blobEndpoint }
        { name: 'UPLOAD_CONTAINER', value: uploadContainer }
        { name: 'CHUNK_SIZE', value: string(chunkSize) }
        { name: 'MAX_UPLOAD_MB', value: string(maxUploadMb) }
      ]
    }
  }
}

output name string = funcApp.name
output id string = funcApp.id
output principalId string = funcApp.identity.principalId
output defaultHostName string = funcApp.properties.defaultHostName
