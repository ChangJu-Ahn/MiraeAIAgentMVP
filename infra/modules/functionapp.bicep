@description('Function App 이름 (전역 유니크)')
param name string
param location string
@description('Function 런타임 스토리지 겸 업로드 대상 기존 스토리지 계정 이름')
param storageAccountName string
@description('배포 패키지를 저장할 blob 컨테이너 이름')
param deploymentContainer string
@description('AI Search 엔드포인트 (https://<name>.search.windows.net)')
param searchEndpoint string
@description('Application Insights 연결 문자열 (관측/디버깅용)')
param appInsightsConnectionString string = ''
param searchIndexName string = 'demo-blob-index'
param uploadContainer string = 'pdfs'
param chunkSize int = 1000
param maxUploadMb int = 50

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

var blobEndpoint = 'https://${sa.name}.blob.${environment().suffixes.storage}'

// Flex Consumption(FC1) 플랜: 공유키 없이 관리 ID로만 동작하는 서버리스 플랜.
// 기존 스토리지의 allowSharedKeyAccess=false 정책과 호환된다.
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource funcApp 'Microsoft.Web/sites@2024-04-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${blobEndpoint}/${deploymentContainer}'
          authentication: {
            // 배포 컨테이너 접근을 시스템 관리 ID로 처리 → 공유키 불필요
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
    siteConfig: {
      ftpsState: 'Disabled'
      appSettings: [
        // AzureWebJobsStorage를 연결 문자열 대신 계정 이름 + 관리 ID로 지정 (키리스)
        { name: 'AzureWebJobsStorage__accountName', value: sa.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'SEARCH_INDEX_NAME', value: searchIndexName }
        { name: 'STORAGE_BLOB_ENDPOINT', value: blobEndpoint }
        { name: 'UPLOAD_CONTAINER', value: uploadContainer }
        { name: 'CHUNK_SIZE', value: string(chunkSize) }
        { name: 'MAX_UPLOAD_MB', value: string(maxUploadMb) }
      ]
    }
  }
}

output name string = funcApp.name
output id string = funcApp.id
output principalId string = funcApp.identity.principalId
output defaultHostName string = funcApp.properties.defaultHostName
