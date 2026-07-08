@description('Container App 이름')
param name string
param location string
param environmentId string
param acrLoginServer string
@description('UAMI 리소스 ID')
param uamiId string
@description('컨테이너 이미지 (초기 배포는 placeholder, 이후 실이미지로 갱신)')
param image string
@description('환경변수 배열 [{name, value}]')
param envVars array

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto' // websocket 지원 (Chainlit)
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'chat'
          image: image
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: envVars
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1 // Chainlit 웹소켓 세션: 단일 레플리카 (MVP)
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output name string = app.name
