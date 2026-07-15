@description('ACA 앱 UAMI principalId')
param uamiPrincipalId string
param searchName string
param foundryName string
param acrName string

var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var openAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryName
}
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

// UAMI → Search (인덱스 질의, 읽기)
resource uamiSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, uamiPrincipalId, searchIndexDataReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// UAMI → Foundry (LLM/임베딩 추론)
resource uamiFoundryOpenAI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, uamiPrincipalId, openAIUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAIUser)
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource uamiFoundryCog 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, uamiPrincipalId, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// UAMI → ACR (이미지 pull)
resource uamiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, uamiPrincipalId, acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}
