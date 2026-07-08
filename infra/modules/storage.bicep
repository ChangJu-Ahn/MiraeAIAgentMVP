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
    allowBlobPublicAccess: true // 공개자료 익명 읽기 허용
    allowSharedKeyAccess: false // 키리스: 업로드는 Entra RBAC로만
    publicNetworkAccess: 'Enabled'
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
    publicAccess: 'Blob' // 컨테이너 아닌 blob 단위 익명 읽기
  }
}

output accountName string = sa.name
output accountId string = sa.id
output containerName string = containerName
output blobBaseUrl string = '${sa.properties.primaryEndpoints.blob}${containerName}'
