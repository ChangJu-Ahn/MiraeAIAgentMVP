@description('Storage 계정 이름 (전역 유니크, 소문자 영숫자, ≤24)')
param name string
param location string
@description('원본 PDF 공개 컨테이너 이름')
param containerName string = 'source-docs'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false // 정책 준수: 익명 공개 액세스 금지 → 앱이 단기 SAS 발급
    allowSharedKeyAccess: false // 키리스: Entra RBAC만
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow' // ACA 아웃바운드에서 데이터 평면 접근 허용(키리스 RBAC로 보호)
      bypass: 'AzureServices'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

output accountName string = sa.name
output accountId string = sa.id
output containerName string = containerName
output blobEndpoint string = sa.properties.primaryEndpoints.blob
