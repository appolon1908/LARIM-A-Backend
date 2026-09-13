# Azure staging source and deployment gates

Cloud provisioning/deployment was excluded from the active repository-only instruction. No Azure URL,
Entra login, cloud backup restore or cloud E2E is claimed. Bicep templates are compiled locally; API
compatibility, network permissions, resource availability and subscriptions require live validation.

`infra/main.bicep` creates the resource group and calls the foundation: VNet, private PostgreSQL Flexible
Server/PostGIS allowlist, private Azure Managed Redis, ACR, managed identities, Key Vault, private Blob
container, Service Bus queue, Log Analytics, Application Insights and Container Apps environment.
Parameters include region, prefix and separately supplied secure migration/runtime passwords. Use
secure deployment parameter inputs; never put parameter values in Git or command logs.

`infra/runtime.bicep` creates the migration job first. The manual staging workflow waits for job success
before promoting the API and worker image by digest. Runtime and migrator identities are distinct;
only the migrator sees the migration secret. `scripts/migrate.py` applies Alembic and establishes the
restricted runtime role. The worker's network event publisher is a separate process/container so a
Service Bus failure cannot block notification/dispatch recovery polling.

The template uses managed identity for ACR, Key Vault, Blob and Service Bus. PostgreSQL and Redis use
Key Vault-delivered credentials pending a separately verified Entra database/Redis token rotation
integration. Azure Managed Redis private DNS uses `privatelink.redis.azure.net` and public access is
disabled. These choices follow Microsoft's [Service Bus identity example](https://learn.microsoft.com/en-us/python/api/overview/azure/servicebus-readme?view=azure-python),
[registry identity guidance](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull)
and [Managed Redis Private Link guidance](https://learn.microsoft.com/en-us/azure/redis/private-link).

## Required GitHub environment configuration

Create the `staging` environment with release authorization policies and federated Azure login. Set
AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP and AZURE_REGISTRY.
STAGING_PARAMETERS is a nonsecret JSON object containing the runtime Bicep parameters:

- appName, environmentId, identityName, migratorIdentityName, registryServer
- databaseSecretUri, migrationDatabaseSecretUri, redisSecretUri (versioned Key Vault URIs)
- oidcIssuer, oidcAudience, oidcJwksUrl; workforceIssuer, workforceAudience, workforceJwksUrl
- allowedOrigins, storageUrl, serviceBusNamespace, optional otlpEndpoint and replica settings

STAGING_CERTIFICATION_TOKENS_JSON must contain short-lived tokens for **dedicated test identities**:
customer1, admin and provider1–provider4. Provision their DB issuer bindings and test profiles/addresses;
never use real customer/provider accounts. The HTTP scenario checks that the server reports mock
payments before any financial command. A missing token or failed scenario fails the workflow, not
silently skips certification. Use refreshed tokens rather than long-lived credentials.

The Azure release identity needs deployment, ACR build and Container Apps job permissions; foundation
provisioning also needs approved role-assignment/Key Vault permissions. SKU availability and service
provider registration must be confirmed in the selected subscription. No Kubernetes is deployed.

## Rollback

Retain previous immutable image digests and database restore points. Migration job failure leaves the
previous running app revision intact; promotion does not run. Migrations 0003+ intentionally refuse
blind destructive downgrade. Restore into an isolated database and reconcile financial/outbox state
before a database rollback. Re-run health, identity, scenario, worker and storage checks after promotion.
A compiled template and local scenario are not substitutes for these cloud gates.
