# Hospital Quality Data Pipeline — Azure

A personal project that pulls US hospital quality data from the CMS (Centers for Medicare & Medicaid Services) public API, stores it in Azure SQL Database, and exposes it through a REST API and a web dashboard.

The goal was to connect all the pieces end-to-end: automated ETL, cloud infrastructure as code, a queryable API layer, and BI visualization — using only managed Azure services.

**Live:** https://www.dba-azure.techcloudup.com

---

## Architecture

```
CMS Public API (Hospital Info + Quality Metrics)
        │  HTTP GET (no auth, quarterly updates)
        ▼
Azure Function App  (Python 3.11)
  ├── Timer Trigger  — CRON 0 0 0,12 * * *  (ETL, twice daily)
  └── HTTP Trigger   — REST API (5 endpoints)
        │
        ▼
Azure SQL Database  (Serverless, GP_S_Gen5_1)
  ├── dbo.Hospital              — hospital master (~5,400 records)
  ├── dbo.HospitalVisitMetrics  — quality metric snapshots
  └── dbo.ETL_Log               — ETL run audit log
        │
        ├──▶ Azure Static Web Apps  — web dashboard (Chart.js)
        └──▶ Power BI Service       — DirectQuery reports

Azure Key Vault        — connection strings (no secrets in code)
Application Insights   — API performance monitoring + ETL alerts
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11 |
| Cloud | Azure (Function App, SQL Database, Key Vault, Static Web Apps, Application Insights) |
| Infrastructure | Bicep (IaC) |
| Data sources | CMS Hospital General Info API, CMS Unplanned Hospital Visits API |
| Web dashboard | Chart.js, HTML/CSS (build-time DB snapshot) |
| BI | Power BI Desktop + Service (DirectQuery) |
| Dependencies | `azure-functions`, `azure-identity`, `azure-keyvault-secrets`, `pyodbc`, `requests` |

---

## Project Structure

```
.
├── function_app.py          # Azure Functions v2 — HTTP Trigger (REST API)
├── requirements.txt
├── .env.example             # local env var template (no real values)
│
├── etl/
│   ├── etl_runner.py        # ETL entry point (Timer Trigger → cms_client → db_client)
│   ├── cms_client.py        # CMS API fetch + field mapping
│   └── db_client.py         # MERGE upsert + ETL_Log writes
│
├── api/
│   └── db.py                # SQL query helpers (REST API)
│
├── sql/
│   ├── 01_schema.sql        # table DDL
│   ├── 02_indexes.sql       # indexes
│   └── 03_queries.sql       # ad-hoc analysis queries
│
├── infra/
│   ├── main.bicep           # core infrastructure (SQL, Key Vault, App Insights)
│   └── func.bicep           # Function App deployment
│
├── site/
│   ├── index.html           # project docs (renders dba-azure-project.md via marked.js)
│   ├── dashboard.html       # live dashboard (Chart.js, build-time DB snapshot)
│   └── staticwebapp.config.json
│
├── bi/
│   ├── dax_measures.dax     # Power BI DAX measures
│   └── powerbi_setup.md     # Power BI connection setup guide
│
├── monitoring/
│   └── dashboard.json       # Azure Monitor dashboard definition
│
└── build_dashboard.py       # embeds DB snapshot into dashboard.html before deploy
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- ODBC Driver 18 for SQL Server
- Azure CLI (`az login` completed)

### 1. Configure environment variables

```bash
cp .env.example .env
# fill in the values in .env
```

| Variable | Description |
|----------|-------------|
| `AZURE_KEY_VAULT_URL` | Key Vault endpoint (`https://<name>.vault.azure.net/`) |
| `DB_CONNECTION_STRING` | Azure SQL connection string (local dev only; production reads from Key Vault) |
| `AzureWebJobsStorage` | local Function App storage (`UseDevelopmentStorage=true`) |

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run ETL manually (local)

```bash
python -c "
import os, dotenv
dotenv.load_dotenv()
from etl.etl_runner import run
run()
"
```

### 4. Run the REST API locally

```bash
func start
```

