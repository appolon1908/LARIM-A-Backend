targetScope = 'subscription'
param location string
param resourceGroupName string = 'larimia-staging'
@minLength(3)
@maxLength(10)
param prefix string = 'larimia'
@secure()
param postgresAdminPassword string
@secure()
param postgresRuntimePassword string
resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = { name: resourceGroupName, location: location }
module foundation 'staging.bicep' = {
  name: 'larimia-foundation'
  scope: group
  params: { location: location, prefix: prefix, postgresAdminPassword: postgresAdminPassword, postgresRuntimePassword: postgresRuntimePassword }
}
output registryServer string = foundation.outputs.registryServer
output environmentId string = foundation.outputs.environmentId
output keyVaultUri string = foundation.outputs.keyVaultUri
output runtimeIdentityName string = foundation.outputs.runtimeIdentityName
output migratorIdentityName string = foundation.outputs.migratorIdentityName
