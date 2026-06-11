# Power BI Setup Guide — HospitalDB

## 1. Connection (DirectQuery)

1. Power BI Desktop → **Get Data → Azure → Azure SQL Database**
2. Server: `sql-dba-xvel6ncdvwsre.database.windows.net`
3. Database: `HospitalDB`
4. Data Connectivity mode: **DirectQuery**
5. Authentication: **Database** → Username: `dbadmin`

## 2. Tables to Import

Select these 4 views (not the raw tables):

| View | Used on Page |
|------|-------------|
| `dbo.vw_HospitalNationalOverview` | Page 1, 2 |
| `dbo.vw_StateSummary` | Page 2 |
| `dbo.vw_MetricsQuality` | Page 3 |
| `dbo.vw_ETLOperations` | Page 4 |

## 3. DAX Measures

Import all measures from `bi/dax_measures.dax`.
Create a dedicated **Measures** table (blank query) to hold them.

## 4. Report Pages

### Page 1 — National Overview
| Visual | Fields | Notes |
|--------|--------|-------|
| Filled Map | State, [Total Hospitals] | Color = count intensity |
| Bar Chart | State, [Avg Rating] | Sort DESC, top 15 |
| Donut Chart | EmergencyServices | Y vs N |
| Column Chart | OverallRating (1–5), count | Rating distribution |
| KPI Cards | [Total Hospitals], [Avg Rating], [Emergency Coverage %], [Top Rated Hospitals] | |

### Page 2 — State Drill-Down
| Visual | Fields | Notes |
|--------|--------|-------|
| Slicer | State | Single select |
| Table | FacilityName, City, HospitalType, OverallRating, EmergencyServices | Sorted by rating DESC |
| Pie Chart | HospitalType, count | Acute vs Critical etc. |
| KPI Cards | [Selected State Hospitals], [State Avg Rating], [State Emergency %] | |

### Page 3 — Quality Metrics
| Visual | Fields | Notes |
|--------|--------|-------|
| Slicer | MeasureID | Multi-select |
| Slicer | State | Filter |
| Bar Chart | FacilityName, Score | Top 10 by Score ASC |
| Stacked Bar | State, ComparedToNational | Better/Same/Worse |
| Line Chart | PeriodEnd, Avg Score | Trend over time |
| KPI Cards | [Better Than National], [Better %], [Unique Measures] | |

### Page 4 — ETL Operations (DBA View)
| Visual | Fields | Notes |
|--------|--------|-------|
| Table | RunStart, DurationSec, HospitalsLoaded, MetricsLoaded, Status | Last 30 runs |
| Donut Chart | Status, count | SUCCESS vs FAILED |
| Line Chart | RunDate, MetricsLoaded | Volume trend |
| KPI Cards | [Total ETL Runs], [ETL Success Rate %], [Avg ETL Duration (sec)], [Last ETL Status] | |

## 5. Publish to Power BI Service

```
File → Publish → Publish to Power BI → Select workspace
```

After publish, set dataset refresh (if switching from DirectQuery to Import mode):
- Schedule: Daily 01:00 UTC

## 6. DirectQuery Optimization Tips

- Views already pre-aggregate where possible
- Avoid cross-view relationships — use DAX `CALCULATE` instead
- Set query reduction options: **Disable cross-highlighting** for page 3 (67K rows)
- Apply a MeasureID slicer selection as default to limit initial query size
