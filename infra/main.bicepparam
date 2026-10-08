using 'main.bicep'

param developerObjectId = readEnvironmentVariable('DEVELOPER_OBJECT_ID', '')
param ingestApiEndpoint = readEnvironmentVariable('INGEST_API_ENDPOINT', '')
