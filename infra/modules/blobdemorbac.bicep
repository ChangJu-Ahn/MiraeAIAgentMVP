@description('Function App 시스템 관리 ID의 principalId')
param functionPrincipalId string
param storageAccountName string
param searchName string

// Storage Blob Data Owner: 런타임(AzureWebJobsStorage)·배포 컨테이너·업로드 컨테이너를
// 공유키 없이 관리 ID로 읽고 쓰기 위해 필요.
var storageBlobDataOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}

resource fnStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, functionPrincipalId, storageBlobDataOwner)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwner)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource fnSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, functionPrincipalId, searchServiceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource fnSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, functionPrincipalId, searchIndexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}
