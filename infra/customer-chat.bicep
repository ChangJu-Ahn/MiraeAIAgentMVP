targetScope = 'resourceGroup'

param name string
param location string = resourceGroup().location
param environmentId string
param acrLoginServer string
param uamiId string
param image string
param envVars array
param authMode string = 'identity'
param searchName string = ''
param foundryName string = ''
param acrName string = ''
param resourceTags object = {}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}
resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: foundryName
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

module chat 'modules/containerapp.bicep' = {
  name: 'customer-chat'
  params: {
    name: name
    location: location
    environmentId: environmentId
    acrLoginServer: acrLoginServer
    uamiId: uamiId
    image: image
    envVars: concat(envVars, [{ name: 'AZURE_AUTH_MODE', value: authMode }], authMode == 'keys' ? [
      { name: 'SEARCH_API_KEY', secretRef: 'search-key' }
      { name: 'FOUNDRY_API_KEY', secretRef: 'foundry-key' }
    ] : [])
    secretsJson: authMode == 'keys' ? string([
      { name: 'search-key', value: search.listAdminKeys().primaryKey }
      { name: 'foundry-key', value: foundry.listKeys().key1 }
      { name: 'acr-password', value: registry.listCredentials().passwords[0].value }
    ]) : ''
    registryUsername: authMode == 'keys' ? registry.listCredentials().username : ''
    registryPasswordSecretRef: authMode == 'keys' ? 'acr-password' : ''
    resourceTags: resourceTags
  }
}

output chatbotUrl string = 'https://${chat.outputs.fqdn}'