Test at `http://localhost:7071/api/hospitals?state=CA`.

### 5. Build the dashboard (optional)

```bash
# embeds a DB snapshot into dashboard.html
python build_dashboard.py
```

---

## REST API

Base URL: `https://<function-app>.azurewebsites.net/api`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/hospitals` | list hospitals with filter + pagination |
| GET | `/hospitals/{id}` | single hospital detail |
| GET | `/hospitals/{id}/metrics` | quality metric history for a hospital |
| GET | `/states/summary` | aggregated stats per state |
| GET | `/metrics/top` | top hospitals by quality score for a given measure |

### Query parameters

**`GET /hospitals`**

| Parameter | Type | Example |
|-----------|------|---------|
| `state` | string | `CA` |
| `rating` | int | `4` (4 stars and above) |
| `emergency` | string | `Y` |
| `limit` | int | `20` (default) |
| `offset` | int | `0` |

**`GET /hospitals/{id}/metrics`**

| Parameter | Type | Description |
|-----------|------|-------------|
| `measure_id` | string | e.g. `EDAC_30_AMI` |
| `limit` | int | number of snapshots (default: 10) |

### Error format

```json
{
  "error": "NOT_FOUND",
  "message": "Hospital with facility_id '999999' not found.",
  "status": 404
}
```

---

## Database Schema

```sql
-- hospital master data
CREATE TABLE dbo.Hospital (
    FacilityID        NVARCHAR(10)  NOT NULL PRIMARY KEY,
    FacilityName      NVARCHAR(200) NOT NULL,
    State             NCHAR(2),
    HospitalType      NVARCHAR(100),
    EmergencyServices NCHAR(1),     -- 'Y' / 'N'
    OverallRating     TINYINT,      -- 1–5, NULL if not rated
    Latitude          DECIMAL(9,6),
    Longitude         DECIMAL(9,6),
    UpdatedAt         DATETIME2 DEFAULT GETDATE()
);

-- quality metric snapshots
CREATE TABLE dbo.HospitalVisitMetrics (
    MetricID           INT IDENTITY PRIMARY KEY,
    FacilityID         NVARCHAR(10) NOT NULL REFERENCES dbo.Hospital(FacilityID),
    MeasureID          NVARCHAR(20) NOT NULL,
    Score              DECIMAL(8,2),
    ComparedToNational NVARCHAR(10), -- 'Better' / 'Same' / 'Worse'
    PeriodStart        DATE,
    PeriodEnd          DATE,
    CollectedAt        DATETIME2 DEFAULT GETDATE()
);

-- ETL run audit log
CREATE TABLE dbo.ETL_Log (
    LogID            INT IDENTITY PRIMARY KEY,
    RunStart         DATETIME2 DEFAULT GETDATE(),
    RunEnd           DATETIME2,
    HospitalsLoaded  INT,
    MetricsLoaded    INT,
    Status           NVARCHAR(20), -- 'SUCCESS' / 'FAILED'
    ErrorMessage     NVARCHAR(MAX)
);
```

ETL uses `MERGE` for upserts, so repeated runs don't produce duplicate records.

---

## Infrastructure (Bicep)

```bash
# deploy core infrastructure (SQL, Key Vault, App Insights)
az deployment group create \
  --resource-group rg-dba-project \
  --template-file infra/main.bicep

# deploy Function App
az deployment group create \
  --resource-group rg-dba-project \
  --template-file infra/func.bicep
```

The Function App's Managed Identity is granted `Key Vault Secrets User` on the vault. At runtime, `DefaultAzureCredential` fetches the connection string — no secrets in code or config files.

---

## Live URLs

| URL | Description |
|-----|-------------|
| https://www.dba-azure.techcloudup.com | project documentation |
| https://www.dba-azure.techcloudup.com/dashboard.html | live dashboard |

---

## Security Notes

- `.env` is in `.gitignore` — never committed
- Connection strings live in Azure Key Vault only
- Code reads secrets at runtime via `DefaultAzureCredential`
- Azure SQL enforces TLS 1.2; TDE is enabled by default
