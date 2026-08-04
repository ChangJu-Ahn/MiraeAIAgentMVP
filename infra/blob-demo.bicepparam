using 'blob-demo.bicep'

param existingStorageAccountName = readEnvironmentVariable('UPLOAD_STORAGE_ACCOUNT', '')
param existingSearchName = readEnvironmentVariable('SEARCH_SERVICE_NAME', '')
param existingAppInsightsName = readEnvironmentVariable('APP_INSIGHTS_NAME', '')
