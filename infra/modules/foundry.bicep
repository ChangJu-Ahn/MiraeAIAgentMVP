@description('Foundry(AIServices) 계정 이름')
param name string
param location string
param projectName string = 'proj-mirae-poc'

param chatModelName string = 'gpt-4o'
param chatModelVersion string = '2024-11-20'
param chatDeploymentName string = 'chat'
param chatCapacity int = 20

param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
param embeddingDeploymentName string = 'embedding'
param embeddingCapacity int = 50

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: name
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: chatDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: embeddingDeploymentName
  dependsOn: [chat]
  sku: {
    name: 'Standard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

output foundryName string = account.name
output foundryEndpoint string = account.properties.endpoint
output foundryProjectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${projectName}'
output foundryPrincipalId string = account.identity.principalId
output chatDeploymentName string = chat.name
output embeddingDeploymentName string = embedding.name
