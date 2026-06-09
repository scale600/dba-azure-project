@description('Location for monitoring/KV resources (already provisioned in eastus)')
param location string = 'eastus'

@description('Location for SQL Server (eastus capacity unavailable)')
param sqlLocation string = 'westus3'

@description('SQL Server administrator login')
param sqlAdminLogin string = 'dbadmin'

@secure()
@description('SQL Server administrator password')
param sqlAdminPassword string

@description('Object ID of the deploying user (for Key Vault access policy)')
param deployerObjectId string

// ── Names ─────────────────────────────────────────────────────────────────
var suffix           = uniqueString(resourceGroup().id)
var sqlServerName    = 'sql-dba-${suffix}'
var sqlDbName        = 'HospitalDB'
var kvName           = 'kv-dba-${take(suffix, 10)}'
var appInsightsName  = 'appi-dba-project'
var logWorkspaceName = 'log-dba-project'

// ── Log Analytics Workspace ───────────────────────────────────────────────
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logWorkspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Application Insights ──────────────────────────────────────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logWorkspace.id
  }
}

// ── Key Vault ─────────────────────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// ── Key Vault — deployer gets Secrets Officer role ────────────────────────
resource kvRoleDeployer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, deployerObjectId, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets Officer
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// ── SQL Server (westus3) ──────────────────────────────────────────────────
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: sqlLocation
  properties: {
    administratorLogin: sqlAdminLogin
    administratorLoginPassword: sqlAdminPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// ── SQL Database (Serverless GP_S_Gen5_1) ────────────────────────────────
resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDbName
  location: sqlLocation
  sku: {
    name: 'GP_S_Gen5'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 1
  }
  properties: {
    autoPauseDelay: 60
    minCapacity: json('0.5')
    collation: 'SQL_Latin1_General_CP1_CI_AS'
    zoneRedundant: false
    requestedBackupStorageRedundancy: 'Local'
  }
}

// ── SQL — allow Azure services ────────────────────────────────────────────
resource sqlFirewallAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────
output sqlServerFqdn   string = sqlServer.properties.fullyQualifiedDomainName
output sqlServerName   string = sqlServer.name
output sqlDatabaseName string = sqlDb.name
output keyVaultUri     string = keyVault.properties.vaultUri
output keyVaultName    string = keyVault.name
output appInsightsKey  string = appInsights.properties.InstrumentationKey
output appInsightsConnectionString string = appInsights.properties.ConnectionString
