// blob 데모용 네트워킹: Dedicated(App Service) 지역 VNet 통합 + 스토리지 프라이빗 엔드포인트.
// 기존 스토리지가 publicNetworkAccess=Disabled(정책 강제)라, Function이
// 스토리지에 접근하려면 VNet 통합 + 프라이빗 엔드포인트 + 프라이빗 DNS가 필요하다.
param location string
param vnetName string
param storageAccountName string
param funcSubnetName string = 'snet-func'
param peSubnetName string = 'snet-pe'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: ['10.30.0.0/16']
    }
    subnets: [
      {
        name: funcSubnetName
        properties: {
          addressPrefix: '10.30.1.0/24'
          // Dedicated(App Service) 지역 VNet 통합용 위임
          delegations: [
            {
              name: 'serverfarmdelegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
        }
      }
      {
        name: peSubnetName
        properties: {
          addressPrefix: '10.30.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource blobDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: blobDnsZone
  name: 'link-${vnetName}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource peBlob 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${storageAccountName}-blob'
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/${peSubnetName}'
    }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          privateLinkServiceId: sa.id
          groupIds: ['blob']
        }
      }
    ]
  }
}

resource peDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peBlob
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: blobDnsZone.id
        }
      }
    ]
  }
}

output funcSubnetId string = '${vnet.id}/subnets/${funcSubnetName}'
