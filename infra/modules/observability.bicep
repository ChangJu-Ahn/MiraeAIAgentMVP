@description('Log Analytics/App Insights 이름 접미사')
param name string
param location string
param resourceTags object = {}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${name}'
  location: location
  tags: resourceTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  tags: resourceTags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
  }
}

output appInsightsName string = appi.name
output appInsightsConnectionString string = appi.properties.ConnectionString
output logAnalyticsName string = law.name
