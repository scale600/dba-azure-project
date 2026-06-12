@description('Location for Function App resources')
param location string = 'eastus'

@description('Key Vault URI (from main.bicep output)')
param keyVaultUri string

@description('Application Insights connection string (from main.bicep output)')
param appInsightsConnectionString string

@description('Application Insights instrumentation key (from main.bicep output)')
param appInsightsKey string

// ── Names ─────────────────────────────────────────────────────────────────
var suffix          = uniqueString(resourceGroup().id)
var kvName          = 'kv-dba-${take(suffix, 10)}'
var funcStorageName = 'stfunc${take(suffix, 12)}'
var funcPlanName    = 'asp-dba-project'
var funcAppName     = 'func-dba-${suffix}'

// ── Storage Account for Function App ─────────────────────────────────────
resource funcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: funcStorageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

// ── App Service Plan (Consumption / Linux) ────────────────────────────────
resource funcPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: funcPlanName
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  kind: 'functionapp'
  properties: {
    reserved: true  // Linux
  }
}

// ── Function App ──────────────────────────────────────────────────────────
resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  name: funcAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: funcPlan.id
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION',           value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME',               value: 'python' }
        { name: 'AzureWebJobsStorage',                    value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorage.name};AccountKey=${funcStorage.listKeys().keys[0].value};EndpointSuffix=core.windows.net' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY',         value: appInsightsKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING',  value: appInsightsConnectionString }
        { name: 'KEY_VAULT_URL',                          value: keyVaultUri }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

// ── Function App Managed Identity → Key Vault Secrets User ───────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvName
}

resource kvRoleFuncApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, funcApp.id, 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7') // Key Vault Secrets User
    principalId: funcApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────
output funcAppName        string = funcApp.name
output funcAppPrincipalId string = funcApp.identity.principalId
