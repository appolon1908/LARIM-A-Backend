// Repository-only staging foundation. Deployment must be explicitly invoked by release automation.
targetScope = 'resourceGroup'
param location string = resourceGroup().location
@minLength(3)
@maxLength(10)
param prefix string = 'larimia'
param environment string = 'staging'
param postgresSku string = 'Standard_B1ms'
param postgresTier string = 'Burstable'
param postgresStorageGiB int = 32
param redisSku string = 'Balanced_B5'
@secure()
@minLength(24)
param postgresAdminPassword string
@secure()
@minLength(24)
param postgresRuntimePassword string

var suffix = uniqueString(resourceGroup().id, prefix, environment)
var name = '${prefix}-${environment}'

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${name}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.82.0.0/16'] }
    subnets: [
      { name: 'apps', properties: { addressPrefix: '10.82.0.0/23' } }
      { name: 'endpoints', properties: { addressPrefix: '10.82.3.0/24', privateEndpointNetworkPolicies: 'Disabled' } }
      {
        name: 'postgres'
        properties: {
          addressPrefix: '10.82.2.0/24'
          delegations: [{ name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }]
        }
      }
    ]
  }
}
resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${name}.postgres.database.azure.com'
  location: 'global'
}
resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dns
  name: 'apps'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${name}-pg-${suffix}'
  location: location
  sku: { name: postgresSku, tier: postgresTier }
  properties: {
    administratorLogin: 'larimia_migrator'
    administratorLoginPassword: postgresAdminPassword
    version: '17'
    storage: { storageSizeGB: postgresStorageGiB }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    network: {
      delegatedSubnetResourceId: '${network.id}/subnets/postgres'
      privateDnsZoneArmResourceId: dns.id
      publicNetworkAccess: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
  }
  dependsOn: [dnsLink]
}
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'larimia'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}
resource extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'POSTGIS', source: 'user-override' }
}
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${prefix}${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-workload'
  location: location
}
resource migratorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-migrator'
  location: location
}
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: { retentionInDays: 30, sku: { name: 'PerGB2018' } }
}
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}
resource apps 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-apps'
  location: location
  properties: {
    vnetConfiguration: { infrastructureSubnetId: '${network.id}/subnets/apps', internal: false }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${prefix}-${suffix}'
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 30
    accessPolicies: []
  }
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${prefix}${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false, allowSharedKeyAccess: false, supportsHttpsTrafficOnly: true }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 7 } }
}
resource documents 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'private-documents'
  properties: { publicAccess: 'None' }
}
resource bus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: '${name}-events-${suffix}'
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
  properties: { minimumTlsVersion: '1.2', disableLocalAuth: true }
}
resource events 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: bus
  name: 'marketplace-events'
  properties: {
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'P1D'
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
  }
}
resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: '${name}-redis-${suffix}'
  location: location
  sku: { name: redisSku }
  properties: { minimumTlsVersion: '1.2', highAvailability: 'Disabled', publicNetworkAccess: 'Disabled' }
}
resource redisDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: { clientProtocol: 'Encrypted', clusteringPolicy: 'EnterpriseCluster', evictionPolicy: 'NoEviction', port: 10000 }
}
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'pull')
  scope: registry
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','7f951dda-4ed3-4680-a7ca-43fe172d538d') }
}
resource migrationAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, migratorIdentity.id, 'pull')
  scope: registry
  properties: { principalId: migratorIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','7f951dda-4ed3-4680-a7ca-43fe172d538d') }
}
resource migrationVaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, migratorIdentity.id, 'secrets')
  scope: vault
  properties: { principalId: migratorIdentity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','4633458b-17de-408a-b874-0445c86b69e6') }
}
resource runtimeDatabaseSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: { value: 'postgresql+psycopg://larimia_app:${uriComponent(postgresRuntimePassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/larimia?sslmode=require' }
}
resource migrationDatabaseSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'migration-database-url'
  properties: { value: 'postgresql+psycopg://larimia_migrator:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/larimia?sslmode=require' }
}
resource redisSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-url'
  properties: { value: 'rediss://:${uriComponent(redisDatabase.listKeys().primaryKey)}@${redis.properties.hostName}:10000/0' }
}
resource databaseSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(runtimeDatabaseSecret.id, identity.id, 'read')
  scope: runtimeDatabaseSecret
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','4633458b-17de-408a-b874-0445c86b69e6') }
}
resource redisSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(redisSecret.id, identity.id, 'read')
  scope: redisSecret
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','4633458b-17de-408a-b874-0445c86b69e6') }
}
resource blobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, 'blobs')
  scope: storage
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','ba92f5b4-2d11-453d-a403-e96b0029c9fe') }
}
resource eventSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(bus.id, identity.id, 'sender')
  scope: bus
  properties: { principalId: identity.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions','69a216fc-b8fb-44d8-bc22-1f3c2cd27a39') }
}
output registryServer string = registry.properties.loginServer
output environmentId string = apps.id
output identityId string = identity.id
output keyVaultUri string = vault.properties.vaultUri
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output redisHost string = redis.properties.hostName
output storageUrl string = storage.properties.primaryEndpoints.blob
output serviceBusNamespace string = '${bus.name}.servicebus.windows.net'

resource redisDns 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.redis.azure.net'
  location: 'global'
}
resource redisDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: redisDns
  name: name
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: network.id } }
}
resource redisEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${name}-redis-private'
  location: location
  properties: {
    subnet: { id: '${network.id}/subnets/endpoints' }
    privateLinkServiceConnections: [{ name: 'redis', properties: { privateLinkServiceId: redis.id, groupIds: ['redisEnterprise'] } }]
  }
}
resource redisDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: redisEndpoint
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: 'redis', properties: { privateDnsZoneId: redisDns.id } }] }
}

output migratorIdentityName string = migratorIdentity.name
output runtimeIdentityName string = identity.name
