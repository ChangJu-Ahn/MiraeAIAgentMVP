@description('Document Intelligence(FormRecognizer) 계정 이름')
param name string
param location string
param disableLocalAuth bool = true
param resourceTags object = {}

resource di 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: resourceTags
  kind: 'FormRecognizer'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    disableLocalAuth: disableLocalAuth
    publicNetworkAccess: 'Enabled'
  }
}

output docIntelligenceEndpoint string = di.properties.endpoint
output docIntelligenceName string = di.name
