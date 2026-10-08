@description('Function App 시스템 관리 ID의 principalId')
param functionPrincipalId string
param storageAccountName string
param searchName string
param docIntelligenceName string
param foundryName string

// Storage Blob Data Owner: 런타임(AzureWebJobsStorage)·배포 컨테이너·업로드 컨테이너를
// 공유키 없이 관리 ID로 읽고 쓰기 위해 필요.
var storageBlobDataOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

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
resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: docIntelligenceName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryName
}
resource fnDI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: di
  name: guid(di.id, functionPrincipalId, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource fnFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, functionPrincipalId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
  }
}
