targetScope = 'resourceGroup'
param location string = resourceGroup().location
param appName string = 'larimia-staging'
param environmentId string
param identityName string
param migratorIdentityName string
param registryServer string
@description('Immutable digest or full commit SHA image reference; never latest.')
param image string
param databaseSecretUri string
param migrationDatabaseSecretUri string
param redisSecretUri string
param oidcIssuer string
param oidcAudience string
param oidcJwksUrl string
param workforceIssuer string
param workforceAudience string
param workforceJwksUrl string
param allowedOrigins string
param storageUrl string
param serviceBusNamespace string
param otlpEndpoint string = ''
param notificationRelayUrl string = ''
param notificationTokenSecretUri string = ''
@allowed(['migration', 'runtime'])
param phase string = 'migration'
param minReplicas int = 1
param maxReplicas int = 3

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: identityName }
resource migratorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: migratorIdentityName }
var assignedIdentity = { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
var secrets = concat([
  { name: 'database-url', keyVaultUrl: databaseSecretUri, identity: identity.id }
  { name: 'migration-database-url', keyVaultUrl: migrationDatabaseSecretUri, identity: identity.id }
  { name: 'redis-url', keyVaultUrl: redisSecretUri, identity: identity.id }
], empty(notificationTokenSecretUri) ? [] : [{ name: 'notification-token', keyVaultUrl: notificationTokenSecretUri, identity: identity.id }])
var env = [
  { name: 'LARIMIA_ENV', value: 'staging' }
  { name: 'LARIMIA_AUTH_MODE', value: 'oidc' }
  { name: 'LARIMIA_OIDC_ISSUER', value: oidcIssuer }
  { name: 'LARIMIA_OIDC_AUDIENCE', value: oidcAudience }
  { name: 'LARIMIA_OIDC_JWKS_URL', value: oidcJwksUrl }
  { name: 'LARIMIA_WORKFORCE_OIDC_ISSUER', value: workforceIssuer }
  { name: 'LARIMIA_WORKFORCE_OIDC_AUDIENCE', value: workforceAudience }
  { name: 'LARIMIA_WORKFORCE_OIDC_JWKS_URL', value: workforceJwksUrl }
  { name: 'LARIMIA_CORS_ORIGINS', value: allowedOrigins }
  { name: 'LARIMIA_DATABASE_URL', secretRef: 'database-url' }
  { name: 'LARIMIA_REDIS_URL', secretRef: 'redis-url' }
  { name: 'LARIMIA_AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'LARIMIA_STORAGE_MODE', value: 'azure' }
  { name: 'LARIMIA_AZURE_STORAGE_URL', value: storageUrl }
  { name: 'LARIMIA_EVENT_TRANSPORT', value: 'azure' }
  { name: 'LARIMIA_SERVICE_BUS_NAMESPACE', value: serviceBusNamespace }
  { name: 'LARIMIA_PAYMENT_MODE', value: 'mock' }
  { name: 'LARIMIA_TELEMETRY_OTLP_ENDPOINT', value: otlpEndpoint }
  { name: 'LARIMIA_BUILD_VERSION', value: image }
]
var notificationEnv = concat(env, empty(notificationTokenSecretUri) ? [] : [
  { name: 'LARIMIA_NOTIFICATION_MODE', value: 'relay' }
  { name: 'LARIMIA_NOTIFICATION_RELAY_URL', value: notificationRelayUrl }
  { name: 'LARIMIA_NOTIFICATION_RELAY_TOKEN', secretRef: 'notification-token' }
])
var registries = [{ server: registryServer, identity: identity.id }]
resource migration 'Microsoft.App/jobs@2024-03-01' = {
  name: '${appName}-migration'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${migratorIdentity.id}': {} } }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: [for secret in secrets: { name: secret.name, keyVaultUrl: secret.keyVaultUrl, identity: migratorIdentity.id }]
      registries: [{ server: registryServer, identity: migratorIdentity.id }]
    }
    template: {
      containers: [{
        name: 'migration'
        image: image
        command: ['python', 'scripts/migrate.py']
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: concat(filter(env, item => item.name != 'LARIMIA_DATABASE_URL' && item.name != 'LARIMIA_AZURE_CLIENT_ID'), [{ name: 'LARIMIA_DATABASE_URL', secretRef: 'migration-database-url' }, { name: 'LARIMIA_RUNTIME_DATABASE_URL', secretRef: 'database-url' }, { name: 'LARIMIA_AZURE_CLIENT_ID', value: migratorIdentity.properties.clientId }])
      }]
    }
  }
}
resource api 'Microsoft.App/containerApps@2024-03-01' = if (phase == 'runtime') {
  name: '${appName}-api'
  location: location
  identity: assignedIdentity
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: filter(secrets, item => item.name != 'migration-database-url')
      registries: registries
      ingress: { external: true, targetPort: 8000, allowInsecure: false, transport: 'auto' }
    }
    template: {
      containers: [{
        name: 'api'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: env
        probes: [
          { type: 'Liveness', httpGet: { path: '/health/live', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 10 }
          { type: 'Readiness', httpGet: { path: '/health/ready', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 10 }
        ]
      }]
      scale: { minReplicas: minReplicas, maxReplicas: maxReplicas, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '50' } } }] }
    }
  }
}
resource worker 'Microsoft.App/containerApps@2024-03-01' = if (phase == 'runtime') {
  name: '${appName}-worker'
  location: location
  identity: assignedIdentity
  properties: {
    managedEnvironmentId: environmentId
    configuration: { activeRevisionsMode: 'Single', secrets: filter(secrets, item => item.name != 'migration-database-url'), registries: registries }
    template: {
      containers: [
        { name: 'worker', image: image, command: ['python','-m','larimia.marketplace.worker'], env: env, resources: { cpu: json('0.25'), memory: '0.5Gi' } }
        { name: 'notifications', image: image, command: ['python','-m','larimia.marketplace.notification_delivery'], env: notificationEnv, resources: { cpu: json('0.25'), memory: '0.5Gi' } }
        { name: 'event-publisher', image: image, command: ['python','-m','larimia.marketplace.event_transport'], env: env, resources: { cpu: json('0.25'), memory: '0.5Gi' } }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}
output migrationJob string = migration.name
output apiHost string = phase == 'runtime' ? api!.properties.configuration.ingress!.fqdn : ''
