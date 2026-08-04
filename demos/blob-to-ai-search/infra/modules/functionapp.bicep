@description('Function App 이름 (전역 유니크)')
param name string
param location string
@description('Function 런타임 스토리지 겸 업로드 대상 기존 스토리지 계정 이름')
param storageAccountName string
@description('AI Search 엔드포인트 (https://<name>.search.windows.net)')
param searchEndpoint string
@description('Function VNet 통합용 서브넷 리소스 ID (Microsoft.Web/serverFarms 위임)')
param funcSubnetId string
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

// Dedicated(App Service) Linux B1 플랜.
// 기존 스토리지가 allowSharedKeyAccess=false + publicNetworkAccess=Disabled(정책 강제)라,
// - Flex/Consumption/Elastic Premium은 공유키 기반 Azure Files 콘텐츠 공유가 필요해 사용 불가
// - Flex는 배포(빌드) 파이프라인이 프라이빗 스토리지에 도달하지 못해 배포 자체가 403 실패
// Dedicated 플랜은 코드가 플랫폼 관리 wwwroot에 배포되어(사용자 스토리지 미접근) 배포가 가능하고,
// 런타임 스토리지 접근만 VNet 통합 + 프라이빗 엔드포인트로 처리한다.
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
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
    // 지역 VNet 통합(아웃바운드) → 스토리지 프라이빗 엔드포인트 접근 경로
    virtualNetworkSubnetId: funcSubnetId
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      ftpsState: 'Disabled'
      // 모든 아웃바운드를 VNet으로 라우팅 → 스토리지 프라이빗 엔드포인트 + 프라이빗 DNS 사용
      vnetRouteAllEnabled: true
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        // 원격(express) 빌드 산출물을 SitePackages 패키지로 마운트해 실행
        { name: 'WEBSITE_RUN_FROM_PACKAGE', value: '1' }
        // AzureWebJobsStorage를 연결 문자열 대신 blob 엔드포인트 + 관리 ID로 지정 (키리스)
        { name: 'AzureWebJobsStorage__blobServiceUri', value: blobEndpoint }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        // 함수 키를 스토리지 대신 파일시스템에 저장 → 시작 시 스토리지 의존도 최소화
        { name: 'AzureWebJobsSecretStorageType', value: 'files' }
        // 프라이빗 DNS 존(privatelink.blob) 조회를 위해 Azure DNS 사용
        { name: 'WEBSITE_DNS_SERVER', value: '168.63.129.16' }
        // 배포 시 Oryx 원격 빌드(pip install)를 wwwroot에서 수행
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
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
