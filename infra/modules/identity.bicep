@description('User-Assigned Managed Identity 이름')
param name string
param location string

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

output id string = uami.id
output principalId string = uami.properties.principalId
output clientId string = uami.properties.clientId
