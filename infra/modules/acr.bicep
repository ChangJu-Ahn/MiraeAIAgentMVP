@description('Container Registry 이름 (전역 유니크, 영숫자)')
param name string
param location string
param adminUserEnabled bool = false
param resourceTags object = {}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: name
  location: location
  tags: resourceTags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: adminUserEnabled
  }
}

output loginServer string = acr.properties.loginServer
output name string = acr.name
output id string = acr.id
