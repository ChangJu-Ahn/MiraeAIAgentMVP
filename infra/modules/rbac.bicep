@description('개발자(현재 사용자) objectId')
param developerObjectId string
@description('Search 서비스 시스템 관리 ID principalId')
param searchPrincipalId string
param searchName string
param docIntelligenceName string
param foundryName string

var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var openAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}
resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: docIntelligenceName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryName
}

// 개발자 → Search 데이터/서비스
resource devSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchIndexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: developerObjectId
    principalType: 'User'
  }
}
resource devSearchSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, developerObjectId, searchServiceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// 개발자 → Document Intelligence
resource devDI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: di
  name: guid(di.id, developerObjectId, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// 개발자 → Foundry (OpenAI 데이터 평면)
resource devFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, developerObjectId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: developerObjectId
    principalType: 'User'
  }
}

// Search 관리 ID → Foundry (agentic retrieval이 임베딩/LLM 호출)
resource searchToFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, searchPrincipalId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
  }
}
