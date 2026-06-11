# DBA Azure Project

> **TechCloudUp DBA Lab** — CMS Public API → Azure Function App → Azure SQL Database → Custom REST API + Power BI, secured by Azure Key Vault, monitored via Application Insights & Azure Monitor.

A portfolio project demonstrating end-to-end data engineering and DBA competencies: automated ETL from CMS public APIs, Azure SQL Database administration, a custom REST API layer, and Power BI dashboards for business intelligence.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Data Model](#3-data-model)
4. [CMS API Specification & Field Mapping](#4-cms-api-specification--field-mapping)
5. [ETL Pipeline Design](#5-etl-pipeline-design)
6. [REST API Design](#6-rest-api-design)
7. [BI Dashboard Design](#7-bi-dashboard-design)
8. [Azure Deployment Guide](#8-azure-deployment-guide)
9. [Deployed Resources](#9-deployed-resources)
10. [Test Plan](#10-test-plan)
11. [File Structure](#11-file-structure)
12. [Progress Checklist](#12-progress-checklist)

---

## 1. Project Overview

### Goals

| Layer | Goal |
|-------|------|
| **DBA** | Design schema, tune indexes, automate ETL, validate backup/recovery |
| **API** | Build a custom REST API on top of the database (Azure Functions HTTP Trigger) |
| **BI** | Deliver actionable Power BI dashboards connected to Azure SQL Database |

### Data Sources

| API | Provider | Auth | Update Cycle | Role |
|-----|----------|------|-------------|------|
| Hospital General Information | CMS | None | Quarterly | Hospital master data |
| Unplanned Hospital Visits | CMS | None | Quarterly | Quality metrics snapshots |

### Scope

| Item | Included |
|------|----------|
| Python-based ETL pipeline | ✅ |
| Azure SQL Database | ✅ |
| Azure Function App — Timer Trigger (ETL scheduler) | ✅ |
| Azure Function App — HTTP Trigger (REST API) | ✅ |
| Power BI Dashboard | ✅ |
| Azure Key Vault (secret management) | ✅ |
| Web frontend | ❌ (validated via API + Power BI) |

### Success Criteria

1. Automatically ingest data twice daily at UTC 00:00 and 12:00
2. Query response time for per-hospital metrics **under 500 ms** after index application
3. REST API `GET /api/hospitals` responds **under 300 ms** (p95)
4. Power BI dashboard refreshes successfully against live Azure SQL Database
5. Point-in-Time Restore completes with data integrity verified; recovery time recorded
6. All code published on GitHub with execution instructions in README

### HIPAA Considerations

> The CMS datasets used in this project are **publicly available, fully de-identified** under the Safe Harbor method (45 CFR §164.514(b)) and do not contain Protected Health Information (PHI). HIPAA obligations therefore do not apply to this project.
>
> However, the architecture is designed with HIPAA-readiness in mind. If this system were extended to handle PHI, the following controls would be required and are already structurally supported:

| Control | Azure Service / Mechanism | Notes |
|---------|--------------------------|-------|
| Encryption at rest | Azure SQL TDE (enabled by default) | AES-256; no extra config needed on GP tier |
| Encryption in transit | TLS 1.2 enforced on SQL Server | Set `minimalTlsVersion: '1.2'` in Bicep |
| Access control | Azure RBAC + Managed Identity | No passwords in code; `DefaultAzureCredential` pattern already applied |
| Audit logging | Azure SQL Auditing → Storage Account / Log Analytics | Enable `auditingSettings` in Bicep for PHI workloads |
| Secret management | Azure Key Vault | Connection strings never in code or config files |
| Network isolation | Private Endpoint + VNet Integration | Recommended addition for PHI; not provisioned in this demo |
| Breach notification | Azure Security Center / Defender for SQL | Threat detection policy enables anomaly alerts |
| Business Associate Agreement | Microsoft BAA | Available under Microsoft's standard OST for Azure |

This design pattern demonstrates awareness of HIPAA technical safeguards (§164.312) and can be extended to a compliant architecture with minimal structural changes.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Data Sources                            │
│   CMS Hospital General Info    CMS Unplanned Hospital Visits│
└──────────────┬──────────────────────────┬───────────────────┘
               │ HTTP GET (no auth)        │ HTTP GET (no auth)
               ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│           Azure Function App  (Python 3.11)                 │
│  ┌────────────────────────┐  ┌──────────────────────────┐   │
│  │ Timer Trigger (ETL)    │  │ HTTP Trigger (REST API)  │   │
│  │ CRON: 0 0 0,12 * * *   │  │ GET /api/hospitals       │   │
│  │ • fetch → transform    │  │ GET /api/hospitals/{id}  │   │
│  │ • MERGE + INSERT       │  │ GET /api/hospitals/{id}  │   │
│  │ • ETL_Log write        │  │   /metrics               │   │
│  └──────────┬─────────────┘  │ GET /api/states/summary  │   │
│             │                │ GET /api/metrics/top     │   │
└─────────────┼────────────────┴──────────┬───────────────────┘
              │                           │
              ▼                           │
┌─────────────────────────┐               │
│   Azure SQL Database    │◄──────────────┘
│   (Serverless tier)     │
│   • dbo.Hospital        │
│   • dbo.HospitalVisit   │◄──────────── Power BI Service
│     Metrics             │              (DirectQuery)
│   • dbo.ETL_Log         │
└─────────────────────────┘
        ▲
        │ Secrets
┌───────────────┐     ┌────────────────────┐
│ Azure Key     │     │ Application        │
│ Vault         │     │ Insights + Monitor │
└───────────────┘     └────────────────────┘
```

---

## 3. Data Model

### Core Table DDL

```sql
-- US hospital master data (CMS Hospital General Information)
CREATE TABLE dbo.Hospital (
    FacilityID        NVARCHAR(10)  NOT NULL PRIMARY KEY,
    FacilityName      NVARCHAR(200) NOT NULL,
    Address           NVARCHAR(200),
    City              NVARCHAR(100),
    State             NCHAR(2),
    ZipCode           NVARCHAR(10),
    Phone             NVARCHAR(20),
    HospitalType      NVARCHAR(100),
    EmergencyServices NCHAR(1),     -- 'Y' or 'N'
    OverallRating     TINYINT,      -- 1–5, NULL if not rated
    UpdatedAt         DATETIME2     DEFAULT GETDATE()
);

-- Periodic quality metrics snapshots (CMS Unplanned Hospital Visits)
CREATE TABLE dbo.HospitalVisitMetrics (
    MetricID           INT           IDENTITY PRIMARY KEY,
    FacilityID         NVARCHAR(10)  NOT NULL REFERENCES dbo.Hospital(FacilityID),
    CollectedAt        DATETIME2     NOT NULL DEFAULT GETDATE(),
    MeasureID          NVARCHAR(20)  NOT NULL,  -- e.g. 'EDAC_30_AMI'
    MeasureName        NVARCHAR(300),
    Score              DECIMAL(8,2),
    NumberOfPatients   INT,
    NumberReturned     INT,
    ComparedToNational NVARCHAR(10), -- 'Better', 'Same', 'Worse'
    PeriodStart        DATE,
    PeriodEnd          DATE
);

-- ETL execution audit log
CREATE TABLE dbo.ETL_Log (
    LogID           INT           IDENTITY PRIMARY KEY,
    RunStart        DATETIME2     DEFAULT GETDATE(),
    RunEnd          DATETIME2,
    RecordsInserted INT,
    Status          NVARCHAR(20), -- 'SUCCESS', 'FAILED'
    ErrorMessage    NVARCHAR(MAX)
);
```

### Index Strategy

```sql
-- Optimize date range queries on metrics history
CREATE INDEX IX_VisitMetrics_CollectedAt
    ON dbo.HospitalVisitMetrics (CollectedAt DESC)
    INCLUDE (FacilityID, MeasureID, Score);

-- Optimize per-hospital metric lookups (API + BI)
CREATE INDEX IX_VisitMetrics_FacilityID_MeasureID
    ON dbo.HospitalVisitMetrics (FacilityID, MeasureID, CollectedAt DESC);

-- Optimize state-level queries (API + BI)
CREATE INDEX IX_Hospital_State
    ON dbo.Hospital (State)
    INCLUDE (FacilityName, EmergencyServices, OverallRating);

-- Optimize ETL log queries
CREATE INDEX IX_ETLLog_RunStart
    ON dbo.ETL_Log (RunStart DESC);
```

---

## 4. CMS API Specification & Field Mapping

### Endpoints (no authentication required)

```
Hospital General Info:
  GET https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0
  Params: limit=5000, offset=0

Unplanned Hospital Visits:
  GET https://data.cms.gov/provider-data/api/1/datastore/query/632h-zaca/0
  Params: limit=10000, offset=0
```

### Field Mapping — Hospital General Information → `dbo.Hospital`

| API Field | Type | Target Column | Transformation Rule |
|-----------|------|---------------|---------------------|
| `facility_id` | string | `FacilityID` | Use as-is (PK) |
| `facility_name` | string | `FacilityName` | `str.strip().title()` |
| `address` | string | `Address` | `str.strip()` |
| `citytown` | string | `City` | `str.strip().title()` |
| `state` | string | `State` | Use as-is (2-char code) |
| `zip_code` | string | `ZipCode` | Use as-is |
| `telephone_number` | string | `Phone` | Format as `(XXX) XXX-XXXX` |
| `hospital_type` | string | `HospitalType` | `str.strip()` |
| `emergency_services` | string | `EmergencyServices` | `'Yes'→'Y'`, `'No'→'N'` |
| `hospital_overall_rating` | string | `OverallRating` | `int()`, `'Not Available'→NULL` |

### Field Mapping — Unplanned Hospital Visits → `dbo.HospitalVisitMetrics`

| API Field | Type | Target Column | Transformation Rule |
|-----------|------|---------------|---------------------|
| `facility_id` | string | `FacilityID` | Use as-is (FK) |
| `measure_id` | string | `MeasureID` | Use as-is |
| `measure_name` | string | `MeasureName` | `str.strip()` |
| `score` | string | `Score` | `float()`, `'Not Available'→NULL` |
| `number_of_patients` | string | `NumberOfPatients` | `int()`, missing→NULL |
| `number_of_patients_returned` | string | `NumberReturned` | `int()`, missing→NULL |
| `compared_to_national` | string | `ComparedToNational` | `'Better...'→'Better'`, `'No Different...'→'Same'`, `'Worse...'→'Worse'`, other→NULL |
| `start_date` | string | `PeriodStart` | `datetime.strptime('%m/%d/%Y')` |
| `end_date` | string | `PeriodEnd` | `datetime.strptime('%m/%d/%Y')` |

---

## 5. ETL Pipeline Design

### Schedule

- **Trigger**: Azure Function App Timer Trigger
- **CRON expression**: `0 0 0,12 * * *` (UTC 00:00 and 12:00)

### Data Flow

```
[CMS data.cms.gov]
    ↓  HTTP GET (no auth)
[Python Function — Timer Trigger]
    ↓  JSON parse → field mapping → type conversion
[dbo.Hospital]             ← MERGE (upsert on FacilityID)
[dbo.HospitalVisitMetrics] ← INSERT snapshot each run
[dbo.ETL_Log]              ← Success/failure recorded
```

### MERGE Pattern — Hospital Master

```sql
MERGE dbo.Hospital AS target
USING (VALUES (@FacilityID, @FacilityName, @Address, @City, @State,
               @ZipCode, @Phone, @HospitalType, @EmergencyServices, @OverallRating))
      AS source (FacilityID, FacilityName, Address, City, State,
                 ZipCode, Phone, HospitalType, EmergencyServices, OverallRating)
ON target.FacilityID = source.FacilityID
WHEN MATCHED AND (
    target.FacilityName      <> source.FacilityName OR
    target.OverallRating     <> source.OverallRating OR
    target.EmergencyServices <> source.EmergencyServices
) THEN
    UPDATE SET FacilityName      = source.FacilityName,
               Address           = source.Address,
               City              = source.City,
               State             = source.State,
               ZipCode           = source.ZipCode,
               Phone             = source.Phone,
               HospitalType      = source.HospitalType,
               EmergencyServices = source.EmergencyServices,
               OverallRating     = source.OverallRating,
               UpdatedAt         = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (FacilityID, FacilityName, Address, City, State,
            ZipCode, Phone, HospitalType, EmergencyServices, OverallRating)
    VALUES (source.FacilityID, source.FacilityName, source.Address, source.City,
            source.State, source.ZipCode, source.Phone, source.HospitalType,
            source.EmergencyServices, source.OverallRating);
```

### Error Handling Policy

| Error Type | Handling |
|------------|----------|
| HTTP 429 (Rate Limit) | Exponential backoff retry (max 3 attempts, wait 2^n seconds) |
| Network timeout | Retry then write FAILED to `ETL_Log` |
| Data parsing error | Skip the record, log error details |
| DB connection failure | Fail immediately and alert via Application Insights |

---

## 6. REST API Design

Built on **Azure Functions HTTP Trigger** — no additional infrastructure required.

### Base URL

```
https://www.dba-azure.techcloudup.com/api
```

### Endpoints

#### `GET /api/hospitals`

List hospitals with optional filters and pagination.

| Query Param | Type | Example | Description |
|-------------|------|---------|-------------|
| `state` | string | `CA` | Filter by 2-char state code |
| `emergency` | string | `Y` | Filter by emergency services (`Y`/`N`) |
| `rating` | int | `4` | Minimum overall rating |
| `limit` | int | `20` | Page size (default: 20, max: 100) |
| `offset` | int | `0` | Pagination offset |

**Sample Response:**
```json
{
  "total": 342,
  "limit": 20,
  "offset": 0,
  "data": [
    {
      "facility_id": "050317",
      "facility_name": "Cedars-Sinai Medical Center",
      "city": "Los Angeles",
      "state": "CA",
      "emergency_services": "Y",
      "overall_rating": 5
    }
  ]
}
```

---

#### `GET /api/hospitals/{facility_id}`

Return full details for a single hospital.

**Sample Response:**
```json
{
  "facility_id": "050317",
  "facility_name": "Cedars-Sinai Medical Center",
  "address": "8700 Beverly Blvd",
  "city": "Los Angeles",
  "state": "CA",
  "zip_code": "90048",
  "phone": "(310) 423-3277",
  "hospital_type": "Acute Care Hospitals",
  "emergency_services": "Y",
  "overall_rating": 5,
  "updated_at": "2025-01-15T09:00:00Z"
}
```

---

#### `GET /api/hospitals/{facility_id}/metrics`

Return quality metric history for a hospital.

| Query Param | Type | Description |
|-------------|------|-------------|
| `measure_id` | string | Filter by specific measure (e.g. `EDAC_30_AMI`) |
| `limit` | int | Number of snapshots (default: 10) |

**Sample Response:**
```json
{
  "facility_id": "050317",
  "facility_name": "Cedars-Sinai Medical Center",
  "metrics": [
    {
      "collected_at": "2025-06-08T00:00:00Z",
      "measure_id": "EDAC_30_AMI",
      "measure_name": "Hospital return days for heart attack patients",
      "score": -18.5,
      "compared_to_national": "Better",
      "number_of_patients": 412
    }
  ]
}
```

---

#### `GET /api/states/summary`

Aggregated statistics per state.

**Sample Response:**
```json
{
  "data": [
    {
      "state": "CA",
      "total_hospitals": 342,
      "with_emergency": 289,
      "avg_rating": 3.4,
      "top_rated_count": 42
    }
  ]
}
```

---

#### `GET /api/metrics/top`

Top hospitals by quality score for a given measure.

| Query Param | Type | Description |
|-------------|------|-------------|
| `measure_id` | string | Required — measure ID |
| `state` | string | Optional — filter by state |
| `limit` | int | Number of results (default: 10) |

### Error Response Format

```json
{
  "error": "NOT_FOUND",
  "message": "Hospital with facility_id '999999' not found.",
  "status": 404
}
```

### Standard HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Invalid query parameters |
| 404 | Resource not found |
| 500 | Internal server error (logged to Application Insights) |

---

## 7. BI Dashboard Design

Tool: **Power BI Service** (DirectQuery to Azure SQL Database)

### Report Pages

#### Page 1 — National Overview
| Visual | Type | Description |
|--------|------|-------------|
| Hospital count by state | Filled map | Color intensity = hospital count |
| Average rating by state | Bar chart | Sorted descending |
| Emergency services coverage | Donut chart | Y vs N ratio |
| Rating distribution | Histogram | 1–5 star breakdown |
| KPI cards | Card | Total hospitals / Avg rating / % with emergency |

#### Page 2 — State Drill-Down
| Visual | Type | Description |
|--------|------|-------------|
| State slicer | Slicer | Filter all visuals |
| Hospital list | Table | Name, city, type, rating, emergency |
| Rating trend over ETL runs | Line chart | Tracks rating changes over time |
| Hospital type breakdown | Pie chart | Acute Care vs Critical Access etc. |

#### Page 3 — Quality Metrics
| Visual | Type | Description |
|--------|------|-------------|
| Measure slicer | Slicer | Select measure (e.g. EDAC_30_AMI) |
| Score distribution | Box plot | National spread |
| Better / Same / Worse | Stacked bar | By state |
| Top 10 hospitals by score | Bar chart | For selected measure |
| Score trend over time | Line chart | Per hospital, per measure |

#### Page 4 — ETL Operations (DBA View)
| Visual | Type | Description |
|--------|------|-------------|
| ETL run history | Table | RunStart, RunEnd, Records, Status |
| Success vs Failed | Donut chart | Last 30 days |
| Records inserted over time | Line chart | Data volume trend |
| Avg ETL duration | KPI card | Seconds |

### Key DAX Measures

```dax
Total Hospitals = COUNTROWS(Hospital)

Avg Rating = AVERAGE(Hospital[OverallRating])

Emergency Coverage % =
DIVIDE(
    COUNTROWS(FILTER(Hospital, Hospital[EmergencyServices] = "Y")),
    COUNTROWS(Hospital)
) * 100

ETL Success Rate % =
DIVIDE(
    COUNTROWS(FILTER(ETL_Log, ETL_Log[Status] = "SUCCESS")),
    COUNTROWS(ETL_Log)
) * 100
```

---

## 8. Azure Deployment Guide

### Resource Creation Order

1. Resource Group ✅
2. Azure Key Vault
3. Azure SQL Server + Database (Serverless tier)
4. Azure Function App (Python 3.11) — hosts both Timer + HTTP triggers
5. Firewall rules / Managed Identity permissions
6. Power BI workspace connection

### Bicep Template (Core)

```bicep
// main.bicep
param location string = resourceGroup().location
param adminLogin string
@secure()
param adminPassword string

resource sqlServer 'Microsoft.Sql/servers@2021-11-01' = {
  name: 'sql-dba-${uniqueString(resourceGroup().id)}'
  location: location
  properties: {
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
  }
}

resource sqlDB 'Microsoft.Sql/servers/databases@2021-11-01' = {
  parent: sqlServer
  name: 'HospitalDB'
  location: location
  sku: {
    name: 'GP_S_Gen5_1'  // Serverless — auto-pauses when idle
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: 1
  }
  properties: {
    // DB may be paused at each ETL run (12h interval), causing cold-start delay
    // If timeout errors occur, change to -1 (disable auto-pause)
    autoPauseDelay: 60
    minCapacity: json('0.5')
  }
}
```

---

## 9. Deployed Resources

| Resource | Name | Location | Status |
|----------|------|----------|--------|
| Resource Group | `rg-dba-project` | East US | ✅ Active |
| Azure DNS Zone | `dba-azure.techcloudup.com` | Global | ✅ Active |
| Azure Static Web Apps | `swa-dba-project` | East US 2 | ✅ Active |
| Custom Domain | `www.dba-azure.techcloudup.com` | — | ✅ Ready (SSL) |
| Azure Key Vault | `kv-dba-xvel6ncdvw` | East US | ✅ Active |
| Azure SQL Server | `sql-dba-xvel6ncdvwsre` | West US 3 | ✅ Active |
| Azure SQL Database | `HospitalDB` | West US 3 | ✅ Active (Serverless GP_S_Gen5_1) |
| Azure Function App (ETL + API) | — | — | ⬜ Pending (VM quota) |
| Application Insights | `appi-dba-project` | East US | ✅ Active |
| Power BI Workspace | — | — | ⬜ Pending |

**Live URL:** https://www.dba-azure.techcloudup.com

---

## 10. Test Plan

| ID | Scenario | Expected Result | Verification |
|----|----------|-----------------|--------------|
| TC-01 | CMS API response delayed 10 seconds | Retry then write FAILED to `ETL_Log` | `SELECT * FROM dbo.ETL_Log WHERE Status='FAILED'` |
| TC-02 | Date range query without indexes | Table Scan in execution plan | `SET STATISTICS IO ON` + execution plan |
| TC-03 | Same query after index creation | Index Seek, under 500 ms | Execution plan + elapsed time comparison |
| TC-04 | Point-in-Time Restore | Records after restore point absent; earlier records intact | `SELECT COUNT(*)` before/after comparison |
| TC-05 | Re-ingesting identical CMS data | MERGE skips unchanged rows, updates only changed | `RecordsInserted` vs UPDATE count |
| TC-06 | `GET /api/hospitals?state=CA` | Returns paginated CA hospitals, status 200 | Response time < 300 ms, correct JSON schema |
| TC-07 | `GET /api/hospitals/invalid_id` | Returns 404 with error JSON | `{"error":"NOT_FOUND", "status":404}` |
| TC-08 | Power BI DirectQuery refresh | Dashboard loads without timeout | Refresh completes under 30 seconds |

---

## 11. File Structure

```
dba-azure-project/
├── dba-azure-project.md          # English original (full project design)
├── dba-azure-project-kor.md      # Korean clone
├── site/
│   ├── index.html                # Project docs web page (SWA)
│   └── dba-azure-project.md      # Markdown copy for browser rendering
├── infra/
│   ├── main.bicep                # Azure resource IaC
│   └── parameters.json
├── sql/
│   ├── 01_schema.sql             # Table DDL
│   ├── 02_indexes.sql            # Indexes
│   └── 03_queries.sql            # Performance tuning queries
├── etl/
│   └── function_app/
│       ├── timer_trigger/
│       │   └── __init__.py       # ETL Timer Trigger entry point
│       ├── etl.py                # fetch / transform / load logic
│       └── requirements.txt
├── api/
│   └── function_app/
│       ├── hospitals/
│       │   └── __init__.py       # GET /api/hospitals
│       ├── hospital_detail/
│       │   └── __init__.py       # GET /api/hospitals/{id}
│       ├── hospital_metrics/
│       │   └── __init__.py       # GET /api/hospitals/{id}/metrics
│       ├── states_summary/
│       │   └── __init__.py       # GET /api/states/summary
│       ├── metrics_top/
│       │   └── __init__.py       # GET /api/metrics/top
│       └── shared/
│           └── db.py             # Shared DB connection helper
├── bi/
│   └── hospital_quality.pbix     # Power BI report file
├── monitoring/
│   └── dashboard.json            # Azure Monitor dashboard export
├── .env.example
└── README.md
```

---

## 12. Progress Checklist

### Phase 1 — Prerequisites

- [ ] ~~API key~~ → CMS APIs require no authentication
- [x] Azure account active (`scale600@outlook.com`, subscription: `Azure subscription 1`)
- [x] Azure CLI installed and `az login` complete
- [x] Python 3.11 + `pyodbc`, `azure-functions`, `azure-identity`, `requests` installed
- [x] GitHub repository created (`dba-azure-project`) — https://github.com/scale600/dba-azure-project
- [x] `.gitignore` configured — exclude `.env`, `*.pyc`, `local.settings.json`, `*.pbix`
- [x] `.env.example` created (key names only)

---

### Phase 2 — Azure Infrastructure Setup

- [x] Resource Group (`rg-dba-project`, `eastus`)
- [x] Azure DNS Zone (`dba-azure.techcloudup.com`) — Cloudflare NS delegation complete
- [x] Azure Static Web Apps (`swa-dba-project`) — `www.dba-azure.techcloudup.com` live
- [x] Azure Key Vault (`kv-dba-xvel6ncdvw`, `eastus`) — `DB-CONNECTION-STRING` registered
- [x] Deploy `main.bicep` — SQL Server (`sql-dba-xvel6ncdvwsre`, `westus3`) + `HospitalDB` + Log Analytics + App Insights
- [x] Azure SQL Server firewall rule — local IP `108.94.142.34` allowed
- [x] Test Azure SQL connection — `pyodbc` connected, `HospitalDB` verified
- [ ] Function App (`func.bicep`) — pending VM quota or region availability
- [ ] Function App Managed Identity → Key Vault access

---

### Phase 3 — Database Schema Setup

- [x] Run `sql/01_schema.sql` — create `Hospital`, `HospitalVisitMetrics`, `ETL_Log`
- [x] Run `sql/02_indexes.sql` — apply all indexes
- [x] Verify schema: `SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo'`
- [x] Manual sample INSERT + SELECT verification

---

### Phase 4 — ETL Code Development

- [x] `etl/cms_client.py` — validate CMS API call and field mapping locally
- [x] `etl/db_client.py` + `etl/etl_runner.py`
  - [x] `fetch_hospitals()` — paginated GET (5,433 records)
  - [x] `fetch_visit_metrics()` — paginated GET (67,088 records)
  - [x] transform + type conversion, normalization (built into upsert)
  - [x] `upsert_hospitals()` — MERGE upsert on FacilityID
  - [x] `upsert_metrics()` — MERGE upsert on FacilityID + MeasureID + PeriodEnd
  - [x] `log_start()` / `log_end()` — ETL_Log write
- [ ] Timer Trigger `__init__.py` + `function.json` (`0 0 0,12 * * *`) — pending Function App
- [ ] `requirements.txt`
- [ ] Local `func start` test
- [ ] Deploy to Azure + manual trigger test via portal

---

### Phase 5 — REST API Development

- [x] `api/db.py` — connection helper (env var + Key Vault fallback)
- [x] `GET /api/hospitals` — filter, pagination, JSON response
- [x] `GET /api/hospitals/{id}` — single hospital detail
- [x] `GET /api/hospitals/{id}/metrics` — metrics history with optional measure filter
- [x] `GET /api/states/summary` — aggregate per state
- [x] `GET /api/metrics/top` — ranked hospitals by score
- [x] Error handling — standard `{"error", "message", "status"}` format
- [ ] Deploy to Azure Function App (pending VM quota)
- [ ] Verify all endpoints via TC-06 / TC-07

---

### Phase 6 — Performance Tuning (Core DBA)

- [x] Capture baseline (PK Scan) vs index execution — 4개 쿼리 비교
- [x] Record elapsed time before/after (min of 5 runs each)
  - 병원메트릭 조회: 35.6 ms → 16.5 ms (-54%)
  - National비교 필터: 36.9 ms → 15.7 ms (-57%)
  - 이름 검색: 18.4 ms → 15.9 ms (-14%)
- [x] DMV missing index 분석 → IX_VisitMetrics_MeasureID_Score 추가 적용 (impact 63.9)
- [x] Document results in `sql/03_queries.sql`

---

### Phase 7 — Backup & Recovery Validation

- [ ] Confirm Azure SQL auto-backup (default 7-day retention)
- [ ] Point-in-Time Restore test + data integrity check
- [ ] Record actual recovery time (Serverless tier)
- [ ] Document restore procedure in `README.md`

---

### Phase 8 — BI Dashboard (Power BI)

- [ ] Connect Power BI Desktop to Azure SQL Database (DirectQuery)
- [ ] Build Page 1 — National Overview (map, rating distribution, KPI cards)
- [ ] Build Page 2 — State Drill-Down (slicer, hospital list, trend)
- [ ] Build Page 3 — Quality Metrics (measure slicer, score distribution, top 10)
- [ ] Build Page 4 — ETL Operations (run history, success rate, volume trend)
- [ ] Write key DAX measures (`Total Hospitals`, `Avg Rating`, `ETL Success Rate %`)
- [ ] Publish to Power BI Service
- [ ] Schedule dataset refresh
- [ ] Verify TC-08 (refresh under 30 seconds)
- [ ] Save `bi/hospital_quality.pbix`

---

### Phase 9 — Monitoring Setup

- [ ] Connect Application Insights — track ETL + API function execution
- [ ] Azure Monitor alerts
  - Email on ETL failure
  - API error rate > 5% alert
  - DB CPU > 80% alert
- [ ] Azure Portal dashboard — ETL history, API request rate, DTU usage
- [ ] Export `monitoring/dashboard.json`

---

### Phase 10 — Wrap-up & Portfolio Polish

- [ ] Write `README.md` — architecture diagram, local run instructions, API docs, BI screenshots
- [ ] Add ASCII architecture diagram
- [ ] GitHub Actions CI — SQL lint on PR
- [ ] Run full test plan TC-01 ~ TC-08
- [ ] Final secret exposure check
- [ ] Switch GitHub repository to Public
