targetScope = 'resourceGroup'

param location string = resourceGroup().location
@description('기존 스토리지 계정 이름 (pdfs 컨테이너 추가 + Function 런타임)')
param existingStorageAccountName string
@description('기존 AI Search 서비스 이름')
param existingSearchName string
param namePrefix string = 'blobsearch'
param suffix string = uniqueString(resourceGroup().id)
param uploadContainer string = 'pdfs'
param searchIndexName string = 'demo-blob-index'

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

module fn 'modules/functionapp.bicep' = {
  name: 'blobdemo-func'
  params: {
    name: '${namePrefix}-${suffix}'
    location: location
    storageAccountName: existingStorageAccountName
    searchEndpoint: 'https://${existingSearchName}.search.windows.net'
    searchIndexName: searchIndexName
    uploadContainer: uploadContainer
  }
}

module rbac 'modules/blobdemorbac.bicep' = {
  name: 'blobdemo-rbac'
  params: {
    functionPrincipalId: fn.outputs.principalId
    storageAccountName: existingStorageAccountName
    searchName: existingSearchName
  }
}

output functionAppName string = fn.outputs.name
output functionAppId string = fn.outputs.id
output functionHostName string = fn.outputs.defaultHostName
output uploadUrl string = 'https://${fn.outputs.defaultHostName}/api/upload'
